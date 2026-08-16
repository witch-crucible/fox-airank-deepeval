import json
import os
import tempfile
import threading
import unittest
import warnings
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from model_dashboard.server import (
    ARENA_DATASET_URL,
    ARTIFICIAL_ANALYSIS_URL,
    LLM_STATS_INDEX_URL,
    DashboardError,
    SameOriginRedirectHandler,
    DashboardStore,
    calculate_scores,
    create_server,
    fetch_json,
    normalize_model,
    url_origin,
    normalize_arena_webdev_rows,
    normalize_artificial_analysis_html,
    normalize_external_rows,
    normalize_llm_stats_indexes,
)


class ModelDashboardTests(unittest.TestCase):
    @staticmethod
    def _artificial_analysis_document(count=3, score_offset=0):
        rows = []
        for index in range(1, count + 1):
            score = (70 - index + score_offset) / 100
            rows.append(
                {
                    "id": f"aa-{index}",
                    "display": {
                        "agent": f"Agent {index}",
                        "model": f"Model {index}",
                        "creator": {"agent": "Test Lab", "model": "Test Lab"},
                    },
                    "displayLabel": f"Agent {index} - Model {index}",
                    "indexScore": score,
                    "evals": [
                        {"datasetIndexName": "deep-swe", "mean": {"reward": score - 0.01}},
                        {"datasetIndexName": "terminal-bench-v2", "mean": {"reward": score + 0.02}},
                        {"datasetIndexName": "swe-atlas-qna", "mean": {"reward": score - 0.01}},
                    ],
                    "mean": {"costUsd": index / 10, "agentWallTimeSec": index * 100},
                }
            )
        payload = json.dumps([1, "prefix" + "".join(json.dumps(row) for row in rows)])
        return (
            "<html><body>Artificial Analysis Coding Agent Index v1.3"
            f"<script>self.__next_f.push({payload})</script></body></html>"
        )

    @staticmethod
    def _arena_document(count=31, score_offset=0):
        return {
            "rows": [
                {
                    "row": {
                        "model_name": f"Arena Model {rank}",
                        "organization": "Test Lab",
                        "license": "Test License",
                        "rating": 1701 - rank + score_offset,
                        "rank": rank,
                        "category": "overall",
                        "leaderboard_publish_date": "2026-08-12",
                    }
                }
                for rank in range(1, count + 1)
            ]
        }

    @staticmethod
    def _llm_stats_document(count=3, score_offset=0):
        def rows(category_offset):
            return [
                {
                    "model_id": f"llm-{rank}",
                    "model_name": f"LLM {rank}",
                    "organization_id": "test-lab",
                    "organization_name": "Test Lab",
                    "conservative": 60 - rank + category_offset + score_offset,
                    "rank": rank,
                    "rank_delta_14d": 1 - rank,
                    "games_played": 10 + rank,
                }
                for rank in range(1, count + 1)
            ]

        return {
            "general": {"models": rows(0)},
            "reasoning": {"models": rows(-1)},
            "code": {"models": rows(-2)},
            "agents": {"models": rows(-3)},
        }

    def test_calculate_scores_preserves_missing_values_and_uses_case_weights(self):
        scores = calculate_scores(
            {
                "skill_call": 10,
                "code_review": 8,
                "logic_analysis": 9,
                "function_fix": 9,
                "model_test_correction": 100,
                "model_test_generation": 100,
                "model_test_logic": 87.14,
                "arena_webdev": 1565,
            }
        )
        self.assertEqual(scores["manual_total"], 36)
        self.assertEqual(scores["model_test_total"], 93.08)
        self.assertEqual(scores["composite_total"], 1694.08)

        missing = calculate_scores({})
        self.assertIsNone(missing["manual_total"])
        self.assertIsNone(missing["model_test_total"])
        self.assertIsNone(missing["composite_total"])

    def test_external_rows_use_dot_paths_and_reject_unknown_targets(self):
        models = normalize_external_rows(
            {"data": {"models": [{"identity": {"agent": "Codex", "model": "GPT-X"}, "score": 96.5}]}},
            "data.models",
            {"tool": "identity.agent", "model": "identity.model", "scores.model_test_total": "score"},
            "测试接口",
            "https://example.com/models",
        )
        self.assertEqual(models[0]["tool"], "Codex")
        self.assertEqual(models[0]["scores"]["model_test_total"], 96.5)
        self.assertEqual(models[0]["source"]["type"], "third_party")

        with self.assertRaisesRegex(DashboardError, "不支持的目标字段"):
            normalize_external_rows([], "", {"tool": "tool", "model": "model", "unsafe": "x"}, "source", "https://example.com")

    def test_arena_rows_require_and_normalize_top_30(self):
        models = normalize_arena_webdev_rows(self._arena_document())
        self.assertEqual(len(models), 30)
        self.assertEqual(models[0]["model"], "Arena Model 1")
        self.assertEqual(models[0]["scores"]["arena_webdev"], 1700)
        self.assertEqual(models[0]["source"]["type"], "arena_webdev")
        self.assertEqual(models[-1]["source"]["rank"], 30)

        with self.assertRaisesRegex(DashboardError, "不足 30 条"):
            normalize_arena_webdev_rows(self._arena_document(count=29))

    def test_artificial_analysis_html_normalizes_score_and_rank(self):
        models = normalize_artificial_analysis_html(self._artificial_analysis_document())
        self.assertEqual(len(models), 3)
        self.assertEqual(models[0]["tool"], "Agent 1")
        self.assertEqual(models[0]["model"], "Model 1")
        self.assertEqual(models[0]["scores"]["artificial_analysis_index"], 69)
        self.assertEqual(models[0]["scores"]["aa_deep_swe"], 68)
        self.assertEqual(models[0]["source"]["rank"], 1)
        self.assertEqual(models[0]["source"]["index_version"], "v1.3")

        with self.assertRaisesRegex(DashboardError, "缺少榜单数据"):
            normalize_artificial_analysis_html("<html></html>")

    def test_llm_stats_indexes_normalize_official_rank_and_scores(self):
        models = normalize_llm_stats_indexes(self._llm_stats_document())
        self.assertEqual(len(models), 3)
        self.assertEqual(models[0]["tool"], "Test Lab")
        self.assertEqual(models[0]["model"], "LLM 1")
        self.assertEqual(models[0]["scores"]["llm_stats_score"], 59)
        self.assertEqual(models[0]["scores"]["llm_stats_reasoning"], 58)
        self.assertEqual(models[0]["scores"]["llm_stats_code"], 57)
        self.assertEqual(models[0]["scores"]["llm_stats_agents"], 56)
        self.assertEqual(models[0]["source"]["rank"], 1)
        self.assertEqual(models[0]["source"]["source_id"], "llm-1")

        with self.assertRaisesRegex(DashboardError, "缺少 general 总榜"):
            normalize_llm_stats_indexes({})

    def test_http_page_add_model_and_import_third_party_data(self):
        third_party_document = {
            "payload": [
                {
                    "agent": "OpenCode",
                    "name": "Remote Model",
                    "scores": {"model_test": 91, "arena": 1500},
                }
            ]
        }
        fetched = []

        def fake_fetcher(url, auth):
            fetched.append((url, auth))
            return third_party_document

        with tempfile.TemporaryDirectory() as directory:
            data_path = Path(directory) / "dashboard.json"
            server = create_server("127.0.0.1", 0, data_path=data_path, json_fetcher=fake_fetcher)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base_url = f"http://127.0.0.1:{server.server_port}"
            try:
                with urlopen(f"{base_url}/", timeout=3) as response:
                    html = response.read().decode("utf-8")
                    self.assertIn("AI 模型能力测试", html)
                    self.assertIn("增加模型", html)
                    self.assertIn("看板模式", html)
                    self.assertIn("表格模式", html)
                    self.assertIn("按归档状态筛选", html)
                    self.assertIn('aria-sort', html)
                    self.assertIn('按${column.label}排序', html)
                    self.assertIn('每页 50 条', html)
                    self.assertIn('本地更新', html)
                    self.assertIn('role="status"', html)
                    self.assertNotIn('<main id="app" aria-live=', html)
                    self.assertIn("同步 Arena 前 30", html)
                    self.assertIn("同步 AA 编程榜", html)
                    self.assertIn("同步 LLM Stats", html)
                    self.assertIn('data-view="table"', html)
                    self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")

                created = self._post_json(
                    f"{base_url}/api/models",
                    {
                        "id": "client-controlled-id",
                        "tool": "Codex",
                        "model": "Local Model",
                        "scores": {"skill_call": 8},
                        "source": {"type": "arena_webdev", "name": "伪造来源"},
                        "archived": True,
                    },
                )
                self.assertEqual(created["model"]["scores"]["manual_total"], 8)
                self.assertNotEqual(created["model"]["id"], "client-controlled-id")
                self.assertEqual(created["model"]["source"], {"type": "manual", "name": "手工录入"})
                self.assertFalse(created["model"]["archived"])

                imported = self._post_json(
                    f"{base_url}/api/import",
                    {
                        "name": "远端榜单",
                        "url": "https://example.com/models.json",
                        "array_path": "payload",
                        "mapping": {
                            "tool": "agent",
                            "model": "name",
                            "scores.model_test_total": "scores.model_test",
                            "scores.arena_webdev": "scores.arena",
                        },
                    },
                )
                self.assertEqual(imported, {"created": 1, "updated": 0, "skipped": 0, "received": 1})
                self.assertEqual(fetched, [("https://example.com/models.json", None)])

                with urlopen(f"{base_url}/api/models", timeout=3) as response:
                    data = json.load(response)
                self.assertEqual(len(data["models"]), 22)
                self.assertEqual(data["models"][-1]["source"]["name"], "远端榜单")
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=3)

    def test_authenticated_json_source_requires_https_before_network_access(self):
        with patch.dict(os.environ, {"MODEL_API_TOKEN": "secret"}, clear=False):
            with patch("model_dashboard.server.urlopen") as mocked_urlopen:
                with self.assertRaisesRegex(DashboardError, "必须使用 HTTPS"):
                    fetch_json("http://example.com/models.json", {"env": "MODEL_API_TOKEN"})
                mocked_urlopen.assert_not_called()

    def test_authenticated_redirect_rejects_cross_origin_before_copying_headers(self):
        request = Request(
            "https://source.example/models.json",
            headers={"Authorization": "Bearer secret"},
        )
        handler = SameOriginRedirectHandler()
        with self.assertRaisesRegex(DashboardError, "不能重定向到其他站点"):
            handler.redirect_request(
                request,
                None,
                302,
                "Found",
                {},
                "https://other.example/models.json",
            )

    def test_authenticated_redirect_treats_default_https_port_as_same_origin(self):
        request = Request(
            "https://source.example/models.json",
            headers={"Authorization": "Bearer secret"},
        )
        redirected = SameOriginRedirectHandler().redirect_request(
            request,
            None,
            302,
            "Found",
            {},
            "https://source.example:443/next.json",
        )
        self.assertIsNotNone(redirected)
        self.assertEqual(redirected.get_header("Authorization"), "Bearer secret")

    def test_normalize_model_rejects_all_non_object_sources(self):
        for source in ([], False, 0, "", "bad"):
            with self.subTest(source=source):
                with self.assertRaisesRegex(DashboardError, "source 必须是对象"):
                    normalize_model({"tool": "Codex", "model": "Model", "source": source})

    def test_url_origin_rejects_invalid_ports_with_dashboard_error(self):
        for url in ("https://example.com:bad/models", "https://example.com:70000/models"):
            with self.subTest(url=url):
                with self.assertRaisesRegex(DashboardError, "URL 端口无效"):
                    url_origin(url)

    def test_archive_rejects_duplicate_legacy_ids_without_modifying_data(self):
        with tempfile.TemporaryDirectory() as directory:
            data_path = Path(directory) / "dashboard.json"
            data = {
                "meta": {},
                "models": [
                    {"id": "duplicate", "archived": False, "updated_at": "first"},
                    {"id": "duplicate", "archived": False, "updated_at": "second"},
                ],
            }
            data_path.write_text(json.dumps(data), encoding="utf-8")
            store = DashboardStore(data_path=data_path)

            with self.assertRaisesRegex(DashboardError, "包含重复的模型 ID"):
                store.set_model_archived("duplicate", True)

            self.assertEqual(json.loads(data_path.read_text(encoding="utf-8")), data)

    def test_http_archives_and_restores_model_without_deleting_it(self):
        with tempfile.TemporaryDirectory() as directory:
            server = create_server("127.0.0.1", 0, data_path=Path(directory) / "dashboard.json")
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base_url = f"http://127.0.0.1:{server.server_port}"
            try:
                created = self._post_json(
                    f"{base_url}/api/models",
                    {"tool": "Codex", "model": "Archive Model"},
                )["model"]
                archived = self._post_json(
                    f"{base_url}/api/models/{created['id']}/archive",
                    {"archived": True},
                )["model"]
                self.assertTrue(archived["archived"])
                self.assertTrue(archived["archived_at"])

                with urlopen(f"{base_url}/api/models", timeout=3) as response:
                    data = json.load(response)
                stored = next(model for model in data["models"] if model["id"] == created["id"])
                self.assertTrue(stored["archived"])

                restored = self._post_json(
                    f"{base_url}/api/models/{created['id']}/archive",
                    {"archived": False},
                )["model"]
                self.assertFalse(restored["archived"])
                self.assertEqual(restored["archived_at"], "")
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=3)

    def test_third_party_overwrite_preserves_archived_state(self):
        with tempfile.TemporaryDirectory() as directory:
            data_path = Path(directory) / "dashboard.json"
            server = create_server("127.0.0.1", 0, data_path=data_path)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base_url = f"http://127.0.0.1:{server.server_port}"
            try:
                created = self._post_json(
                    f"{base_url}/api/models",
                    {"tool": "Codex", "model": "Archive Model", "scores": {"skill_call": 5}},
                )["model"]
                self._post_json(
                    f"{base_url}/api/models/{created['id']}/archive",
                    {"archived": True},
                )
                replacement = {
                    **created,
                    "scores": {"skill_call": 9},
                    "source": {"type": "third_party", "name": "测试接口"},
                }
                result = server.store.import_models([replacement], overwrite=True)  # type: ignore[attr-defined]
                self.assertEqual(result, {"created": 0, "updated": 1, "skipped": 0})

                with urlopen(f"{base_url}/api/models", timeout=3) as response:
                    data = json.load(response)
                stored = next(model for model in data["models"] if model["id"] == created["id"])
                self.assertTrue(stored["archived"])
                self.assertTrue(stored["archived_at"])
                self.assertEqual(stored["scores"]["skill_call"], 9)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=3)

    def test_http_syncs_arena_top_30_without_overwriting_other_models(self):
        documents = [self._arena_document(), self._arena_document(score_offset=5)]
        fetched = []

        def fake_fetcher(url, auth):
            fetched.append((url, auth))
            return documents.pop(0)

        with tempfile.TemporaryDirectory() as directory:
            server = create_server("127.0.0.1", 0, data_path=Path(directory) / "dashboard.json", json_fetcher=fake_fetcher)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base_url = f"http://127.0.0.1:{server.server_port}"
            try:
                first = self._post_json(f"{base_url}/api/import/arena-webdev", {})
                self.assertEqual(first, {"created": 30, "updated": 0, "removed": 0, "received": 30})
                second = self._post_json(f"{base_url}/api/import/arena-webdev", {})
                self.assertEqual(second, {"created": 0, "updated": 30, "removed": 0, "received": 30})
                self.assertEqual(fetched, [(ARENA_DATASET_URL, None), (ARENA_DATASET_URL, None)])

                with urlopen(f"{base_url}/api/models", timeout=3) as response:
                    data = json.load(response)
                arena_models = [model for model in data["models"] if model["source"]["type"] == "arena_webdev"]
                self.assertEqual(len(arena_models), 30)
                self.assertEqual(arena_models[0]["scores"]["arena_webdev"], 1705)
                self.assertEqual(len(data["models"]), 50)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=3)

    def test_arena_sync_retains_archived_model_after_it_leaves_top_30(self):
        first_document = self._arena_document()
        second_document = self._arena_document()
        second_document["rows"] = [
            row
            for row in second_document["rows"]
            if row["row"]["model_name"] != "Arena Model 30"
        ]
        documents = [first_document, second_document]

        def fake_fetcher(url, auth):
            return documents.pop(0)

        with tempfile.TemporaryDirectory() as directory:
            server = create_server(
                "127.0.0.1",
                0,
                data_path=Path(directory) / "dashboard.json",
                json_fetcher=fake_fetcher,
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base_url = f"http://127.0.0.1:{server.server_port}"
            try:
                self._post_json(f"{base_url}/api/import/arena-webdev", {})
                with urlopen(f"{base_url}/api/models", timeout=3) as response:
                    data = json.load(response)
                archived_model = next(model for model in data["models"] if model["model"] == "Arena Model 30")
                self._post_json(
                    f"{base_url}/api/models/{archived_model['id']}/archive",
                    {"archived": True},
                )

                result = self._post_json(f"{base_url}/api/import/arena-webdev", {})
                self.assertEqual(result, {"created": 1, "updated": 29, "removed": 0, "received": 30})
                with urlopen(f"{base_url}/api/models", timeout=3) as response:
                    data = json.load(response)
                retained = next(model for model in data["models"] if model["model"] == "Arena Model 30")
                self.assertTrue(retained["archived"])
                self.assertEqual(len([model for model in data["models"] if model["source"]["type"] == "arena_webdev"]), 31)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=3)

    def test_http_syncs_artificial_analysis_ranking_without_overwriting_other_models(self):
        documents = [self._artificial_analysis_document(), self._artificial_analysis_document(score_offset=5)]
        fetched = []

        def fake_text_fetcher(url):
            fetched.append(url)
            return documents.pop(0)

        with tempfile.TemporaryDirectory() as directory:
            server = create_server(
                "127.0.0.1",
                0,
                data_path=Path(directory) / "dashboard.json",
                text_fetcher=fake_text_fetcher,
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base_url = f"http://127.0.0.1:{server.server_port}"
            try:
                first = self._post_json(f"{base_url}/api/import/artificial-analysis", {})
                self.assertEqual(first, {"created": 3, "updated": 0, "removed": 0, "received": 3})
                second = self._post_json(f"{base_url}/api/import/artificial-analysis", {})
                self.assertEqual(second, {"created": 0, "updated": 3, "removed": 0, "received": 3})
                self.assertEqual(fetched, [ARTIFICIAL_ANALYSIS_URL, ARTIFICIAL_ANALYSIS_URL])

                with urlopen(f"{base_url}/api/models", timeout=3) as response:
                    data = json.load(response)
                aa_models = [model for model in data["models"] if model["source"]["type"] == "artificial_analysis"]
                self.assertEqual(len(aa_models), 3)
                self.assertEqual(aa_models[0]["scores"]["artificial_analysis_index"], 74)
                self.assertEqual(len(data["models"]), 23)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=3)

    def test_http_syncs_llm_stats_ranking_and_preserves_previous_data_on_invalid_response(self):
        documents = [self._llm_stats_document(), self._llm_stats_document(score_offset=5), {}]
        fetched = []

        def fake_fetcher(url, auth):
            fetched.append((url, auth))
            return documents.pop(0)

        with tempfile.TemporaryDirectory() as directory:
            server = create_server(
                "127.0.0.1",
                0,
                data_path=Path(directory) / "dashboard.json",
                json_fetcher=fake_fetcher,
            )
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base_url = f"http://127.0.0.1:{server.server_port}"
            try:
                first = self._post_json(f"{base_url}/api/import/llm-stats", {})
                self.assertEqual(first, {"created": 3, "updated": 0, "removed": 0, "received": 3})
                second = self._post_json(f"{base_url}/api/import/llm-stats", {})
                self.assertEqual(second, {"created": 0, "updated": 3, "removed": 0, "received": 3})
                with self.assertRaises(HTTPError) as raised:
                    self._post_json(f"{base_url}/api/import/llm-stats", {})
                self.assertEqual(raised.exception.code, 400)
                raised.exception.close()
                self.assertEqual(fetched, [(LLM_STATS_INDEX_URL, None)] * 3)

                with urlopen(f"{base_url}/api/models", timeout=3) as response:
                    data = json.load(response)
                llm_stats_models = [model for model in data["models"] if model["source"]["type"] == "llm_stats"]
                self.assertEqual(len(llm_stats_models), 3)
                self.assertEqual(llm_stats_models[0]["scores"]["llm_stats_score"], 64)
                self.assertEqual(len(data["models"]), 23)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=3)

    def test_http_rejects_invalid_model(self):
        with tempfile.TemporaryDirectory() as directory:
            server = create_server("127.0.0.1", 0, data_path=Path(directory) / "dashboard.json")
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            try:
                with self.assertRaises(HTTPError) as raised:
                    self._post_json(
                        f"http://127.0.0.1:{server.server_port}/api/models",
                        {"tool": "", "model": "Missing tool"},
                    )
                self.assertEqual(raised.exception.code, 400)
                error = json.loads(raised.exception.read().decode("utf-8"))
                self.assertEqual(error["error"], "AI 编程工具不能为空")
                raised.exception.close()
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=3)

    def test_seed_data_matches_excel_source(self):
        try:
            from openpyxl import load_workbook
        except ImportError:
            self.skipTest("未安装可选的 openpyxl，跳过 Excel 源文件对账")
        workbook_path = Path("/Users/ben/Downloads/模型能力测试-20260623-展示优化版.xlsx")
        if not workbook_path.exists():
            self.skipTest("原始 Excel 不在当前机器上")
        seed_path = Path(__file__).resolve().parent.parent / "model_dashboard" / "seed_data.json"
        seed = json.loads(seed_path.read_text(encoding="utf-8"))
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", UserWarning)
            sheet = load_workbook(workbook_path, data_only=True)["测试结果"]
        self.assertEqual(len(seed["models"]), sheet.max_row - 1)
        for row, model in zip(sheet.iter_rows(min_row=2, values_only=True), seed["models"]):
            self.assertEqual([model["tool"], model["model"], model["reasoning_effort"]], [row[0] or "", row[1] or "", row[2] or ""])
            source_scores = {
                "manual_total": row[7] if row[7] != "" else None,
                "model_test_total": row[11] if row[11] != "" else None,
                "arena_webdev": row[12] if row[12] != "" else None,
            }
            for field, value in source_scores.items():
                self.assertEqual(model["scores"][field], value)
            has_component = any(value is not None for value in source_scores.values())
            expected_composite = row[13] if has_component else None
            self.assertEqual(model["scores"]["composite_total"], expected_composite)

    @staticmethod
    def _post_json(url, payload):
        request = Request(
            url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=3) as response:
            return json.load(response)


if __name__ == "__main__":
    unittest.main()
