import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from benchmark.cli import Case, load_cases, prepare, select_cases
from benchmark.evaluation import build_test_cases, collect_actual_output, load_specs


class BenchmarkTests(unittest.TestCase):
    def test_select_cases_rejects_empty_filter_result(self):
        case = Case("test-case", "test", "Test case", Path("unused"))
        with self.assertRaisesRegex(ValueError, "没有匹配任何 case"):
            select_cases([case], [], ["missing-category"])

    def test_all_cases_have_deepeval_specs(self):
        cases = load_cases()
        specs = load_specs()
        self.assertEqual(len(cases), 3)
        self.assertEqual({case.id for case in cases}, set(specs))
        self.assertEqual(specs["draw-pelican-bicycle"]["actual_files"], ["index.html"])

    def test_prepare_does_not_copy_hidden_reference_or_result_artifacts(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source"
            source.mkdir()
            (source / "TASK.md").write_text("task", encoding="utf-8")
            (source / "result.json").write_text("old", encoding="utf-8")
            (source / "agent.live.log").write_text("old agent output", encoding="utf-8")
            case = Case("test-case", "test", "Test case", source)
            run_dir = Path(directory) / "run"
            prepare(run_dir, ["tool"], [case])
            workspace = run_dir / "tool" / case.id
            self.assertTrue((workspace / "TASK.md").is_file())
            self.assertFalse((workspace / "result.json").exists())
            self.assertFalse((workspace / "agent.live.log").exists())
            self.assertFalse((workspace / "tests").exists())

    def test_prepare_scopes_pelican_workspace_by_identity(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source"
            source.mkdir()
            (source / "TASK.md").write_text("task", encoding="utf-8")
            case = Case("draw-pelican-bicycle", "code_generation", "Pelican", source)
            run_dir = Path(directory) / "run"
            identities = {
                "codex": {"agent": "Codex CLI", "model": "provider/model", "intelligence": "high"}
            }
            prepare(run_dir, ["codex"], [case], identities)
            workspace = run_dir / "pelican" / "Codex-CLI" / "provider-model" / "high" / "codex" / case.id
            self.assertTrue((workspace / "TASK.md").is_file())
            self.assertIn("不得调用、启动或委派给任何子 Agent", (workspace / "AGENTS.md").read_text())
            self.assertIn(
                '"submodels_used": false',
                (workspace / "RESULT_PROTOCOL.md").read_text(),
            )
            self.assertFalse((run_dir / "codex" / case.id).exists())
            manifest = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["identities"], identities)

    def test_prepare_pelican_starts_without_an_existing_solution(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source"
            source.mkdir()
            (source / "TASK.md").write_text("从头实现鹈鹕动画", encoding="utf-8")
            (source / "case.json").write_text('{"id":"draw-pelican-bicycle"}', encoding="utf-8")
            for name in ("index.html", "build.mjs", "package.json", "public-test.mjs",
                         "src/main.ts", "dist/main.js", "node_modules/package/index.js", "verification/shot.png"):
                path = source / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("previous solution", encoding="utf-8")
            case = Case("draw-pelican-bicycle", "code_generation", "Pelican", source)
            run_dir = Path(directory) / "run"

            prepare(run_dir, ["first", "second"], [case])

            for tool in ("first", "second"):
                workspace = run_dir / tool / case.id
                self.assertEqual(
                    {path.name for path in workspace.iterdir()},
                    {"TASK.md", "case.json", "AGENTS.md", "RESULT_PROTOCOL.md"},
                )
            self.assertEqual((source / "index.html").read_text(), "previous solution")

    def test_prepare_materializes_git_fixture_without_leaking_fixture_sources(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source"
            fixture = source / "_git_fixture"
            first = fixture / "commits" / "001-initial"
            second = fixture / "commits" / "002-fix"
            first.mkdir(parents=True)
            second.mkdir(parents=True)
            (source / "TASK.md").write_text("review sample-repo HEAD", encoding="utf-8")
            (first / "cache.js").write_text("export const key = id => `${id}`;\n", encoding="utf-8")
            (second / "cache.js").write_text("export const key = (tenant, id) => `${tenant}:${id}`;\n", encoding="utf-8")
            (fixture / "manifest.json").write_text(
                json.dumps(
                    {
                        "target": "sample-repo",
                        "commits": [
                            {
                                "snapshot": "commits/001-initial",
                                "message": "feat: add cache key",
                                "timestamp": "2026-01-01T00:00:00+00:00",
                            },
                            {
                                "snapshot": "commits/002-fix",
                                "message": "fix: isolate cache by tenant",
                                "timestamp": "2026-01-02T00:00:00+00:00",
                            },
                        ],
                    }
                ),
                encoding="utf-8",
            )

            case = Case("git-case", "logic_analysis", "Git fixture", source)
            run_dir = Path(directory) / "run"
            prepare(run_dir, ["tool"], [case])

            workspace = run_dir / "tool" / case.id
            repository = workspace / "sample-repo"
            self.assertFalse((workspace / "_git_fixture").exists())
            self.assertTrue((repository / ".git").is_dir())
            subjects = subprocess.run(
                ["git", "-C", str(repository), "log", "--format=%s"],
                check=True,
                capture_output=True,
                text=True,
            ).stdout.splitlines()
            self.assertEqual(subjects, ["fix: isolate cache by tenant", "feat: add cache key"])
            self.assertEqual(
                subprocess.run(
                    ["git", "-C", str(repository), "status", "--short"],
                    check=True,
                    capture_output=True,
                    text=True,
                ).stdout,
                "",
            )

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
        cases = [case for case in load_cases() if case.id == "draw-pelican-bicycle"]
        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory)
            workspace = run_dir / "codex" / cases[0].id
            workspace.mkdir(parents=True)
            (workspace / "execution.json").write_text(json.dumps({"status": "timeout", "elapsed_seconds": 3.2}), encoding="utf-8")
            test_case = build_test_cases(run_dir, "codex", cases)[0]
            self.assertEqual(test_case.name, "codex/draw-pelican-bicycle")
            metadata = getattr(test_case, "metadata", None) or getattr(test_case, "custom_column_key_values")
            self.assertEqual(metadata["execution_status"], "timeout")
            self.assertIn("===== index.html =====", test_case.actual_output)


class ReportCommandTests(unittest.TestCase):
    def test_report_command_writes_run_report(self):
        from benchmark.cli import main as cli_main

        with tempfile.TemporaryDirectory() as directory:
            run_dir = Path(directory) / "sample-run"
            run_dir.mkdir()
            cli_main(["report", "--run-dir", str(run_dir), "--tool", "codex"])
            self.assertTrue((run_dir / "report.md").is_file())
            self.assertIn("没有找到任何 DeepEval 评测产物", (run_dir / "report.md").read_text(encoding="utf-8"))

    def test_report_command_history_mode(self):
        from benchmark import report as report_module
        from benchmark.cli import main as cli_main

        with tempfile.TemporaryDirectory() as directory:
            runs_root = Path(directory) / "runs"
            (runs_root / "run-a" / "deepeval" / "codex").mkdir(parents=True)
            (runs_root / "run-a" / "run.json").write_text(json.dumps({"tools": ["codex"]}), encoding="utf-8")
            # 目录存在但没有任何 test_run_*.json：历史收集应为空并渲染空态文案
            history = report_module.collect_history(runs_root)
            self.assertEqual(history, [])
            self.assertIn("没有找到任何评测产物", report_module.render_history_markdown(history))
            cli_main(["report", "--run-dir", str(runs_root / "run-a"), "--tool", "codex"])


if __name__ == "__main__":
    unittest.main()
