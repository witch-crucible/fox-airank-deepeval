from __future__ import annotations

import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import urlopen

from model_dashboard.local_results import PELICAN_CASE, collect_local_results, resolve_pelican_preview
from model_dashboard.server import create_server
from benchmark.paths import workspace_path


class LocalResultsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.runs = self.root / "runs"
        self.run = self.runs / "sample"
        self.workspace = self.run / "codex" / PELICAN_CASE
        self.workspace.mkdir(parents=True)
        self.report = self.run / "deepeval" / "codex" / "test_run_20260919_120000.json"
        self.write(self.run / "run.json", {
            "created_at": "2026-09-19T12:00:00+00:00", "tools": ["codex"], "cases": [PELICAN_CASE],
            "identities": {"codex": {"agent": "Codex", "model": "sample-model", "intelligence": "high"}},
        })
        (self.workspace / "TASK.md").write_text("自定义题目：检查鹈鹕避障。", encoding="utf-8")
        (self.workspace / "agent.live.log").write_text(
            "command=secret command is not public\n\n[PROMPT]\n自定义鹈鹕测试提示词\n[/PROMPT]\n",
            encoding="utf-8",
        )
        self.write(self.workspace / "execution.json", {"status": "completed", "elapsed_seconds": 120, "command": "secret command is not public"})
        self.report_data = {
            "hyperparameters": {"judge_model": "judge", "judge_reasoning_effort": "medium", "metric_version": "v1"},
            "testCases": [{
                "metadata": {"case_id": PELICAN_CASE, "category": "code_generation"},
                "metricsData": [
                    {"name": "Task Correctness [GEval]", "score": 1, "threshold": .8, "success": True, "reason": "meets the task"},
                    {"name": "Robustness, Safety and Regression [GEval]", "score": .9, "threshold": .7, "success": True},
                    {"name": "Delivery Evidence [GEval]", "score": .8, "threshold": .7, "success": True},
                ],
            }],
        }
        self.write(self.report, self.report_data)
        (self.workspace / "index.html").write_text("<!doctype html><p>pelican</p><script>document.body.dataset.ready='yes'</script>")

    def write(self, path, data):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")

    def collect(self):
        return collect_local_results(self.runs, self.root / "empty-cases")

    def test_reads_raw_metric_evidence_and_separates_agent_from_judge(self):
        result = self.collect()
        record = result["records"][0]
        self.assertEqual(result["warnings"], [])
        self.assertEqual(record["model"], "sample-model")
        self.assertEqual(record["reasoning_effort"], "high")
        self.assertEqual(record["judge_reasoning_effort"], "medium")
        self.assertEqual(record["metrics"]["Task Correctness"]["score"], 1)
        self.assertEqual(record["metrics"]["Task Correctness"]["reason"], "meets the task")
        self.assertTrue(record["passed"])
        self.assertEqual(record["elapsed_seconds"], 120)
        self.assertEqual(record["preview_url"], "/api/local-benchmarks/preview/sample/codex")
        self.assertEqual(record["task_text"], "自定义题目：检查鹈鹕避障。")
        self.assertEqual(record["prompt"], "自定义鹈鹕测试提示词")
        self.assertNotIn("model_test_total", record)
        self.assertNotIn("secret command", json.dumps(result))

    def test_failed_ungraded_run_and_missing_identity_are_preserved(self):
        self.report.unlink()
        self.write(self.run / "run.json", {"tools": ["codex"], "cases": [PELICAN_CASE]})
        self.write(self.workspace / "execution.json", {"status": "failed", "elapsed_seconds": .2})
        record = self.collect()["records"][0]
        self.assertEqual(record["execution_status"], "failed")
        self.assertEqual(record["model"], "unknown")
        self.assertFalse(record["evaluated"])
        self.assertEqual(record["metrics"], {})
        self.assertIsNotNone(record["preview_url"])

    def test_errors_and_missing_scores_are_not_zero_and_zero_is_valid(self):
        metrics = self.report_data["testCases"][0]["metricsData"]
        metrics[0]["score"] = 0
        metrics[0]["success"] = False
        metrics[1]["score"] = None
        metrics[2]["error"] = "judge unavailable"
        self.write(self.report, self.report_data)
        record = self.collect()["records"][0]
        self.assertEqual(record["metrics"]["Task Correctness"]["score"], 0)
        self.assertIsNone(record["metrics"]["Robustness, Safety and Regression"]["score"])
        self.assertIsNone(record["metrics"]["Delivery Evidence"]["score"])
        self.assertFalse(record["evaluated"])
        self.assertFalse(record["passed"])

    def test_latest_report_is_used_and_corruption_does_not_hide_the_artifact(self):
        newer = self.report.with_name("test_run_20260919_130000.json")
        self.report_data["testCases"][0]["metricsData"][0]["score"] = .4
        self.write(newer, self.report_data)
        self.assertEqual(self.collect()["records"][0]["metrics"]["Task Correctness"]["score"], .4)
        newer.write_text("{unfinished", encoding="utf-8")
        result = self.collect()
        self.assertTrue(result["warnings"])
        self.assertFalse(result["records"][0]["evaluated"])
        self.assertIsNotNone(result["records"][0]["preview_url"])

    def test_invalid_manifest_does_not_break_other_runs(self):
        self.write(self.runs / "bad" / "run.json", ["invalid"])
        result = self.collect()
        self.assertEqual(len(result["records"]), 1)
        self.assertEqual(len(result["warnings"]), 1)
        self.assertEqual(collect_local_results(self.root / "absent")["records"], [])

    def test_unchanged_initial_html_is_not_a_generated_preview(self):
        cases = self.root / "cases"
        initial = cases / "code_generation" / "pelican_bicycle" / "index.html"
        initial.parent.mkdir(parents=True)
        initial.write_bytes((self.workspace / "index.html").read_bytes())
        self.write(self.workspace / "execution.json", {"status": "failed"})

        record = collect_local_results(self.runs, cases)["records"][0]

        self.assertIsNone(record["preview_url"])
        self.assertIn("初始文件", record["preview_unavailable_reason"])
        with patch("model_dashboard.local_results.CASES_ROOT", cases):
            self.assertIsNone(resolve_pelican_preview(self.runs, "sample", "codex"))
        self.assertTrue((self.workspace / "index.html").is_file())

    def test_explicit_submission_can_preview_html_equal_to_case_source(self):
        cases = self.root / "cases"
        initial = cases / "code_generation" / "pelican_bicycle" / "index.html"
        initial.parent.mkdir(parents=True)
        initial.write_bytes((self.workspace / "index.html").read_bytes())
        self.write(self.workspace / "result.json", {
            "case_id": PELICAN_CASE, "status": "completed", "changed_files": ["index.html"],
        })

        record = collect_local_results(self.runs, cases)["records"][0]

        self.assertIsNotNone(record["preview_url"])
        self.assertIsNone(record["preview_unavailable_reason"])

    def test_identity_scoped_previews_keep_each_models_own_html(self):
        identities = {
            "first": {"agent": "Agent", "model": "model-a", "intelligence": "high"},
            "second": {"agent": "Agent", "model": "model-b", "intelligence": "high"},
        }
        self.write(self.run / "run.json", {
            "tools": list(identities), "cases": [PELICAN_CASE], "identities": identities,
        })
        for tool in identities:
            path = workspace_path(self.run, tool, PELICAN_CASE, identities) / "index.html"
            path.parent.mkdir(parents=True)
            path.write_text(f"<p>{tool}</p>")

        records = self.collect()["records"]

        self.assertEqual(len({record["preview_url"] for record in records}), 2)
        for record in records:
            path = resolve_pelican_preview(self.runs, record["run_id"], record["tool"])
            self.assertEqual(path.read_text(), f"<p>{record['tool']}</p>")

    def test_preview_rejects_traversal_and_symlink_escape(self):
        for run_id, tool in [("..", "codex"), ("sample", "../codex"), ("/tmp", "codex"), ("sample", "co\\dex")]:
            self.assertIsNone(resolve_pelican_preview(self.runs, run_id, tool))
        html = self.workspace / "index.html"
        html.unlink()
        outside = self.root / "private.html"
        outside.write_text("private")
        html.symlink_to(outside)
        self.assertIsNone(resolve_pelican_preview(self.runs, "sample", "codex"))
        self.assertIsNone(self.collect()["records"][0]["preview_url"])

    def test_report_symlink_cannot_read_outside_runs(self):
        self.report.unlink()
        outside = self.root / "private.json"
        self.write(outside, self.report_data)
        self.report.symlink_to(outside)
        result = self.collect()
        self.assertTrue(result["warnings"])
        self.assertEqual(result["records"][0]["metrics"], {})

    def test_read_only_http_api_and_preview_have_isolated_policies(self):
        data_path = self.root / "data.json"
        server = create_server("127.0.0.1", 0, data_path=data_path, runs_root=self.runs)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f"http://127.0.0.1:{server.server_port}"
        try:
            with urlopen(base + "/api/local-benchmarks") as response:
                record = json.load(response)["records"][0]
            with urlopen(base + record["preview_url"]) as response:
                self.assertIn("<p>pelican</p>", response.read().decode())
                policy = response.headers["Content-Security-Policy"]
                self.assertIn("sandbox allow-scripts;", policy)
                self.assertIn("connect-src 'none'", policy)
                self.assertIn("form-action 'none'", policy)
                self.assertNotIn("allow-same-origin", policy)
                self.assertEqual(response.headers["Referrer-Policy"], "no-referrer")
                self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
            for path in ["/api/local-benchmarks/preview/%2e%2e/codex", "/api/local-benchmarks/preview/sample/codex%2f..", "/api/local-benchmarks/preview/sample/codex/execution.json"]:
                with self.assertRaises(HTTPError) as blocked:
                    urlopen(base + path)
                try:
                    self.assertEqual(blocked.exception.code, 404)
                finally:
                    blocked.exception.close()
            self.assertFalse(data_path.exists())
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=3)


if __name__ == "__main__":
    unittest.main()
