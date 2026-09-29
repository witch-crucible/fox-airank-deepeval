from __future__ import annotations

import unittest

from model_dashboard.ai_insights import _prompt
from model_dashboard.baseline import grade_intelligence, intelligence_baseline
from model_dashboard.efficiency import build_balance_ranking, build_efficiency_overview
from model_dashboard.insight_data import build_insight_snapshot
from model_dashboard.leaderboards import build_model_overview


def aa_model(name, intelligence, *, slug, effort="max", rank=1, tool="DeepSeek", archived=False):
    return {
        "tool": tool,
        "model": name,
        "reasoning_effort": effort,
        "archived": archived,
        "scores": {"aa_model_intelligence": intelligence, "aa_model_speed": 60.0},
        "source": {
            "type": "artificial_analysis_model",
            "name": "Artificial Analysis Models",
            "url": "https://artificialanalysis.ai/models",
            "fetched_at": "2026-09-28T00:00:00+00:00",
            "rank": rank,
            "source_id": f"model-{rank}",
            "slug": slug,
            "intelligence_cost_per_task": 1.25,
            "intelligence_time_per_task": 220.0,
        },
    }


def snapshot_models():
    return [
        aa_model("DeepSeek V4 Flash 0420 (Reasoning, Max Effort)", 26.0076, slug="deepseek-v4-flash-0420-high", effort="high", rank=1),
        aa_model("DeepSeek V4 Flash 0420 (Non-reasoning)", 18.8769, slug="deepseek-v4-flash-0420-non-reasoning", rank=2),
        aa_model("DeepSeek V4.1 Flash (Non-Reasoning)", 24.6734, slug="deepseek-v4-1-flash-non-reasoning", rank=3),
        aa_model("DeepSeek V4.1 Flash (Reasoning, Max Effort)", 39.4562, slug="deepseek-v4-1-flash", rank=4),
        aa_model("DeepSeek V5 Flash Vision (Reasoning, Max Effort)", 99.0, slug="deepseek-v5-flash-vision", rank=5),
        aa_model("GPT 6-Sol (max)", 52.0, slug="gpt-6-sol", tool="OpenAI", rank=6),
    ]


class BaselineResolutionTests(unittest.TestCase):
    def test_baseline_uses_newest_deepseek_flash_peak_configuration(self):
        baseline = intelligence_baseline(snapshot_models())
        self.assertEqual(baseline["model"], "DeepSeek V4.1 Flash (Reasoning, Max Effort)")
        self.assertEqual(baseline["intelligence"], 39.4562)
        self.assertEqual(baseline["slug"], "deepseek-v4-1-flash")
        self.assertEqual(baseline["url"], "https://artificialanalysis.ai/models/deepseek-v4-1-flash")
        self.assertEqual(baseline["configurations"], 2)

    def test_baseline_ignores_archived_rows_and_other_sources(self):
        models = [
            aa_model("DeepSeek V4 Flash 0420 (Reasoning, Max Effort)", 26.0076, slug="deepseek-v4-flash-0420-high", effort="high"),
            aa_model("DeepSeek V4.1 Flash (Reasoning, Max Effort)", 39.4562, slug="deepseek-v4-1-flash", archived=True),
        ]
        self.assertEqual(intelligence_baseline(models)["model"], "DeepSeek V4 Flash 0420 (Reasoning, Max Effort)")
        self.assertIsNone(intelligence_baseline([{"tool": "Lab", "model": "Alpha", "scores": {}, "source": {"type": "llm_stats"}}]))
        self.assertIsNone(intelligence_baseline([]))
        self.assertIsNone(intelligence_baseline(None))

    def test_grade_treats_equal_as_baseline_and_missing_as_ungraded(self):
        baseline = intelligence_baseline(snapshot_models())
        self.assertEqual(grade_intelligence(30.0, baseline)["grade"], "差")
        self.assertEqual(grade_intelligence(39.4562, baseline)["grade"], "达标")
        self.assertEqual(grade_intelligence(45.0, baseline)["grade"], "达标")
        for value in (None, "", True, float("nan")):
            self.assertIsNone(grade_intelligence(value, baseline))
        self.assertIsNone(grade_intelligence(30.0, None))


