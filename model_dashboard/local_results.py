"""Read local benchmark evidence without importing it into the editable model store."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any
from urllib.parse import quote

from benchmark.report import METRIC_ORDER, collect_tool_summary, latest_test_run
from benchmark.paths import PELICAN_CASE, load_identities, workspace_path


RUNS_ROOT = Path(__file__).resolve().parent.parent / "runs"
CASES_ROOT = Path(__file__).resolve().parent.parent / "cases"


def _component(value: Any) -> bool:
    return isinstance(value, str) and bool(value) and value not in {".", ".."} and not any(
        char in value for char in ("/", "\\", "\x00")
    )


def _inside(path: Path, root: Path) -> bool:
    return path.resolve().is_relative_to(root.resolve())


def _read_object(path: Path, root: Path) -> dict[str, Any]:
    if not _inside(path, root):
        raise ValueError("路径超出本地运行目录")
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("JSON 必须为对象")
    return value


def _number(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
        return float(value)
    return None


def resolve_pelican_preview(runs_root: Path, run_id: str, tool: str) -> Path | None:
    """Only expose the self-contained pelican HTML, never arbitrary run files."""
    return _pelican_preview(runs_root, run_id, tool, CASES_ROOT)[0]


def _pelican_preview(
    runs_root: Path, run_id: str, tool: str, cases_root: Path,
) -> tuple[Path | None, str | None]:
    missing = "未生成作品：未找到可预览的 HTML"
    if not all(_component(value) for value in (run_id, tool)):
        return None, missing
    run_dir = runs_root / run_id
    if not _inside(run_dir, runs_root):
        return None, missing
    workspace = workspace_path(run_dir, tool, PELICAN_CASE, load_identities(run_dir))
    path = workspace / "index.html"
    if not path.is_file():
        # Historical runs used runs/<run>/<tool>/<case>; keep them previewable.
        workspace = run_dir / tool / PELICAN_CASE
        path = workspace / "index.html"
    if not _inside(workspace, runs_root) or not _inside(path, workspace):
        return None, missing
    if not path.is_file():
        return None, missing
    initial = cases_root / "code_generation" / "pelican_bicycle" / "index.html"
    try:
        # Older prepare() calls copied local solutions into every workspace, even
        # when execution failed. Explicit submissions (including imports) remain valid.
        if _inside(initial, cases_root) and initial.is_file() and path.read_bytes() == initial.read_bytes():
            try:
                result = _read_object(workspace / "result.json", workspace)
            except (OSError, ValueError):
                result = {}
            changed = result.get("changed_files")
            if not (result.get("case_id") == PELICAN_CASE and result.get("status") == "completed"
                    and isinstance(changed, list) and "index.html" in changed):
                return None, "未生成作品：仅有测试初始文件"
    except OSError:
        return None, "作品文件无法读取"
    return path, None


def collect_local_results(runs_root: Path = RUNS_ROOT, cases_root: Path = CASES_ROOT) -> dict[str, Any]:
    """Keep each run/configuration/case and its original metric evidence separate."""
    registry: dict[str, dict[str, str]] = {}
    for path in sorted(cases_root.glob("*/*/case.json")):
        try:
            case = _read_object(path, cases_root)
            registry[case["id"]] = {"title": case.get("title", ""), "category": case.get("category", "")}
        except (OSError, ValueError, KeyError, TypeError):
            continue

    records: list[dict[str, Any]] = []
    warnings: list[str] = []
    if not runs_root.is_dir():
        return {"records": records, "warnings": warnings}
    for run_dir in sorted(runs_root.iterdir()):
        if not run_dir.is_dir() or not (run_dir / "run.json").is_file():
            continue
        try:
            manifest = _read_object(run_dir / "run.json", runs_root)
            tools = manifest.get("tools", [])
            case_ids = manifest.get("cases", [])
            if not isinstance(tools, list) or not isinstance(case_ids, list):
                raise ValueError("tools 和 cases 必须为数组")
            identities = manifest.get("identities")
            if not isinstance(identities, dict):
                identities = {}
        except (OSError, ValueError):
            warnings.append(f"{run_dir.name}：运行记录无法读取，已跳过")
            continue
        for tool in dict.fromkeys(value for value in tools if _component(value)):
            tool_dir = run_dir / "deepeval" / tool
            identity = identities.get(tool)
            identity = identity if isinstance(identity, dict) else {}
            rows = {}
            judge_model = metric_version = judge_effort = None
            evidence_file = None
            try:
                test_run = latest_test_run(tool_dir) if _inside(tool_dir, runs_root) else None
                if test_run is not None:
                    evidence = _read_object(test_run, runs_root)
                    hyperparameters = evidence.get("hyperparameters") or {}
                    judge_effort = hyperparameters.get("judge_reasoning_effort")
                    summary = collect_tool_summary(run_dir, tool, registry, {**manifest, "identities": identities})
                    rows = {row.case_id: row for row in summary.rows}
                    judge_model, metric_version = summary.judge_model, summary.metric_version
                    evidence_file = str(test_run.relative_to(runs_root))
            except (OSError, ValueError, TypeError, AttributeError, KeyError):
                warnings.append(f"{run_dir.name} / {tool}：评分文件无法读取，仍可查看执行状态和作品")
            selected_cases = dict.fromkeys([*(value for value in case_ids if _component(value)), *(value for value in rows if _component(value))])
            for case_id in selected_cases:
                row = rows.get(case_id)
                execution: dict[str, Any] = {}
                execution_path = workspace_path(run_dir, tool, case_id, identities) / "execution.json"
                if not execution_path.is_file():
                    execution_path = run_dir / tool / case_id / "execution.json"
                if execution_path.is_file():
                    try:
                        execution = _read_object(execution_path, runs_root)
                    except (OSError, ValueError):
                        warnings.append(f"{run_dir.name} / {tool} / {case_id}：执行记录无法读取")
                metrics = {}
                for name, value in (row.metrics.items() if row else []):
                    score, threshold = _number(value.get("score")), _number(value.get("threshold"))
                    error = value.get("error")
                    metrics[name] = {
                        "score": score if score is not None and 0 <= score <= 1 and not error else None,
                        "threshold": threshold,
                        "success": value.get("success") is True,
                        "reason": str(value.get("reason") or ""),
                        "error": str(error) if error else None,
                    }
                graded = all(metrics.get(name, {}).get("score") is not None for name in METRIC_ORDER)
                preview, preview_reason = (
                    _pelican_preview(runs_root, run_dir.name, tool, cases_root)
                    if case_id == PELICAN_CASE else (None, None)
                )
                status = str(execution.get("status") or (row.execution_status if row else "missing"))
                info = registry.get(case_id, {})
                records.append({
                    "id": f"{run_dir.name}/{tool}/{case_id}",
                    "run_id": run_dir.name,
                    "created_at": str(manifest.get("created_at") or ""),
                    "tool": tool,
                    "agent": str(identity.get("agent") or tool),
                    "model": str(identity.get("model") or "unknown"),
                    "reasoning_effort": str(identity.get("intelligence") or "unknown"),
                    "case_id": case_id,
                    "title": str(info.get("title") or (row.title if row else "") or case_id),
                    "category": str(info.get("category") or (row.category if row else "")),
                    "execution_status": status,
                    "elapsed_seconds": _number(execution.get("elapsed_seconds", row.elapsed_seconds if row else None)),
                    "evaluated": graded,
                    "passed": graded and all(value["success"] for value in metrics.values()),
                    "metrics": metrics,
                    "judge_model": judge_model,
                    "judge_reasoning_effort": judge_effort,
                    "metric_version": metric_version,
                    "evidence_file": evidence_file,
                    "preview_url": f"/api/local-benchmarks/preview/{quote(run_dir.name, safe='')}/{quote(tool, safe='')}" if preview else None,
                    "preview_unavailable_reason": preview_reason,
                })
    records.sort(key=lambda record: (record["created_at"], record["id"]), reverse=True)
    return {"records": records, "warnings": warnings}
