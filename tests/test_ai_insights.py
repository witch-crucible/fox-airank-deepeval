from __future__ import annotations

import json
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from model_dashboard.ai_insights import (
    InsightConfig, normalize_goal, output_schema, run_codex_insight,
    snapshot_hash, validate_analysis,
)
from model_dashboard.domain import DashboardError
from model_dashboard.server import create_server
from model_dashboard.storage import DashboardStore


def example_snapshot():
    return {
        "candidates": [{
            "id": "alpha-high", "kind": "model", "model": "Alpha", "tool": "",
            "reasoning_effort": "high", "evidence": [{
                "id": "alpha-score", "label": "AA Intelligence", "value": 0,
                "unit": "分", "source": "Artificial Analysis", "as_of": "2026-09-25",
            }],
        }],
        "coverage": {"candidate_count": 1, "evidence_count": 1}, "warnings": ["本地测试不足"],
    }


def example_output(snapshot=None):
    snapshot = snapshot or example_snapshot()
    candidate = snapshot["candidates"][0]
    refs = [candidate["evidence"][0]["id"]]
    return {
        "summary": "当前数据仅可用于初步比较。",
        "findings": [{"title": "数据覆盖", "detail": "保留有效零分。", "evidence_ids": refs}],
        "recommendations": [{
            "candidate_id": candidate["id"], "use_case": "待补测", "reason": "已有公开指标。",
            "tradeoffs": "本地实测证据不足。", "evidence_ids": refs,
        }],
        "limitations": ["不代表生产效果。"],
    }


class InsightValidationTests(unittest.TestCase):
    def test_identity_and_evidence_come_from_snapshot(self):
        result = validate_analysis(example_output(), example_snapshot(), "代码审查", InsightConfig())
        self.assertEqual(result["recommendations"][0]["candidate"]["model"], "Alpha")
        self.assertEqual(result["recommendations"][0]["evidence"][0]["value"], 0)
        self.assertEqual(result["findings"][0]["evidence"][0]["reasoning_effort"], "high")
        self.assertEqual(result["snapshot_hash"], snapshot_hash(example_snapshot()))
        self.assertEqual(result["goal"], "代码审查")

    def test_invented_candidate_or_evidence_is_rejected(self):
        for field, value in [("candidate_id", "made-up"), ("candidate_id", []), ("evidence_ids", ["made-up"]), ("evidence_ids", [])]:
            with self.subTest(field=field, value=value):
                output = example_output()
                output["recommendations"][0][field] = value
                with self.assertRaises(DashboardError):
                    validate_analysis(output, example_snapshot(), "", InsightConfig())

    def test_other_configuration_cannot_supply_recommendation_evidence(self):
        snapshot = example_snapshot()
        snapshot["candidates"].append({
            **snapshot["candidates"][0], "id": "alpha-low", "reasoning_effort": "low",
            "evidence": [{**snapshot["candidates"][0]["evidence"][0], "id": "alpha-low-score"}],
        })
        output = example_output()
        output["recommendations"][0]["evidence_ids"] = ["alpha-low-score"]
        with self.assertRaisesRegex(DashboardError, "不属于"):
            validate_analysis(output, snapshot, "", InsightConfig())

    def test_malformed_or_excessive_output_is_rejected(self):
        invalid = [None, [], {**example_output(), "summary": ""}, {**example_output(), "summary": "长" * 2001},
                   {**example_output(), "limitations": ["x"] * 9}, {**example_output(), "extra": "field"}]
        for output in invalid:
            with self.subTest(output_type=type(output)):
                with self.assertRaises(DashboardError):
                    validate_analysis(output, example_snapshot(), "", InsightConfig())

    def test_schema_constrains_existing_ids_and_strict_objects(self):
        schema = output_schema(example_snapshot())
        row = schema["properties"]["recommendations"]["items"]
        self.assertEqual(row["properties"]["candidate_id"]["enum"], ["alpha-high"])
        self.assertFalse(row["additionalProperties"])
        self.assertEqual(set(row["required"]), set(row["properties"]))

    def test_hash_is_stable_but_changes_with_evidence(self):
        first = example_snapshot()
        self.assertEqual(snapshot_hash(first), snapshot_hash(dict(reversed(list(first.items())))))
        first["candidates"][0]["evidence"][0]["value"] = 1
        self.assertNotEqual(snapshot_hash(first), snapshot_hash(example_snapshot()))

    def test_goal_and_environment_validation(self):
        self.assertTrue(normalize_goal({"goal": "  "}))
        self.assertEqual(normalize_goal({"goal": " 审查 "}), "审查")
        for value in [[], {"goal": 3}, {"goal": "长" * 1001}, {"model": "other"}]:
            with self.assertRaises(DashboardError):
                normalize_goal(value)
        for kwargs in [{"model": "--help"}, {"timeout_seconds": 0}, {"timeout_seconds": True}, {"reasoning_effort": "invalid"}]:
            with self.assertRaises(DashboardError):
                InsightConfig(**kwargs)
        with patch.dict("os.environ", {"MODEL_DASHBOARD_AI_TIMEOUT": "bad"}):
            with self.assertRaises(DashboardError):
                InsightConfig.from_env()


