"""DeepEval 数据集、指标和本地 Codex 裁判。"""

from __future__ import annotations

import asyncio
import json
import subprocess
import tempfile
from pathlib import Path
from typing import Any

try:
    from deepeval.models.base_model import DeepEvalBaseLLM
except ImportError:
    class DeepEvalBaseLLM:
        pass

ROOT = Path(__file__).resolve().parent.parent
JUDGE_MODEL = "gpt-5.6-sol"
JUDGE_EFFORT = "high"
JUDGE_TIMEOUT = 600
METRIC_VERSION = "2026-08-26-v1"


def load_specs() -> dict[str, dict[str, Any]]:
    return json.loads((ROOT / "benchmark" / "specs.json").read_text(encoding="utf-8"))


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as error:
        return f"[缺失或无法读取文件: {path.name}: {error}]"


def collect_actual_output(workspace: Path, spec: dict[str, Any]) -> str:
    parts = []
    for name in ("execution.json", "result.json", *spec.get("actual_files", [])):
        path = workspace / name
        if not path.is_file():
            parts.append(f"===== {name} =====\n[缺失文件]")
        else:
            parts.append(f"===== {name} =====\n{_read(path)}")
    return "\n\n".join(parts)


def collect_expected_output(spec: dict[str, Any]) -> str:
    parts = []
    for name in spec.get("reference_files", []):
        reference = ROOT / "tests" / "reference" / name
        parts.append(f"===== 参考实现/{name} =====\n{_read(reference)}")
    if "expected_answer" in spec:
        parts.append("===== 隐藏标准答案 =====\n" + json.dumps(spec["expected_answer"], ensure_ascii=False, indent=2))
    return "\n\n".join(parts) or "[该 case 没有独立参考文件；以 TASK.md 和实际证据判断。]"


def _test_case(name: str, task: str, actual: str, expected: str, metadata: dict[str, Any]):
    from deepeval.test_case import LLMTestCase

    values = {
        "name": name,
        "input": task,
        "actual_output": actual,
        "expected_output": expected,
        "metadata": metadata,
        "custom_column_key_values": {
            key: value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
            for key, value in metadata.items()
        },
    }
    try:
        return LLMTestCase(**values)
    except TypeError:
        values.pop("metadata")
        values.pop("custom_column_key_values")
        case = LLMTestCase(**values)
        setattr(case, "custom_column_key_values", metadata)
        return case


