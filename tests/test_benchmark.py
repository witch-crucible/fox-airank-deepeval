import json
import sys
import tempfile
import unittest
from pathlib import Path

from benchmark.cli import ROOT, Case, execute, grade, grade_case, load_cases, manual_answer_checks, prepare, select_cases
from benchmark.report import render_report_html


class BenchmarkTests(unittest.TestCase):
    def test_readme_stepwise_tool_names_exist_in_default_config(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        tools = json.loads((ROOT / "tools.json").read_text(encoding="utf-8"))
        self.assertNotIn("--tool claude-code", readme)
        for name in ("codex", "claude", "opencode"):
            self.assertIn(name, tools)

    def test_select_cases_rejects_empty_filter_result(self):
        case = Case("test-case", "test", "Test case", Path("unused"))
        with self.assertRaisesRegex(ValueError, "没有匹配任何 case"):
            select_cases([case], [], ["missing-category"])

    def test_execute_preflights_all_tools_before_running_any_agent(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            (source / "TASK.md").write_text("task", encoding="utf-8")
            (source / "fake_agent.py").write_text(
                "from pathlib import Path\nPath('marker').write_text('ran', encoding='utf-8')\n",
                encoding="utf-8",
            )
            case = Case("test-case", "test", "Test case", source)
            run_dir = root / "run"
            prepare(run_dir, ["available", "missing"], [case])
            config_path = root / "tools.json"
            config_path.write_text(
                json.dumps(
                    {
                        "available": {"command": [sys.executable, "fake_agent.py", "{prompt}"]},
                        "missing": {"command": ["missing-agent-executable", "{prompt}"]},
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(ValueError, "找不到工具命令"):
                execute(run_dir, ["available", "missing"], [case], config_path, timeout=10)

            workspace = run_dir / "available" / case.id
            self.assertFalse((workspace / "marker").exists())
            self.assertFalse((workspace / "execution.json").exists())

    def test_prepare_excludes_execution_artifacts(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source"
            source.mkdir()
            (source / "TASK.md").write_text("task", encoding="utf-8")
            artifacts = ("result.json", "agent.log", "execution.json")
            for name in artifacts:
                (source / name).write_text("generated", encoding="utf-8")
            case = Case("test-case", "test", "Test case", source)
            run_dir = Path(directory) / "run"
            prepare(run_dir, ["test"], [case])
            workspace = run_dir / "test" / case.id
            self.assertTrue((workspace / "TASK.md").exists())
            for name in artifacts:
                self.assertFalse((workspace / name).exists())

    def test_reference_solutions_score_full_marks(self):
        cases = load_cases()
        self.assertEqual(len(cases), 13)
        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory) / "run"
            prepare(run_dir, ["reference"], cases)
            specs = json.loads((ROOT / "benchmark" / "specs.json").read_text(encoding="utf-8"))
            reference_files = {
                "fix-cart-total": ("cart.js", "cart.js"),
                "fix-query-string": ("query.js", "query.js"),
                "fix-pagination-window": ("pagination.js", "pagination.js"),
                "write-product-filter": ("product-filter.js", "product-filter.js"),
                "write-pagination-reducer": ("pagination-reducer.js", "pagination-reducer.js"),
                "write-product-card": ("product-card.js", "product-card.js"),
            }
            for case in cases:
                workspace = run_dir / "reference" / case.id
                result = {
                    "case_id": case.id,
                    "status": "completed",
                    "summary": "reference solution",
                    "changed_files": ["result.json"],
                    "verification": ["reference check"],
                }
                if specs[case.id]["type"] == "logic":
                    result["answer"] = specs[case.id]["expected"]
                else:
                    source_name, target_name = reference_files[case.id]
                    source = ROOT / "tests" / "reference" / source_name
                    (workspace / target_name).write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
                    result["changed_files"].append(target_name)
                (workspace / "result.json").write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
            report = grade(run_dir, ["reference"], cases)
            self.assertEqual(report["summary"]["reference"]["overall"], 100.0)
            html = (run_dir / "report.html").read_text(encoding="utf-8")
            self.assertIn("AI 代码代理评测对比", html)
            self.assertIn('"overall": 100.0', html)

    def test_report_html_escapes_embedded_data(self):
        html = render_report_html(
            {
                "graded_at": "2026-07-14T00:00:00+00:00",
                "summary": {"</script><script>alert(1)</script>": {"overall": 0, "by_category": {}}},
                "results": [],
            }
        )
        self.assertNotIn("</script><script>alert(1)</script>", html)
        self.assertIn("\\u003c/script\\u003e", html)

    def test_report_html_displays_manual_score(self):
        html = render_report_html(
            {
                "summary": {"agent": {"overall": 70, "by_category": {"manual_test": 70}}},
                "results": [
                    {
                        "tool": "agent",
                        "case_id": "manual-review",
                        "category": "manual_test",
                        "score": 70,
                        "manual_score": 6.67,
                        "protocol": {"passed": True, "detail": "结果协议有效"},
                        "checks": [],
                    }
                ],
            }
        )
        self.assertIn("手动测试得分", html)
        self.assertIn("manual_score", html)

    def test_manual_answer_missing_null_field_does_not_pass(self):
        checks = manual_answer_checks({}, {"optional": None})
        self.assertEqual(checks, [{"name": "answer.optional", "passed": False, "detail": "缺少字段"}])

    def test_manual_case_runs_headless_and_scores_against_standard_answer(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            (source / "TASK.md").write_text("生成结构化 answer", encoding="utf-8")
            (source / "case.json").write_text(
                json.dumps({"id": "manual-review", "category": "manual_test", "title": "手动评测"}),
                encoding="utf-8",
            )
            (source / "fake_agent.py").write_text(
                "import json\n"
                "from pathlib import Path\n"
                "Path('result.json').write_text(json.dumps({\n"
                "    'case_id': 'manual-review',\n"
                "    'status': 'completed',\n"
                "    'summary': 'done',\n"
                "    'changed_files': ['result.json'],\n"
                "    'verification': ['headless'],\n"
                "    'answer': {'decision': 'reject', 'evidence': {'count': 2, 'risk': 'wrong'}},\n"
                "}), encoding='utf-8')\n",
                encoding="utf-8",
            )
            case = Case("manual-review", "manual_test", "手动评测", source)
            run_dir = root / "run"
            prepare(run_dir, ["fake-headless"], [case])
            config_path = root / "tools.json"
            config_path.write_text(
                json.dumps({"fake-headless": {"command": [sys.executable, "fake_agent.py", "{prompt}"]}}),
                encoding="utf-8",
            )

            execute(run_dir, ["fake-headless"], [case], config_path, timeout=10)
            workspace = run_dir / "fake-headless" / case.id
            record = grade_case(
                workspace,
                case,
                {
                    "type": "manual",
                    "expected": {"decision": "reject", "evidence": {"count": 2, "risk": "high"}},
                },
            )

            self.assertTrue((workspace / "agent.log").is_file())
            self.assertTrue((workspace / "execution.json").is_file())
            self.assertTrue((workspace / "result.json").is_file())
            self.assertEqual(record["manual_score"], 6.67)
            self.assertEqual(record["score"], 70.0)
            self.assertEqual(record["answer"]["decision"], "reject")
            self.assertEqual([check["passed"] for check in record["checks"]], [True, True, False])


if __name__ == "__main__":
    unittest.main()
