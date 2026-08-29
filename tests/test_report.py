import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from benchmark.report import (
    collect_history,
    collect_run_report,
    latest_test_run,
    render_history_markdown,
    render_markdown,
    write_history_report,
    write_run_report,
)


def make_test_run(case_id: str, scores: dict[str, float], tool: str = "codex") -> dict:
    """构造与 DeepEval 4.2.0 真实导出一致的 TestRun 结构。"""
    metrics_data = []
    metric_thresholds = {
        "Task Correctness [GEval]": 0.8,
        "Robustness, Safety and Regression [GEval]": 0.7,
        "Delivery Evidence [GEval]": 0.7,
    }
    for name, score in scores.items():
        threshold = metric_thresholds.get(name, 0.7)
        metrics_data.append(
            {
                "name": name,
                "threshold": threshold,
                "success": score >= threshold,
                "score": score,
                "reason": "单元测试固定理由",
                "evaluationModel": "gpt-5.6-sol",
                "verboseLogs": "Score: ...",
            }
        )
    return {
        "testCases": [
            {
                "name": f"{tool}/{case_id}",
                "input": "任务描述",
                "actualOutput": "实际输出",
                "expectedOutput": "期望输出",
                "success": all(entry["success"] for entry in metrics_data),
                "metricsData": metrics_data,
                "runDuration": 1,
                "order": 0,
                "metadata": {
                    "tool": tool,
                    "case_id": case_id,
                    "category": "code_correction",
                    "execution_status": "completed",
                    "elapsed_seconds": 12.5,
                    "agent_identity": "codex/gpt-5.6",
                },
            }
        ],
        "metricsScores": [
            {"metric": entry["name"], "scores": [entry["score"]], "passes": int(entry["success"]), "fails": int(not entry["success"]), "errors": 0}
            for entry in metrics_data
        ],
        "identifier": f"run:{tool}",
        "hyperparameters": {"judge_model": "gpt-5.6-sol", "metric_version": "2026-08-26-v1"},
        "testPassed": int(all(entry["success"] for entry in metrics_data)),
        "testFailed": int(not all(entry["success"] for entry in metrics_data)),
        "runDuration": 2.0,
        "official": False,
    }


def build_run(root: Path, run_id: str, tool: str, case_id: str, scores: dict[str, float], identity: dict | None = None) -> Path:
    run_dir = root / run_id
    tool_dir = run_dir / "deepeval" / tool
    tool_dir.mkdir(parents=True, exist_ok=True)
    (tool_dir / "test_run_20260829_090000.json").write_text(
        json.dumps(make_test_run(case_id, scores, tool), ensure_ascii=False), encoding="utf-8"
    )
    manifest = {"created_at": "2026-08-29", "tools": [tool], "cases": [case_id]}
    if identity:
        manifest["identities"] = {tool: identity}
    (run_dir / "run.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    return run_dir


class LatestTestRunTests(unittest.TestCase):
    def test_picks_latest_timestamp_and_ignores_other_files(self) -> None:
        with TemporaryDirectory() as raw:
            tool_dir = Path(raw) / "deepeval" / "codex"
            tool_dir.mkdir(parents=True)
            for name in ("test_run_20260829_090000.json", "test_run_20260829_100000.json", "notes.json"):
                (tool_dir / name).write_text("{}", encoding="utf-8")
            latest = latest_test_run(tool_dir)
            assert latest is not None
            self.assertEqual(latest.name, "test_run_20260829_100000.json")

    def test_missing_directory_returns_none(self) -> None:
        with TemporaryDirectory() as raw:
            self.assertIsNone(latest_test_run(Path(raw) / "deepeval" / "codex"))


class CollectToolSummaryTests(unittest.TestCase):
    def test_reads_scores_identity_and_pass_state(self) -> None:
        with TemporaryDirectory() as raw:
            root = Path(raw)
            build_run(
                root,
                "run-1",
                "codex",
                "fix-cart-total",
                {
                    "Task Correctness [GEval]": 0.9,
                    "Robustness, Safety and Regression [GEval]": 0.75,
                    "Delivery Evidence [GEval]": 0.5,
                },
                identity={"agent": "Codex CLI", "model": "gpt-5.6-sol", "intelligence": "high"},
            )
            report = collect_run_report(root / "run-1", ())
            self.assertEqual(report["run_id"], "run-1")
            tool = report["tools"][0]
            self.assertEqual(tool["agent"], "Codex CLI")
            self.assertEqual(tool["model"], "gpt-5.6-sol")
            self.assertEqual(tool["intelligence"], "high")
            summary = tool["summary"]
            self.assertEqual((summary["evaluated"], summary["passed"]), (1, 0))
            self.assertAlmostEqual(summary["pass_rate"], 0.0)
            self.assertAlmostEqual(summary["metric_averages"]["Task Correctness"], 0.9)
            self.assertAlmostEqual(summary["metric_averages"]["Delivery Evidence"], 0.5)
            case = tool["cases"][0]
            self.assertEqual(case["case_id"], "fix-cart-total")
            self.assertFalse(case["passed"])
            self.assertEqual(case["execution_status"], "completed")

    def test_tool_without_artifacts_reports_empty(self) -> None:
        with TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "run-1").mkdir()
            report = collect_run_report(root / "run-1", ("claude",))
            tool = report["tools"][0]
            self.assertEqual(tool["cases"], [])
            self.assertIsNone(tool["summary"]["pass_rate"])


