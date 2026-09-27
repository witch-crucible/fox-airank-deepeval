"""跨 run 稳定性分析：按「工具 + 配置身份 + case」聚合多次运行的分数波动。

只读取 `runs/<run-id>/run.json` 与 `runs/<run-id>/deepeval/<tool>/test_run_*.json`，
复用 `benchmark.report` 的收集逻辑与渲染原语，不依赖 deepeval，可离线重新生成。

单次分数只能说明“跑过一次”，不足以支撑“该配置适合日常使用”的结论；本模块按
配置身份聚合同一 case 的多次运行，给出样本数、均值、极差、标准差和通过率，
并用统一口径判定「样本不足 / 波动偏大 / 稳定失败 / 部分失败 / 稳定通过」。
"""

from __future__ import annotations

import json
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

from benchmark.report import (
    CATEGORY_LABELS,
    METRIC_ORDER,
    collect_run_report,
    escape_html,
    html_doc,
    html_table,
    iter_run_dirs,
)

DEFAULT_MIN_SAMPLES = 3
DEFAULT_MAX_RANGE = 0.2
REPORT_BASENAME = "stability-report"

VERDICT_UNRATED = "未评测"
VERDICT_INSUFFICIENT = "样本不足"
VERDICT_UNSTABLE = "波动偏大"
VERDICT_FAILING = "稳定失败"
VERDICT_PARTIAL = "部分失败"
VERDICT_STABLE = "稳定通过"

# 汇总区按“需要关注”的程度排序：越靠前越应先处理。
VERDICT_ORDER = (
    VERDICT_UNSTABLE,
    VERDICT_FAILING,
    VERDICT_PARTIAL,
    VERDICT_INSUFFICIENT,
    VERDICT_STABLE,
    VERDICT_UNRATED,
)

VERDICT_NOTES = {
    VERDICT_UNRATED: "从未产出有效评分，先检查执行与评分链路",
    VERDICT_INSUFFICIENT: f"有效样本少于 {DEFAULT_MIN_SAMPLES} 次，不足以判定稳定性",
    VERDICT_UNSTABLE: "同一配置多次运行的分数极差超过阈值，结果不可复现",
    VERDICT_FAILING: "样本充足且分数一致，但每次都未达到阈值",
    VERDICT_PARTIAL: "样本充足且分数一致，但存在未通过的运行",
    VERDICT_STABLE: "样本充足、分数一致且全部通过",
}


def validate_criteria(min_samples: int, max_range: float) -> None:
    """校验稳定性判定口径；非法值在进入扫描前就报错，避免产出误导性报告。"""
    if not isinstance(min_samples, int) or isinstance(min_samples, bool):
        raise ValueError("--min-samples 必须是整数")
    if min_samples < 1:
        raise ValueError("--min-samples 至少为 1")
    if not isinstance(max_range, (int, float)) or isinstance(max_range, bool):
        raise ValueError("--max-range 必须是数字")
    if not 0 <= float(max_range) <= 1:
        raise ValueError("--max-range 必须在 0 到 1 之间")


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if number == number and number not in (float("inf"), float("-inf")) else None


def _round(value: float, digits: int = 4) -> float:
    return round(value, digits)


def _read_manifest(run_dir: Path) -> dict[str, Any]:
    manifest_path = run_dir / "run.json"
    if not manifest_path.is_file():
        return {}
    try:
        value = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _metric_names(names: Sequence[str]) -> list[str]:
    known = [name for name in METRIC_ORDER if name in names]
    return known + sorted(name for name in names if name not in known)


def _metric_stats(values: Sequence[float], max_range: float) -> dict[str, Any]:
    mean = statistics.fmean(values)
    lowest, highest = min(values), max(values)
    spread = highest - lowest
    return {
        "samples": len(values),
        "mean": _round(mean),
        "min": _round(lowest),
        "max": _round(highest),
        "range": _round(spread),
        "stdev": _round(statistics.stdev(values)) if len(values) > 1 else 0.0,
        "stable": spread <= max_range,
    }


