import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from benchmark import cli
from benchmark.stability import (
    DEFAULT_MAX_RANGE,
    DEFAULT_MIN_SAMPLES,
    VERDICT_FAILING,
    VERDICT_INSUFFICIENT,
    VERDICT_PARTIAL,
    VERDICT_STABLE,
    VERDICT_UNRATED,
    VERDICT_UNSTABLE,
    collect_stability,
    render_html,
    render_markdown,
    validate_criteria,
    write_stability_report,
)

METRIC_THRESHOLDS = {
    "Task Correctness [GEval]": 0.8,
    "Robustness, Safety and Regression [GEval]": 0.7,
    "Delivery Evidence [GEval]": 0.7,
}


def metric_entry(name: str, score: float) -> dict:
    threshold = METRIC_THRESHOLDS.get(name, 0.7)
    return {
        "name": name,
        "threshold": threshold,
        "success": score >= threshold,
        "score": score,
        "reason": "单元测试固定理由",
    }


def build_run(
    root: Path,
    run_id: str,
    tool: str,
    case_id: str,
    scores: dict[str, float],
    created_at: str,
    *,
    category: str = "code_generation",
    identity: dict | None = None,
    stamp: str | None = None,
) -> Path:
    run_dir = root / run_id
    tool_dir = run_dir / "deepeval" / tool
    tool_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "testCases": [
            {
                "name": f"{tool}/{case_id}",
                "metricsData": [metric_entry(name, score) for name, score in scores.items()],
                "metadata": {
                    "tool": tool,
                    "case_id": case_id,
                    "category": category,
                    "execution_status": "completed",
                    "elapsed_seconds": 30.0,
                    "timeout_seconds": 1800,
                },
            }
        ],
        "hyperparameters": {"judge_model": "gpt-5.6-sol"},
        "runDuration": 1.0,
    }
    (tool_dir / f"test_run_{stamp or '20260829_090000'}.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )
    manifest = {"created_at": created_at, "tools": [tool], "cases": [case_id]}
    if identity:
        manifest["identities"] = {tool: identity}
    (run_dir / "run.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    return run_dir


IDENTITY = {"agent": "Codex CLI", "model": "gpt-5.6-sol", "intelligence": "high"}
PASSING = {"Task Correctness [GEval]": 0.9, "Robustness, Safety and Regression [GEval]": 0.9,
           "Delivery Evidence [GEval]": 0.9}


def first_group(report: dict) -> dict:
    groups = report["groups"]
    assert groups, "预期至少生成一个聚合分组"
    return groups[0]


class CriteriaTests(unittest.TestCase):
    def test_rejects_invalid_criteria(self):
        with self.assertRaisesRegex(ValueError, "至少为 1"):
            validate_criteria(0, DEFAULT_MAX_RANGE)
        with self.assertRaisesRegex(ValueError, "0 到 1 之间"):
            validate_criteria(DEFAULT_MIN_SAMPLES, 1.5)
        with self.assertRaisesRegex(ValueError, "0 到 1 之间"):
            validate_criteria(DEFAULT_MIN_SAMPLES, -0.1)

    def test_accepts_default_criteria(self):
        validate_criteria(DEFAULT_MIN_SAMPLES, DEFAULT_MAX_RANGE)


class VerdictTests(unittest.TestCase):
    def test_stable_pass(self):
        with TemporaryDirectory() as raw:
            root = Path(raw)
            for index in range(3):
                build_run(root, f"run-{index}", "codex", "draw-pelican-bicycle", PASSING,
                          f"2026-08-0{index + 1}T00:00:00+00:00", identity=IDENTITY)
            group = first_group(collect_stability(root))
            self.assertEqual(group["verdict"], VERDICT_STABLE)
            self.assertEqual(group["samples"], 3)
            self.assertEqual(group["pass_rate"], 1.0)

    def test_insufficient_samples(self):
        with TemporaryDirectory() as raw:
            root = Path(raw)
            for index in range(2):
                build_run(root, f"run-{index}", "codex", "draw-pelican-bicycle", PASSING,
                          f"2026-08-0{index + 1}T00:00:00+00:00", identity=IDENTITY)
            self.assertEqual(first_group(collect_stability(root))["verdict"], VERDICT_INSUFFICIENT)

    def test_unstable_when_range_exceeds_threshold(self):
        with TemporaryDirectory() as raw:
            root = Path(raw)
            scores = [0.95, 0.95, 0.7]
            for index, score in enumerate(scores):
                build_run(root, f"run-{index}", "codex", "draw-pelican-bicycle",
                          {"Task Correctness [GEval]": score,
                           "Robustness, Safety and Regression [GEval]": 0.9,
                           "Delivery Evidence [GEval]": 0.9},
                          f"2026-08-0{index + 1}T00:00:00+00:00", identity=IDENTITY)
            group = first_group(collect_stability(root))
            self.assertEqual(group["verdict"], VERDICT_UNSTABLE)
            self.assertFalse(group["metrics"]["Task Correctness"]["stable"])
            self.assertAlmostEqual(group["metrics"]["Task Correctness"]["range"], 0.25)

    def test_stable_failure(self):
        with TemporaryDirectory() as raw:
            root = Path(raw)
            failing = {name: 0.5 for name in PASSING}
            for index in range(3):
                build_run(root, f"run-{index}", "codex", "draw-pelican-bicycle", failing,
                          f"2026-08-0{index + 1}T00:00:00+00:00", identity=IDENTITY)
            group = first_group(collect_stability(root))
            self.assertEqual(group["verdict"], VERDICT_FAILING)
            self.assertEqual(group["pass_rate"], 0.0)

    def test_partial_failure(self):
        with TemporaryDirectory() as raw:
            root = Path(raw)
            # 分数波动 0.06（未超过阈值），但其中一次未达到 Task Correctness 阈值
            scores = [0.85, 0.85, 0.79]
            for index, score in enumerate(scores):
                build_run(root, f"run-{index}", "codex", "draw-pelican-bicycle",
                          {"Task Correctness [GEval]": score,
                           "Robustness, Safety and Regression [GEval]": 0.9,
                           "Delivery Evidence [GEval]": 0.9},
                          f"2026-08-0{index + 1}T00:00:00+00:00", identity=IDENTITY)
            group = first_group(collect_stability(root))
            self.assertEqual(group["verdict"], VERDICT_PARTIAL)
            self.assertEqual(group["passed"], 2)

    def test_unrated_without_metrics(self):
        with TemporaryDirectory() as raw:
            root = Path(raw)
            build_run(root, "run-0", "codex", "draw-pelican-bicycle", {},
                      "2026-08-01T00:00:00+00:00", identity=IDENTITY)
            group = first_group(collect_stability(root))
            self.assertEqual(group["verdict"], VERDICT_UNRATED)
            self.assertEqual(group["samples"], 0)
            self.assertEqual(group["attempts"], 1)

    def test_custom_min_samples_changes_verdict(self):
        with TemporaryDirectory() as raw:
            root = Path(raw)
            for index in range(2):
                build_run(root, f"run-{index}", "codex", "draw-pelican-bicycle", PASSING,
                          f"2026-08-0{index + 1}T00:00:00+00:00", identity=IDENTITY)
            report = collect_stability(root, min_samples=2)
            self.assertEqual(first_group(report)["verdict"], VERDICT_STABLE)


class CollectionTests(unittest.TestCase):
    def test_groups_by_configuration_identity(self):
        with TemporaryDirectory() as raw:
            root = Path(raw)
            build_run(root, "run-a", "codex", "draw-pelican-bicycle", PASSING,
                      "2026-08-01T00:00:00+00:00",
                      identity={"agent": "Codex CLI", "model": "gpt-5.6-sol", "intelligence": "high"},
                      stamp="20260801_090000")
            build_run(root, "run-b", "codex", "draw-pelican-bicycle", PASSING,
                      "2026-08-02T00:00:00+00:00",
                      identity={"agent": "Codex CLI", "model": "gpt-5.6-sol", "intelligence": "medium"},
                      stamp="20260802_090000")
            report = collect_stability(root)
            self.assertEqual(len(report["groups"]), 2)
            self.assertEqual({group["intelligence"] for group in report["groups"]}, {"high", "medium"})

    def test_filters_by_tool_case_and_category(self):
        with TemporaryDirectory() as raw:
            root = Path(raw)
            build_run(root, "run-a", "codex", "draw-pelican-bicycle", PASSING,
                      "2026-08-01T00:00:00+00:00", identity=IDENTITY)
            build_run(root, "run-b", "claude", "magento-lady-dior-features", PASSING,
                      "2026-08-02T00:00:00+00:00", category="magento_business", identity=IDENTITY)
            self.assertEqual(len(collect_stability(root, tools=["codex"])["groups"]), 1)
            self.assertEqual(
                len(collect_stability(root, case_ids=["magento-lady-dior-features"])["groups"]), 1
            )
            self.assertEqual(len(collect_stability(root, categories=["magento_business"])["groups"]), 1)
            self.assertEqual(len(collect_stability(root)["groups"]), 2)

    def test_corrupted_test_run_becomes_warning(self):
        with TemporaryDirectory() as raw:
            root = Path(raw)
            tool_dir = root / "broken" / "deepeval" / "codex"
            tool_dir.mkdir(parents=True)
            (tool_dir / "test_run_20260829_090000.json").write_text("{not json", encoding="utf-8")
            (root / "broken" / "run.json").write_text(
                json.dumps({"created_at": "2026-08-29", "tools": ["codex"]}), encoding="utf-8"
            )
            report = collect_stability(root)
            self.assertEqual(report["groups"], [])
            self.assertTrue(any("评测产物损坏" in warning for warning in report["warnings"]))

    def test_runs_are_listed_in_chronological_order(self):
        with TemporaryDirectory() as raw:
            root = Path(raw)
            for index in range(3):
                build_run(root, f"run-{index}", "codex", "draw-pelican-bicycle", PASSING,
                          f"2026-08-0{3 - index}T00:00:00+00:00", identity=IDENTITY,
                          stamp=f"2026080{3 - index}_090000")
            group = first_group(collect_stability(root))
            self.assertEqual([run["run_id"] for run in group["runs"]], ["run-2", "run-1", "run-0"])


class RenderTests(unittest.TestCase):
    def _report(self) -> dict:
        with TemporaryDirectory() as raw:
            root = Path(raw)
            for index in range(3):
                build_run(root, f"run-{index}", "codex", "draw-pelican-bicycle", PASSING,
                          f"2026-08-0{index + 1}T00:00:00+00:00", identity=IDENTITY)
            return collect_stability(root)

    def test_markdown_contains_criteria_and_verdicts(self):
        markdown = render_markdown(self._report())
        self.assertIn("跨 run 稳定性分析", markdown)
        self.assertIn("判定口径", markdown)
        self.assertIn(VERDICT_STABLE, markdown)
        self.assertIn("Task Correctness", markdown)

    def test_html_is_self_contained_and_escapes(self):
        html = render_html(self._report())
        self.assertIn("<style>", html)
        self.assertIn("<table>", html)
        self.assertNotIn("<script", html)

    def test_empty_report_renders_empty_state(self):
        empty = {"generated_at": "2026-08-29", "criteria": {}, "summary": {}, "warnings": [], "groups": []}
        self.assertIn("没有找到任何可聚合的评测产物", render_markdown(empty))
        self.assertIn("没有找到任何可聚合的评测产物", render_html(empty))


class WriteReportTests(unittest.TestCase):
    def test_writes_json_markdown_and_html(self):
        with TemporaryDirectory() as raw:
            root = Path(raw)
            for index in range(3):
                build_run(root, f"run-{index}", "codex", "draw-pelican-bicycle", PASSING,
                          f"2026-08-0{index + 1}T00:00:00+00:00", identity=IDENTITY)
            write_stability_report(root, formats=("md", "html"))
            self.assertTrue((root / "stability-report.json").is_file())
            self.assertTrue((root / "stability-report.md").is_file())
            self.assertTrue((root / "stability-report.html").is_file())

    def test_html_only_format_skips_markdown(self):
        with TemporaryDirectory() as raw:
            root = Path(raw)
            write_stability_report(root, formats=("html",))
            self.assertFalse((root / "stability-report.md").exists())
            self.assertTrue((root / "stability-report.html").is_file())

    def test_cli_stability_command(self):
        with TemporaryDirectory() as raw:
            root = Path(raw)
            runs_root = root / "runs"
            for index in range(3):
                build_run(runs_root, f"run-{index}", "codex", "draw-pelican-bicycle", PASSING,
                          f"2026-08-0{index + 1}T00:00:00+00:00", identity=IDENTITY)
            cli.main(["stability", "--runs-dir", str(runs_root), "--format", "md"])
            self.assertIn("判定口径", (runs_root / "stability-report.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
