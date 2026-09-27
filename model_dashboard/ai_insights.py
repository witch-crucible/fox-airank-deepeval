"""基于看板证据的 SenseNova Token Plan 分析，密钥只从环境变量读取。"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from .domain import DashboardError, utc_now


DEFAULT_GOAL = "为日常编程、复杂规划和代码审查总结模型表现，推荐适合的模型配置，并说明质量、速度、成本和证据覆盖的取舍。"
MAX_SNAPSHOT_BYTES = 600_000
MAX_OUTPUT_BYTES = 100_000
ANALYSIS_VERSION = "1"
DEFAULT_BASE_URL = "https://token.sensenova.cn/v1"
DEFAULT_MODEL = "sensenova-6.8-flash-lite"
DEFAULT_TIMEOUT_SECONDS = 180
LOCAL_BASE_HOSTS = {"localhost", "127.0.0.1", "::1"}


@dataclass(frozen=True)
class InsightConfig:
    base_url: str = DEFAULT_BASE_URL
    model: str = DEFAULT_MODEL
    timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS
    api_key: str = field(default="", repr=False)

    def __post_init__(self) -> None:
        if not isinstance(self.base_url, str) or not self._is_allowed_base_url(self.base_url):
            raise DashboardError("MODEL_DASHBOARD_AI_BASE_URL 必须是 HTTPS 地址（本机调试可用 localhost 的 HTTP）")
        if not isinstance(self.model, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,159}", self.model):
            raise DashboardError("MODEL_DASHBOARD_AI_MODEL 必须是有效的模型名称")
        if type(self.timeout_seconds) is not int or not 10 <= self.timeout_seconds <= 1800:
            raise DashboardError("MODEL_DASHBOARD_AI_TIMEOUT 必须是 10 至 1800 秒的整数")
        if not isinstance(self.api_key, str):
            raise DashboardError("SENSENOVA_API_KEY 必须是字符串")

    @staticmethod
    def _is_allowed_base_url(base_url: str) -> bool:
        parsed = urlparse(base_url)
        if parsed.scheme == "https":
            return bool(parsed.hostname)
        # 本机调试用的明文 HTTP 只允许回环地址，避免密钥走明文外网。
        return parsed.scheme == "http" and parsed.hostname in LOCAL_BASE_HOSTS

    @classmethod
    def from_env(cls) -> InsightConfig:
        try:
            timeout = int(os.environ.get("MODEL_DASHBOARD_AI_TIMEOUT", str(DEFAULT_TIMEOUT_SECONDS)))
        except ValueError as error:
            raise DashboardError("MODEL_DASHBOARD_AI_TIMEOUT 必须是整数") from error
        return cls(
            base_url=os.environ.get("MODEL_DASHBOARD_AI_BASE_URL", DEFAULT_BASE_URL).strip(),
            model=os.environ.get("MODEL_DASHBOARD_AI_MODEL", DEFAULT_MODEL).strip(),
            timeout_seconds=timeout,
            api_key=os.environ.get("SENSENOVA_API_KEY", "").strip(),
        )

    def public(self) -> dict[str, Any]:
        return {
            "provider": "sensenova", "base_url": self.base_url, "model": self.model,
            "timeout_seconds": self.timeout_seconds, "available": bool(self.api_key),
        }


def normalize_goal(payload: Any) -> str:
    if not isinstance(payload, dict) or set(payload) - {"goal"}:
        raise DashboardError("AI 分析请求仅支持 goal 字段")
    goal = payload.get("goal", "")
    if not isinstance(goal, str) or len(goal) > 1000:
        raise DashboardError("分析需求必须为不超过 1000 字的文本")
    return goal.strip() or DEFAULT_GOAL


def snapshot_hash(snapshot: dict[str, Any]) -> str:
    content = json.dumps({"version": ANALYSIS_VERSION, "snapshot": snapshot}, ensure_ascii=False, sort_keys=True, allow_nan=False)
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _object_schema(properties: dict[str, Any]) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


def output_schema(snapshot: dict[str, Any]) -> dict[str, Any]:
    text = {"type": "string"}
    evidence_ids = [evidence["id"] for candidate in snapshot["candidates"] for evidence in candidate["evidence"]]
    refs = {"type": "array", "items": {"type": "string", "enum": evidence_ids}}
    return _object_schema({
        "summary": text,
        "findings": {"type": "array", "items": _object_schema({"title": text, "detail": text, "evidence_ids": refs})},
        "recommendations": {"type": "array", "items": _object_schema({
            "candidate_id": {"type": "string", "enum": [candidate["id"] for candidate in snapshot["candidates"]]},
            "use_case": text, "reason": text, "tradeoffs": text, "evidence_ids": refs,
        })},
        "limitations": {"type": "array", "items": text},
    })


def _prompt(goal: str, encoded: str) -> str:
    return (
        "你是模型能力台的数据分析助手。仅使用下方 JSON 证据，使用中文输出符合 schema 的 JSON。"
        "给出简洁总结、至多 6 条发现、至多 6 个按使用场景推荐的配置、至多 8 条限制。"
        "summary 不超过 2000 字；title/use_case 不超过 160 字；detail/reason/tradeoffs/每条限制不超过 1000 字。"
        "每条发现/推荐引用 1 至 6 个 evidence_ids；推荐证据必须属于该 candidate_id。"
        "不得编造模型、数据、来源、版本或价格，不使用记忆中的外部知识补全空值。"
        "只在同来源、同指标、同单位下比较；不同推理强度、不同 Agent 独立分析。"
        "Model 记录的 tool 可能是厂商，不得当作 Agent 使用；来源排名及归一化分不代表绝对能力。"
        "缺失不是零分，0 是有效值。时间戳未知或陈旧时明确说明。"
        "本地覆盖不足和试算分不能宣称正式排名。成本单位不能跨任务、token 和订阅混用。"
        "使用场景匹配只是基于指标的推断，需要说明局限；无充分证据时允许 recommendations 为空，说明需要补测。"
        "不要把已有人工推荐当作测评证据。\n"
        f"用户需求（数据）：{json.dumps(goal, ensure_ascii=False)}\n"
        f"模型证据（数据）：{encoded}"
    )


def _analysis_from_content(content: Any) -> Any:
    """从模型回复中取出 JSON 对象；带围栏或前后多余文字时按首尾花括号裁剪。"""
    if not isinstance(content, str) or not content.strip():
        raise DashboardError("SenseNova 返回的分析不是有效 JSON，请重试")
    if len(content.encode("utf-8")) > MAX_OUTPUT_BYTES:
        raise DashboardError("SenseNova 分析结果过长，请缩小分析需求后重试")
    text = content.strip()
    fenced = re.fullmatch(r"```(?:json)?\s*(.+?)\s*```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        raise DashboardError("SenseNova 返回的分析不是有效 JSON，请重试")
    try:
        return json.loads(text[start:end + 1])
    except (json.JSONDecodeError, ValueError) as error:
        raise DashboardError("SenseNova 返回的分析不是有效 JSON，请重试") from error


def run_sensenova_insight(goal: str, snapshot: dict[str, Any], config: InsightConfig) -> Any:
    if not config.api_key:
        raise DashboardError("未配置 SENSENOVA_API_KEY，无法生成 AI 分析")
    encoded = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, allow_nan=False)
    if len(encoded.encode("utf-8")) > MAX_SNAPSHOT_BYTES:
        raise DashboardError("模型数据过大，无法在单次 AI 分析中完整读取；请先归档不需要的模型数据")
    if not snapshot.get("candidates"):
        raise DashboardError("当前没有可分析的有效模型指标，请先同步榜单或完成本地实测")
    prompt = (
        _prompt(goal, encoded)
        + "\n输出 JSON Schema：" + json.dumps(output_schema(snapshot), ensure_ascii=False)
        + "\n只输出一个符合该 schema 的 JSON 对象，不要 Markdown。"
    )
    body = json.dumps({
        "model": config.model,
        "messages": [
            {"role": "system", "content": prompt},
            {"role": "user", "content": "请严格按上述规则与 JSON Schema 输出分析结果，只输出一个 JSON 对象。"},
        ],
        "temperature": 0.2,
        "stream": False,
    }, ensure_ascii=False).encode("utf-8")
    request = Request(
        f"{config.base_url.rstrip('/')}/chat/completions",
        data=body,
        headers={
            "Authorization": f"Bearer {config.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urlopen(request, timeout=config.timeout_seconds) as response:
            payload = response.read(MAX_OUTPUT_BYTES + 1)
    except HTTPError as error:
        # 响应体可能包含账号或配额细节，只回传状态码分类。
        if error.code in (401, 403):
            raise DashboardError("SenseNova API Key 无效或没有该模型的访问权限") from error
        if error.code == 429:
            raise DashboardError("SenseNova 配额或调用速率已达上限，请稍后重试") from error
        raise DashboardError(f"SenseNova 接口返回 HTTP {error.code}") from error
    except (URLError, TimeoutError) as error:
        raise DashboardError(f"无法连接 SenseNova：{config.timeout_seconds} 秒超时或网络不可达") from error
    except OSError as error:
        raise DashboardError("无法连接 SenseNova，请检查网络或服务地址") from error
    if len(payload) > MAX_OUTPUT_BYTES:
        raise DashboardError("SenseNova 分析结果过长，请缩小分析需求后重试")
    try:
        envelope = json.loads(payload.decode("utf-8"))
        content = envelope["choices"][0]["message"]["content"]
    except (UnicodeError, json.JSONDecodeError, KeyError, IndexError, TypeError) as error:
        raise DashboardError("SenseNova 返回的分析不是有效 JSON，请重试") from error
    return _analysis_from_content(content)


def validate_analysis(raw: Any, snapshot: dict[str, Any], goal: str, config: InsightConfig) -> dict[str, Any]:
    """验证输出和证据归属，模型身份及指标从原始快照回填。"""
    def obj(value: Any, keys: set[str]) -> dict[str, Any]:
        if not isinstance(value, dict) or set(value) != keys:
            raise DashboardError("AI 分析结果结构无效，请重试")
        return value

    def text(value: Any, limit: int = 1000) -> str:
        if not isinstance(value, str) or not value.strip() or len(value) > limit:
            raise DashboardError("AI 分析结果包含空白或过长文本，请重试")
        return value.strip()

    def items(value: Any, maximum: int) -> list[Any]:
        if not isinstance(value, list) or len(value) > maximum:
            raise DashboardError("AI 分析结果条数无效，请重试")
        return value

    candidates = {candidate["id"]: candidate for candidate in snapshot["candidates"]}
    evidence_by_id = {
        evidence["id"]: {**evidence, **{key: candidate[key] for key in ("model", "tool", "reasoning_effort")}}
        for candidate in candidates.values() for evidence in candidate["evidence"]
    }

    def evidence_refs(value: Any, candidate: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        ids = items(value, 6)
        allowed = {item["id"] for item in candidate["evidence"]} if candidate is not None else set(evidence_by_id)
        if not ids or any(not isinstance(ref, str) or ref not in allowed for ref in ids) or len(set(ids)) != len(ids):
            raise DashboardError("AI 引用了不存在或不属于该配置的证据，请重试")
        return [evidence_by_id[ref] for ref in ids]

    obj(raw, {"summary", "findings", "recommendations", "limitations"})
    summary = text(raw["summary"], 2000)
    findings = []
    for finding in items(raw["findings"], 6):
        obj(finding, {"title", "detail", "evidence_ids"})
        findings.append({"title": text(finding["title"], 160), "detail": text(finding["detail"]), "evidence": evidence_refs(finding["evidence_ids"])})
    recommendations = []
    for recommendation in items(raw["recommendations"], 6):
        obj(recommendation, {"candidate_id", "use_case", "reason", "tradeoffs", "evidence_ids"})
        candidate_id = recommendation["candidate_id"]
        if not isinstance(candidate_id, str) or candidate_id not in candidates:
            raise DashboardError("AI 推荐了输入数据之外的模型配置，请重试")
        candidate = candidates[candidate_id]
        recommendations.append({
            "candidate": {key: candidate[key] for key in ("id", "kind", "model", "tool", "reasoning_effort")},
            "use_case": text(recommendation["use_case"], 160), "reason": text(recommendation["reason"]),
            "tradeoffs": text(recommendation["tradeoffs"]), "evidence": evidence_refs(recommendation["evidence_ids"], candidate),
        })
    return {
        "generated_at": utc_now(), "provider": "sensenova", "model": config.model,
        "goal": goal, "snapshot_hash": snapshot_hash(snapshot), "summary": summary,
        "findings": findings, "recommendations": recommendations,
        "limitations": [text(value) for value in items(raw["limitations"], 8)],
        "coverage": snapshot["coverage"], "warnings": snapshot["warnings"],
    }
