from __future__ import annotations

from copy import deepcopy
from typing import Any

from .domain import DashboardError


DEFAULT_PURPOSE_TYPES = ["Ask", "Plan", "Build", "Review", "Ship"]

DEFAULT_RECOMMENDATIONS: dict[str, Any] = {
    "purpose_types": DEFAULT_PURPOSE_TYPES,
    "agent_plan": [
        {"tool": "Codex", "model": "GPT 6-Astra", "reasoning_effort": "高", "primary_purpose_types": ["Plan"], "secondary_purpose_types": [], "is_core": False, "purpose": "复杂、多步骤且需要充分推理的 Agent 任务。"},
        {"tool": "Codex", "model": "GPT 6-Sol", "reasoning_effort": "高", "primary_purpose_types": ["Plan"], "secondary_purpose_types": [], "is_core": False, "purpose": "复杂、多步骤且需要充分推理的 Agent 任务。"},
        {"tool": "Codex", "model": "GPT 5.6-Luna", "reasoning_effort": "中", "primary_purpose_types": ["Plan"], "secondary_purpose_types": [], "is_core": False, "purpose": "日常开发与需要平衡速度、质量的 Agent 任务。"},
        {"tool": "Claude Code", "model": "Opus 5", "reasoning_effort": "High", "primary_purpose_types": ["Plan"], "secondary_purpose_types": [], "is_core": False, "purpose": "复杂、多步骤且需要充分推理的 Agent 任务。"},
        {"tool": "Cursor", "model": "grok 4.6", "reasoning_effort": "High", "primary_purpose_types": ["Plan"], "secondary_purpose_types": [], "is_core": False, "purpose": "复杂、多步骤且需要充分推理的 Agent 任务。"},
        {"tool": "Cursor", "model": "Composer 2.5", "reasoning_effort": "", "primary_purpose_types": ["Plan"], "secondary_purpose_types": [], "is_core": False, "purpose": "日常 Agent 编码与工具调用任务。"},
    ],
    "coding_plan": [
        {"tool": "", "model": "DeepSeek V4.1 Flash", "reasoning_effort": "", "primary_purpose_types": ["Ship"], "secondary_purpose_types": ["Build"], "is_core": False, "purpose": "代码生成、补全与快速修改。"},
    ],
}

_GROUPS = ("agent_plan", "coding_plan")
_LIMITS = {
    "tool": 120,
    "model": 200,
    "reasoning_effort": 80,
    "purpose_type": 40,
    "secondary_purpose_type": 40,
    "purpose": 300,
}


def _normalize_purpose_types(raw: Any) -> list[str]:
    if raw is None:
        return deepcopy(DEFAULT_PURPOSE_TYPES)
    if not isinstance(raw, list):
        raise DashboardError("recommendations.purpose_types 必须是数组")
    if not raw or len(raw) > 20:
        raise DashboardError("recommendations.purpose_types 必须包含 1 至 20 个类型")
    normalized: list[str] = []
    seen: set[str] = set()
    for index, value in enumerate(raw):
        if not isinstance(value, str):
            raise DashboardError(f"purpose_types 第 {index + 1} 项必须是字符串")
        value = value.strip()
        if not value or len(value) > 40:
            raise DashboardError(f"purpose_types 第 {index + 1} 项必须为 1 至 40 个字符")
        key = value.casefold()
        if key in seen:
            raise DashboardError(f"purpose_types 包含重复类型：{value}")
        seen.add(key)
        normalized.append(value)
    return normalized