def _elapsed_stats(values: Sequence[float]) -> dict[str, Any]:
    return {
        "samples": len(values),
        "mean": _round(statistics.fmean(values), 3),
        "min": _round(min(values), 3),
        "max": _round(max(values), 3),
    }


def group_verdict(
    evaluated: int,
    passed: int,
    metrics: dict[str, dict[str, Any]],
    min_samples: int,
) -> str:
    """按统一口径给出一组运行的结论。

    判定顺序从“证据不足”到“证据可信”：先排除没有评分或样本不足的情况，
    再判断波动，最后才解释通过与失败，避免用不稳定的分数下稳定结论。
    """
    if evaluated <= 0:
        return VERDICT_UNRATED
    if evaluated < min_samples:
        return VERDICT_INSUFFICIENT
    if any(not entry["stable"] for entry in metrics.values()):
        return VERDICT_UNSTABLE
    if passed == 0:
        return VERDICT_FAILING
    if passed < evaluated:
        return VERDICT_PARTIAL
    return VERDICT_STABLE


def collect_stability(
    runs_root: Path,
    cases: Sequence[Any] | None = None,
    tools: Sequence[str] = (),
    case_ids: Sequence[str] = (),
    categories: Sequence[str] = (),
    min_samples: int = DEFAULT_MIN_SAMPLES,
    max_range: float = DEFAULT_MAX_RANGE,
) -> dict[str, Any]:
    """扫描 runs/ 下全部含评测产物的 run，按配置身份聚合输出稳定性报告。"""
    validate_criteria(min_samples, max_range)
    max_range = float(max_range)
    wanted_tools = set(tools)
    wanted_cases = set(case_ids)
    wanted_categories = set(categories)
    groups: dict[tuple[str, str, str, str, str], dict[str, Any]] = {}
    warnings: list[str] = []

    for run_dir in iter_run_dirs(runs_root):
        manifest = _read_manifest(run_dir)
        created_at = str(manifest.get("created_at") or "")
        try:
            run_report = collect_run_report(run_dir, (), cases)
        except ValueError as error:
            # 单个 run 的产物损坏不应中断整份稳定性报告。
            warnings.append(f"{run_dir.name}：{error}")
            continue
        for entry in run_report.get("tools", []):
            tool = str(entry.get("tool", ""))
            if wanted_tools and tool not in wanted_tools:
                continue
            for case in entry.get("cases", []):
                case_id = str(case.get("case_id", ""))
                category = str(case.get("category") or "")
                if wanted_cases and case_id not in wanted_cases:
                    continue
                if wanted_categories and category not in wanted_categories:
                    continue
                key = (
                    tool,
                    str(entry.get("agent") or "unknown"),
                    str(entry.get("model") or "unknown"),
                    str(entry.get("intelligence") or "unknown"),
                    case_id,
                )
                group = groups.setdefault(
                    key,
                    {
                        "attempts": 0,
                        "evaluated": 0,
                        "passed": 0,
                        "title": str(case.get("title") or ""),
                        "category": category,
                        "metric_values": {},
                        "elapsed_values": [],
                        "runs": [],
                    },
                )
                group["attempts"] += 1
                if not group["title"] and case.get("title"):
                    group["title"] = str(case["title"])
                if not group["category"] and category:
                    group["category"] = category

                scores: dict[str, float] = {}
                for name, metric in (case.get("metrics") or {}).items():
                    if not isinstance(metric, dict):
                        continue
                    value = _number(metric.get("score"))
                    if value is None or metric.get("error"):
                        continue
                    scores[str(name)] = value
                    group["metric_values"].setdefault(str(name), []).append(value)

                elapsed = _number(case.get("elapsed_seconds"))
                if elapsed is not None:
                    group["elapsed_values"].append(elapsed)

                evaluated = bool(case.get("evaluated")) and bool(scores)
                if evaluated:
                    group["evaluated"] += 1
                    if case.get("passed"):
                        group["passed"] += 1
                group["runs"].append(
                    {
                        "run_id": run_dir.name,
                        "created_at": created_at,
                        "execution_status": str(case.get("execution_status") or "missing"),
                        "evaluated": evaluated,
                        "passed": bool(evaluated and case.get("passed")),
                        "elapsed_seconds": elapsed,
                        "scores": {name: _round(value) for name, value in scores.items()},
                    }
                )

    rendered: list[dict[str, Any]] = []
    for key, group in sorted(groups.items(), key=lambda item: item[0]):
        tool, agent, model, intelligence, case_id = key
        metrics = {
            name: _metric_stats(values, max_range)
            for name, values in sorted(group["metric_values"].items())
        }
        elapsed_values = group["elapsed_values"]
        evaluated, passed = group["evaluated"], group["passed"]
        verdict = group_verdict(evaluated, passed, metrics, min_samples)
        group["runs"].sort(key=lambda item: (item["created_at"], item["run_id"]))
        rendered.append(
            {
                "tool": tool,
                "agent": agent,
                "model": model,
                "intelligence": intelligence,
                "case_id": case_id,
                "title": group["title"],
                "category": group["category"],
                "attempts": group["attempts"],
                "samples": evaluated,
                "passed": passed,
                "pass_rate": round(passed / evaluated, 4) if evaluated else None,
                "metrics": metrics,
                "elapsed_seconds": _elapsed_stats(elapsed_values) if elapsed_values else None,
                "verdict": verdict,
                "verdict_note": VERDICT_NOTES[verdict],
                "runs": group["runs"],
            }
        )

    rendered.sort(key=lambda item: (VERDICT_ORDER.index(item["verdict"]), item["tool"], item["case_id"]))
    summary = {verdict: sum(1 for item in rendered if item["verdict"] == verdict) for verdict in VERDICT_ORDER}
    summary["groups"] = len(rendered)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "runs_root": str(runs_root),
        "criteria": {"min_samples": min_samples, "max_range": max_range},
        "summary": summary,
        "warnings": warnings,
        "groups": rendered,
    }


