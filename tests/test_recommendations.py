from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from model_dashboard.server import create_server
from model_dashboard.storage import DashboardStore
from model_dashboard.domain import DashboardError


class RecommendationTests(unittest.TestCase):
    def _data_path(self, directory: str) -> Path:
        path = Path(directory) / "dashboard.json"
        path.write_text(json.dumps({"meta": {}, "models": [{"id": "keep"}], "pricing": {"x": 1}}), encoding="utf-8")
        return path

    def test_old_data_gets_defaults_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self._data_path(directory)
            before = path.read_text(encoding="utf-8")
            data = DashboardStore(data_path=path).read()
            self.assertEqual(data["recommendations"]["agent_plan"][0]["model"], "GPT 6-Astra")
            self.assertEqual(data["recommendations"]["purpose_types"], ["Ask", "Plan", "Build", "Review", "Ship"])
            self.assertEqual(data["recommendations"]["agent_plan"][0]["primary_purpose_types"], ["Plan"])
            self.assertEqual(data["recommendations"]["agent_plan"][0]["secondary_purpose_types"], [])
            self.assertEqual(data["recommendations"]["agent_plan"][0]["purpose_types"], ["Plan"])
            self.assertEqual(data["recommendations"]["agent_plan"][0]["purpose_type"], "Plan")
            self.assertFalse(data["recommendations"]["agent_plan"][0]["is_core"])
            self.assertEqual(data["recommendations"]["agent_plan"][0]["core_purpose_types"], [])
            self.assertEqual(data["recommendations"]["agent_plan"][0]["purpose"], "复杂、多步骤且需要充分推理的 Agent 任务。")
            self.assertEqual(path.read_text(encoding="utf-8"), before)

    def test_old_partial_data_preserves_existing_empty_group(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self._data_path(directory)
            path.write_text(json.dumps({"meta": {}, "models": [], "recommendations": {"agent_plan": []}}), encoding="utf-8")
            recommendations = DashboardStore(data_path=path).read()["recommendations"]
            self.assertEqual(recommendations["agent_plan"], [])
        self.assertEqual(recommendations["coding_plan"][0]["model"], "DeepSeek V4.1 Flash")

    def test_default_deepseek_flash_is_visible_in_ship(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            recommendations = DashboardStore(data_path=Path(directory) / "dashboard.db").read()["recommendations"]
            row = recommendations["coding_plan"][0]
            self.assertEqual(row["model"], "DeepSeek V4.1 Flash")
            self.assertEqual(row["primary_purpose_types"], ["Ship"])
            self.assertEqual(row["secondary_purpose_types"], ["Build"])

    def test_save_preserves_other_data_and_survives_reopen(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self._data_path(directory)
            value = {
                "purpose_types": ["Ask", "Plan", "Build", "Review", "Ship"],
                "agent_plan": [],
                "coding_plan": [{
                    "tool": "", "model": "X", "reasoning_effort": "",
                    "primary_purpose_types": ["Build", "Review"],
                    "secondary_purpose_types": ["Ship"],
                    "is_core": True, "purpose": "快速生成代码",
                }],
            }
            saved = DashboardStore(data_path=path).save_recommendations(value)
            self.assertEqual(saved["coding_plan"][0]["purpose_types"], ["Build", "Review", "Ship"])
            self.assertEqual(saved["coding_plan"][0]["primary_purpose_types"], ["Build", "Review"])
            self.assertEqual(saved["coding_plan"][0]["secondary_purpose_types"], ["Ship"])
            self.assertEqual(saved["coding_plan"][0]["core_purpose_types"], ["Build", "Review"])
            self.assertEqual(saved["coding_plan"][0]["purpose_type"], "Build")
            self.assertEqual(saved["coding_plan"][0]["secondary_purpose_type"], "Ship")
            reopened = DashboardStore(data_path=path).read()
            self.assertEqual(reopened["recommendations"], saved)
            self.assertEqual(reopened["pricing"], {"x": 1})

    def test_invalid_input_does_not_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self._data_path(directory)
            before = path.read_bytes()
            with self.assertRaises(DashboardError):
                DashboardStore(data_path=path).save_recommendations({"agent_plan": [], "coding_plan": [{"model": 3}]})
            self.assertEqual(path.read_bytes(), before)

    def test_invalid_purpose_type_does_not_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self._data_path(directory)
            before = path.read_bytes()
            with self.assertRaisesRegex(DashboardError, "purpose_types"):
                DashboardStore(data_path=path).save_recommendations({
                    "purpose_types": ["Plan", "Review"],
                    "agent_plan": [{"model": "X", "purpose_types": ["Unknown"]}],
                    "coding_plan": [],
                })
            self.assertEqual(path.read_bytes(), before)

    def test_invalid_core_marker_does_not_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self._data_path(directory)
            before = path.read_bytes()
            with self.assertRaisesRegex(DashboardError, "is_core"):
                DashboardStore(data_path=path).save_recommendations({
                    "purpose_types": ["Plan"],
                    "agent_plan": [{"model": "X", "purpose_type": "Plan", "is_core": "yes"}],
                    "coding_plan": [],
                })
            self.assertEqual(path.read_bytes(), before)

    def test_core_marker_is_scoped_to_purpose_and_entry(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self._data_path(directory)
            saved = DashboardStore(data_path=path).save_recommendations({
                "purpose_types": ["Build", "Review"],
                "agent_plan": [{
                    "model": "X",
                    "primary_purpose_types": ["Build", "Review"],
                    "secondary_purpose_types": [],
                    "core_purpose_types": ["Review"],
                    "is_core": True,
                }],
                "coding_plan": [],
            })
            row = saved["agent_plan"][0]
            self.assertEqual(row["core_purpose_types"], ["Review"])
            self.assertTrue(row["is_core"])
            with self.assertRaisesRegex(DashboardError, "核心用途不是该条目的主用途"):
                DashboardStore(data_path=path).save_recommendations({
                    "purpose_types": ["Build", "Review"],
                    "agent_plan": [{
                        "model": "X",
                        "primary_purpose_types": ["Build"],
                        "secondary_purpose_types": ["Review"],
                        "core_purpose_types": ["Review"],
                    }],
                    "coding_plan": [],
                })

    def test_duplicate_purpose_types_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self._data_path(directory)
            before = path.read_bytes()
            with self.assertRaisesRegex(DashboardError, "重复类型"):
                DashboardStore(data_path=path).save_recommendations({
                    "purpose_types": ["Plan", "plan"], "agent_plan": [], "coding_plan": [],
                })
            with self.assertRaisesRegex(DashboardError, "重复类型"):
                DashboardStore(data_path=path).save_recommendations({
                    "purpose_types": ["Plan", "Review"],
                    "agent_plan": [{"model": "X", "purpose_types": ["Plan", "Plan"]}],
                    "coding_plan": [],
                })
            with self.assertRaisesRegex(DashboardError, "主用途与副用途包含重复类型"):
                DashboardStore(data_path=path).save_recommendations({
                    "purpose_types": ["Plan", "Review"],
                    "agent_plan": [{
                        "model": "X",
                        "primary_purpose_types": ["Plan", "Review"],
                        "secondary_purpose_types": ["Review"],
                    }],
                    "coding_plan": [],
                })
            self.assertEqual(path.read_bytes(), before)

    def test_old_row_without_purpose_is_normalized_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self._data_path(directory)
            path.write_text(json.dumps({
                "meta": {},
                "models": [],
                "recommendations": {
                    "agent_plan": [{"tool": "Codex", "model": "Legacy", "reasoning_effort": "High"}],
                    "coding_plan": [],
                },
            }), encoding="utf-8")
            before = path.read_text(encoding="utf-8")
            row = DashboardStore(data_path=path).read()["recommendations"]["agent_plan"][0]
            self.assertEqual(row["purpose_types"], [])
            self.assertEqual(row["primary_purpose_types"], [])
            self.assertEqual(row["secondary_purpose_types"], [])
            self.assertEqual(row["purpose_type"], "")
            self.assertEqual(row["secondary_purpose_type"], "")
            self.assertFalse(row["is_core"])
            self.assertEqual(row["core_purpose_types"], [])
            self.assertEqual(row["purpose"], "")
            self.assertEqual(path.read_text(encoding="utf-8"), before)

    def test_legacy_primary_and_secondary_purposes_become_multi_select(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self._data_path(directory)
            path.write_text(json.dumps({
                "meta": {},
                "models": [],
                "recommendations": {
                    "purpose_types": ["Plan", "Review", "Ship"],
                    "agent_plan": [{
                        "model": "Legacy", "purpose_type": "Plan",
                        "secondary_purpose_type": "Review",
                    }],
                    "coding_plan": [],
                },
            }), encoding="utf-8")
            before = path.read_text(encoding="utf-8")
            row = DashboardStore(data_path=path).read()["recommendations"]["agent_plan"][0]
            self.assertEqual(row["purpose_types"], ["Plan", "Review"])
            self.assertEqual(row["primary_purpose_types"], ["Plan"])
            self.assertEqual(row["secondary_purpose_types"], ["Review"])
            self.assertEqual(row["purpose_type"], "Plan")
            self.assertEqual(row["secondary_purpose_type"], "Review")
            self.assertEqual(path.read_text(encoding="utf-8"), before)

    def test_http_read_and_write(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self._data_path(directory)
            server = create_server("127.0.0.1", 0, data_path=path)
            thread = Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                base = f"http://127.0.0.1:{server.server_port}"
                with urlopen(f"{base}/api/models") as response:
                    payload = json.loads(response.read())
                self.assertIn("recommendations", payload)
                value = {
                    "purpose_types": ["Review", "Goal"],
                    "agent_plan": [],
                    "coding_plan": [{
                        "model": "Y", "primary_purpose_types": ["Review", "Goal"],
                        "secondary_purpose_types": [],
                        "is_core": True, "purpose": "代码补全",
                    }],
                }
                request = Request(f"{base}/api/recommendations", data=json.dumps(value).encode(), headers={"Content-Type": "application/json"}, method="POST")
                with urlopen(request) as response:
                    result = json.loads(response.read())
                self.assertEqual(result["recommendations"]["coding_plan"][0]["tool"], "")
                self.assertEqual(result["recommendations"]["coding_plan"][0]["purpose_types"], ["Review", "Goal"])
                self.assertEqual(result["recommendations"]["coding_plan"][0]["primary_purpose_types"], ["Review", "Goal"])
                self.assertEqual(result["recommendations"]["coding_plan"][0]["secondary_purpose_types"], [])
                self.assertEqual(result["recommendations"]["coding_plan"][0]["purpose_type"], "Review")
                self.assertEqual(result["recommendations"]["coding_plan"][0]["secondary_purpose_type"], "")
                self.assertTrue(result["recommendations"]["coding_plan"][0]["is_core"])
                self.assertEqual(result["recommendations"]["coding_plan"][0]["core_purpose_types"], ["Review", "Goal"])
                self.assertEqual(result["recommendations"]["coding_plan"][0]["purpose"], "代码补全")
                self.assertEqual(DashboardStore(data_path=path).read()["recommendations"], result["recommendations"])
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

    def test_publish_creates_immutable_versions_and_tracks_changes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self._data_path(directory)
            store = DashboardStore(data_path=path)

            first = store.publish_recommendations("首版")
            self.assertEqual(first["version"], 1)
            self.assertEqual(first["summary"]["initial"], 1)
            self.assertEqual(len(first["snapshot_sha256"]), 64)
            with self.assertRaisesRegex(DashboardError, "无需重复发布"):
                store.publish_recommendations()

            draft = store.read()["recommendations"]
            draft["agent_plan"][0]["purpose"] = "更新后的用途"
            store.save_recommendations(draft)
            second = store.publish_recommendations("调整用途")

            self.assertEqual(second["version"], 2)
            self.assertEqual(second["summary"]["updated"], 1)
            self.assertEqual(second["changes"][0]["fields"], ["purpose"])
            history = DashboardStore(data_path=path).recommendation_releases()
            self.assertTrue(history["is_current"])
            self.assertEqual(history["latest_version"], 2)
            self.assertEqual([item["version"] for item in history["releases"]], [2, 1])
            self.assertEqual(history["releases"][1]["recommendations"], first["recommendations"])

            draft = store.read()["recommendations"]
            draft["coding_plan"].append({
                "tool": "Codex", "model": "New", "reasoning_effort": "Low",
                "purpose_types": ["Build"], "is_core": False, "purpose": "快速处理",
            })
            store.save_recommendations(draft)
            self.assertFalse(store.recommendation_releases()["is_current"])

    def test_publish_note_validation_does_not_create_release(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            store = DashboardStore(data_path=self._data_path(directory))
            with self.assertRaisesRegex(DashboardError, "最多 300"):
                store.publish_recommendations("x" * 301)
            self.assertEqual(store.recommendation_releases()["releases"], [])

    def test_http_publish_and_read_release_history(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self._data_path(directory)
            server = create_server("127.0.0.1", 0, data_path=path)
            thread = Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                base = f"http://127.0.0.1:{server.server_port}"
                request = Request(
                    f"{base}/api/recommendations/publish",
                    data=json.dumps({"note": "HTTP 发布"}).encode(),
                    headers={"Content-Type": "application/json"},
                    method="POST",
                )
                with urlopen(request) as response:
                    self.assertEqual(response.status, 201)
                    release = json.loads(response.read())["release"]
                self.assertEqual(release["version"], 1)
                with urlopen(f"{base}/api/recommendations/releases?limit=10") as response:
                    history = json.loads(response.read())
                self.assertTrue(history["is_current"])
                self.assertEqual(history["releases"][0]["note"], "HTTP 发布")
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)

    def test_http_rejects_missing_group_and_keeps_file(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self._data_path(directory)
            before = path.read_bytes()
            server = create_server("127.0.0.1", 0, data_path=path)
            thread = Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                request = Request(f"http://127.0.0.1:{server.server_port}/api/recommendations", data=b'{"agent_plan": []}', headers={"Content-Type": "application/json"}, method="POST")
                with self.assertRaises(HTTPError) as context:
                    urlopen(request)
                self.assertEqual(context.exception.code, 400)
                self.assertEqual(path.read_bytes(), before)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
