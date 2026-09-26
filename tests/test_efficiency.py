import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from model_dashboard.domain import DashboardError, normalize_model
from model_dashboard.efficiency import (
    AA_AGENT_FOCUS,
    AA_MODEL_FOCUS,
    DEFAULT_BALANCE_WEIGHTS,
    build_balance_ranking,
    build_efficiency_overview,
    efficiency_key,
    normalize_balance_weights,
    normalized_series,
)
from model_dashboard.server import create_server
from model_dashboard.sources import normalize_artificial_analysis_models_html


def agent_record(tool, model, index, cost, wall_time=1000.0, rank=1):
    return normalize_model(
        {
            "tool": tool,
            "model": model,
            "reasoning_effort": "max",
            "scores": {"artificial_analysis_index": index},
        },
        source={
            "type": "artificial_analysis_agent",
            "name": "Artificial Analysis Coding Agents",
            "url": "https://artificialanalysis.ai/agents/coding-agents",
            "fetched_at": "2026-09-25T00:00:00+00:00",
            "rank": rank,
            "source_id": f"agent-{rank}",
            "cost_usd_per_task": cost,
            "wall_time_seconds_per_task": wall_time,
        },
    )


def model_record(name, slug, intelligence, cost=None, seconds=None, rank=1):
    return normalize_model(
        {
            "tool": "Lab",
            "model": name,
            "reasoning_effort": "max",
            "scores": {"aa_model_intelligence": intelligence},
        },
        source={
            "type": "artificial_analysis_model",
            "name": "Artificial Analysis Models",
            "url": "https://artificialanalysis.ai/models",
            "fetched_at": "2026-09-25T00:00:00+00:00",
            "rank": rank,
            "source_id": f"model-{rank}",
            "slug": slug,
            "price_1m_blended": 8.0,
            "intelligence_cost_per_task": cost,
            "intelligence_time_per_task": seconds,
        },
    )


class EfficiencySourceTests(unittest.TestCase):
    def test_artificial_analysis_models_exposes_price_and_task_metrics(self):
        references = (
            '"manifest":{"path":"/data/canonical.txt","key":"' + "01" * 32 + '"}'
            '"manifest":{"path":"/data/hosts.txt","key":"' + "02" * 32 + '"}'
        )
        payload = json.dumps([1, references])
        document = (
            "<html>Artificial Analysis Intelligence Index v4.3.2"
            f"<script>self.__next_f.push({payload})</script></html>"
        )
        canonical = {
            "models": [{
                "id": "model-1",
                "slug": "alpha-1",
                "name": "Alpha 1 (max)",
                "intelligenceIndex": 72.5,
                "price1mInputTokens": 4.0,
                "price1mOutputTokens": 20.0,
                "price1mBlended0To3To1": 8.0,
                "intelligenceIndexCostPerTask": {"cost": {"total": 3.4591}},
                "intelligenceIndexTimePerTask": 210.5,
                "creator": {"name": "Test Lab"},
            }]
        }
        hosts = [{
            "id": "host-1",
            "slug": "lab_alpha-1",
            "modelId": "model-1",
            "modelSlug": "alpha-1",
            "host": {"name": "Provider"},
            "price1mBlended0To3To1": 8.0,
            "intelligenceIndexCostPerTask": {"cost": {"total": 3.4591}},
            "intelligenceIndexTimePerTask": 210.5,
        }]
        with patch("model_dashboard.sources.decrypt_artificial_analysis_manifest", side_effect=[canonical, hosts]):
            models = normalize_artificial_analysis_models_html(document, lambda _url: b"encrypted")

        source = models[0]["source"]
        self.assertEqual(source["price_1m_blended"], 8.0)
        self.assertEqual(source["intelligence_cost_per_task"], 3.4591)
        self.assertEqual(source["intelligence_time_per_task"], 210.5)
        variant = source["variants"][0]
        self.assertEqual(variant["price_1m_blended"], 8.0)
        self.assertEqual(variant["intelligence_cost_per_task"], 3.4591)
        self.assertEqual(variant["intelligence_time_per_task"], 210.5)

    def test_artificial_analysis_models_tolerates_missing_task_metrics(self):
        references = (
            '"manifest":{"path":"/data/canonical.txt","key":"' + "01" * 32 + '"}'
            '"manifest":{"path":"/data/hosts.txt","key":"' + "02" * 32 + '"}'
        )
        payload = json.dumps([1, references])
        document = (
            "<html>Artificial Analysis Intelligence Index v4.3.2"
            f"<script>self.__next_f.push({payload})</script></html>"
        )
        canonical = {"models": [{"id": "model-2", "slug": "beta-2", "name": "Beta 2", "intelligenceIndex": 30.0}]}
        with patch("model_dashboard.sources.decrypt_artificial_analysis_manifest", side_effect=[canonical, []]):
            models = normalize_artificial_analysis_models_html(document, lambda _url: b"encrypted")
        source = models[0]["source"]
        self.assertIsNone(source["price_1m_blended"])
        self.assertIsNone(source["intelligence_cost_per_task"])
        self.assertIsNone(source["intelligence_time_per_task"])