class InsightRunnerTests(unittest.TestCase):
    def test_headless_stdin_schema_and_final_file(self):
        def run(command, **kwargs):
            self.assertEqual(command[:4], ["codex", "exec", "--skip-git-repo-check", "--ephemeral"])
            self.assertEqual(command[command.index("--sandbox") + 1], "read-only")
            self.assertIn("--ignore-user-config", command)
            self.assertIn("--ignore-rules", command)
            self.assertIn("shell_tool", command)
            self.assertIn("multi_agent", command)
            self.assertEqual(command[-1], "-")
            self.assertEqual(kwargs["timeout"], 25)
            self.assertIn("仅使用下方 JSON 证据", kwargs["input"])
            self.assertIn("AA Intelligence", kwargs["input"])
            self.assertTrue(Path(kwargs["cwd"]).is_dir())
            schema = json.loads(Path(command[command.index("--output-schema") + 1]).read_text())
            self.assertFalse(schema["additionalProperties"])
            Path(command[command.index("--output-last-message") + 1]).write_text(json.dumps(example_output()))
            return SimpleNamespace(returncode=0, stdout="progress is not JSON", stderr="")

        with patch("model_dashboard.ai_insights.subprocess.run", side_effect=run):
            output = run_codex_insight("需求", example_snapshot(), InsightConfig(timeout_seconds=25))
        self.assertEqual(output, example_output())

    def test_failure_never_exposes_cli_stderr(self):
        with patch("model_dashboard.ai_insights.subprocess.run", return_value=SimpleNamespace(returncode=7, stderr="secret-token", stdout="private/path")):
            with self.assertRaisesRegex(DashboardError, "退出码 7") as raised:
                run_codex_insight("", example_snapshot(), InsightConfig())
        self.assertNotIn("secret-token", str(raised.exception))
        self.assertNotIn("private/path", str(raised.exception))

    def test_timeout_missing_cli_and_missing_result(self):
        for error, expected in [(subprocess.TimeoutExpired("codex", 10), "超时"), (FileNotFoundError(), "未找到"), (PermissionError(), "无法运行")]:
            with patch("model_dashboard.ai_insights.subprocess.run", side_effect=error):
                with self.assertRaisesRegex(DashboardError, expected):
                    run_codex_insight("", example_snapshot(), InsightConfig())
        with patch("model_dashboard.ai_insights.subprocess.run", return_value=SimpleNamespace(returncode=0)):
            with self.assertRaisesRegex(DashboardError, "未返回"):
                run_codex_insight("", example_snapshot(), InsightConfig())

    def test_invalid_json_rejected(self):
        def run(command, **kwargs):
            Path(command[command.index("--output-last-message") + 1]).write_text("not json")
            return SimpleNamespace(returncode=0)
        with patch("model_dashboard.ai_insights.subprocess.run", side_effect=run):
            with self.assertRaisesRegex(DashboardError, "有效 JSON"):
                run_codex_insight("", example_snapshot(), InsightConfig())

    def test_empty_or_oversized_input_never_calls_codex(self):
        with patch("model_dashboard.ai_insights.subprocess.run") as run:
            with self.assertRaisesRegex(DashboardError, "有效模型"):
                run_codex_insight("", {"candidates": []}, InsightConfig())
            with patch("model_dashboard.ai_insights.MAX_SNAPSHOT_BYTES", 20):
                with self.assertRaisesRegex(DashboardError, "数据过大"):
                    run_codex_insight("", example_snapshot(), InsightConfig())
            run.assert_not_called()


class InsightApiTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        root = Path(self.directory.name)
        self.path = root / "dashboard.json"
        self.path.write_text(json.dumps({"meta": {}, "models": [{
            "id": "alpha", "tool": "Lab", "model": "Alpha", "reasoning_effort": "high",
            "scores": {"aa_model_intelligence": 80},
            "source": {"type": "artificial_analysis_model", "fetched_at": "2026-09-25"},
        }]}))
        self.runner = Mock(side_effect=lambda goal, snapshot, config: example_output(snapshot))
        self.server = create_server("127.0.0.1", 0, data_path=self.path, runs_root=root / "runs", cases_root=root / "cases",
                                    insight_runner=self.runner, insight_config=InsightConfig())
        self.addCleanup(self.server.server_close)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.thread.join, 2)
        self.addCleanup(self.server.shutdown)
        self.url = f"http://127.0.0.1:{self.server.server_port}/api/ai-insights"

    def request(self, payload=None):
        request = Request(self.url, data=json.dumps(payload).encode() if payload is not None else None,
                          headers={"Content-Type": "application/json"})
        with urlopen(request, timeout=5) as response:
            return json.load(response)

    def test_generation_persists_separately_and_get_does_not_generate(self):
        before = self.server.store.read()
        empty = self.request()
        self.assertIsNone(empty["analysis"])
        self.runner.assert_not_called()
        result = self.request({"goal": "代码审查"})
        self.assertEqual(result["analysis"]["goal"], "代码审查")
        self.assertFalse(result["stale"])
        self.assertFalse(result["busy"])
        self.assertEqual(self.server.store.read(), before)
        self.assertEqual(DashboardStore(data_path=self.path).latest_ai_insight(), result["analysis"])
        self.assertEqual(self.request()["analysis"], result["analysis"])
        self.runner.assert_called_once()

    def test_failure_preserves_success_and_releases_busy_lock(self):
        success = self.request({})["analysis"]
        self.runner.side_effect = DashboardError("模拟超时")
        with self.assertRaises(HTTPError) as raised:
            self.request({})
        self.assertEqual(raised.exception.code, 400)
        self.assertEqual(self.request()["analysis"], success)
        self.assertFalse(self.server.insight_lock.locked())

    def test_bad_ai_reference_never_overwrites_last_result(self):
        success = self.request({})["analysis"]
        self.runner.side_effect = None
        self.runner.return_value = example_output()
        with self.assertRaises(HTTPError):
            self.request({})
        self.assertEqual(self.request()["analysis"], success)

    def test_changes_during_generation_are_marked_stale(self):
        def run(goal, snapshot, config):
            self.server.store.set_model_archived("alpha", True)
            return example_output(snapshot)
        self.runner.side_effect = run
        result = self.request({})
        self.assertTrue(result["stale"])
        self.assertEqual(result["coverage"]["candidate_count"], 0)

    def test_concurrent_generation_and_invalid_input_do_not_start_runner(self):
        self.server.insight_lock.acquire()
        try:
            with self.assertRaises(HTTPError) as raised:
                self.request({})
            self.assertEqual(raised.exception.code, 409)
            self.assertTrue(self.request()["busy"])
        finally:
            self.server.insight_lock.release()
        with self.assertRaises(HTTPError):
            self.request({"goal": ["invalid"]})
        self.runner.assert_not_called()

    def test_no_evidence_does_not_start_runner(self):
        self.server.store.set_model_archived("alpha", True)
        with self.assertRaises(HTTPError):
            self.request({})
        self.runner.assert_not_called()


if __name__ == "__main__":
    unittest.main()