def metric_names(report: dict[str, Any]) -> list[str]:
    names: list[str] = []
    for group in report.get("groups", []):
        for name in group.get("metrics", {}):
            if name not in names:
                names.append(name)
    return _metric_names(names)


def _format_score(value: float | int | None) -> str:
    return "—" if value is None else f"{float(value):.2f}"


def _format_duration(value: float | int | None) -> str:
    if value is None:
        return "—"
    seconds = float(value)
    return f"{seconds / 60:.1f}m" if seconds >= 60 else f"{seconds:.1f}s"


def _format_metric(entry: dict[str, Any] | None) -> str:
    if entry is None:
        return "—"
    text = f"{_format_score(entry['mean'])} ±{_format_score(entry['range'])}"
    return f"{text}{'' if entry['stable'] else ' ⚠'}"


def render_markdown(report: dict[str, Any]) -> str:
    criteria = report.get("criteria", {})
    lines: list[str] = ["# 跨 run 稳定性分析", ""]
    generated = report.get("generated_at")
    if generated:
        lines += [f"生成时间：{generated}", ""]
    lines += [
        f"判定口径：有效样本不少于 {criteria.get('min_samples', DEFAULT_MIN_SAMPLES)} 次才判定稳定性；"
        f"任一指标极差超过 {criteria.get('max_range', DEFAULT_MAX_RANGE)} 记为「{VERDICT_UNSTABLE}」。"
        "「均值 ±极差」中的 ⚠ 表示该指标波动超过阈值。",
        "",
    ]
    if not report.get("groups"):
        lines += ["runs/ 目录下没有找到任何可聚合的评测产物。", ""]
        return "\n".join(lines)

    lines += ["## 汇总", "", "| 结论 | 组数 | 说明 |", "|---|---|---|"]
    for verdict in VERDICT_ORDER:
        lines.append(f"| {verdict} | {report['summary'].get(verdict, 0)} | {VERDICT_NOTES[verdict]} |")

    names = metric_names(report)
    headers = ["工具", "Agent", "模型", "智能度", "Case", "分类", "样本", "通过", "通过率"]
    headers += [f"{name} 均值±极差" for name in names]
    headers += ["平均耗时", "结论"]
    lines += ["", "## 明细", "", "| " + " | ".join(headers) + " |", "|---" * len(headers) + "|"]
    for group in report["groups"]:
        rate = group.get("pass_rate")
        rate_text = f"{rate * 100:.0f}%" if rate is not None else "—"
        elapsed = group.get("elapsed_seconds")
        cells = [
            f"`{group['tool']}`",
            group["agent"],
            group["model"],
            group["intelligence"],
            f"`{group['case_id']}`",
            CATEGORY_LABELS.get(group["category"], group["category"] or "—"),
            str(group["samples"]),
            str(group["passed"]),
            rate_text,
        ]
        cells += [_format_metric(group["metrics"].get(name)) for name in names]
        cells += [_format_duration(elapsed["mean"] if elapsed else None), group["verdict"]]
        lines.append("| " + " | ".join(cells) + " |")

    for group in report["groups"]:
        if group["verdict"] in (VERDICT_STABLE,):
            continue
        lines += ["", f"### {group['tool']} / {group['case_id']}：{group['verdict']}", "",
                  f"- 配置：{group['agent']} / {group['model']}"
                  + (f"（{group['intelligence']}）" if group["intelligence"] != "unknown" else "")]
        lines.append(f"- 说明：{group['verdict_note']}")
        lines += ["", "| Run | 创建时间 | 执行状态 | 通过 | 耗时 | "
                  + " | ".join(names) + " |", "|---" * (5 + len(names)) + "|"] if names else \
                 ["", "| Run | 创建时间 | 执行状态 | 通过 | 耗时 |", "|---|---|---|---|---|"]
        for run in group["runs"]:
            cells = [
                f"`{run['run_id']}`",
                run["created_at"] or "—",
                run["execution_status"],
                "✅" if run["passed"] else ("—" if not run["evaluated"] else "❌"),
                _format_duration(run["elapsed_seconds"]),
            ]
            if names:
                cells += [_format_score(run["scores"].get(name)) for name in names]
            lines.append("| " + " | ".join(cells) + " |")

    if report.get("warnings"):
        lines += ["", "## 扫描告警", ""]
        lines += [f"- {warning}" for warning in report["warnings"]]
    lines.append("")
    return "\n".join(lines)