class EfficiencyOverviewTests(unittest.TestCase):
    def test_agent_key_matches_artificial_analysis_url_slug(self):
        record = agent_record("Claude Code", "Fable 5.1 (max) (with fallback)", 62.2, 12.3)
        self.assertEqual(efficiency_key(record), "claude-code-fable-5-1-max-with-fallback")

    def test_model_key_uses_artificial_analysis_slug(self):
        record = model_record("GPT-6 Astra (max)", "gpt-6-astra", 52.6, cost=7.4, seconds=900.0)
        self.assertEqual(efficiency_key(record), "gpt-6-astra")

    def test_default_scope_keeps_only_focused_entries(self):
        models = [
            agent_record("Claude Code", "Opus 5.5 (max)", 59.7, 10.7, rank=1),
            agent_record("Codex", "GPT-6 Astra (max)", 61.6, 7.4, rank=2),
            agent_record("Other Agent", "Unknown 1 (max)", 40.0, 1.0, rank=3),
            model_record("GPT-6 Astra (max)", "gpt-6-astra", 52.6, cost=7.4, seconds=900.0),
            model_record("Kimi K3 (max)", "kimi-k3", 43.5, cost=5.0, seconds=1200.0),
            model_record("Noise Model", "noise-model", 10.0, cost=0.1, seconds=10.0),
        ]
        overview = build_efficiency_overview(models)
        charts = {chart["key"]: chart for chart in overview["charts"]}
        self.assertEqual(sorted(charts), ["agent_cost", "model_cost", "model_time"])
        agent_points = charts["agent_cost"]["points"]
        self.assertEqual([point["key"] for point in agent_points], ["codex-gpt-6-astra-max", "claude-code-opus-5-5-max"])
        self.assertTrue(all(point["focused"] for point in agent_points))
        self.assertEqual(charts["model_cost"]["points"][0]["key"], "gpt-6-astra")
        self.assertEqual(charts["model_time"]["points"][0]["x"], 900.0)
        self.assertEqual(overview["scope"], "focus")

    def test_scope_all_keeps_every_scored_row_and_flags_focus(self):
        models = [
            agent_record("Claude Code", "Opus 5.5 (max)", 59.7, 10.7, rank=1),
            agent_record("Other Agent", "Unknown 1 (max)", 40.0, 1.0, rank=3),
        ]
        overview = build_efficiency_overview(models, scope="all")
        points = overview["charts"][0]["points"]
        self.assertEqual(len(points), 2)
        self.assertEqual(points[0]["focused"], True)
        self.assertEqual(points[1]["focused"], False)

    def test_rows_without_axis_values_are_skipped(self):
        models = [
            agent_record("Claude Code", "Opus 5.5 (max)", 59.7, None, rank=1),
            model_record("GPT-6 Astra (max)", "gpt-6-astra", 52.6, cost=7.4, seconds=None),
        ]
        overview = build_efficiency_overview(models)
        charts = {chart["key"]: chart for chart in overview["charts"]}
        self.assertEqual(charts["agent_cost"]["points"], [])
        self.assertEqual(len(charts["model_cost"]["points"]), 1)
        self.assertEqual(charts["model_time"]["points"], [])
        self.assertIn("claude-code-opus-5-5-max", charts["agent_cost"]["missing"])

    def test_focus_lists_cover_shared_artificial_analysis_selection(self):
        self.assertIn("kimi-code-cli-kimi-k3", AA_AGENT_FOCUS)
        self.assertIn("gpt-6-astra", AA_MODEL_FOCUS)

    def test_attractive_quadrant_splits_on_median_capability_and_cost(self):
        models = [
            model_record("Alpha (max)", "alpha", 60.0, cost=10.0, rank=1),
            model_record("Beta (max)", "beta", 55.0, cost=4.0, rank=2),
            model_record("Gamma (max)", "gamma", 50.0, cost=8.0, rank=3),
            model_record("Delta (max)", "delta", 45.0, cost=2.0, rank=4),
        ]
        overview = build_efficiency_overview(models, scope="all")
        chart = next(item for item in overview["charts"] if item["key"] == "model_cost")
        self.assertEqual(chart["quadrant"]["x_max"], 6.0)
        self.assertEqual(chart["quadrant"]["y_min"], 52.5)
        self.assertEqual(chart["quadrant"]["count"], 1)
        inside = [
            point["key"]
            for point in chart["points"]
            if point["x"] <= chart["quadrant"]["x_max"] and point["y"] >= chart["quadrant"]["y_min"]
        ]
        self.assertEqual(inside, ["beta"])

    def test_scatter_pareto_keys_traces_upper_left_envelope(self):
        models = [
            model_record("Alpha (max)", "alpha", 60.0, cost=10.0, rank=1),
            model_record("Beta (max)", "beta", 55.0, cost=2.0, rank=2),
            model_record("Gamma (max)", "gamma", 30.0, cost=1.0, rank=3),
            model_record("Delta (max)", "delta", 40.0, cost=5.0, rank=4),
        ]
        overview = build_efficiency_overview(models, scope="all")
        chart = next(item for item in overview["charts"] if item["key"] == "model_cost")
        # delta(5, 40) 被 beta(2, 55) 支配；其余三点构成左上包络线，按成本升序。
        self.assertEqual(chart["pareto_keys"], ["gamma", "beta", "alpha"])

    def test_scatter_pareto_keys_is_empty_for_single_point(self):
        overview = build_efficiency_overview([model_record("Alpha (max)", "alpha", 60.0, cost=10.0)], scope="all")
        chart = next(item for item in overview["charts"] if item["key"] == "model_cost")
        self.assertEqual(chart["pareto_keys"], ["alpha"])

    def test_quadrant_is_absent_without_enough_points(self):
        overview = build_efficiency_overview([model_record("Alpha (max)", "alpha", 60.0, cost=10.0)], scope="all")
        chart = next(item for item in overview["charts"] if item["key"] == "model_cost")
        self.assertIsNone(chart["quadrant"])

    def test_unknown_scope_is_rejected(self):
        with self.assertRaises(DashboardError):
            build_efficiency_overview([], scope="everyone")


