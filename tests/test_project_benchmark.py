import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from benchmark.cli import Case, execute, load_cases, prepare, select_cases
from benchmark.evaluation import collect_project_evidence
from benchmark.report import CaseRow, ToolSummary, _category_stats_dict


class ProjectBenchmarkTests(unittest.TestCase):
    def test_magento_category_selects_both_business_questions(self):
        cases = select_cases(load_cases(), [], ["magento_business"])
        self.assertEqual({case.id for case in cases}, {
            "magento-lady-dior-features", "magento-post-shipment-exchange-intent",
        })
        self.assertTrue(all(case.project_dir == Path("/Users/ben/Code/Work/cdc-dior/middleground") for case in cases))

    def test_project_prepare_and_execute_separate_cwd_from_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "magento"
            project.mkdir()
            original = project / "source.php"
            original.write_text("<?php // original\n", encoding="utf-8")
            source = root / "case"
            source.mkdir()
            (source / "TASK.md").write_text("只读分析项目", encoding="utf-8")
            case = Case("business", "magento_business", "Business", source, project)
            run_dir = root / "run"
            context = {"path": str(project), "commit": "abc", "working_tree": "M source.php"}
            with patch("benchmark.cli.project_context", return_value=context):
                prepare(run_dir, ["test-agent"], [case])
            workspace = run_dir / "test-agent" / case.id
            self.assertEqual(json.loads((workspace / "PROJECT.json").read_text()), context)
            self.assertIn("只读分析项目", (workspace / "AGENTS.md").read_text())
            self.assertEqual(list(project.iterdir()), [original])
            config = root / "tools.json"
            config.write_text(json.dumps({"test-agent": {"command": [
                "fake-agent", "--dir", "{workspace}", "--add-dir", "{output_dir}", "{prompt}",
            ]}}), encoding="utf-8")
            # 只检查进程参数，不启动真实 Agent。
            with patch("benchmark.cli.shutil.which", return_value="fake-agent"), patch(
                "benchmark.cli._stream_command", return_value=subprocess.CompletedProcess([], 0, "answer", "")
            ) as process:
                execute(run_dir, ["test-agent"], [case], config, 10)
            command = process.call_args.args[0]
            self.assertEqual(process.call_args.kwargs["cwd"], project)
            self.assertEqual(command[2], str(project))
            self.assertEqual(command[4], str(workspace.resolve()))
            self.assertIn(str(workspace.resolve()), command[-1])
            self.assertIn("不得修改项目文件", command[-1])
            self.assertTrue((workspace / "execution.json").is_file())
            self.assertTrue((workspace / "agent.log").is_file())
            self.assertTrue((workspace / "agent.live.log").is_file())
            execution = json.loads((workspace / "execution.json").read_text(encoding="utf-8"))
            self.assertEqual(execution["status"], "completed")
            self.assertEqual(execution["timeout_seconds"], 10)
            self.assertIn("started_at", execution)
            self.assertIn("finished_at", execution)
            self.assertEqual(list(project.iterdir()), [original])
            self.assertEqual(original.read_text(), "<?php // original\n")

    def test_missing_project_fails_before_creating_run(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            case = Case("business", "magento_business", "Business", root, root / "missing")
            with self.assertRaisesRegex(ValueError, "项目目录不存在"):
                prepare(root / "run", ["test-agent"], [case])
            self.assertFalse((root / "run").exists())

    def test_evidence_reads_source_and_rejects_outside_paths_and_bad_ranges(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "project"
            project.mkdir()
            (project / "sample.php").write_text("<?php\nreturn 'source truth';\n", encoding="utf-8")
            outside = root / "outside.php"
            outside.write_text("outside secret", encoding="utf-8")
            (project / "link.php").symlink_to(outside)
            (root / "evidence.json").write_text(json.dumps([
                {"path": "sample.php", "start_line": 2, "end_line": 2},
                {"path": "../outside.php", "start_line": 1, "end_line": 1},
                {"path": "link.php", "start_line": 1, "end_line": 1},
                {"path": "sample.php", "start_line": 1, "end_line": 81},
                {"path": "sample.php", "start_line": 1, "end_line": 3},
            ]), encoding="utf-8")
            evidence = collect_project_evidence(root, project)
            self.assertIn("2: return 'source truth';", evidence)
            self.assertNotIn("outside secret", evidence)
            self.assertEqual(evidence.count("无效源码引用"), 4)

    def test_report_includes_magento_category(self):
        summary = ToolSummary("test-agent", "unknown", "unknown", "unknown", None, None, None, None)
        summary.rows.append(CaseRow("business", "Business", "magento_business", passed=True, evaluated=True))
        stats = _category_stats_dict(summary)
        self.assertEqual(stats["magento_business"], {"evaluated": 1, "passed": 1, "pass_rate": 1.0})


if __name__ == "__main__":
    unittest.main()