class RenderMarkdownTests(unittest.TestCase):
    def test_markdown_contains_matrix_and_conclusion(self) -> None:
        with TemporaryDirectory() as raw:
            root = Path(raw)
            build_run(
                root,
                "run-1",
                "codex",
                "fix-cart-total",
                {
                    "Task Correctness [GEval]": 0.9,
                    "Robustness, Safety and Regression [GEval]": 0.75,
                    "Delivery Evidence [GEval]": 0.5,
                },
                identity={"agent": "Codex CLI", "model": "gpt-5.6-sol", "intelligence": "high"},
            )
            report = collect_run_report(root / "run-1", ())
            markdown = render_markdown(report)
            self.assertIn("评测对比报告：run-1", markdown)
            self.assertIn("| Codex CLI | gpt-5.6-sol | high | 0 / 1 | 0% |", markdown)
            self.assertIn("0.90 ✓", markdown)
            self.assertIn("0.50 ✗", markdown)
            self.assertIn("❌ 未通过", markdown)
            self.assertIn("fix-cart-total", markdown)

    def test_markdown_without_artifacts(self) -> None:
        with TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "run-1").mkdir()
            markdown = render_markdown(collect_run_report(root / "run-1", ()))
            self.assertIn("没有找到任何 DeepEval 评测产物", markdown)


class HistoryTests(unittest.TestCase):
    def test_collect_history_and_markdown_across_runs(self) -> None:
        with TemporaryDirectory() as raw:
            root = Path(raw)
            build_run(
                root, "run-a", "codex", "fix-cart-total",
                {"Task Correctness [GEval]": 0.9, "Robustness, Safety and Regression [GEval]": 0.8, "Delivery Evidence [GEval]": 0.8},
                identity={"agent": "Codex CLI", "model": "gpt-5.6-sol", "intelligence": "high"},
            )
            build_run(
                root, "run-b", "claude", "fix-cart-total",
                {"Task Correctness [GEval]": 0.95, "Robustness, Safety and Regression [GEval]": 0.85, "Delivery Evidence [GEval]": 0.9},
                identity={"agent": "Claude Code", "model": "claude-4.5", "intelligence": "high"},
            )
            (root / "empty-run").mkdir()
            history = collect_history(root)
            self.assertEqual([report["run_id"] for report in history], ["run-a", "run-b"])
            markdown = render_history_markdown(history)
            self.assertIn("跨 run 历史对比", markdown)
            self.assertIn("| run-a | codex | Codex CLI | gpt-5.6-sol | high | 1 / 1 | 100% |", markdown)
            self.assertIn("| run-b | claude | Claude Code | claude-4.5 | high | 1 / 1 | 100% |", markdown)

    def test_write_files(self) -> None:
        with TemporaryDirectory() as raw:
            root = Path(raw)
            build_run(
                root, "run-a", "codex", "fix-cart-total",
                {"Task Correctness [GEval]": 0.9, "Robustness, Safety and Regression [GEval]": 0.8, "Delivery Evidence [GEval]": 0.8},
            )
            run_dir = root / "run-a"
            report = write_run_report(run_dir, ("codex",))
            history = write_history_report(root)
            self.assertTrue((run_dir / "report.md").is_file())
            self.assertTrue((run_dir / "report.json").is_file())
            self.assertTrue((root / "history-report.md").is_file())
            self.assertTrue((root / "history-report.json").is_file())
            self.assertEqual(len(history), 1)
            reloaded = json.loads((root / "history-report.json").read_text(encoding="utf-8"))
            self.assertEqual(len(reloaded["runs"]), 1)
            self.assertEqual(report["run_id"], "run-a")


if __name__ == "__main__":
    unittest.main()