class BalanceRankingTests(unittest.TestCase):
    def test_normalized_series_uses_log_scale_for_wide_ranges(self):
        self.assertEqual(normalized_series([1.0, 10.0, 1000.0]), [0.0, 1 / 3, 1.0])
        self.assertEqual(normalized_series([1.0, 2.0, 4.0]), [0.0, 1 / 3, 1.0])
        self.assertEqual(normalized_series([5.0, 5.0]), [1.0, 1.0])

    def test_balance_weights_accept_string_and_validate_total(self):
        self.assertEqual(
            normalize_balance_weights("capability:0.6,cost:0.2,time:0.2"),
            {"capability": 0.6, "cost": 0.2, "time": 0.2},
        )
        self.assertEqual(normalize_balance_weights(None), DEFAULT_BALANCE_WEIGHTS)
        for invalid in ("capability:0.5,cost:0.5", "capability:0.5,cost:0.3,time:0.3", "capability:2,cost:-1,time:0", {"capability": 0.5}):
            with self.assertRaises(DashboardError):
                normalize_balance_weights(invalid)

    def test_balance_ranking_picks_best_trade_off_and_marks_pareto(self):
        models = [
            model_record("Alpha (max)", "alpha", 60.0, cost=10.0, seconds=1000.0, rank=1),
            model_record("Beta (max)", "beta", 55.0, cost=2.0, seconds=500.0, rank=2),
            model_record("Gamma (max)", "gamma", 30.0, cost=1.0, seconds=300.0, rank=3),
        ]
        balance = build_balance_ranking(models, scope="all")
        group = next(item for item in balance["groups"] if item["key"] == "artificial_analysis_model")
        self.assertEqual([row["key"] for row in group["rows"]], ["beta", "gamma", "alpha"])
        self.assertEqual(group["best"]["key"], "beta")
        # alpha 强但贵、gamma 便宜但弱、beta 居中，三者互不支配，全部落在前沿上。
        self.assertEqual(group["pareto_count"], 3)
        pareto = {row["key"]: row["pareto"] for row in group["rows"]}
        self.assertEqual(pareto, {"beta": True, "alpha": True, "gamma": True})
        self.assertAlmostEqual(group["best"]["balance_score"], 81.43, places=1)

    def test_balance_ranking_respects_weight_presets(self):
        models = [
            model_record("Alpha (max)", "alpha", 60.0, cost=10.0, seconds=1000.0, rank=1),
            model_record("Beta (max)", "beta", 55.0, cost=2.0, seconds=500.0, rank=2),
        ]
        capability_first = build_balance_ranking(models, scope="all", weights={"capability": 0.6, "cost": 0.2, "time": 0.2})
        cost_first = build_balance_ranking(models, scope="all", weights={"capability": 0.2, "cost": 0.5, "time": 0.3})
        group = next(item for item in capability_first["groups"] if item["key"] == "artificial_analysis_model")
        self.assertEqual(group["best"]["key"], "alpha")
        group = next(item for item in cost_first["groups"] if item["key"] == "artificial_analysis_model")
        self.assertEqual(group["best"]["key"], "beta")

    def test_balance_ranking_skips_rows_missing_a_dimension(self):
        models = [
            model_record("Alpha (max)", "alpha", 60.0, cost=10.0, seconds=None, rank=1),
            model_record("Beta (max)", "beta", 55.0, cost=2.0, seconds=500.0, rank=2),
        ]
        group = next(
            item for item in build_balance_ranking(models, scope="all")["groups"]
            if item["key"] == "artificial_analysis_model"
        )
        self.assertEqual([row["key"] for row in group["rows"]], ["beta"])
        self.assertEqual(group["incomplete"], [{"key": "alpha", "label": "Alpha (max)", "missing": ["time"]}])

    def test_overview_exposes_balance_block(self):
        models = [agent_record("Claude Code", "Opus 5.5 (max)", 59.7, 10.7, wall_time=1000.0, rank=1)]
        overview = build_efficiency_overview(models, weights="capability:0.5,cost:0.3,time:0.2")
        self.assertEqual(overview["balance"]["weights"], {"capability": 0.5, "cost": 0.3, "time": 0.2})
        self.assertTrue(overview["balance"]["presets"])
        self.assertEqual(
            [group["key"] for group in overview["balance"]["groups"]],
            ["artificial_analysis_agent", "artificial_analysis_model"],
        )


