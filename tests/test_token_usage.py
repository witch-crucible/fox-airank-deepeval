import json
import unittest
from datetime import datetime, timezone
from pathlib import Path

from benchmark.token_usage import (
    TokenUsage,
    collect_token_usage,
    estimate_cost,
    merge_token_usage,
    parse_claude_json,
    parse_codex_jsonl,
    parse_commandcode_json,
    parse_openai_usage,
    parse_opencode_json,
    price_for,
    _claude_latest_cost_state,
    _codex_session_usages,
)


class OpenAIUsageTests(unittest.TestCase):
    def test_codex_style_usage(self):
        usage = parse_openai_usage({
            "usage": {
                "input_tokens": 27307,
                "cached_input_tokens": 25088,
                "cache_write_input_tokens": 0,
                "output_tokens": 622,
                "reasoning_output_tokens": 189,
                "total_tokens": 27929,
            },
            "model": "gpt-5-codex",
        })
        self.assertIsNotNone(usage)
        self.assertEqual(usage.input_tokens, 27307)
        self.assertEqual(usage.cache_read_tokens, 25088)
        self.assertEqual(usage.cache_creation_tokens, 0)
        self.assertEqual(usage.output_tokens, 622)
        self.assertEqual(usage.reasoning_tokens, 189)
        self.assertEqual(usage.total_tokens, 27929)

    def test_claude_style_usage_with_prompt_details(self):
        usage = parse_openai_usage({
            "usage": {
                "input_tokens": 2,
                "cache_creation_input_tokens": 13386,
                "cache_read_input_tokens": 39963,
                "output_tokens": 306,
                "output_tokens_details": {"thinking_tokens": 129},
            }
        })
        self.assertIsNotNone(usage)
        self.assertEqual(usage.cache_creation_tokens, 13386)
        self.assertEqual(usage.cache_read_tokens, 39963)
        self.assertEqual(usage.reasoning_tokens, 129)

    def test_prompt_tokens_alias(self):
        usage = parse_openai_usage({"usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15}})
        self.assertEqual(usage.input_tokens, 10)
        self.assertEqual(usage.output_tokens, 5)

    def test_no_usage_shape_returns_none(self):
        self.assertIsNone(parse_openai_usage({"model": "x"}))


class CodexJsonlTests(unittest.TestCase):
    def test_token_usage_record_thread_total(self):
        text = json.dumps({
            "type": "token_usage_record",
            "payload": {
                "thread_token_usage": {
                    "input_tokens": 66814, "cached_input_tokens": 52992,
                    "cache_write_input_tokens": 0, "output_tokens": 1296,
                    "reasoning_output_tokens": 264, "total_tokens": 68110,
                }
            },
        })
        usage = parse_codex_jsonl(text)
        self.assertIsNotNone(usage)
        self.assertEqual(usage.input_tokens, 66814)
        self.assertEqual(usage.total_tokens, 68110)
        self.assertEqual(usage.source, "stdout")

    def test_multiple_records_takes_thread_total(self):
        lines = [
            json.dumps({"type": "token_usage_record", "payload": {"usage": {"input_tokens": 1, "output_tokens": 1, "total_tokens": 2}}}),
            json.dumps({"type": "token_usage_record", "payload": {"thread_token_usage": {"input_tokens": 100, "output_tokens": 50, "total_tokens": 150}}}),
        ]
        usage = parse_codex_jsonl("\n".join(lines))
        self.assertEqual(usage.total_tokens, 150)


class ClaudeJsonTests(unittest.TestCase):
    def test_output_format_json(self):
        text = json.dumps({
            "model": "claude-opus-5-5",
            "cost_usd": 1.1562738,
            "usage": {
                "input_tokens": 32, "output_tokens": 11642, "thinking_tokens": 4627,
                "cacheReadInputTokens": 1475289, "cacheCreationInputTokens": 78531,
            },
        })
        usage = parse_claude_json(text)
        self.assertIsNotNone(usage)
        self.assertEqual(usage.input_tokens, 32)
        self.assertEqual(usage.output_tokens, 11642)
        self.assertEqual(usage.cache_read_tokens, 1475289)
        self.assertEqual(usage.cache_creation_tokens, 78531)
        self.assertAlmostEqual(usage.cost_usd, 1.1562738)

    def test_embedded_in_text(self):
        text = "thinking...\n" + json.dumps({"usage": {"input_tokens": 3, "output_tokens": 4, "total_tokens": 7}})
        usage = parse_claude_json(text)
        self.assertEqual(usage.total_tokens, 7)


class CommandCodeJsonTests(unittest.TestCase):
    def test_camel_case_fields(self):
        text = json.dumps({
            "model": "qwen3.8-max",
            "totalTokens": 224710,
            "inputTokens": 100000, "outputTokens": 90000,
            "cacheReadTokens": 30000, "cacheCreationTokens": 4700,
            "cost": 6.29,
        })
        usage = parse_commandcode_json(text)
        self.assertIsNotNone(usage)
        self.assertEqual(usage.input_tokens, 100000)
        self.assertEqual(usage.output_tokens, 90000)
        self.assertEqual(usage.cache_read_tokens, 30000)
        self.assertEqual(usage.cache_creation_tokens, 4700)
        self.assertEqual(usage.total_tokens, 224710)
        self.assertAlmostEqual(usage.cost_usd, 6.29)


class OpenCodeJsonTests(unittest.TestCase):
    def test_json_events(self):
        lines = [
            json.dumps({"model": "gpt-5", "usage": {"input_tokens": 10, "output_tokens": 20, "total_tokens": 30}}),
            json.dumps({"model": "gpt-5", "usage": {"input_tokens": 5, "output_tokens": 5, "total_tokens": 10}}),
        ]
        usage = parse_opencode_json("\n".join(lines))
        self.assertEqual(usage.input_tokens, 15)
        self.assertEqual(usage.output_tokens, 25)


class CostEstimationTests(unittest.TestCase):
    def test_price_for_substring(self):
        self.assertEqual(price_for("claude-opus-5-5")[0], 15.0)
        self.assertEqual(price_for("gpt-5-codex")[0], 5.0)
        self.assertIsNone(price_for(None))

    def test_estimate_from_tokens(self):
        usage = TokenUsage(
            input_tokens=1_000_000, output_tokens=1_000_000,
            cache_read_tokens=1_000_000, cache_creation_tokens=0,
            model="claude-opus",
        )
        # 15*1 + 75*1 + 1.5*1 = 91.5
        self.assertAlmostEqual(estimate_cost(usage), 91.5, places=2)

    def test_existing_cost_preferred(self):
        usage = TokenUsage(input_tokens=10, output_tokens=10, model="gpt-5", cost_usd=0.42)
        self.assertEqual(estimate_cost(usage), 0.42)


class MergeTests(unittest.TestCase):
    def test_merge_sums_and_by_model(self):
        merged = merge_token_usage([
            TokenUsage(input_tokens=100, output_tokens=10, model="gpt-5", source="stdout", cost_usd=0.01),
            TokenUsage(input_tokens=200, output_tokens=20, model="gpt-5", source="stdout", cost_usd=0.02),
        ])
        self.assertEqual(merged.input_tokens, 300)
        self.assertEqual(merged.output_tokens, 30)
        self.assertEqual(len(merged.by_model), 1)
        self.assertAlmostEqual(merged.cost_usd, 0.03)

    def test_merge_estimates_cost_when_missing(self):
        merged = merge_token_usage([
            TokenUsage(input_tokens=1_000_000, output_tokens=0, model="gpt-5"),
        ])
        self.assertAlmostEqual(merged.cost_usd, 5.0, places=2)


class CollectTests(unittest.TestCase):
    def test_codex_stdout(self):
        text = json.dumps({"type": "token_usage_record", "payload": {"thread_token_usage": {"input_tokens": 50, "output_tokens": 5, "total_tokens": 55}}})
        usage = collect_token_usage("codex", stdout=text)
        self.assertEqual(usage.total_tokens, 55)
        self.assertEqual(usage.source, "stdout")

    def test_claude_stdout(self):
        text = json.dumps({"usage": {"input_tokens": 7, "output_tokens": 8, "total_tokens": 15}, "model": "claude-sonnet", "cost_usd": 0.1})
        usage = collect_token_usage("claude", stdout=text)
        self.assertEqual(usage.total_tokens, 15)
        self.assertEqual(usage.source, "stdout")

    def test_empty_returns_none_source(self):
        # 用过去的时间窗排除本机真实会话日志，确保只验证 stdout 解析路径。
        past = datetime(2000, 1, 1, tzinfo=timezone.utc)
        usage = collect_token_usage("codex", stdout="no usage here", started_at=past, finished_at=past)
        self.assertEqual(usage.source, "none")
        self.assertTrue(usage.is_empty())


class LogScanHelperTests(unittest.TestCase):
    def test_codex_session_usages_from_temp(self):
        path = Path(__file__).parent / "_scratch_codex.jsonl"
        path.write_text(json.dumps({
            "type": "token_usage_record",
            "payload": {
                "session_id": "s1",
                "thread_token_usage": {"input_tokens": 400, "output_tokens": 40, "total_tokens": 440},
            },
        }) + "\n", encoding="utf-8")
        try:
            usages = _codex_session_usages(path, cwd=None)
            self.assertEqual(usages["s1"].total_tokens, 440)
        finally:
            path.unlink(missing_ok=True)

    def test_claude_cost_state_from_temp(self):
        path = Path(__file__).parent / "_scratch_claude.jsonl"
        path.write_text(json.dumps({
            "type": "cost-state",
            "modelUsage": {
                "claude-opus-5-5": {
                    "inputTokens": 32, "outputTokens": 11642, "thinkingTokens": 4627,
                    "cacheReadInputTokens": 1475289, "cacheCreationInputTokens": 78531,
                    "costUSD": 1.1562738,
                }
            },
        }) + "\n", encoding="utf-8")
        try:
            state = _claude_latest_cost_state(path)
            self.assertIn("claude-opus-5-5", state)
        finally:
            path.unlink(missing_ok=True)


class TokenUsageModelTests(unittest.TestCase):
    def test_total_derived_when_missing(self):
        usage = TokenUsage(input_tokens=1, output_tokens=2, cache_read_tokens=3, cache_creation_tokens=4)
        self.assertEqual(usage.total_tokens, 10)

    def test_to_dict_roundtrip_keys(self):
        usage = TokenUsage(input_tokens=1, output_tokens=2, model="gpt-5", cost_usd=0.5, source="stdout")
        data = usage.to_dict()
        self.assertEqual(data["total_tokens"], 3)
        self.assertEqual(data["source"], "stdout")
        self.assertEqual(data["cost_usd"], 0.5)


if __name__ == "__main__":
    unittest.main()