class LeaderboardBaselineTests(unittest.TestCase):
    def test_model_rows_carry_baseline_and_per_row_grade(self):
        models = [
            aa_model("DeepSeek V4.1 Flash (Reasoning, Max Effort)", 39.4562, slug="deepseek-v4-1-flash"),
            aa_model("Alpha Strong", 50.0, slug="alpha-strong", tool="Lab", rank=2),
            aa_model("Beta Weak", 30.0, slug="beta-weak", tool="Lab", rank=3),
        ]
        overview = build_model_overview(models, [], set())
        self.assertEqual(overview["intelligence_baseline"]["intelligence"], 39.4562)
        rows = {row["model"]: row for row in overview["models"]}
        self.assertEqual(rows["Beta Weak"]["intelligence_check"]["grade"], "差")
        self.assertAlmostEqual(rows["Beta Weak"]["intelligence_check"]["delta"], -9.4562)
        self.assertEqual(rows["Alpha Strong"]["intelligence_check"]["grade"], "达标")
        self.assertEqual(rows["DeepSeek V4.1 Flash"]["intelligence_check"]["grade"], "达标")

    def test_rows_without_aa_intelligence_are_not_graded(self):
        models = [
            aa_model("DeepSeek V4.1 Flash (Reasoning, Max Effort)", 39.4562, slug="deepseek-v4-1-flash"),
            {"tool": "Arena", "model": "Only Arena", "scores": {"arena_webdev": 1200.0}, "source": {"type": "arena_webdev", "rank": 1}},
        ]
        overview = build_model_overview(models, [], set())
        rows = {row["model"]: row for row in overview["models"]}
        self.assertIsNone(rows["Only Arena"]["intelligence_check"])


class EfficiencyBaselineTests(unittest.TestCase):
    def test_intelligence_charts_carry_baseline_and_below_flags(self):
        charts = {chart["key"]: chart for chart in build_efficiency_overview(snapshot_models(), scope="all")["charts"]}
        self.assertEqual(charts["model_cost"]["baseline"]["intelligence"], 39.4562)
        flags = {point["label"]: point["below_baseline"] for point in charts["model_cost"]["points"]}
        self.assertTrue(flags["DeepSeek V4 Flash 0420 (Reasoning, Max Effort)"])
        self.assertFalse(flags["DeepSeek V4.1 Flash (Reasoning, Max Effort)"])
        self.assertFalse(flags["GPT 6-Sol (max)"])
        self.assertIsNone(charts["agent_cost"]["baseline"])

    def test_balance_rows_flagged_only_where_capability_is_intelligence(self):
        balance = build_balance_ranking(snapshot_models(), scope="all")
        model_group = next(group for group in balance["groups"] if group["key"] == "artificial_analysis_model")
        agent_group = next(group for group in balance["groups"] if group["key"] == "artificial_analysis_agent")
        self.assertEqual(model_group["baseline"]["intelligence"], 39.4562)
        below = {row["label"] for row in model_group["rows"] if row["below_baseline"]}
        self.assertIn("DeepSeek V4 Flash 0420 (Reasoning, Max Effort)", below)
        self.assertNotIn("GPT 6-Sol (max)", below)
        self.assertIsNone(agent_group["baseline"])


class InsightBaselineTests(unittest.TestCase):
    def test_snapshot_exposes_baseline_and_grading_methodology(self):
        snapshot = build_insight_snapshot({"models": snapshot_models()}, {"records": []}, set())
        self.assertEqual(snapshot["intelligence_baseline"]["intelligence"], 39.4562)
        self.assertIn("intelligence_baseline.intelligence", snapshot["methodology"]["intelligence_grading"])

    def test_missing_baseline_is_reported_as_warning(self):
        models = [model for model in snapshot_models() if "DeepSeek" not in model["tool"]]
        snapshot = build_insight_snapshot({"models": models}, {"records": []}, set())
        self.assertIsNone(snapshot["intelligence_baseline"])
        self.assertTrue(any("DeepSeek Flash" in warning for warning in snapshot["warnings"]))

    def test_prompt_states_the_baseline_rule(self):
        prompt = _prompt("日常开发选型", "{}")
        self.assertIn("智力基线", prompt)
        self.assertIn("判为「差」", prompt)
        self.assertIn("不得自行设定阈值", prompt)


if __name__ == "__main__":
    unittest.main()