def render_html(report: dict[str, Any]) -> str:
    """渲染稳定性分析的静态页面（自包含 HTML，内联 CSS，无外部依赖）。"""
    criteria = report.get("criteria", {})
    body = ["<h1>跨 run 稳定性分析</h1>"]
    if report.get("generated_at"):
        body.append(f'<p class="meta">生成时间：{escape_html(report["generated_at"])}</p>')
    body.append(
        '<p class="note">判定口径：有效样本不少于 '
        f'{escape_html(criteria.get("min_samples", DEFAULT_MIN_SAMPLES))} 次才判定稳定性；'
        f'任一指标极差超过 {escape_html(criteria.get("max_range", DEFAULT_MAX_RANGE))} '
        f'记为「{VERDICT_UNSTABLE}」。</p>'
    )
    if not report.get("groups"):
        body.append('<p class="note">runs/ 目录下没有找到任何可聚合的评测产物。</p>')
        return html_doc("跨 run 稳定性分析", "\n".join(body))

    summary_rows = [
        [escape_html(verdict), str(report["summary"].get(verdict, 0)), escape_html(VERDICT_NOTES[verdict])]
        for verdict in VERDICT_ORDER
    ]
    body += ["<h2>汇总</h2>", html_table(["结论", "组数", "说明"], summary_rows)]

    names = metric_names(report)
    headers = ["工具", "Agent", "模型", "智能度", "Case", "分类", "样本", "通过", "通过率"]
    headers += [f"{name} 均值±极差" for name in names]
    headers += ["平均耗时", "结论"]
    rows: list[list[str]] = []
    for group in report["groups"]:
        rate = group.get("pass_rate")
        elapsed = group.get("elapsed_seconds")
        cells = [
            f'<code>{escape_html(group["tool"])}</code>',
            escape_html(group["agent"]),
            escape_html(group["model"]),
            escape_html(group["intelligence"]),
            f'<code>{escape_html(group["case_id"])}</code>',
            escape_html(CATEGORY_LABELS.get(group["category"], group["category"] or "—")),
            str(group["samples"]),
            str(group["passed"]),
            escape_html(f"{rate * 100:.0f}%" if rate is not None else "—"),
        ]
        cells += [escape_html(_format_metric(group["metrics"].get(name))) for name in names]
        cells += [escape_html(_format_duration(elapsed["mean"] if elapsed else None)),
                  escape_html(group["verdict"])]
        rows.append(cells)
    body += ["<h2>明细</h2>", html_table(headers, rows)]

    for group in report["groups"]:
        if group["verdict"] == VERDICT_STABLE:
            continue
        identity = f'{group["agent"]} / {group["model"]}'
        if group["intelligence"] != "unknown":
            identity += f'（{group["intelligence"]}）'
        body.append(f'<h2>{escape_html(group["tool"])} / {escape_html(group["case_id"])}：'
                    f'{escape_html(group["verdict"])}</h2>')
        body.append('<ul class="summary-list">'
                    f'<li>配置：{escape_html(identity)}</li>'
                    f'<li>说明：{escape_html(group["verdict_note"])}</li></ul>')
        run_headers = ["Run", "创建时间", "执行状态", "通过", "耗时"] + list(names)
        run_rows: list[list[str]] = []
        for run in group["runs"]:
            cells = [
                f'<code>{escape_html(run["run_id"])}</code>',
                escape_html(run["created_at"] or "—"),
                escape_html(run["execution_status"]),
                escape_html("✅" if run["passed"] else ("—" if not run["evaluated"] else "❌")),
                escape_html(_format_duration(run["elapsed_seconds"])),
            ]
            cells += [escape_html(_format_score(run["scores"].get(name))) for name in names]
            run_rows.append(cells)
        body.append(html_table(run_headers, run_rows))

    if report.get("warnings"):
        body.append("<h2>扫描告警</h2>")
        body.append('<ul class="summary-list">'
                    + "".join(f"<li>{escape_html(warning)}</li>" for warning in report["warnings"])
                    + "</ul>")
    return html_doc("跨 run 稳定性分析", "\n".join(body))


def write_stability_report(
    runs_root: Path,
    cases: Sequence[Any] | None = None,
    tools: Sequence[str] = (),
    case_ids: Sequence[str] = (),
    categories: Sequence[str] = (),
    min_samples: int = DEFAULT_MIN_SAMPLES,
    max_range: float = DEFAULT_MAX_RANGE,
    formats: Sequence[str] = ("md", "html"),
) -> dict[str, Any]:
    """生成并写入 runs/stability-report.json 及所选格式的报告文件。"""
    validate_criteria(min_samples, max_range)
    report = collect_stability(
        runs_root,
        cases,
        tools=tools,
        case_ids=case_ids,
        categories=categories,
        min_samples=min_samples,
        max_range=max_range,
    )
    runs_root.mkdir(parents=True, exist_ok=True)
    (runs_root / f"{REPORT_BASENAME}.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if "md" in formats:
        (runs_root / f"{REPORT_BASENAME}.md").write_text(render_markdown(report), encoding="utf-8")
    if "html" in formats:
        (runs_root / f"{REPORT_BASENAME}.html").write_text(render_html(report), encoding="utf-8")
    return report
