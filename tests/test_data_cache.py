from __future__ import annotations

import json
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from urllib.request import Request, urlopen

from model_dashboard.data_cache import cache_status, cached_local_results, local_fingerprint
from model_dashboard.domain import normalize_model
from model_dashboard.local_results import PELICAN_CASE, collect_local_results
from model_dashboard.server import create_server
from model_dashboard.storage import DashboardStore


class DataCacheTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.runs = self.root / "runs"
        self.cases = self.root / "cases"
        self.run = self.runs / "sample"
        workspace = self.run / "codex" / PELICAN_CASE
        workspace.mkdir(parents=True)
        self.write(self.run / "run.json", {
            "created_at": "2026-09-19T12:00:00+00:00", "tools": ["codex"], "cases": [PELICAN_CASE],
            "identities": {"codex": {"agent": "Codex", "model": "sample-model", "intelligence": "high"}},
        })
        (workspace / "TASK.md").write_text("自定义题目：检查鹈鹕避障。", encoding="utf-8")
        self.cases.mkdir()
        case_dir = self.cases / "code_generation" / PELICAN_CASE
        case_dir.mkdir(parents=True)
        self.write(case_dir / "case.json", {"id": PELICAN_CASE, "title": "鹈鹕", "category": "code_generation"})
        (case_dir / "TASK.md").write_text("题目说明", encoding="utf-8")
        self.seed = self.root / "seed.json"
        self.seed.write_text(json.dumps({"models": []}), encoding="utf-8")

    def write(self, path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")

    def store(self):
        return DashboardStore(seed_path=self.seed, data_path=self.root / "data.db")

    def test_fingerprint_tracks_run_files_and_ignores_archive(self):
        first = local_fingerprint(self.runs, self.cases)
        self.write(self.runs / "_archive" / "old" / "run.json", {"tools": [], "cases": []})
        (self.runs / "_archive" / "old" / "extra.txt").write_text("archived", encoding="utf-8")
        (self.runs / "not-a-run").mkdir()
        (self.runs / "not-a-run" / "extra.txt").write_text("run-less dir", encoding="utf-8")
        self.assertEqual(local_fingerprint(self.runs, self.cases), first)
        (self.run / "extra.txt").write_text("new file", encoding="utf-8")
        second = local_fingerprint(self.runs, self.cases)
        self.assertNotEqual(second, first)
        (self.run / "extra.txt").write_text("modified file", encoding="utf-8")
        self.assertNotEqual(local_fingerprint(self.runs, self.cases), second)
        case_task = self.cases / "code_generation" / PELICAN_CASE / "TASK.md"
        case_task.write_text("修改后的题目", encoding="utf-8")
        self.assertNotEqual(local_fingerprint(self.runs, self.cases), second)

    def test_cached_local_results_builds_once_and_persists(self):
        store = self.store()
        with patch(
            "model_dashboard.data_cache.collect_local_results",
            wraps=collect_local_results,
        ) as collect:
            first = cached_local_results(store, self.runs)
            self.assertEqual(collect.call_count, 1)
            second = cached_local_results(store, self.runs)
            self.assertEqual(collect.call_count, 1)
            self.assertEqual(second, first)
            reopened = DashboardStore(seed_path=self.seed, data_path=self.root / "data.db")
            self.assertEqual(cached_local_results(reopened, self.runs), first)
            self.assertEqual(collect.call_count, 1)
            cached_local_results(store, self.runs, refresh=True)
            self.assertEqual(collect.call_count, 2)

    def test_cache_status_local_stale_after_change_and_fresh_after_refresh(self):
        store = self.store()
        status = cache_status(store, self.runs, 24)
        local = status["sources"][0]
        self.assertEqual((local["key"], local["kind"]), ("local_benchmarks", "local"))
        self.assertTrue(local["stale"])
        self.assertEqual(local["reason"], "尚未建立缓存")
        cached_local_results(store, self.runs)
        status = cache_status(store, self.runs, 24)
        self.assertFalse(status["sources"][0]["stale"])
        self.assertEqual(status["sources"][0]["reason"], "")
        self.write(self.runs / "second" / "run.json", {"tools": ["codex"], "cases": [PELICAN_CASE]})
        status = cache_status(store, self.runs, 24)
        local = status["sources"][0]
        self.assertTrue(local["stale"])
        self.assertEqual(local["reason"], "runs/ 有新的运行或评测结果")
        cached_local_results(store, self.runs, refresh=True)
        status = cache_status(store, self.runs, 24)
        self.assertFalse(status["sources"][0]["stale"])

    def test_cache_status_leaderboard_sources(self):
        store = self.store()
        now = datetime.now(timezone.utc)
        status = cache_status(store, self.runs, 24, now=now)
        by_key = {source["key"]: source for source in status["sources"]}
        self.assertEqual(
            list(by_key),
            ["local_benchmarks", "arena_webdev", "artificial_analysis_model",
             "artificial_analysis_agent", "llm_stats"],
        )
        for key in ("arena_webdev", "artificial_analysis_model", "artificial_analysis_agent", "llm_stats"):
            self.assertTrue(by_key[key]["stale"])
            self.assertEqual(by_key[key]["reason"], "尚未同步")
            self.assertEqual(by_key[key]["max_age_hours"], 24)
        self.assertGreaterEqual(status["stale_count"], 5)

        store.sync_arena_webdev([self.arena_record((now - timedelta(hours=2)).isoformat())])
        status = cache_status(store, self.runs, 24, now=now)
        arena = {source["key"]: source for source in status["sources"]}["arena_webdev"]
        self.assertFalse(arena["stale"])
        self.assertEqual(arena["reason"], "")
        self.assertAlmostEqual(arena["age_hours"], 2, delta=0.01)

        store.sync_arena_webdev([self.arena_record((now - timedelta(hours=30)).isoformat())])
        status = cache_status(store, self.runs, 24, now=now)
        arena = {source["key"]: source for source in status["sources"]}["arena_webdev"]
        self.assertTrue(arena["stale"])
        self.assertEqual(arena["reason"], "已超过 24 小时未同步")

        store.sync_arena_webdev([self.arena_record("not-a-date")])
        status = cache_status(store, self.runs, 24, now=now)
        arena = {source["key"]: source for source in status["sources"]}["arena_webdev"]
        self.assertTrue(arena["stale"])
        self.assertEqual(arena["reason"], "同步时间未知")

    @staticmethod
    def arena_record(fetched_at):
        return normalize_model(
            {"tool": "Lab", "model": "Alpha", "reasoning_effort": "high",
             "scores": {"arena_webdev": 60}},
            source={"type": "arena_webdev", "fetched_at": fetched_at, "rank": 1},
        )

    def test_http_cache_status_and_prompt_only_refresh(self):
        server = create_server(
            "127.0.0.1", 0, data_path=self.seed, runs_root=self.runs, cases_root=self.cases,
        )
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}"
        try:
            with urlopen(base + "/api/local-benchmarks", timeout=5) as response:
                records = json.load(response)["records"]
            self.assertEqual(len(records), 1)
            self.write(self.runs / "second" / "run.json", {
                "created_at": "2026-09-20T12:00:00+00:00", "tools": ["codex"], "cases": [PELICAN_CASE],
            })
            # prompt-only：缓存未刷新前，新运行不出现在结果里。
            with urlopen(base + "/api/local-benchmarks", timeout=5) as response:
                self.assertEqual(len(json.load(response)["records"]), 1)
            with urlopen(base + "/api/cache/status", timeout=5) as response:
                status = json.load(response)
            self.assertIn("checked_at", status)
            self.assertIsInstance(status["stale_count"], int)
            keys = {source["key"] for source in status["sources"]}
            self.assertEqual(keys, {
                "local_benchmarks", "arena_webdev", "artificial_analysis_model",
                "artificial_analysis_agent", "llm_stats",
            })
            local = next(source for source in status["sources"] if source["key"] == "local_benchmarks")
            self.assertTrue(local["stale"])
            self.assertEqual(local["reason"], "runs/ 有新的运行或评测结果")
            arena = next(source for source in status["sources"] if source["key"] == "arena_webdev")
            self.assertEqual(
                {key for key in arena},
                {"key", "label", "kind", "cached_at", "age_hours", "max_age_hours", "stale", "reason"},
            )
            request = Request(
                base + "/api/cache/local-benchmarks/refresh",
                data=b"{}", headers={"Content-Type": "application/json"}, method="POST",
            )
            with urlopen(request, timeout=5) as response:
                refreshed = json.load(response)
            self.assertEqual(refreshed["records"], 2)
            self.assertEqual(refreshed["status"]["sources"][0]["stale"], False)
            with urlopen(base + "/api/local-benchmarks", timeout=5) as response:
                self.assertEqual(len(json.load(response)["records"]), 2)
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)


if __name__ == "__main__":
    unittest.main()
