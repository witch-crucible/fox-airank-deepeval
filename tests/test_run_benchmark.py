import json
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import run_benchmark


class RunBenchmarkIdentityTests(unittest.TestCase):
    def test_batch_preflight_runs_before_identity_discovery_or_prepare(self) -> None:
        args = SimpleNamespace(
            run_id=None,
            config=Path("tools.json"),
            tools=["available", "missing"],
            case_ids=[],
            category=[],
            timeout=None,
        )
        configs = {
            "available": {"command": ["available-agent", "{prompt}"]},
            "missing": {"command": ["missing-agent", "{prompt}"]},
        }
        with (
            patch("run_benchmark.parse_args", return_value=args),
            patch("run_benchmark.load_tool_config", return_value=configs),
            patch("run_benchmark.preflight_tools", side_effect=ValueError("找不到工具命令")) as preflight,
            patch("run_benchmark.query_identities") as query_identities,
            patch("run_benchmark.run") as run,
        ):
            with self.assertRaisesRegex(SystemExit, "找不到工具命令"):
                run_benchmark.main()

        preflight.assert_called_once_with(configs, ("available", "missing"))
        query_identities.assert_not_called()
        run.assert_not_called()

    def test_opencode_identity_command_reuses_execution_identity_options(self) -> None:
        command = run_benchmark.identity_command(
            "opencode",
            {
                "command": [
                    "opencode", "run", "--pure", "--auto", "--dir", "{workspace}",
                    "--agent", "build", "--model", "provider/model", "--variant", "high", "{prompt}",
                ]
            },
        )

        self.assertIsNotNone(command)
        self.assertIn("--pure", command)
        self.assertEqual(run_benchmark.command_option(command, "--agent"), "build")
        self.assertEqual(run_benchmark.command_option(command, "--model"), "provider/model")
        self.assertEqual(run_benchmark.command_option(command, "--variant"), "high")

    def test_commandcode_identity_command_uses_status_json(self) -> None:
        command = run_benchmark.identity_command(
            "commandcode",
            {
                "command": [
                    "commandcode", "-p", "--yolo", "--no-session", "--skip-onboarding",
                    "--no-auto-update", "--output-format", "json", "--model", "provider/model",
                    "--effort", "high", "{prompt}",
                ]
            },
        )

        self.assertEqual(["commandcode", "status", "--json", "--no-auto-update"], command)

    def test_parse_commandcode_identity_from_status_json(self) -> None:
        output = json.dumps(
            {
                "authenticated": True,
                "version": "1.38.2",
                "provider": "example-provider",
                "model": "provider/default-model",
                "context_window": 200000,
            }
        )

        self.assertEqual(
            ("Command Code", "provider/default-model", "unknown"),
            run_benchmark.parse_identity_output("commandcode", output),
        )

    def test_commandcode_status_identity_uses_configured_model_and_effort(self) -> None:
        config = {
            "agent": "Command Code",
            "command": [
                "commandcode", "-p", "--yolo", "--model", "provider/configured-model",
                "--effort", "high", "{prompt}",
            ],
        }
        status = json.dumps({"model": "provider/default-model"})
        with patch(
            "run_benchmark.subprocess.run",
            return_value=SimpleNamespace(returncode=0, stdout=status, stderr=""),
        ):
            identity = run_benchmark.query_identity("commandcode", config)

        self.assertEqual(("Command Code", "provider/configured-model", "high"), identity)

    def test_commandcode_execution_disables_project_taste_learning(self) -> None:
        config = json.loads(Path("tools.json").read_text(encoding="utf-8"))["commandcode"]
        command = config["command"]

        self.assertEqual(
            "taste-learning-project=disabled",
            run_benchmark.command_option(command, "--config"),
        )

    def test_fixed_run_id_skips_live_identity_discovery(self) -> None:
        args = SimpleNamespace(
            run_id="fixed-run",
            config=Path("tools.json"),
            tools=["example"],
            case_ids=[],
            category=[],
            timeout=None,
        )
        configs = {
            "example": {
                "agent": "configured-agent",
                "model": "configured-model",
                "command": ["example", "{prompt}"],
            }
        }
        with (
            patch("run_benchmark.parse_args", return_value=args),
            patch("run_benchmark.load_tool_config", return_value=configs),
            patch("run_benchmark.preflight_tools") as preflight,
            patch("run_benchmark.query_identities") as query_identities,
            patch("run_benchmark.run") as run,
        ):
            self.assertEqual(run_benchmark.main(), 0)

        preflight.assert_called_once_with(configs, ("example",))
        query_identities.assert_not_called()
        self.assertEqual(run.call_count, 4)

    def test_parse_json_object_includes_intelligence(self) -> None:
        identity = run_benchmark.parse_json_object(
            json.dumps(
                {
                    "agent": "build",
                    "model": "example-model",
                    "intelligence": "high",
                }
            )
        )

        self.assertEqual(("build", "example-model", "high"), identity)

    def test_parse_json_object_defaults_missing_intelligence_to_unknown(self) -> None:
        identity = run_benchmark.parse_json_object(
            json.dumps({"agent": "build", "model": "example-model"})
        )

        self.assertEqual(("build", "example-model", "unknown"), identity)

    def test_execution_identity_reads_configured_reasoning_effort(self) -> None:
        identity = run_benchmark.execution_identity(
            {
                "agent": "build",
                "model": "example-model",
                "reasoning_effort": "xhigh",
                "command": ["example", "{prompt}"],
            }
        )

        self.assertEqual(("build", "example-model", "xhigh"), identity)

    def test_execution_identity_reads_effort_from_command(self) -> None:
        identity = run_benchmark.execution_identity(
            {
                "command": ["example", "--effort", "high", "{prompt}"],
            }
        )

        self.assertEqual(("unknown", "unknown", "high"), identity)


if __name__ == "__main__":
    unittest.main()
