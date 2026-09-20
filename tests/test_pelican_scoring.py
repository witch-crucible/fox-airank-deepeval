import argparse
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from benchmark.cli import Case
from benchmark.paths import workspace_path
from benchmark.pelican_scoring import (
    artifact_path,
    create_scoring_run,
    evaluate_and_report,
    parse_elapsed_seconds,
)


class PelicanScoringTests(unittest.TestCase):
    def test_parses_supported_elapsed_formats(self) -> None:
        expected = {
            "2065": 2065.0,
            "34:25": 2065.0,
            "00:34:25": 2065.0,
            "34m25s": 2065.0,
            "34分25秒": 2065.0,
        }
        for value, seconds in expected.items():
            with self.subTest(value=value):
                self.assertEqual(parse_elapsed_seconds(value), seconds)

    def test_rejects_invalid_elapsed_formats(self) -> None:
        for value in ("", "-1", "1:60", "later"):
            with self.subTest(value=value):
                with self.assertRaises(argparse.ArgumentTypeError):
                    parse_elapsed_seconds(value)

    def test_accepts_local_path_and_file_url(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            result = Path(directory) / "result file.html"
            result.write_text("<html></html>", encoding="utf-8")
            self.assertEqual(artifact_path(str(result)), result.resolve())
            self.assertEqual(artifact_path(result.as_uri()), result.resolve())
        with self.assertRaises(argparse.ArgumentTypeError):
            artifact_path("https://example.com/index.html")

    def test_creates_identity_scoped_scoring_run_with_manual_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            (source / "TASK.md").write_text("task", encoding="utf-8")
            (source / "case.json").write_text(
                json.dumps(
                    {
                        "id": "draw-pelican-bicycle",
                        "category": "code_generation",
                        "title": "Pelican",
                    }
                ),
                encoding="utf-8",
            )
            artifact = root / "generated.html"
            artifact.write_text("<html>generated</html>", encoding="utf-8")
            run_dir = root / "run"
            case = Case("draw-pelican-bicycle", "code_generation", "Pelican", source)

            workspace = create_scoring_run(
                artifact=artifact,
                run_dir=run_dir,
                tool="commandcode",
                agent="Command Code",
                model="qwen/qwen3.8-max-0902",
                intelligence="unknown",
                elapsed_seconds=2065,
                timeout_seconds=1800,
                submodels_used=False,
                case=case,
            )

            identities = {
                "commandcode": {
                    "agent": "Command Code",
                    "model": "qwen/qwen3.8-max-0902",
                    "intelligence": "unknown",
                }
            }
            self.assertEqual(
                workspace,
                workspace_path(run_dir, "commandcode", case.id, identities),
            )
            self.assertEqual((workspace / "index.html").read_text(), "<html>generated</html>")
            execution = json.loads((workspace / "execution.json").read_text())
            self.assertEqual(execution["elapsed_seconds"], 2065)
            self.assertEqual(execution["timeout_seconds"], 1800)
            self.assertEqual(execution["execution_mode"], "manual_result_import")
            self.assertEqual(execution["agent_identity"], identities["commandcode"])
            self.assertEqual(len(execution["artifact_sha256"]), 64)
            result = json.loads((workspace / "result.json").read_text())
            self.assertEqual(result["changed_files"], ["index.html"])
            self.assertFalse(result["submodels_used"])
            manifest = json.loads((run_dir / "run.json").read_text())
            self.assertEqual(manifest["identities"], identities)

    def test_rejects_missing_non_html_and_empty_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source"
            source.mkdir()
            case = Case("draw-pelican-bicycle", "code_generation", "Pelican", source)
            common = {
                "run_dir": root / "run",
                "tool": "manual",
                "agent": "manual",
                "model": "model",
                "intelligence": "unknown",
                "elapsed_seconds": 1,
                "timeout_seconds": 1800,
                "submodels_used": False,
                "case": case,
            }
            with self.assertRaisesRegex(ValueError, "不存在"):
                create_scoring_run(artifact=root / "missing.html", **common)
            text = root / "result.txt"
            text.write_text("result", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "HTML"):
                create_scoring_run(artifact=text, **common)
            empty = root / "empty.html"
            empty.write_text("  ", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "为空"):
                create_scoring_run(artifact=empty, **common)

    @patch("benchmark.pelican_scoring.load_cases", return_value=[])
    @patch("benchmark.report.write_run_report")
    @patch("benchmark.pelican_scoring.subprocess.run")
    def test_evaluate_uses_existing_worker_and_sanitized_environment(
        self, run, write_report, _load_cases
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict("os.environ", {"CONFIDENT_API_KEY": "secret", "KEEP": "yes"}, clear=True):
                evaluate_and_report(Path(directory), "manual")

        command = run.call_args.args[0]
        self.assertIn("benchmark.evaluation_worker", command)
        self.assertEqual(command[-2:], ["--case", "draw-pelican-bicycle"])
        environment = run.call_args.kwargs["env"]
        self.assertNotIn("CONFIDENT_API_KEY", environment)
        self.assertEqual(environment["KEEP"], "yes")
        self.assertEqual(environment["DEEPEVAL_DISABLE_DOTENV"], "1")
        write_report.assert_called_once()


if __name__ == "__main__":
    unittest.main()
