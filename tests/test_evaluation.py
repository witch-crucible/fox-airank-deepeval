import json
import unittest
from pathlib import Path
from unittest.mock import patch

from benchmark.evaluation import CodexJudge, _make_strict_schema


class CodexJudgeTests(unittest.TestCase):
    def test_schema_command_and_json_model_validation(self):
        try:
            from pydantic import BaseModel
            import deepeval  # noqa: F401
        except ImportError:
            self.skipTest("当前环境未安装 deepeval")

        class Result(BaseModel):
            score: float
            reason: str

        completed = type("Completed", (), {"returncode": 0, "stdout": '{"score": 0.9, "reason": "ok"}', "stderr": ""})()
        with patch("benchmark.evaluation.subprocess.run", return_value=completed) as run:
            result = CodexJudge(timeout=5).generate("judge input", Result)
        self.assertEqual(result.score, 0.9)
        command = run.call_args.args[0]
        self.assertEqual(command[:4], ["codex", "exec", "--skip-git-repo-check", "--ephemeral"])
        self.assertIn("--ignore-user-config", command)
        self.assertIn("--ignore-rules", command)
        self.assertIn("--sandbox", command)
        self.assertIn("read-only", command)
        self.assertIn("--model", command)
        self.assertEqual(command[command.index("--model") + 1], "gpt-5.6-sol")
        self.assertIn('model_reasoning_effort="high"', command)
        self.assertEqual(command[-1], "-")
        self.assertEqual(run.call_args.kwargs["input"], "judge input")
        schema_path = Path(command[command.index("--output-schema") + 1])
        self.assertFalse(schema_path.exists())

    def test_nonzero_codex_exit_is_not_converted_to_score(self):
        try:
            import deepeval  # noqa: F401
        except ImportError:
            self.skipTest("当前环境未安装 deepeval")
        completed = type("Completed", (), {"returncode": 7, "stdout": "", "stderr": "bad judge"})()
        with patch("benchmark.evaluation.subprocess.run", return_value=completed):
            with self.assertRaisesRegex(RuntimeError, "退出码 7"):
                CodexJudge(timeout=5).generate("judge input")


def _assert_strict(node, path):
    """每个对象节点都必须声明 additionalProperties:false 且 required 列出全部属性。"""
    if isinstance(node, dict):
        if "properties" in node or node.get("type") == "object":
            if not node.get("additionalProperties") is False:
                raise AssertionError(f"{path}: additionalProperties 应为 false")
            required = node.get("required")
            if not isinstance(required, list):
                raise AssertionError(f"{path}: required 缺失")
            properties = node.get("properties") or {}
            if set(required) != set(properties.keys()):
                raise AssertionError(
                    f"{path}: required {set(required)} 与 properties {set(properties.keys())} 不一致"
                )
        for key, value in node.items():
            _assert_strict(value, f"{path}.{key}")
    elif isinstance(node, list):
        for index, value in enumerate(node):
            _assert_strict(value, f"{path}[{index}]")


class StrictSchemaTests(unittest.TestCase):
    """回归测试：_make_strict_schema 产出 OpenAI strict 模式兼容的 schema。"""

    def test_flat_object_gets_additional_properties_and_required(self):
        node = {
            "type": "object",
            "properties": {
                "score": {"type": "number"},
                "reason": {"type": "string"},
            },
            "title": "ReasonScore",
        }
        out = _make_strict_schema(node)
        self.assertIs(out.get("additionalProperties"), False)
        self.assertEqual(set(out.get("required", [])), {"score", "reason"})

    def test_recurses_into_defs_items_and_nested_properties(self):
        node = {
            "$defs": {
                "Detail": {
                    "type": "object",
                    "properties": {"msg": {"type": "string"}, "code": {"type": "integer"}},
                }
            },
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "details": {"$ref": "#/$defs/Detail"},
                "tags": {
                    "type": "array",
                    "items": {"type": "object", "properties": {"label": {"type": "string"}}},
                },
            },
        }
        _assert_strict(_make_strict_schema(node), "$")

    def test_leaves_non_dict_non_list_leaves_untouched(self):
        self.assertEqual(_make_strict_schema("string"), "string")
        self.assertEqual(_make_strict_schema(42), 42)
        self.assertIs(_make_strict_schema(True), True)
        self.assertIsNone(_make_strict_schema(None))

    def test_preserves_existing_false_additional_properties(self):
        node = {
            "type": "object",
            "additionalProperties": False,
            "properties": {"a": {"type": "string"}},
        }
        out = _make_strict_schema(node)
        self.assertIs(out.get("additionalProperties"), False)
        self.assertEqual(out.get("required"), ["a"])

    def test_written_schema_file_passes_strict_check(self):
        """_invoke 写入的 schema.json 必须满足 strict 模式。"""
        try:
            from pydantic import BaseModel
            import deepeval  # noqa: F401
        except ImportError:
            self.skipTest("当前环境未安装 deepeval")

        class ReasonScore(BaseModel):
            reason: str
            score: float

        captured = {}

        def fake_run(command, **kwargs):
            schema_path = Path(command[command.index("--output-schema") + 1])
            captured["schema"] = json.loads(schema_path.read_text(encoding="utf-8"))
            return type("Completed", (), {
                "returncode": 0,
                "stdout": '{"score": 0.5, "reason": "ok"}',
                "stderr": "",
            })()

        with patch("benchmark.evaluation.subprocess.run", side_effect=fake_run):
            CodexJudge(timeout=5).generate("prompt", ReasonScore)

        _assert_strict(captured["schema"], "$")


if __name__ == "__main__":
    unittest.main()
