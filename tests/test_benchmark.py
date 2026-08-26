import json
import tempfile
import unittest
from pathlib import Path

from benchmark.cli import Case, ROOT, load_cases, prepare, select_cases
from benchmark.evaluation import build_test_cases, collect_actual_output, load_specs


class BenchmarkTests(unittest.TestCase):
    def test_select_cases_rejects_empty_filter_result(self):
        case = Case("test-case", "test", "Test case", Path("unused"))
        with self.assertRaisesRegex(ValueError, "没有匹配任何 case"):
            select_cases([case], [], ["missing-category"])

    def test_all_cases_have_deepeval_specs(self):
        cases = load_cases()
        specs = load_specs()
        self.assertEqual(len(cases), 14)
        self.assertEqual({case.id for case in cases}, set(specs))
        self.assertEqual(specs["write-plane-shooter"]["actual_files"], ["game-logic.js", "game.js", "index.html"])

    def test_prepare_does_not_copy_hidden_reference_or_result_artifacts(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source"
            source.mkdir()
            (source / "TASK.md").write_text("task", encoding="utf-8")
            (source / "result.json").write_text("old", encoding="utf-8")
            case = Case("test-case", "test", "Test case", source)
            run_dir = Path(directory) / "run"
            prepare(run_dir, ["tool"], [case])
            workspace = run_dir / "tool" / case.id
            self.assertTrue((workspace / "TASK.md").is_file())
            self.assertFalse((workspace / "result.json").exists())
            self.assertFalse((workspace / "tests").exists())

    def test_missing_and_invalid_execution_evidence_is_explicit(self):
        with tempfile.TemporaryDirectory() as directory:
            workspace = Path(directory)
            spec = {"actual_files": ["solution.js"]}
            self.assertIn("execution.json", collect_actual_output(workspace, spec))
            self.assertIn("缺失文件", collect_actual_output(workspace, spec))

    def test_test_case_name_and_metadata_are_stable(self):
        try:
            import deepeval  # noqa: F401
        except ImportError:
            self.skipTest("当前环境未安装 deepeval")
        cases = [case for case in load_cases() if case.id == "write-plane-shooter"]
        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory)
            workspace = run_dir / "codex" / cases[0].id
            workspace.mkdir(parents=True)
            (workspace / "execution.json").write_text(json.dumps({"status": "timeout", "elapsed_seconds": 3.2}), encoding="utf-8")
            test_case = build_test_cases(run_dir, "codex", cases)[0]
            self.assertEqual(test_case.name, "codex/write-plane-shooter")
            metadata = getattr(test_case, "metadata", None) or getattr(test_case, "custom_column_key_values")
            self.assertEqual(metadata["execution_status"], "timeout")
            self.assertIn("===== game.js =====", test_case.actual_output)


if __name__ == "__main__":
    unittest.main()