class EfficiencyHttpTests(unittest.TestCase):
    def _get(self, url):
        with urlopen(url, timeout=3) as response:
            return json.load(response)

    def test_http_efficiency_endpoint_returns_three_charts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            server = create_server("127.0.0.1", 0, data_path=root / "dashboard.json")
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base_url = f"http://127.0.0.1:{server.server_port}"
            try:
                payload = self._get(f"{base_url}/api/efficiency")
                self.assertEqual([chart["key"] for chart in payload["charts"]], ["agent_cost", "model_cost", "model_time"])
                self.assertEqual(payload["scope"], "focus")
                self.assertEqual(payload["balance"]["weights"], {"capability": 0.4, "cost": 0.3, "time": 0.3})

                weighted = self._get(f"{base_url}/api/efficiency?scope=all&weights=capability:0.6,cost:0.2,time:0.2")
                self.assertEqual(weighted["balance"]["weights"], {"capability": 0.6, "cost": 0.2, "time": 0.2})

                with self.assertRaises(HTTPError) as raised:
                    self._get(f"{base_url}/api/efficiency?scope=everything")
                self.assertEqual(raised.exception.code, 400)
                raised.exception.close()

                with self.assertRaises(HTTPError) as raised:
                    self._get(f"{base_url}/api/efficiency?weights=capability:0.5,cost:0.5")
                self.assertEqual(raised.exception.code, 400)
                raised.exception.close()
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=3)


if __name__ == "__main__":
    unittest.main()
