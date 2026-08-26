import unittest
from pathlib import Path
from unittest.mock import patch

from benchmark.evaluation import CodexJudge


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


if __name__ == "__main__":
    unittest.main()