def _normalize_row(raw: Any, group: str, index: int, purpose_types: list[str]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise DashboardError(f"{group} 第 {index + 1} 行必须是对象")
    row: dict[str, Any] = {}
    for field in ("tool", "model", "reasoning_effort", "purpose"):
        value = raw.get(field, "")
        if not isinstance(value, str):
            raise DashboardError(f"{group} 第 {index + 1} 行的 {field} 必须是字符串")
        value = value.strip()
        if len(value) > _LIMITS[field]:
            raise DashboardError(f"{group} 第 {index + 1} 行的 {field} 过长")
        row[field] = value
    if not row["model"]:
        raise DashboardError(f"{group} 第 {index + 1} 行的 model 不能为空")
    if "primary_purpose_types" in raw or "secondary_purpose_types" in raw:
        primary_raw = raw.get("primary_purpose_types", [])
        secondary_raw = raw.get("secondary_purpose_types", [])
    else:
        selected_raw = raw.get("purpose_types")
        if selected_raw is None:
            selected_raw = []
            for field in ("purpose_type", "secondary_purpose_type"):
                value = raw.get(field, "")
                if not isinstance(value, str):
                    raise DashboardError(f"{group} 第 {index + 1} 行的 {field} 必须是字符串")
                value = value.strip()
                if len(value) > _LIMITS[field]:
                    raise DashboardError(f"{group} 第 {index + 1} 行的 {field} 过长")
                if value:
                    selected_raw.append(value)
        if not isinstance(selected_raw, list):
            raise DashboardError(f"{group} 第 {index + 1} 行的 purpose_types 必须是数组")
        primary_raw = selected_raw[:1]
        secondary_raw = selected_raw[1:]
    allowed = set(purpose_types)
    seen: set[str] = set()

    def normalize_selected(raw_values: Any, field: str) -> list[str]:
        if not isinstance(raw_values, list):
            raise DashboardError(f"{group} 第 {index + 1} 行的 {field} 必须是数组")
        selected: list[str] = []
        for selected_index, value in enumerate(raw_values):
            if not isinstance(value, str):
                raise DashboardError(f"{group} 第 {index + 1} 行的 {field} 第 {selected_index + 1} 项必须是字符串")
            value = value.strip()
            if not value or len(value) > 40:
                raise DashboardError(f"{group} 第 {index + 1} 行的 {field} 第 {selected_index + 1} 项无效")
            if value not in allowed:
                raise DashboardError(f"{group} 第 {index + 1} 行的 {field} 包含未配置类型：{value}")
            identity = value.casefold()
            if identity in seen:
                raise DashboardError(f"{group} 第 {index + 1} 行的主用途与副用途包含重复类型：{value}")
            seen.add(identity)
            selected.append(value)
        return selected

    primary = normalize_selected(primary_raw, "primary_purpose_types")
    secondary = normalize_selected(secondary_raw, "secondary_purpose_types")
    legacy_is_core = raw.get("is_core", False)
    if not isinstance(legacy_is_core, bool):
        raise DashboardError(f"{group} 第 {index + 1} 行的 is_core 必须是布尔值")
    core_raw = raw.get("core_purpose_types")
    if core_raw is None:
        fallback = "Build" if group == "coding_plan" else "Plan"
        legacy_core = primary or ([fallback] if fallback in purpose_types else purpose_types[:1])
        core_raw = legacy_core if legacy_is_core else []
    if not isinstance(core_raw, list):
        raise DashboardError(f"{group} 第 {index + 1} 行的 core_purpose_types 必须是数组")
    effective_primary = primary or (["Build"] if group == "coding_plan" and "Build" in purpose_types else ["Plan"] if "Plan" in purpose_types else purpose_types[:1])
    core: list[str] = []
    core_seen: set[str] = set()
    for core_index, value in enumerate(core_raw):
        if not isinstance(value, str):
            raise DashboardError(f"{group} 第 {index + 1} 行的 core_purpose_types 第 {core_index + 1} 项必须是字符串")
        value = value.strip()
        identity = value.casefold()
        if value not in effective_primary:
            raise DashboardError(f"{group} 第 {index + 1} 行的核心用途不是该条目的主用途：{value}")
        if identity in core_seen:
            raise DashboardError(f"{group} 第 {index + 1} 行的 core_purpose_types 包含重复类型：{value}")
        core_seen.add(identity)
        core.append(value)
    row["primary_purpose_types"] = primary
    row["secondary_purpose_types"] = secondary
    row["core_purpose_types"] = core
    # 兼容旧客户端：任一主用途被标为核心时仍输出布尔别名。
    row["is_core"] = bool(core)
    # 兼容旧客户端：继续输出合并数组及单值别名。
    row["purpose_types"] = [*primary, *secondary]
    row["purpose_type"] = primary[0] if primary else ""
    row["secondary_purpose_type"] = secondary[0] if secondary else ""
    return row


def normalize_recommendations(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise DashboardError("recommendations 必须是对象")
    purpose_types = _normalize_purpose_types(raw.get("purpose_types"))
    normalized: dict[str, Any] = {"purpose_types": purpose_types}
    for group in _GROUPS:
        rows = raw.get(group)
        if not isinstance(rows, list):
            raise DashboardError(f"recommendations.{group} 必须是数组")
        if len(rows) > 100:
            raise DashboardError(f"recommendations.{group} 最多支持 100 行")
        normalized[group] = [_normalize_row(row, group, index, purpose_types) for index, row in enumerate(rows)]
    return normalized


def default_recommendations() -> dict[str, Any]:
    return normalize_recommendations(deepcopy(DEFAULT_RECOMMENDATIONS))


def normalize_stored_recommendations(raw: Any) -> dict[str, Any]:
    """读取旧数据时补齐缺失建议；完整字段仍按同一严格规则校验。"""
    if raw is None:
        return default_recommendations()
    if not isinstance(raw, dict):
        raise DashboardError("本地 recommendations 数据格式无效")
    defaults = default_recommendations()
    for field in ("purpose_types", *_GROUPS):
        if field in raw:
            defaults[field] = raw[field]
    try:
        return normalize_recommendations(defaults)
    except DashboardError as error:
        raise DashboardError(f"本地 recommendations 数据格式无效：{error}") from error
