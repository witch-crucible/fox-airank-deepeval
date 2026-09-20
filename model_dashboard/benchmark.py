from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .domain import DashboardError, MODEL_TEST_WEIGHTS, normalize_model

CATEGORY_TO_MODEL_TEST = {
    "code_correction": "correction",
    "code_generation": "generation",
    "logic_analysis": "logic",
}
MODEL_TEST_FIELD = {
    "correction": "model_test_correction",
    "generation": "model_test_generation",
    "logic": "model_test_logic",
}

TEST_RUN_PATTERN = re.compile(r"^test_run_(\d{8}_\d{6})\.json$")


def _latest_test_run(tool_dir: Path) -> Path | None:
    candidates: list[tuple[str, Path]] = []
    if not tool_dir.is_dir():
        return None
    for path in tool_dir.glob("test_run_*.json"):
        match = TEST_RUN_PATTERN.match(path.name)
        if match:
            candidates.append((match.group(1), path))
    if not candidates:
        return None
    return max(candidates, key=lambda item: item[0])[1]


def _category_from_metadata(entry: dict[str, Any]) -> str:
    metadata = entry.get("metadata") or {}
    return str(metadata.get("category") or "")


def _extract_task_correctness(case: dict[str, Any]) -> float | None:
    for metric in case.get("metricsData", []):
        if str(metric.get("name", "")).startswith("Task Correctness"):
            score = metric.get("score")
            if isinstance(score, (int, float)):
                return float(score)
    return None


def compute_model_test_scores(test_run_path: Path) -> dict[str, float | None]:
    """Compute model_test_correction/generation/logic from a DeepEval TestRun JSON.

    Task Correctness scores (0–1) are averaged per category and scaled to 0–100.
    ``model_test_total`` is a weighted average using the same weights as the
    dashboard (correction 3, generation 4, logic 8).
    """
    try:
        data = json.loads(test_run_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise DashboardError(f"无法读取 TestRun JSON：{error}") from error

    grouped: dict[str, list[float]] = {"correction": [], "generation": [], "logic": []}
    for case in data.get("testCases", []):
        category = _category_from_metadata(case)
        key = CATEGORY_TO_MODEL_TEST.get(category)
        if not key:
            continue
        score = _extract_task_correctness(case)
        if score is not None:
            grouped[key].append(score)

    scores: dict[str, float | None] = {}
    for key in ("correction", "generation", "logic"):
        values = grouped[key]
        field = MODEL_TEST_FIELD[key]
        scores[field] = round(sum(values) / len(values) * 100, 2) if values else None

    parts = {key: scores[MODEL_TEST_FIELD[key]] for key in MODEL_TEST_WEIGHTS}
    if any(value is not None for value in parts.values()):
        weighted = sum(
            float(value or 0) * weight
            for value, weight in zip(parts.values(), MODEL_TEST_WEIGHTS.values())
        ) / sum(MODEL_TEST_WEIGHTS.values())
        scores["model_test_total"] = round(weighted, 2)
    else:
        scores["model_test_total"] = None
    return scores


def _load_run_manifest(run_dir: Path) -> dict[str, Any]:
    manifest_path = run_dir / "run.json"
    if not manifest_path.is_file():
        raise DashboardError(f"run.json 不存在：{run_dir}")
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise DashboardError(f"run.json 不是有效 JSON：{error}") from error
    return manifest


def _normalize_tool_identity(identity: Any) -> tuple[str, str, str]:
    if isinstance(identity, dict):
        agent = str(identity.get("agent") or "unknown")
        model = str(identity.get("model") or "unknown")
        intelligence = str(identity.get("intelligence") or "unknown")
        return agent, model, intelligence
    return "unknown", "unknown", "unknown"


def normalize_benchmark_models(run_dir: Path) -> list[dict[str, Any]]:
    """Read a benchmark run directory and produce dashboard model entries.

    Each tool in the run manifest becomes a model entry with ``source.type``
    set to ``benchmark`` and ``scores`` populated from the DeepEval TestRun.
    """
    manifest = _load_run_manifest(run_dir)
    tools = manifest.get("tools", [])
    if not isinstance(tools, list) or not tools:
        raise DashboardError("run.json 中没有配置 tools")
    identities = manifest.get("identities", {})
    if not isinstance(identities, dict):
        identities = {}

    models: list[dict[str, Any]] = []
    for tool in tools:
        if not isinstance(tool, str):
            continue
        tool_dir = run_dir / "deepeval" / tool
        test_run_path = _latest_test_run(tool_dir)
        if test_run_path is None:
            continue
        agent, model_name, intelligence = _normalize_tool_identity(identities.get(tool))
        mt_scores = compute_model_test_scores(test_run_path)
        raw: dict[str, Any] = {
            "tool": agent,
            "model": model_name,
            "reasoning_effort": intelligence if intelligence != "unknown" else "",
            "scores": mt_scores,
            "report_path": f"{run_dir.name}/{tool}/deepeval/",
            "notes": f"来自 benchmark run {run_dir.name}",
        }
        source = {
            "type": "benchmark",
            "name": "Benchmark run",
            "run_id": run_dir.name,
            "tool": tool,
            "test_run_file": test_run_path.name,
        }
        model = normalize_model(raw, source=source)
        models.append(model)
    if not models:
        raise DashboardError(f"在 {run_dir} 下没有找到可用的 TestRun JSON")
    return models
