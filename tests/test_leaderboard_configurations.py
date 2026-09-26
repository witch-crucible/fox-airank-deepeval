import unittest

from model_dashboard.leaderboards import (
    build_agent_overview,
    build_local_scores,
    build_model_overview,
    model_configuration,
    normalize_reasoning_effort,
    split_model_effort,
)


def row(source, model, score=None, effort=None, rank=1, **extra):
    field = {"artificial_analysis_model": "aa_model_intelligence", "llm_stats": "llm_stats_score"}.get(source, source)
    scores = {} if score is None else {field: score}
    item = {"tool": "Lab", "model": model, "scores": scores,
            "source": {"type": source, "rank": rank}}
    if effort is not None:
        item["reasoning_effort"] = effort
    item.update(extra)
    return item


class LeaderboardConfigurationTests(unittest.TestCase):
    def test_effort_normalization_and_unknown_are_distinct(self):
        self.assertEqual(normalize_reasoning_effort("高"), "high")
        self.assertEqual(normalize_reasoning_effort("Max Effort"), "max")
        self.assertEqual(normalize_reasoning_effort("none"), "none")
        self.assertEqual(normalize_reasoning_effort(16384), "budget_16384")
        self.assertEqual(normalize_reasoning_effort("thinking"), "thinking")
        self.assertEqual(normalize_reasoning_effort("not disclosed"), "unknown")
        self.assertEqual(normalize_reasoning_effort("budget_16384"), "budget_16384")
        self.assertNotEqual(normalize_reasoning_effort(32768), normalize_reasoning_effort(16384))
        self.assertEqual(normalize_reasoning_effort("non-reasoning"), "none")
        self.assertEqual(normalize_reasoning_effort("adaptive"), "adaptive")

    def test_model_configuration_keeps_product_max_and_uses_suffix_fallback(self):
        self.assertEqual(model_configuration({"model": "Qwen3.8 Max"}), ("qwen3 8 max", "unknown"))
        self.assertEqual(model_configuration({"model": "Claude Opus 5 (High Effort)"})[1], "high")
        self.assertEqual(model_configuration({"model": "Claude Opus 5 (max)", "reasoning_effort": "low"})[1], "low")
        self.assertEqual(model_configuration({"model": "qwen3.8-max"}), ("qwen3 8 max", "unknown"))
        self.assertEqual(model_configuration({"model": "claude-opus-5-high"}), ("claude opus 5", "high"))
        self.assertEqual(model_configuration({"model": "grok-4.6-high"}), ("grok 4 6", "high"))
        self.assertEqual(model_configuration({"model": "Opus 5", "reasoning_effort": "高"}), ("claude opus 5", "high"))

    def test_name_annotations_keep_releases_and_composite_models_distinct(self):
        self.assertEqual(split_model_effort("Fable 5.1 (max) (with fallback)"), ("Fable 5.1", "max"))
        self.assertEqual(split_model_effort("Claude Opus 5 (Adaptive Reasoning, High Effort)"), ("Claude Opus 5", "high"))
        self.assertEqual(split_model_effort("Model (Jan '25)"), ("Model (Jan '25)", ""))
        self.assertEqual(split_model_effort("Model (preview)"), ("Model (preview)", ""))
        self.assertEqual(split_model_effort("Model (0613)"), ("Model (0613)", ""))
        self.assertEqual(split_model_effort("Model (budget 16384)"), ("Model", "budget_16384"))
        composite = "GPT-6 Astra XHigh + SWE-2 Medium"
        self.assertEqual(split_model_effort(composite), (composite, ""))

    def test_model_scores_are_isolated_by_effort(self):
        models = [
            row("artificial_analysis_model", "Alpha", 80, effort="high"),
            row("artificial_analysis_model", "Alpha", 60, effort="max", rank=2),
            row("arena_webdev", "Alpha", 80, effort="high"),
            row("arena_webdev", "Alpha", 60, effort="max", rank=2),
            row("llm_stats", "Alpha", 80, effort="high"),
            row("llm_stats", "Alpha", 60, effort="max", rank=2),
        ]
        result = build_model_overview(models, [], set())
        self.assertEqual({r["configuration_key"] for r in result["models"]}, {"alpha:high", "alpha:max"})
        self.assertEqual({r["model_key"] for r in result["models"]}, {"alpha"})
        self.assertEqual({r["reasoning_effort"]: r["third_party_score"] for r in result["models"]}, {"high": 100, "max": 0})
        self.assertTrue(all(not r["legion"]["matched"] for r in result["models"]))

    def test_legion_highlight_and_star_are_matched_by_configuration(self):
        models = [row("artificial_analysis_model", "Alpha", 80, effort="high"),
                  row("artificial_analysis_model", "Alpha", 90, effort="max")]
        recommendations = {"agent_plan": [
            {"model": "Alpha", "tool": "Codex", "reasoning_effort": "高", "core_purpose_types": ["Plan"]},
            {"model": "Alpha", "tool": "Cursor", "reasoning_effort": "high", "core_purpose_types": [], "is_core": True},
        ]}
        rows = {item["reasoning_effort"]: item for item in build_model_overview(models, [], set(), recommendations=recommendations)["models"]}
        self.assertTrue(rows["high"]["legion"]["matched"])
        self.assertTrue(rows["high"]["legion"]["is_core"])
        self.assertEqual(len(rows["high"]["legion"]["entries"]), 2)
        self.assertFalse(rows["max"]["legion"]["matched"])
        self.assertFalse(rows["high"]["supplemental"])

    def test_local_repetitions_normalize_effort_before_grouping(self):
        metrics = {name: {"score": .9} for name in ("Task Correctness", "Robustness, Safety and Regression", "Delivery Evidence")}
        records = [{"agent": "Codex", "model": "Alpha (high)", "reasoning_effort": effort, "case_id": "c", "metrics": metrics}
                   for effort in ("高", "High", "")]
        local = build_local_scores(records, {"c"})
        self.assertEqual(len(local), 1)
        self.assertEqual(local[0]["minimum_repeats"], 3)
        self.assertTrue(local[0]["eligible"])
        self.assertEqual(local[0]["reasoning_effort"], "high")

    def test_unknown_source_does_not_match_known_local_effort(self):
        models = [row("artificial_analysis_model", "Alpha", 80)]
        local = [{"agent": "A", "model": "Alpha", "reasoning_effort": "high", "case_id": "c",
                  "metrics": {name: {"score": 1} for name in ("Task Correctness", "Robustness, Safety and Regression", "Delivery Evidence")}}]
        result = build_model_overview(models, local, {"c"})
        config = next(r for r in result["models"] if r["reasoning_effort"] == "high")
        self.assertIsNone(config["third_party_score"])

    def test_recommendation_adds_supplemental_identity_and_core_empty_is_false(self):
        result = build_model_overview([], [], set(), recommendations={"coding_plan": [{"model": "Alpha (high)", "core_purpose_types": []}]})
        item = result["models"][0]
        self.assertEqual(item["configuration_key"], "alpha:high")
        self.assertIsNone(item["third_party_score"])
        self.assertFalse(item["legion"]["is_core"])
        self.assertTrue(item["legion"]["matched"])
        self.assertTrue(item["supplemental"])

    def test_agent_requires_tool_model_and_effort_for_baseline(self):
        baseline = row("artificial_analysis_model", "Claude Opus 5 (max)", 40, effort="max")
        baseline["scores"] = {"aa_model_terminal_bench_v4": 40}
        agent = {"tool": "Claude Code", "model": "Opus 5 (high)", "scores": {"aa_terminal_bench_v4": 55},
                 "source": {"type": "artificial_analysis_agent", "rank": 1, "creator": {"model": "Anthropic"}}}
        result = build_agent_overview([baseline, agent])
        self.assertIsNone(result["agents"][0]["baseline"])
        self.assertIsNone(result["agents"][0]["terminal_bench_uplift"])

    def test_missing_agent_recommendation_is_supplemental_without_rank(self):
        result = build_agent_overview([], [{"tool": "Codex CLI", "model": "GPT-6 Sol", "reasoning_effort": "medium", "is_core": True}])
        item = result["agents"][0]
        self.assertTrue(item["supplemental"])
        self.assertNotIn("rank", item)
        self.assertEqual(item["agent"]["source"]["type"], "legion")
        self.assertTrue(item["legion"]["is_core"])
        self.assertTrue(item["legion"]["matched"])

    def test_agent_legion_requires_tool_and_does_not_borrow_other_effort(self):
        models = [row("artificial_analysis_model", "Alpha", 80, effort="high"),
                  row("arena_webdev", "Alpha", 1500, effort="high"),
                  row("llm_stats", "Alpha", 50, effort="high"),
                  {"tool": "Codex", "model": "Alpha", "reasoning_effort": "max", "scores": {"artificial_analysis_index": 70},
                   "source": {"type": "artificial_analysis_agent", "rank": 1}},
                  {"tool": "Cursor", "model": "Alpha", "reasoning_effort": "high", "scores": {"artificial_analysis_index": 65},
                   "source": {"type": "artificial_analysis_agent", "rank": 2}}]
        recommendations = [{"tool": "Codex CLI", "model": "Alpha", "reasoning_effort": "high", "core_purpose_types": ["Build"]}]
        agents = build_agent_overview(models, recommendations)["agents"]
        self.assertEqual(len(agents), 3)
        self.assertFalse(agents[0]["legion"]["matched"])
        self.assertFalse(agents[1]["legion"]["matched"])
        self.assertTrue(agents[2]["legion"]["matched"])
        self.assertEqual(agents[2]["agent"]["scores"], {})
        self.assertEqual(set(agents[2]["model_sources"]), {"artificial_analysis_model", "arena_webdev", "llm_stats"})

    def test_agent_groups_aggregate_aliases_and_keep_compatibility_fields(self):
        models = [
            {"tool": "Codex", "model": "Alpha", "reasoning_effort": "high", "scores": {"artificial_analysis_index": 70, "aa_terminal_bench_v4": 40}, "source": {"type": "artificial_analysis_agent", "rank": 2}},
            {"tool": "Codex CLI", "model": "Beta", "reasoning_effort": "medium", "scores": {"artificial_analysis_index": 90, "aa_terminal_bench_v4": 20}, "source": {"type": "artificial_analysis_agent", "rank": 1}},
        ]
        result = build_agent_overview(models)
        self.assertEqual(result["count"], 2)
        self.assertEqual(result["group_count"], 1)
        group = result["agent_groups"][0]
        self.assertEqual(group["agent_key"], "codex")
        self.assertEqual(group["configuration_count"], 2)
        self.assertEqual(group["score_sort_value"], 90)
        self.assertEqual(group["score_sort_configuration"]["model_key"], "beta")
        self.assertEqual([item["model_key"] for item in group["configurations"]], ["beta", "alpha"])

    def test_agent_group_metrics_keep_negative_and_null_values_deterministic(self):
        models = [
            {"tool": "Model", "model": "One", "reasoning_effort": "unknown", "scores": {"aa_model_terminal_bench_v4": 0}, "source": {"type": "artificial_analysis_model", "rank": 1}},
            {"tool": "Model", "model": "Two", "reasoning_effort": "unknown", "scores": {"aa_model_terminal_bench_v4": 0}, "source": {"type": "artificial_analysis_model", "rank": 2}},
            {"tool": "A", "model": "One", "scores": {"artificial_analysis_index": -5, "aa_terminal_bench_v4": -3}, "source": {"type": "artificial_analysis_agent", "rank": 2}},
            {"tool": "A", "model": "Two", "scores": {"artificial_analysis_index": -5, "aa_terminal_bench_v4": -3}, "source": {"type": "artificial_analysis_agent", "rank": 1}},
            {"tool": "B", "model": "Three", "scores": {}, "source": {"type": "artificial_analysis_agent", "rank": 3}},
        ]
        group = next(item for item in build_agent_overview(models)["agent_groups"] if item["agent_key"] == "a")
        self.assertEqual(group["score_sort_value"], -5)
        self.assertEqual(group["uplift_sort_value"], -3)
        self.assertEqual(group["score_sort_configuration"]["model_key"], "two")
        self.assertEqual(group["uplift_sort_configuration"]["model_key"], "two")
        empty = next(item for item in build_agent_overview(models)["agent_groups"] if item["agent_key"] == "b")
        self.assertIsNone(empty["score_sort_value"])
        self.assertIsNone(empty["uplift_sort_value"])

    def test_agent_group_aggregates_legion_purposes_without_cross_matching(self):
        models = [
            {"tool": "Codex", "model": "Alpha", "reasoning_effort": "high", "scores": {"artificial_analysis_index": 70}, "source": {"type": "artificial_analysis_agent", "rank": 1}},
            {"tool": "Codex", "model": "Alpha", "reasoning_effort": "max", "scores": {"artificial_analysis_index": 80}, "source": {"type": "artificial_analysis_agent", "rank": 2}},
        ]
        recommendations = {"purpose_types": ["Ask", "Plan", "Build"], "agent_plan": [
            {"tool": "Codex CLI", "model": "Alpha", "reasoning_effort": "high", "primary_purpose_types": ["Build"], "secondary_purpose_types": ["Plan"], "core_purpose_types": ["Build"]},
            {"tool": "Codex", "model": "Alpha", "reasoning_effort": "max", "primary_purpose_types": ["Plan"], "secondary_purpose_types": ["Build"], "core_purpose_types": []},
        ]}
        group = build_agent_overview(models, recommendations)["agent_groups"][0]
        self.assertTrue(group["legion"]["matched"])
        self.assertTrue(group["legion"]["is_core"])
        self.assertEqual(group["legion"]["primary_purpose_types"], ["Plan", "Build"])
        self.assertEqual(group["legion"]["secondary_purpose_types"], [])
        self.assertEqual(group["legion"]["core_purpose_types"], ["Build"])
        self.assertTrue(all(item["legion"]["matched"] for item in group["configurations"]))

    def test_supplemental_only_agent_group_has_no_fabricated_metrics(self):
        result = build_agent_overview([], [{"tool": "Codex", "model": "Alpha", "reasoning_effort": "high", "primary_purpose_types": ["Plan"]}])
        group = result["agent_groups"][0]
        self.assertEqual(group["configuration_count"], 1)
        self.assertIsNone(group["score_sort_value"])
        self.assertIsNone(group["uplift_sort_value"])
        self.assertTrue(group["configurations"][0]["supplemental"])


if __name__ == "__main__":
    unittest.main()
