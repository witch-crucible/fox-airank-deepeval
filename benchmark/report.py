"""汇总 DeepEval 评测产物：跨工具 × case 对比矩阵与跨 run 历史对比。

只读取 `runs/<run-id>/deepeval/<tool>/test_run_*.json`（DeepEval TestRun 导出），
不依赖 deepeval 本身，可在评测完成后离线生成报告。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

METRIC_SUFFIX = " [GEval]"
TEST_RUN_PATTERN = re.compile(r"^test_run_(\d{8}_\d{6})\.json$")
METRIC_ORDER = ("Task Correctness", "Robustness, Safety and Regression", "Delivery Evidence")

CATEGORY_LABELS = {
    "code_correction": "代码修正",
    "code_generation": "代码生成",
    "logic_analysis": "逻辑分析",
    "magento_business": "Magento 业务测试",
}

MODEL_TEST_WEIGHTS = {
    "correction": 3,
    "generation": 4,
    "logic": 8,
}
CATEGORY_TO_MODEL_TEST = {
    "code_correction": "correction",
    "code_generation": "generation",
    "logic_analysis": "logic",
}
MODEL_TEST_CATEGORY_FIELD = {
    "model_test_correction": "code_correction",
    "model_test_generation": "code_generation",
    "model_test_logic": "logic_analysis",
}


@dataclass(frozen=True)
class CaseRow:
    """一个 case 在一个工具下的评测结果。"""

    case_id: str
    title: str
    category: str
    metrics: dict[str, dict[str, Any]] = field(default_factory=dict)
    passed: bool = False
    evaluated: bool = False
    execution_status: str = "missing"
    elapsed_seconds: float | None = None
    timeout_seconds: float | None = None

    def metric_score(self, name: str) -> float | None:
        entry = self.metrics.get(name)
        if entry is None:
            return None
        return entry.get("score")

    @property
    def time_score(self) -> float | None:
        return execution_time_score(
            self.execution_status, self.elapsed_seconds, self.timeout_seconds
        )


@dataclass(frozen=True)
class ToolSummary:
    """一个工具在一次 run 中的汇总。"""

    tool: str
    agent: str
    model: str
    intelligence: str
    test_run_file: str | None
    run_duration_seconds: float | None
    judge_model: str | None
    metric_version: str | None
    rows: list[CaseRow] = field(default_factory=list)

    @property
    def evaluated(self) -> int:
        return sum(1 for row in self.rows if row.evaluated)

    @property
    def passed(self) -> int:
        return sum(1 for row in self.rows if row.evaluated and row.passed)

    @property
    def pass_rate(self) -> float | None:
        if self.evaluated == 0:
            return None
        return self.passed / self.evaluated

    def metric_average(self, name: str) -> float | None:
        scores = [
            row.metrics[name]["score"]
            for row in self.rows
            if name in row.metrics and isinstance(row.metrics[name].get("score"), (int, float))
        ]
        if not scores:
            return None
        return sum(scores) / len(scores)

    @property
    def total_execution_seconds(self) -> float | None:
        values = [row.elapsed_seconds for row in self.rows if isinstance(row.elapsed_seconds, (int, float))]
        return round(sum(values), 3) if values else None

    @property
    def average_execution_seconds(self) -> float | None:
        values = [row.elapsed_seconds for row in self.rows if isinstance(row.elapsed_seconds, (int, float))]
        return round(sum(values) / len(values), 3) if values else None

    @property
    def average_time_score(self) -> float | None:
        values = [row.time_score for row in self.rows if row.time_score is not None]
        return round(sum(values) / len(values), 2) if values else None

    def category_pass_rate(self, category: str) -> float | None:
        rows = [row for row in self.rows if row.evaluated and row.category == category]
        if not rows:
            return None
        passed = sum(1 for row in rows if row.passed)
        return passed / len(rows)

    def model_test_score(self, category_key: str) -> float | None:
        """Average Task Correctness in 0–1, scaled to 0–100, for a model_test category."""
        categories = [cat for cat, key in CATEGORY_TO_MODEL_TEST.items() if key == category_key]
        rows = [
            row
            for row in self.rows
            if row.evaluated and row.category in categories
        ]
        scores = [
            row.metric_score("Task Correctness")
            for row in rows
            if row.metric_score("Task Correctness") is not None
        ]
        if not scores:
            return None
        return round(sum(scores) / len(scores) * 100, 2)

    @property
    def model_test_breakdown(self) -> dict[str, float | None]:
        return {
            "correction": self.model_test_score("correction"),
            "generation": self.model_test_score("generation"),
            "logic": self.model_test_score("logic"),
        }

    @property
    def model_test_total(self) -> float | None:
        """Weighted average of per-category model_test scores (0–100), same weights as dashboard."""
        breakdown = self.model_test_breakdown
        parts = {key: breakdown[key] for key in MODEL_TEST_WEIGHTS}
        if any(value is not None for value in parts.values()):
            weighted = sum(
                (float(value or 0)) * weight for value, weight in zip(parts.values(), MODEL_TEST_WEIGHTS.values())
            ) / sum(MODEL_TEST_WEIGHTS.values())
            return round(weighted, 2)
        return None


def _canonical_metric_name(name: str) -> str:
    return name[: -len(METRIC_SUFFIX)] if name.endswith(METRIC_SUFFIX) else name


def execution_time_score(
    status: str,
    elapsed_seconds: float | None,
    timeout_seconds: float | None,
) -> float | None:
    """将单 case 执行耗时换算为独立的 0–100 效率分。"""
    if not isinstance(elapsed_seconds, (int, float)) or not isinstance(timeout_seconds, (int, float)):
        return None
    if timeout_seconds <= 0:
        return None
    if status != "completed":
        return 0.0
    ratio = max(0.0, min(1.0, float(elapsed_seconds) / float(timeout_seconds)))
    return round((1.0 - ratio) * 100, 2)


def _ordered_metrics(names: Sequence[str]) -> list[str]:
    known = [name for name in METRIC_ORDER if name in names]
    return known + sorted(name for name in names if name not in known)


def latest_test_run(tool_dir: Path) -> Path | None:
    """返回该工具目录下时间戳最新的 TestRun JSON（与 DeepEval 文件名规则一致）。"""
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


def load_test_run(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _identity_from_manifest(manifest: dict[str, Any], tool: str) -> dict[str, str]:
    identity = manifest.get("identities", {}).get(tool, {})
    if isinstance(identity, dict):
        return {
            "agent": str(identity.get("agent") or "unknown"),
            "model": str(identity.get("model") or "unknown"),
            "intelligence": str(identity.get("intelligence") or "unknown"),
        }
    return {"agent": "unknown", "model": "unknown", "intelligence": "unknown"}


def collect_tool_summary(
    run_dir: Path,
    tool: str,
    case_registry: dict[str, dict[str, str]] | None = None,
    run_manifest: dict[str, Any] | None = None,
) -> ToolSummary:
    """从 runs/<run-id>/deepeval/<tool>/ 读取该工具的评测结果。"""
    registry = case_registry or {}
    manifest = run_manifest or {}
    tool_dir = run_dir / "deepeval" / tool
    test_run_path = latest_test_run(tool_dir)
    identity = _identity_from_manifest(manifest, tool)
    rows: list[CaseRow] = []
    duration: float | None = None
    judge_model: str | None = None
    metric_version: str | None = None
    if test_run_path is not None:
        data = load_test_run(test_run_path)
        hyperparameters = data.get("hyperparameters") or {}
        judge_model = hyperparameters.get("judge_model")
        metric_version = hyperparameters.get("metric_version")
        duration = data.get("runDuration")
        for entry in data.get("testCases", []):
            metadata = entry.get("metadata") or {}
            case_id = str(metadata.get("case_id") or entry.get("name") or "unknown")
            metrics: dict[str, dict[str, Any]] = {}
            for metric in entry.get("metricsData", []):
                metrics[_canonical_metric_name(str(metric.get("name", "")))] = {
                    "score": metric.get("score"),
                    "threshold": metric.get("threshold"),
                    "success": bool(metric.get("success")),
                    "error": metric.get("error"),
                    "reason": metric.get("reason"),
                }
            fallback_identity = str(metadata.get("agent_identity") or "")
            if identity["agent"] == "unknown" and "/" in fallback_identity:
                identity = {"agent": fallback_identity, "model": "unknown", "intelligence": "unknown"}
            evaluated = bool(metrics)
            info = registry.get(case_id, {})
            rows.append(
                CaseRow(
                    case_id=case_id,
                    title=str(info.get("title", "")),
                    category=str(metadata.get("category") or info.get("category", "")),
                    metrics=metrics,
                    passed=evaluated and all(item["success"] for item in metrics.values()),
                    evaluated=evaluated,
                    execution_status=str(metadata.get("execution_status", "missing")),
                    elapsed_seconds=metadata.get("elapsed_seconds"),
                    timeout_seconds=metadata.get("timeout_seconds"),
                )
            )
    return ToolSummary(
        tool=tool,
        agent=identity["agent"],
        model=identity["model"],
        intelligence=identity["intelligence"],
        test_run_file=test_run_path.name if test_run_path else None,
        run_duration_seconds=duration,
        judge_model=judge_model,
        metric_version=metric_version,
        rows=rows,
    )


def collect_run_report(run_dir: Path, tools: Sequence[str], cases: Sequence[Any] | None = None) -> dict[str, Any]:
    """汇总一次 run 的全部工具结果，返回可序列化字典。"""
    registry = {
        case.id: {"title": case.title, "category": case.category}
        for case in (cases or [])
    }
    manifest_path = run_dir / "run.json"
    manifest: dict[str, Any] = {}
    if manifest_path.is_file():
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            manifest = {}
    manifest_tools = [name for name in manifest.get("tools", []) if isinstance(name, str)]
    ordered_tools = list(dict.fromkeys([*tools, *manifest_tools]))
    summaries = [collect_tool_summary(run_dir, tool, registry, manifest) for tool in ordered_tools]
    return {
        "run_id": run_dir.name,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "tools": [_summary_to_dict(summary) for summary in summaries],
    }


def _summary_to_dict(summary: ToolSummary) -> dict[str, Any]:
    return {
        "tool": summary.tool,
        "agent": summary.agent,
        "model": summary.model,
        "intelligence": summary.intelligence,
        "test_run_file": summary.test_run_file,
        "run_duration_seconds": summary.run_duration_seconds,
        "judge_model": summary.judge_model,
        "metric_version": summary.metric_version,
        "execution_timing": {
            "total_elapsed_seconds": summary.total_execution_seconds,
            "average_elapsed_seconds": summary.average_execution_seconds,
            "average_time_score": summary.average_time_score,
        },
        "summary": {
            "evaluated": summary.evaluated,
            "passed": summary.passed,
            "pass_rate": summary.pass_rate,
            "metric_averages": {
                name: summary.metric_average(name) for name in _row_metric_names(summary.rows)
            },
        },
        "category_stats": _category_stats_dict(summary),
        "model_test": {
            "correction": summary.model_test_score("correction"),
            "generation": summary.model_test_score("generation"),
            "logic": summary.model_test_score("logic"),
            "total": summary.model_test_total,
        },
        "cases": [
            {
                "case_id": row.case_id,
                "title": row.title,
                "category": row.category,
                "passed": row.passed,
                "evaluated": row.evaluated,
                "execution_status": row.execution_status,
                "elapsed_seconds": row.elapsed_seconds,
                "timeout_seconds": row.timeout_seconds,
                "time_score": row.time_score,
                "metrics": row.metrics,
            }
            for row in summary.rows
        ],
    }


def _category_stats_dict(summary: ToolSummary) -> dict[str, dict[str, Any]]:
    stats: dict[str, dict[str, Any]] = {}
    for category in CATEGORY_LABELS:
        rows = [row for row in summary.rows if row.category == category]
        evaluated = sum(1 for row in rows if row.evaluated)
        passed = sum(1 for row in rows if row.evaluated and row.passed)
        stats[category] = {
            "evaluated": evaluated,
            "passed": passed,
            "pass_rate": passed / evaluated if evaluated else None,
        }
    return stats


def _row_metric_names(rows: Sequence[CaseRow]) -> list[str]:
    names: set[str] = set()
    for row in rows:
        names.update(row.metrics)
    return _ordered_metrics(names)


def _iter_run_dirs(runs_root: Path) -> list[Path]:
    if not runs_root.is_dir():
        return []
    return sorted(
        (path for path in runs_root.iterdir() if path.is_dir() and (path / "deepeval").is_dir()),
        key=lambda path: path.name,
    )


def collect_history(runs_root: Path, cases: Sequence[Any] | None = None) -> list[dict[str, Any]]:
    """扫描 runs/ 下所有含评测产物的 run，输出跨 run 历史对比。

    只保留至少有一个工具存在评测结果的 run；完全空的 run 不进入历史。
    """
    reports = []
    for run_dir in _iter_run_dirs(runs_root):
        report = collect_run_report(run_dir, (), cases)
        if any(tool["cases"] for tool in report["tools"]):
            reports.append(report)
    return reports


def _format_score(value: float | int | None) -> str:
    if value is None:
        return "—"
    return f"{float(value):.2f}"


def _format_duration(value: float | int | None) -> str:
    if not isinstance(value, (int, float)):
        return "—"
    seconds = float(value)
    if seconds >= 60:
        minutes = seconds / 60
        return f"{minutes:.1f}m"
    return f"{seconds:.1f}s"


def _format_cell(row: CaseRow, name: str) -> str:
    entry = row.metrics.get(name)
    if entry is None:
        return "未评测" if row.evaluated else "—"
    if not isinstance(entry.get("score"), (int, float)):
        return "错误"
    mark = "✓" if entry.get("success") else "✗"
    return f"{entry['score']:.2f} {mark}"


def _case_row_from_dict(case: dict[str, Any]) -> CaseRow:
    return CaseRow(
        case_id=str(case.get("case_id", "")),
        title=str(case.get("title", "")),
        category=str(case.get("category", "")),
        metrics=case.get("metrics", {}),
        passed=bool(case.get("passed", False)),
        evaluated=bool(case.get("evaluated", False)),
        execution_status=str(case.get("execution_status", "missing")),
        elapsed_seconds=case.get("elapsed_seconds"),
        timeout_seconds=case.get("timeout_seconds"),
    )


def _report_metric_names(report: dict[str, Any]) -> list[str]:
    names: list[str] = []
    for tool in report["tools"]:
        for name in (tool.get("summary", {}).get("metric_averages") or {}):
            if name not in names:
                names.append(name)
    return names


def render_markdown(report: dict[str, Any]) -> str:
    lines: list[str] = [f"# 评测对比报告：{report['run_id']}", ""]
    generated = report.get("generated_at")
    if generated:
        lines += [f"生成时间：{generated}", ""]
    if not any(tool["cases"] for tool in report["tools"]):
        lines += ["该 run 目录下没有找到任何 DeepEval 评测产物（deepeval/<tool>/test_run_*.json）。", ""]
        return "\n".join(lines)
    metric_names = _report_metric_names(report)

    lines += [
        "耗时分按 `max(0, 100 × (1 - 执行耗时 / 超时上限))` 计算；仅正常完成的执行计分，失败或超时为 0。"
        "耗时分独立展示，不改变现有 GEval 通过判定和 ModelTest 总分。",
        "",
    ]
    lines += ["## 汇总", "", "| 工具 | Agent | 模型 | 智能度 | 通过 / 评测 | 通过率 | "
              + " | ".join(f"{name} 均分" for name in metric_names)
              + " | 平均执行耗时 | 耗时分 | ModelTest 修正 | ModelTest 生成 | ModelTest 逻辑 | ModelTest 总分 |",
              "|---" * (12 + len(metric_names)) + "|"]
    for tool in report["tools"]:
        summary = tool.get("summary", {})
        evaluated = summary.get("evaluated", 0)
        passed = summary.get("passed", 0)
        rate = summary.get("pass_rate")
        averages = summary.get("metric_averages", {})
        rate_text = f"{rate * 100:.0f}%" if rate is not None else "—"
        mt = tool.get("model_test", {})
        timing = tool.get("execution_timing", {})
        cells = [tool["tool"], tool.get("agent", "unknown"), tool.get("model", "unknown"),
                 tool.get("intelligence", "unknown"), f"{passed} / {evaluated}", rate_text]
        cells += [_format_score(averages.get(name)) for name in metric_names]
        cells += [_format_duration(timing.get("average_elapsed_seconds")),
                  _format_score(timing.get("average_time_score"))]
        cells += [_format_score(mt.get("correction")), _format_score(mt.get("generation")),
                  _format_score(mt.get("logic")), _format_score(mt.get("total"))]
        lines.append("| " + " | ".join(cells) + " |")

    for tool in report["tools"]:
        lines += ["", f"## {tool['tool']}", ""]
        identity = f"{tool.get('agent', 'unknown')} / {tool.get('model', 'unknown')}"
        if tool.get("intelligence") not in (None, "", "unknown"):
            identity += f"（{tool['intelligence']}）"
        lines += [f"- Agent / 模型：{identity}"]
        if tool.get("run_duration_seconds") is not None:
            lines.append(f"- 裁判评测耗时：{tool['run_duration_seconds']:.1f}s")
        timing = tool.get("execution_timing", {})
        if timing.get("total_elapsed_seconds") is not None:
            lines.append(
                f"- 代理执行耗时：总计 {_format_duration(timing.get('total_elapsed_seconds'))}，"
                f"平均 {_format_duration(timing.get('average_elapsed_seconds'))}，"
                f"平均耗时分 {_format_score(timing.get('average_time_score'))}"
            )
        if tool.get("judge_model"):
            lines.append(f"- 裁判模型：{tool['judge_model']}")
        if tool.get("metric_version"):
            lines.append(f"- 指标版本：{tool['metric_version']}")
        mt = tool.get("model_test", {})
        if mt:
            lines.append(
                f"- ModelTest：修正 {_format_score(mt.get('correction'))}，"
                f"生成 {_format_score(mt.get('generation'))}，"
                f"逻辑 {_format_score(mt.get('logic'))}，"
                f"总分 {_format_score(mt.get('total'))}"
            )
        cat_stats = tool.get("category_stats", {})
        if cat_stats:
            cat_parts = []
            for cat in CATEGORY_LABELS:
                stat = cat_stats.get(cat, {})
                if stat.get("evaluated"):
                    rate = stat.get("pass_rate")
                    cat_parts.append(f"{CATEGORY_LABELS.get(cat, cat)} {stat['passed']}/{stat['evaluated']} ({rate * 100:.0f}%)" if rate is not None else f"{CATEGORY_LABELS.get(cat, cat)} {stat['passed']}/{stat['evaluated']}")
            if cat_parts:
                lines.append(f"- 分类通过：{', '.join(cat_parts)}")
        lines += ["", "| Case | 分类 | " + " | ".join(metric_names) + " | 执行耗时 / 上限 | 耗时分 | 执行状态 | 结论 |",
                  "|---" * (6 + len(metric_names)) + "|"]
        for case in tool.get("cases", []):
            row = _case_row_from_dict(case)
            label = f"`{row.case_id}`"
            if row.title:
                label += f" {row.title}"
            category = CATEGORY_LABELS.get(row.category, row.category or "—")
            cells = [label, category] + [_format_cell(row, name) for name in metric_names]
            conclusion = "—" if not row.evaluated else ("✅ 通过" if row.passed else "❌ 未通过")
            duration = f"{_format_duration(row.elapsed_seconds)} / {_format_duration(row.timeout_seconds)}"
            cells += [duration, _format_score(row.time_score), row.execution_status, conclusion]
            lines.append("| " + " | ".join(cells) + " |")
    lines.append("")
    return "\n".join(lines)


def render_history_markdown(history: list[dict[str, Any]]) -> str:
    lines: list[str] = ["# 跨 run 历史对比", ""]
    if not history:
        lines += ["runs/ 目录下没有找到任何评测产物。", ""]
        return "\n".join(lines)
    metric_names: list[str] = []
    for report in history:
        for tool in report["tools"]:
            for name in (tool.get("summary", {}).get("metric_averages") or {}):
                if name not in metric_names:
                    metric_names.append(name)
    lines += ["| Run | 工具 | Agent | 模型 | 智能度 | 通过 / 评测 | 通过率 | "
              + " | ".join(f"{name} 均分" for name in metric_names)
              + " | 平均执行耗时 | 耗时分 | ModelTest 总分 |",
              "|---" * (10 + len(metric_names)) + "|"]
    for report in history:
        for tool in report["tools"]:
            summary = tool.get("summary", {})
            evaluated = summary.get("evaluated", 0)
            passed = summary.get("passed", 0)
            rate = summary.get("pass_rate")
            rate_text = f"{rate * 100:.0f}%" if rate is not None else "—"
            averages = summary.get("metric_averages", {})
            mt_total = tool.get("model_test", {}).get("total")
            timing = tool.get("execution_timing", {})
            cells = [report["run_id"], tool["tool"], tool.get("agent", "unknown"),
                     tool.get("model", "unknown"), tool.get("intelligence", "unknown"),
                     f"{passed} / {evaluated}", rate_text]
            cells += [_format_score(averages.get(name)) for name in metric_names]
            cells += [_format_duration(timing.get("average_elapsed_seconds")),
                      _format_score(timing.get("average_time_score"))]
            cells += [_format_score(mt_total)]
            lines.append("| " + " | ".join(cells) + " |")
    lines.append("")
    return "\n".join(lines)


def write_run_report(run_dir: Path, tools: Sequence[str], cases: Sequence[Any] | None = None) -> dict[str, Any]:
    """生成并写入 runs/<run-id>/report.json 与 report.md，返回报告数据。"""
    report = collect_run_report(run_dir, tools, cases)
    (run_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (run_dir / "report.md").write_text(render_markdown(report), encoding="utf-8")
    return report


def write_history_report(runs_root: Path, cases: Sequence[Any] | None = None) -> list[dict[str, Any]]:
    """生成并写入 runs/history-report.json 与 history-report.md。"""
    history = collect_history(runs_root, cases)
    (runs_root / "history-report.json").write_text(
        json.dumps({"generated_at": datetime.now(timezone.utc).isoformat(), "runs": history},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (runs_root / "history-report.md").write_text(render_history_markdown(history), encoding="utf-8")
    return history