def build_test_cases(run_dir: Path, tool: str, cases: list[Any], identities: dict[str, Any] | None = None):
    result = []
    specs = load_specs()
    identities = identities or {}
    for case in cases:
        spec = specs[case.id]
        workspace = run_dir / tool / case.id
        execution = {}
        execution_path = workspace / "execution.json"
        if execution_path.is_file():
            try:
                execution = json.loads(execution_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                execution = {"status": "invalid-execution.json"}
        task = _read(case.source / "TASK.md")
        metadata = {
            "tool": tool, "case_id": case.id, "category": case.category,
            "execution_status": execution.get("status", "missing"),
            "elapsed_seconds": execution.get("elapsed_seconds"),
            "agent_identity": identities.get(tool, "unknown"),
        }
        result.append(_test_case(f"{tool}/{case.id}", task, collect_actual_output(workspace, spec), collect_expected_output(spec), metadata))
    return result


def _make_strict_schema(node: Any) -> Any:
    """将 Pydantic JSON Schema 转成 OpenAI/codex 的 strict 形式。

    codex 要求每个对象节点都声明 ``additionalProperties: false``，
    且 ``required`` 列出其全部属性；Pydantic 默认生成的 schema
    不含这两项，会触发::
        'additionalProperties' is required to be supplied and to be false

    本函数递归处理 ``properties``/``$defs``/``definitions``/``items`` 等子节点。
    """
    if isinstance(node, dict):
        result = dict(node)
        if "properties" in result or result.get("type") == "object":
            result["additionalProperties"] = False
            properties = result.get("properties")
            if isinstance(properties, dict):
                result["required"] = list(properties.keys())
        for key, value in result.items():
            result[key] = _make_strict_schema(value)
        return result
    if isinstance(node, list):
        return [_make_strict_schema(item) for item in node]
    return node


class CodexJudge(DeepEvalBaseLLM):
    def __init__(self, timeout: int = JUDGE_TIMEOUT):
        if DeepEvalBaseLLM.__module__ == __name__:
            raise RuntimeError("未安装 deepeval，请先执行 pip install -e .")
        self.timeout = timeout
        super().__init__()

    def load_model(self):
        return self

    def get_model_name(self) -> str:
        return JUDGE_MODEL

    def generate(self, prompt: str, schema: Any = None, **_: Any):
        return self._invoke(prompt, schema)

    async def a_generate(self, prompt: str, schema: Any = None, **_: Any):
        return await asyncio.to_thread(self._invoke, prompt, schema)

    def _invoke(self, prompt: str, schema: Any = None):
        schema_file = None
        try:
            with tempfile.TemporaryDirectory(prefix="deepeval-codex-judge-") as work:
                command = ["codex", "exec", "--skip-git-repo-check", "--ephemeral", "--ignore-user-config", "--ignore-rules", "--sandbox", "read-only", "--model", JUDGE_MODEL, "-c", 'model_reasoning_effort="high"']
                if schema is not None:
                    schema_file = Path(work) / "schema.json"
                    strict_schema = _make_strict_schema(schema.model_json_schema())
                    schema_file.write_text(json.dumps(strict_schema, ensure_ascii=False), encoding="utf-8")
                    command.extend(["--output-schema", str(schema_file)])
                command.extend(["--color", "never", "-"])
                try:
                    completed = subprocess.run(command, cwd=work, input=prompt, capture_output=True, text=True, timeout=self.timeout, check=False)
                except subprocess.TimeoutExpired as error:
                    raise RuntimeError(f"Codex 裁判超时（{self.timeout}s）") from error
            if completed.returncode != 0:
                detail = (completed.stderr or completed.stdout or "").strip()[-2000:]
                raise RuntimeError(f"Codex 裁判退出码 {completed.returncode}: {detail}")
            if not completed.stdout.strip():
                raise RuntimeError("Codex 裁判输出为空")
            try:
                data = json.loads(completed.stdout)
            except json.JSONDecodeError:
                decoder = json.JSONDecoder()
                candidates = []
                for index, character in enumerate(completed.stdout):
                    if character != "{":
                        continue
                    try:
                        candidate, _ = decoder.raw_decode(completed.stdout[index:])
                    except json.JSONDecodeError:
                        continue
                    if isinstance(candidate, dict):
                        candidates.append(candidate)
                if not candidates:
                    raise RuntimeError("Codex 裁判输出不是合法 JSON")
                data = candidates[-1]
            if schema is not None:
                try:
                    return schema.model_validate(data)
                except Exception as error:
                    raise RuntimeError(f"Codex 裁判 JSON 不符合 schema: {error}") from error
            return completed.stdout
        except OSError as error:
            raise RuntimeError(f"无法启动 Codex 裁判: {error}") from error


def metrics(judge: Any):
    from deepeval.metrics import GEval
    from deepeval.test_case import SingleTurnParams

    common = [SingleTurnParams.INPUT, SingleTurnParams.ACTUAL_OUTPUT, SingleTurnParams.EXPECTED_OUTPUT]
    return [
        GEval(name="Task Correctness", evaluation_steps=["核对实际实现或答案是否满足 TASK.md 和参考结果的行为要求。允许结构、命名和代码风格不同；只因行为差异扣分。", "检查关键需求、边界条件和结果是否正确。"], evaluation_params=common, threshold=0.8, model=judge),
        GEval(name="Robustness, Safety and Regression", evaluation_steps=["检查边界条件、输入不变性、编码与注入安全、错误处理和既有行为回归风险。", "只有有证据的风险才扣分，不因与参考实现不同而扣分。"], evaluation_params=common, threshold=0.7, model=judge),
        GEval(name="Delivery Evidence", evaluation_steps=["检查 execution.json、result.json、变更文件声明、执行状态和验证记录是否真实、完整并与实际输出一致。", "缺失或互相矛盾的交付证据应显著扣分。"], evaluation_params=common, threshold=0.7, model=judge),
    ]


def evaluate_tool(run_dir: Path, tool: str, cases: list[Any], identities: dict[str, Any] | None = None) -> Any:
    from deepeval import evaluate
    from deepeval.evaluate import AsyncConfig, CacheConfig, DisplayConfig
    test_cases = build_test_cases(run_dir, tool, cases, identities)
    judge = CodexJudge()
    output_dir = run_dir / "deepeval" / tool
    output_dir.mkdir(parents=True, exist_ok=True)
    hyperparameters = {
        "judge_model": JUDGE_MODEL,
        "judge_reasoning_effort": JUDGE_EFFORT,
        "metric_version": METRIC_VERSION,
        # DeepEval 的 hyperparameters 值只接受字符串/数字，dict 需序列化
        "agent_identity": identities if isinstance(identities, str) else json.dumps(identities or {}, ensure_ascii=False),
    }
    return evaluate(test_cases=test_cases, metrics=metrics(judge), identifier=f"{run_dir.name}:{tool}", hyperparameters=hyperparameters, async_config=AsyncConfig(max_concurrent=2), display_config=DisplayConfig(results_folder=str(output_dir), file_type="html", file_output_dir=str(output_dir), inspect_after_run=False, print_results=True), cache_config=CacheConfig(use_cache=False, write_cache=False))
