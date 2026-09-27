from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from model_dashboard.ai_insights import (
    InsightConfig, normalize_goal, output_schema, run_sensenova_insight,
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


def chat_payload(content):
    return json.dumps({"choices": [{"message": {"content": content}}]}, ensure_ascii=False).encode("utf-8")


class FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, size=-1):
        return self._payload


class InsightValidationTests(unittest.TestCase):
    def test_identity_and_evidence_come_from_snapshot(self):
        result = validate_analysis(example_output(), example_snapshot(), "代码审查", InsightConfig())
        self.assertEqual(result["recommendations"][0]["candidate"]["model"], "Alpha")
        self.assertEqual(result["recommendations"][0]["evidence"][0]["value"], 0)
        self.assertEqual(result["findings"][0]["evidence"][0]["reasoning_effort"], "high")
        self.assertEqual(result["snapshot_hash"], snapshot_hash(example_snapshot()))
        self.assertEqual(result["goal"], "代码审查")
        self.assertEqual(result["provider"], "sensenova")
        self.assertNotIn("reasoning_effort", result)

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
        for kwargs in [{"model": "--help"}, {"timeout_seconds": 0}, {"timeout_seconds": True},
                       {"base_url": "http://example.com/v1"}, {"base_url": "ftp://token.sensenova.cn/v1"},
                       {"base_url": "https://"}]:
            with self.assertRaises(DashboardError):
                InsightConfig(**kwargs)
        with patch.dict("os.environ", {"MODEL_DASHBOARD_AI_TIMEOUT": "bad"}):
            with self.assertRaises(DashboardError):
                InsightConfig.from_env()
        with patch.dict("os.environ", {"MODEL_DASHBOARD_AI_BASE_URL": "http://localhost:9000/v1", "SENSENOVA_API_KEY": ""}, clear=False):
            self.assertEqual(InsightConfig.from_env().base_url, "http://localhost:9000/v1")

    def test_public_config_hides_the_api_key(self):
        config = InsightConfig(api_key="secret-key-value")
        public = config.public()
        self.assertEqual(public["provider"], "sensenova")
        self.assertEqual(public["model"], "sensenova-6.8-flash-lite")
        self.assertTrue(public["available"])
        self.assertNotIn("secret-key-value", json.dumps(public, ensure_ascii=False))
        self.assertNotIn("secret-key-value", repr(config))
        self.assertFalse(InsightConfig(api_key="").public()["available"])


class InsightRunnerTests(unittest.TestCase):
    def test_request_carries_model_evidence_and_schema(self):
        captured = {}

        def fake_urlopen(request, **kwargs):
            captured["request"] = request
            captured["timeout"] = kwargs.get("timeout")
            return FakeResponse(chat_payload(json.dumps(example_output(), ensure_ascii=False)))

        with patch("model_dashboard.ai_insights.urlopen", side_effect=fake_urlopen):
            output = run_sensenova_insight("需求", example_snapshot(), InsightConfig(api_key="secret-key", timeout_seconds=25))
        self.assertEqual(output, example_output())
        request = captured["request"]
        self.assertEqual(request.full_url, "https://token.sensenova.cn/v1/chat/completions")
        self.assertEqual(request.get_header("Authorization"), "Bearer secret-key")
        self.assertEqual(captured["timeout"], 25)
        body = json.loads(request.data.decode("utf-8"))
        self.assertEqual(body["model"], "sensenova-6.8-flash-lite")
        self.assertFalse(body["stream"])
        prompt = "".join(message["content"] for message in body["messages"])
        self.assertIn("仅使用下方 JSON 证据", prompt)
        self.assertIn("AA Intelligence", prompt)
        self.assertIn("alpha-high", prompt)
        self.assertIn("只输出一个符合该 schema 的 JSON 对象，不要 Markdown", prompt)

    def test_fenced_json_reply_is_parsed(self):
        content = "```json\n" + json.dumps(example_output(), ensure_ascii=False) + "\n```"
        with patch("model_dashboard.ai_insights.urlopen", return_value=FakeResponse(chat_payload(content))):
            self.assertEqual(
                run_sensenova_insight("", example_snapshot(), InsightConfig(api_key="key")),
                example_output(),
            )

    def test_http_and_network_errors_never_expose_key_or_body(self):
        cases = [(401, "Key 无效"), (403, "没有该模型的访问权限"), (429, "配额"), (500, "HTTP 500")]
        for code, expected in cases:
            with self.subTest(code=code):
                error = HTTPError("https://token.sensenova.cn/v1/chat/completions", code, "leaked-body", {}, None)
                with patch("model_dashboard.ai_insights.urlopen", side_effect=error):
                    with self.assertRaisesRegex(DashboardError, expected) as raised:
                        run_sensenova_insight("", example_snapshot(), InsightConfig(api_key="secret-key"))
                self.assertNotIn("secret-key", str(raised.exception))
                self.assertNotIn("leaked-body", str(raised.exception))
        with patch("model_dashboard.ai_insights.urlopen", side_effect=URLError("dns failure")):
            with self.assertRaisesRegex(DashboardError, "无法连接 SenseNova") as raised:
                run_sensenova_insight("", example_snapshot(), InsightConfig(api_key="secret-key"))
        self.assertNotIn("secret-key", str(raised.exception))
        self.assertNotIn("dns failure", str(raised.exception))

    def test_invalid_or_empty_content_is_rejected(self):
        for content in ["not json", "", "   ", "无 JSON 对象", "[1, 2, 3]"]:
            with self.subTest(content=content[:20]):
                with patch("model_dashboard.ai_insights.urlopen", return_value=FakeResponse(chat_payload(content))):
                    with self.assertRaisesRegex(DashboardError, "有效 JSON"):
                        run_sensenova_insight("", example_snapshot(), InsightConfig(api_key="key"))

    def test_malformed_envelope_is_rejected(self):
        for payload in [b"not json", b"", json.dumps({"choices": []}).encode("utf-8")]:
            with self.subTest(payload=payload[:20]):
                with patch("model_dashboard.ai_insights.urlopen", return_value=FakeResponse(payload)):
                    with self.assertRaisesRegex(DashboardError, "有效 JSON"):
                        run_sensenova_insight("", example_snapshot(), InsightConfig(api_key="key"))

    def test_missing_key_raises_before_any_network_call(self):
        with patch("model_dashboard.ai_insights.urlopen") as urlopen_mock:
            with self.assertRaisesRegex(DashboardError, "未配置 SENSENOVA_API_KEY"):
                run_sensenova_insight("", example_snapshot(), InsightConfig(api_key=""))
            urlopen_mock.assert_not_called()

    def test_empty_or_oversized_input_never_calls_api(self):
        with patch("model_dashboard.ai_insights.urlopen") as urlopen_mock:
            with self.assertRaisesRegex(DashboardError, "有效模型"):
                run_sensenova_insight("", {"candidates": []}, InsightConfig(api_key="key"))
            with patch("model_dashboard.ai_insights.MAX_SNAPSHOT_BYTES", 20):
                with self.assertRaisesRegex(DashboardError, "数据过大"):
                    run_sensenova_insight("", example_snapshot(), InsightConfig(api_key="key"))
            urlopen_mock.assert_not_called()


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
                                    insight_runner=self.runner, insight_config=InsightConfig(api_key="test"))
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

    def test_config_endpoint_never_exposes_the_key(self):
        response = self.request()
        self.assertEqual(response["config"]["provider"], "sensenova")
        self.assertTrue(response["config"]["available"])
        self.assertNotIn("test", json.dumps(response["config"]))

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
