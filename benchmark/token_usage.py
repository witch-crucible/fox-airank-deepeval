"""Token 用量采集与统一口径换算。

参考 CodexBar 的做法：逐条会话抽取 input/output/cacheRead/cacheCreation 四类 token，
再按厂商公开定价估算费用。采集走两条路径，按优先级回退：

1. 结构化输出（stdout）：让 agent 以 JSON 形式吐出用量。
   - Codex ``exec --json`` 输出 JSONL 事件；
   - Claude ``-p --output-format json`` 输出单条 JSON；
   - CommandCode ``--output-format json``、OpenCode ``run --format json``、Qwen 等
     输出 OpenAI 兼容 ``usage`` 结构。
2. 本机会话日志（离线回退）：agent 把用量写进本地 JSONL 时，按时间窗扫描。
   - Codex ``~/.codex/sessions/**/rollout-*.jsonl`` 的 ``token_usage_record``；
   - Claude ``~/.claude/projects/<cwd>/*.jsonl`` 的 ``cost-state``。

统一模型（与 CodexBar 字段对齐）：

* ``input_tokens``       —— prompt / 输入 token
* ``output_tokens``      —— completion / 输出 token
* ``cache_read_tokens``  —— 命中缓存的输入 token（CodexBar: cacheReadTokens）
* ``cache_creation_tokens`` —— 写入缓存的输入 token（CodexBar: cacheCreationTokens）
* ``reasoning_tokens``   —— 推理 token（可选，如 Claude thinking / Codex reasoning）
* ``total_tokens``       —— 合计；缺失时由前四项求和推导
* ``cost_usd``           —— 费用（美元）；缺失时按 ``PRICING`` 估算
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

# 统一坐标系单位：百万 token。
MTOK = 1_000_000

# 厂商公开定价（USD / 1M tokens）。CodexBar 默认采用各厂商公布价；
# 仅用于 agent 未回传 costUSD 时的兜底估算，可按需扩展或覆盖。
# 字段顺序：input, cache_read, cache_creation, output
# 注意：子串匹配按列表顺序命中，故把更具体的厂商名放在通用前缀之前。
PRICING: list[tuple[str, tuple[float, float, float, float]]] = [
    # Anthropic Claude（缓存写入 5 分钟档）
    ("claude-opus", (15.0, 1.5, 18.75, 75.0)),
    ("claude-sonnet", (3.0, 0.30, 3.75, 15.0)),
    ("claude-haiku", (0.80, 0.08, 1.0, 4.0)),
    # OpenAI / Codex（gpt-5、o-series）
    ("gpt-5", (5.0, 1.25, 5.0, 20.0)),
    ("gpt-4.1", (2.0, 0.5, 2.0, 8.0)),
    ("o1", (15.0, 3.75, 15.0, 60.0)),
    ("o3", (10.0, 2.5, 10.0, 40.0)),
    ("o4", (5.0, 1.25, 5.0, 20.0)),
    # 通义 / Qwen
    ("qwen", (0.40, 0.10, 0.40, 1.20)),
]


def _to_int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, (int, float)):
        number = int(value)
        return number if number > 0 else 0
    if isinstance(value, str):
        digits = "".join(char for char in value if char.isdigit())
        return int(digits) if digits else 0
    return 0


def _to_float(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return number if number == number and abs(number) != float("inf") else None
    return None


@dataclass
class TokenUsage:
    """一次运行（或一次会话）的统一 token 用量。"""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    reasoning_tokens: int | None = None
    total_tokens: int | None = None
    cost_usd: float | None = None
    model: str | None = None
    by_model: list["TokenUsage"] = field(default_factory=list)
    source: str = "none"  # "stdout" | "log" | "none"

    def __post_init__(self) -> None:
        if self.total_tokens is None:
            self.total_tokens = (
                self.input_tokens
                + self.output_tokens
                + self.cache_read_tokens
                + self.cache_creation_tokens
            )

    def is_empty(self) -> bool:
        return (
            self.input_tokens == 0
            and self.output_tokens == 0
            and self.cache_read_tokens == 0
            and self.cache_creation_tokens == 0
            and not self.by_model
        )

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "cache_creation_tokens": self.cache_creation_tokens,
            "reasoning_tokens": self.reasoning_tokens,
            "total_tokens": self.total_tokens,
            "cost_usd": self.cost_usd,
            "model": self.model,
            "source": self.source,
        }
        if self.by_model:
            data["by_model"] = [item.to_dict() for item in self.by_model]
        return data


def price_for(model: str | None) -> tuple[float, float, float, float] | None:
    """按模型名子串匹配公开定价；无匹配返回 None。"""
    if not model:
        return None
    lowered = model.lower()
    for key, table in PRICING:
        if key in lowered:
            return table
    return None


def estimate_cost(usage: TokenUsage) -> float | None:
    """已有 costUSD 直接采用；否则按 PRICING 估算。"""
    if isinstance(usage.cost_usd, (int, float)) and usage.cost_usd is not None:
        return float(usage.cost_usd)
    table = price_for(usage.model)
    if table is None:
        return None
    in_p, cr_p, cc_p, out_p = table
    cost = (
        usage.input_tokens / MTOK * in_p
        + usage.cache_read_tokens / MTOK * cr_p
        + usage.cache_creation_tokens / MTOK * cc_p
        + usage.output_tokens / MTOK * out_p
    )
    return round(cost, 6) if cost > 0 else (0.0 if cost == 0 else None)


def merge_token_usage(usages: Iterable[TokenUsage]) -> TokenUsage:
    """合并多次采集（同一次运行可能涉及多个会话）；分别汇总四类 token 与费用。"""
    merged = TokenUsage(source="stdout")
    models: dict[str, TokenUsage] = {}
    for usage in usages:
        if usage.is_empty():
            continue
        merged.input_tokens += usage.input_tokens
        merged.output_tokens += usage.output_tokens
        merged.cache_read_tokens += usage.cache_read_tokens
        merged.cache_creation_tokens += usage.cache_creation_tokens
        if usage.model and merged.model is None:
            merged.model = usage.model
        if isinstance(usage.reasoning_tokens, int):
            merged.reasoning_tokens = (merged.reasoning_tokens or 0) + usage.reasoning_tokens
        if isinstance(usage.cost_usd, (int, float)):
            merged.cost_usd = (merged.cost_usd or 0.0) + float(usage.cost_usd)
        if usage.model:
            bucket = models.setdefault(usage.model, TokenUsage(model=usage.model, source=usage.source))
            bucket.input_tokens += usage.input_tokens
            bucket.output_tokens += usage.output_tokens
            bucket.cache_read_tokens += usage.cache_read_tokens
            bucket.cache_creation_tokens += usage.cache_creation_tokens
            if isinstance(usage.cost_usd, (int, float)):
                bucket.cost_usd = (bucket.cost_usd or 0.0) + float(usage.cost_usd)
    merged.by_model = list(models.values())
    merged.total_tokens = (
        merged.input_tokens + merged.output_tokens + merged.cache_read_tokens + merged.cache_creation_tokens
    )
    if merged.cost_usd is None:
        estimated = estimate_cost(merged)
        if estimated is not None:
            merged.cost_usd = estimated
    return merged


# --------------------------------------------------------------------------- #
# 结构化输出解析器
# --------------------------------------------------------------------------- #


def _usage_from_fields(
    *,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_read: int = 0,
    cache_creation: int = 0,
    reasoning: int | None = None,
    total: int | None = None,
    cost_usd: float | None = None,
    model: str | None = None,
    source: str = "stdout",
) -> TokenUsage:
    return TokenUsage(
        input_tokens=_to_int(input_tokens),
        output_tokens=_to_int(output_tokens),
        cache_read_tokens=_to_int(cache_read),
        cache_creation_tokens=_to_int(cache_creation),
        reasoning_tokens=_to_int(reasoning) if reasoning is not None else None,
        total_tokens=_to_int(total) if total is not None else None,
        cost_usd=_to_float(cost_usd),
        model=model,
        source=source,
    )


def _pick(value: Mapping[str, Any], *keys: str) -> Any:
    """返回第一个在 ``value`` 中存在的非空字段；都不存在则返回 None。"""
    for key in keys:
        if key in value and value[key] is not None:
            return value[key]
    return None


def parse_openai_usage(obj: Mapping[str, Any], *, model: str | None = None, cost_usd: float | None = None) -> TokenUsage | None:
    """OpenAI / Codex / Claude / 多数兼容接口的 ``usage`` 结构。

    兼容字段名（含驼峰与 OpenAI/Codex 两套命名）：
    * 输入：``input_tokens`` / ``prompt_tokens`` / ``inputTokens``
    * 输出：``output_tokens`` / ``completion_tokens`` / ``outputTokens``
    * 缓存读：``cache_read_input_tokens`` / ``cached_input_tokens`` / ``cacheReadInputTokens``
      / ``prompt_tokens_details.cached_tokens``
    * 缓存写：``cache_creation_input_tokens`` / ``cache_write_input_tokens`` / ``cacheCreationInputTokens``
      / ``cache_creation.ephemeral_*_input_tokens``
    * 推理：``reasoning_tokens`` / ``reasoning_output_tokens`` / ``thinking_tokens``
    """
    if not isinstance(obj, Mapping):
        return None
    usage = obj.get("usage") if isinstance(obj.get("usage"), Mapping) else obj
    if not isinstance(usage, Mapping):
        return None
    if not any(key in usage for key in ("input_tokens", "prompt_tokens", "output_tokens", "completion_tokens", "total_tokens", "inputTokens", "outputTokens", "totalTokens")):
        return None
    cache_read = _pick(usage, "cache_read_input_tokens", "cached_input_tokens", "cacheReadInputTokens", "cacheReadTokens")
    if cache_read is None:
        details = usage.get("prompt_tokens_details") if isinstance(usage.get("prompt_tokens_details"), Mapping) else {}
        if isinstance(details, Mapping):
            cache_read = details.get("cached_tokens")
    cache_creation = _pick(usage, "cache_creation_input_tokens", "cache_write_input_tokens", "cacheCreationInputTokens", "cacheCreationTokens")
    if cache_creation is None:
        creation = usage.get("cache_creation") if isinstance(usage.get("cache_creation"), Mapping) else {}
        if isinstance(creation, Mapping):
            cache_creation = creation.get("ephemeral_1h_input_tokens") or creation.get("ephemeral_5m_input_tokens")
    reasoning = _pick(usage, "reasoning_tokens", "reasoning_output_tokens", "thinking_tokens")
    if reasoning is None:
        otd = usage.get("output_tokens_details") if isinstance(usage.get("output_tokens_details"), Mapping) else {}
        if isinstance(otd, Mapping):
            reasoning = otd.get("thinking_tokens")
    return _usage_from_fields(
        input_tokens=_to_int(_pick(usage, "input_tokens", "prompt_tokens", "inputTokens")),
        output_tokens=_to_int(_pick(usage, "output_tokens", "completion_tokens", "outputTokens")),
        cache_read=cache_read,
        cache_creation=cache_creation,
        reasoning=reasoning,
        total=usage.get("total_tokens", usage.get("totalTokens")),
        cost_usd=cost_usd if cost_usd is not None else usage.get("cost_usd", usage.get("costUSD")),
        model=model or obj.get("model"),
    )


def parse_codex_jsonl(text: str, *, model: str | None = None) -> TokenUsage | None:
    """Codex ``exec --json`` 的 JSONL 事件流。

    优先取 ``token_usage_record`` 的 ``thread_token_usage``（整会话累计）；
    也兼容 ``message`` 事件里的 ``token_usage``。
    """
    last_thread: TokenUsage | None = None
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, Mapping):
            continue
        if event.get("type") == "token_usage_record":
            payload = event.get("payload") if isinstance(event.get("payload"), Mapping) else {}
            thread = payload.get("thread_token_usage") if isinstance(payload.get("thread_token_usage"), Mapping) else None
            if isinstance(thread, Mapping):
                last_thread = parse_openai_usage(thread, model=model) or last_thread
            elif isinstance(payload.get("usage"), Mapping):
                last_thread = parse_openai_usage(payload["usage"], model=model) or last_thread
        elif event.get("type") == "message":
            token_usage = event.get("token_usage") if isinstance(event.get("token_usage"), Mapping) else None
            if isinstance(token_usage, Mapping):
                candidate = parse_openai_usage(token_usage, model=model)
                if candidate is not None and not candidate.is_empty():
                    last_thread = candidate
    return last_thread


def parse_claude_json(text: str) -> TokenUsage | None:
    """Claude ``-p --output-format json`` 的单条 JSON。

    字段示例：``usage.input_tokens`` / ``usage.output_tokens`` /
    ``usage.cache_creation_input_tokens`` / ``usage.cache_read_input_tokens``，
    以及顶层 ``cost_usd``、``model``。
    """
    text = text.strip()
    if not text:
        return None
    decoder = json.JSONDecoder()
    index = 0
    best: TokenUsage | None = None
    while True:
        idx = text.find("{", index)
        if idx == -1:
            break
        try:
            obj, end = decoder.raw_decode(text, idx)
        except json.JSONDecodeError:
            index = idx + 1
            continue
        index = end
        usage = obj.get("usage") if isinstance(obj.get("usage"), Mapping) else None
        if isinstance(usage, Mapping) and any(key in usage for key in ("input_tokens", "output_tokens", "total_tokens")):
            candidate = parse_openai_usage(usage, model=obj.get("model"), cost_usd=obj.get("cost_usd"))
            if candidate is not None and not candidate.is_empty():
                best = candidate
    return best


def parse_commandcode_json(text: str) -> TokenUsage | None:
    """CommandCode ``--output-format json`` 的兼容解析。

    CommandCode 不一定暴露标准 ``usage``；尽力识别常见字段名
    （``totalTokens`` / ``tokenUsage`` / ``usage`` / ``inputTokens`` 等）。
    """
    text = text.strip()
    if not text:
        return None
    decoder = json.JSONDecoder()
    index = 0
    best: TokenUsage | None = None
    while True:
        idx = text.find("{", index)
        if idx == -1:
            break
        try:
            obj, end = decoder.raw_decode(text, idx)
        except json.JSONDecodeError:
            index = idx + 1
            continue
        index = end
        if not isinstance(obj, Mapping):
            continue
        # 优先标准 usage
        from_usage = parse_openai_usage(obj)
        if from_usage is not None and not from_usage.is_empty():
            if from_usage.cost_usd is None:
                top_cost = obj.get("cost") or obj.get("costUSD") or obj.get("totalCost")
                if isinstance(top_cost, (int, float)):
                    from_usage.cost_usd = float(top_cost)
            best = from_usage
            continue
        # 退而求其次：顶层驼峰字段
        total = obj.get("totalTokens") or obj.get("total_token_count")
        if total is None and not any(k in obj for k in ("inputTokens", "input_tokens", "promptTokens")):
            continue
        candidate = _usage_from_fields(
            input_tokens=obj.get("inputTokens", obj.get("input_tokens", obj.get("promptTokens", 0))),
            output_tokens=obj.get("outputTokens", obj.get("output_tokens", obj.get("completionTokens", 0))),
            cache_read=obj.get("cacheReadTokens", obj.get("cache_read_input_tokens", 0)),
            cache_creation=obj.get("cacheCreationTokens", obj.get("cache_creation_input_tokens", 0)),
            reasoning=obj.get("reasoningTokens"),
            total=total,
            cost_usd=obj.get("cost") or obj.get("costUSD") or obj.get("totalCost"),
            model=obj.get("model"),
        )
        if not candidate.is_empty():
            best = candidate
    return best


def parse_opencode_json(text: str) -> TokenUsage | None:
    """OpenCode ``run --format json`` 的 JSON 事件流（OpenAI 兼容 usage）。

    跨多个事件累计输入/输出/缓存 token 与费用。
    """
    total = TokenUsage(source="stdout")
    by_model: dict[str, TokenUsage] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(event, Mapping):
            continue
        model = event.get("model")
        usage = event.get("usage") if isinstance(event.get("usage"), Mapping) else None
        if not isinstance(usage, Mapping):
            continue
        candidate = parse_openai_usage(usage, model=model)
        if candidate is None or candidate.is_empty():
            continue
        total.input_tokens += candidate.input_tokens
        total.output_tokens += candidate.output_tokens
        total.cache_read_tokens += candidate.cache_read_tokens
        total.cache_creation_tokens += candidate.cache_creation_tokens
        if isinstance(candidate.cost_usd, (int, float)):
            total.cost_usd = (total.cost_usd or 0.0) + float(candidate.cost_usd)
        bucket = by_model.setdefault(model or "unknown", TokenUsage(model=model, source="stdout"))
        bucket.input_tokens += candidate.input_tokens
        bucket.output_tokens += candidate.output_tokens
        bucket.cache_read_tokens += candidate.cache_read_tokens
        bucket.cache_creation_tokens += candidate.cache_creation_tokens
    if total.is_empty():
        return None
    total.by_model = list(by_model.values())
    total.total_tokens = (
        total.input_tokens + total.output_tokens + total.cache_read_tokens + total.cache_creation_tokens
    )
    if total.cost_usd is None:
        estimated = estimate_cost(total)
        if estimated is not None:
            total.cost_usd = estimated
    return total


_STDOUT_PARSERS: dict[str, Any] = {
    "codex": parse_codex_jsonl,
    "claude": parse_claude_json,
    "commandcode": parse_commandcode_json,
    "qwen": parse_commandcode_json,  # Qwen CLI 输出接近 OpenAI 兼容结构
    "opencode": parse_opencode_json,
}


# --------------------------------------------------------------------------- #
# 本机会话日志回退扫描
# --------------------------------------------------------------------------- #


def _parse_iso(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc)
    except ValueError:
        return None


def scan_codex_logs(
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
    cwd: str | None = None,
) -> TokenUsage | None:
    """扫描 ``~/.codex/sessions`` 下的 rollout JSONL，按时间窗与 cwd 匹配。

    取每个会话最后一条 ``token_usage_record`` 的 ``thread_token_usage`` 作为整会话合计。
    """
    root = Path(os.path.expanduser("~/.codex/sessions"))
    if not root.is_dir():
        return None
    lo = _window_low(started_at)
    hi = _window_high(finished_at)
    sessions: dict[str, TokenUsage] = {}
    for path in root.rglob("rollout-*.jsonl"):
        try:
            mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
        except OSError:
            continue
        if lo is not None and mtime < lo:
            continue
        if hi is not None and mtime > hi:
            continue
        try:
            sessions.update(_codex_session_usages(path, cwd=cwd))
        except OSError:
            continue
    if not sessions:
        return None
    merged = merge_token_usage(list(sessions.values()))
    merged.source = "log"
    return merged


def _codex_session_usages(path: Path, cwd: str | None) -> dict[str, TokenUsage]:
    results: dict[str, TokenUsage] = {}
    session_cwd: str | None = None
    last_by_session: dict[str, TokenUsage] = {}
    with path.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, Mapping):
                continue
            if event.get("type") == "session_meta":
                payload = event.get("payload") if isinstance(event.get("payload"), Mapping) else {}
                session_cwd = payload.get("cwd")
            if event.get("type") == "token_usage_record":
                payload = event.get("payload") if isinstance(event.get("payload"), Mapping) else {}
                session_id = payload.get("session_id") or "unknown"
                thread = payload.get("thread_token_usage") if isinstance(payload.get("thread_token_usage"), Mapping) else None
                if isinstance(thread, Mapping):
                    usage = parse_openai_usage(thread)
                    if usage is not None:
                        last_by_session[session_id] = usage
    if cwd and session_cwd and Path(session_cwd).resolve() != Path(cwd).resolve():
        return results
    results.update(last_by_session)
    return results


def scan_claude_logs(
    cwd: str | None = None,
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
) -> TokenUsage | None:
    """扫描 ``~/.claude/projects/<encoded-cwd>`` 下的会话 JSONL。

    取时间窗内每个文件最新的 ``cost-state`` 事件（含 ``modelUsage`` 按模型拆分）。
    """
    base = Path(os.path.expanduser("~/.claude/projects"))
    if not base.is_dir():
        return None
    lo = _window_low(started_at)
    hi = _window_high(finished_at)
    project_dir = None
    if cwd:
        encoded = "-".join(str(cwd).split("/"))
        candidate = base / encoded
        project_dir = candidate if candidate.is_dir() else None
    search_dirs = [project_dir] if project_dir is not None else [d for d in base.iterdir() if d.is_dir()]
    per_model: dict[str, TokenUsage] = {}
    for directory in search_dirs:
        for path in directory.glob("*.jsonl"):
            try:
                mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
            except OSError:
                continue
            if lo is not None and mtime < lo:
                continue
            if hi is not None and mtime > hi:
                continue
            state = _claude_latest_cost_state(path)
            if state is None:
                continue
            for model_name, model_usage in state.items():
                if not isinstance(model_usage, Mapping):
                    continue
                usage = _usage_from_fields(
                    input_tokens=model_usage.get("inputTokens", model_usage.get("input_tokens", 0)),
                    output_tokens=model_usage.get("outputTokens", model_usage.get("output_tokens", 0)),
                    cache_read=model_usage.get("cacheReadInputTokens", model_usage.get("cache_read_input_tokens", 0)),
                    cache_creation=model_usage.get("cacheCreationInputTokens", model_usage.get("cache_creation_input_tokens", 0)),
                    reasoning=model_usage.get("thinkingTokens"),
                    cost_usd=model_usage.get("costUSD") or model_usage.get("cost_usd"),
                    model=model_name,
                    source="log",
                )
                if usage.is_empty():
                    continue
                bucket = per_model.get(model_name, TokenUsage(model=model_name, source="log"))
                bucket.input_tokens += usage.input_tokens
                bucket.output_tokens += usage.output_tokens
                bucket.cache_read_tokens += usage.cache_read_tokens
                bucket.cache_creation_tokens += usage.cache_creation_tokens
                if isinstance(usage.cost_usd, (int, float)):
                    bucket.cost_usd = (bucket.cost_usd or 0.0) + float(usage.cost_usd)
                per_model[model_name] = bucket
    if not per_model:
        return None
    merged = merge_token_usage(list(per_model.values()))
    merged.source = "log"
    return merged


def _claude_latest_cost_state(path: Path) -> dict[str, Any] | None:
    latest: dict[str, Any] | None = None
    latest_ts: datetime | None = None
    with path.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(event, Mapping) or event.get("type") != "cost-state":
                continue
            model_usage = event.get("modelUsage") if isinstance(event.get("modelUsage"), Mapping) else None
            if not model_usage:
                continue
            ts = _parse_iso(event.get("startTime"))
            if latest is None or (ts is not None and (latest_ts is None or ts >= latest_ts)):
                latest = model_usage
                latest_ts = ts
    return latest


def _window_low(started_at: datetime | None) -> datetime | None:
    if started_at is None:
        return None
    # 留 30s 缓冲，兼容日志写入略早于执行开始的情况。
    from datetime import timedelta

    return started_at - timedelta(seconds=30)


def _window_high(finished_at: datetime | None) -> datetime | None:
    if finished_at is None:
        return None
    from datetime import timedelta

    return finished_at + timedelta(seconds=120)


# --------------------------------------------------------------------------- #
# 统一入口
# --------------------------------------------------------------------------- #


def collect_token_usage(
    tool: str,
    *,
    stdout: str = "",
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
    cwd: str | None = None,
) -> TokenUsage:
    """按 tool 采集一次运行的 token 用量：先解析结构化输出，再回退到本机日志。

    找不到任何用量时返回 ``source="none"`` 的空 ``TokenUsage``。
    """
    parser = _STDOUT_PARSERS.get(tool)
    if parser is not None and stdout:
        try:
            usage = parser(stdout)
        except Exception:
            usage = None
        if usage is not None and not usage.is_empty():
            usage.source = "stdout"
            if usage.cost_usd is None:
                estimated = estimate_cost(usage)
                if estimated is not None:
                    usage.cost_usd = estimated
            return usage

    # 通用 OpenAI 兼容 usage 兜底（stdout 中未匹配到特定 agent 形态时）。
    if stdout:
        generic = parse_openai_usage(stdout)
        if generic is not None and not generic.is_empty():
            generic.source = "stdout"
            if generic.cost_usd is None:
                estimated = estimate_cost(generic)
                if estimated is not None:
                    generic.cost_usd = estimated
            return generic

    # 回退：扫描本机会话日志。
    if tool == "codex":
        scanned = scan_codex_logs(started_at, finished_at, cwd)
    elif tool == "claude":
        scanned = scan_claude_logs(cwd, started_at, finished_at)
    else:
        scanned = None
    if scanned is not None and not scanned.is_empty():
        return scanned

    return TokenUsage(source="none")
