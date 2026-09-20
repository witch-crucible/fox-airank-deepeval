from __future__ import annotations

import copy
import csv
import io
import re
import uuid
from datetime import datetime, timezone
from typing import Any


MODEL_TEST_WEIGHTS = {
    "correction": 3,
    "generation": 4,
    "logic": 8,
}
SCORE_FIELDS = {
    "skill_call",
    "code_review",
    "logic_analysis",
    "function_fix",
    "manual_total",
    "model_test_correction",
    "model_test_generation",
    "model_test_logic",
    "model_test_total",
    "arena_webdev",
    "aa_model_intelligence",
    "aa_model_speed",
    "aa_model_cost_per_task",
    "aa_model_terminal_bench_v4",
    "artificial_analysis_index",
    "aa_deep_swe",
    "aa_deep_swe_v1_1",
    "aa_terminal_bench_v2",
    "aa_terminal_bench_v4",
    "aa_swe_atlas_qna",
    "llm_stats_score",
    "llm_stats_reasoning",
    "llm_stats_code",
    "llm_stats_agents",
    "composite_total",
}
IMPORT_FIELDS = {
    "tool",
    "model",
    "reasoning_effort",
    "response_speed",
    "supplement",
    "notes",
    "report_path",
    *(f"scores.{field}" for field in SCORE_FIELDS),
}


class DashboardError(ValueError):
    """可直接展示给页面的输入错误。"""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def optional_number(value: Any, field: str) -> float | int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise DashboardError(f"{field} 必须是数字")
    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise DashboardError(f"{field} 必须是数字") from error
    if not number == number or number in (float("inf"), float("-inf")):
        raise DashboardError(f"{field} 必须是有限数字")
    return int(number) if number.is_integer() else round(number, 4)


def calculate_scores(raw_scores: Any) -> dict[str, float | int | None]:
    if raw_scores is None:
        raw_scores = {}
    if not isinstance(raw_scores, dict):
        raise DashboardError("scores 必须是对象")
    scores = {
        field: optional_number(raw_scores.get(field), f"scores.{field}")
        for field in SCORE_FIELDS
    }

    manual_parts = [
        scores["skill_call"],
        scores["code_review"],
        scores["logic_analysis"],
        scores["function_fix"],
    ]
    if any(value is not None for value in manual_parts):
        scores["manual_total"] = round(sum(value or 0 for value in manual_parts), 2)

    model_test_parts = {
        "correction": scores["model_test_correction"],
        "generation": scores["model_test_generation"],
        "logic": scores["model_test_logic"],
    }
    if all(value is not None for value in model_test_parts.values()):
        weighted_total = sum(
            float(model_test_parts[name]) * weight
            for name, weight in MODEL_TEST_WEIGHTS.items()
        ) / sum(MODEL_TEST_WEIGHTS.values())
        scores["model_test_total"] = round(weighted_total, 2)

    composite_parts = [
        scores["manual_total"],
        scores["model_test_total"],
        scores["arena_webdev"],
    ]
    scores["composite_total"] = (
        round(sum(value or 0 for value in composite_parts), 2)
        if any(value is not None for value in composite_parts)
        else None
    )
    return scores


def optional_text(value: Any, field: str, max_length: int = 500) -> str:
    if value is None:
        return ""
    if not isinstance(value, str):
        value = str(value)
    text = value.strip()
    if len(text) > max_length:
        raise DashboardError(f"{field} 最长 {max_length} 个字符")
    return text


def normalize_agent_usage_entry(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise DashboardError("使用人数数据必须是对象")
    tool = optional_text(raw.get("tool"), "tool", 100)
    if not tool:
        raise DashboardError("AI 编程工具不能为空")
    user_count = optional_number(raw.get("user_count"), "user_count")
    if user_count is None:
        raise DashboardError("使用人数不能为空")
    if user_count < 0:
        raise DashboardError("使用人数不能为负数")
    return {
        "tool": tool,
        "user_count": user_count,
        "notes": optional_text(raw.get("notes"), "notes", 500),
        "updated_at": utc_now(),
    }


AGENT_USAGE_TOOL_HEADERS = {
    "tool",
    "agent",
    "name",
    "工具",
    "ai编程工具",
    "ai 编程工具",
    "编程工具",
}
AGENT_USAGE_COUNT_HEADERS = {
    "user_count",
    "users",
    "count",
    "user count",
    "使用人数",
    "人数",
}
AGENT_USAGE_NOTES_HEADERS = {
    "notes",
    "note",
    "remark",
    "comment",
    "备注",
}


def _normalize_csv_header(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip()).casefold()


def parse_agent_usage_csv(text: str) -> list[dict[str, Any]]:
    """解析使用人数 CSV；同名工具以文件中靠后的行为准。"""
    if not isinstance(text, str) or not text.strip():
        raise DashboardError("CSV 内容不能为空")
    sample = text.lstrip("\ufeff")
    try:
        reader = csv.DictReader(io.StringIO(sample))
    except csv.Error as error:
        raise DashboardError(f"CSV 解析失败：{error}") from error
    if not reader.fieldnames:
        raise DashboardError("CSV 缺少表头")

    column_map: dict[str, str] = {}
    for field in reader.fieldnames:
        if field is None:
            continue
        header = _normalize_csv_header(field)
        if header in AGENT_USAGE_TOOL_HEADERS and "tool" not in column_map:
            column_map["tool"] = field
        elif header in AGENT_USAGE_COUNT_HEADERS and "user_count" not in column_map:
            column_map["user_count"] = field
        elif header in AGENT_USAGE_NOTES_HEADERS and "notes" not in column_map:
            column_map["notes"] = field
    if "tool" not in column_map or "user_count" not in column_map:
        raise DashboardError("CSV 表头需包含工具列和使用人数列（如 tool,user_count 或 工具,使用人数）")

    entries: list[dict[str, Any]] = []
    index_by_tool: dict[str, int] = {}
    try:
        rows = list(reader)
    except csv.Error as error:
        raise DashboardError(f"CSV 解析失败：{error}") from error

    for line_no, row in enumerate(rows, start=2):
        if not isinstance(row, dict):
            continue
        cells = [(row.get(field) or "").strip() for field in reader.fieldnames if field is not None]
        if not any(cells):
            continue
        tool = (row.get(column_map["tool"]) or "").strip()
        count_raw = (row.get(column_map["user_count"]) or "").strip().replace(",", "")
        notes = (row.get(column_map["notes"]) or "").strip() if "notes" in column_map else ""
        try:
            entry = normalize_agent_usage_entry(
                {"tool": tool, "user_count": count_raw, "notes": notes}
            )
        except DashboardError as error:
            raise DashboardError(f"第 {line_no} 行：{error}") from error
        key = entry["tool"].casefold()
        if key in index_by_tool:
            entries[index_by_tool[key]] = entry
        else:
            index_by_tool[key] = len(entries)
            entries.append(entry)

    if not entries:
        raise DashboardError("CSV 没有有效的使用人数数据行")
    return entries


def normalize_model(raw: Any, source: dict[str, Any] | None = None) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise DashboardError("模型数据必须是对象")
    tool = optional_text(raw.get("tool"), "tool", 100)
    model = optional_text(raw.get("model"), "model", 160)
    if not tool:
        raise DashboardError("AI 编程工具不能为空")
    if not model:
        raise DashboardError("模型名称不能为空")
    model_id = optional_text(raw.get("id"), "id", 100) or f"model-{uuid.uuid4().hex[:12]}"
    normalized_source = source if source is not None else raw.get("source")
    if normalized_source is None:
        normalized_source = {"type": "manual", "name": "手工录入"}
    if not isinstance(normalized_source, dict):
        raise DashboardError("source 必须是对象")
    return {
        "id": model_id,
        "tool": tool,
        "model": model,
        "reasoning_effort": optional_text(raw.get("reasoning_effort"), "reasoning_effort", 80),
        "scores": calculate_scores(raw.get("scores")),
        "response_speed": optional_text(raw.get("response_speed"), "response_speed", 40),
        "supplement": optional_text(raw.get("supplement"), "supplement", 500),
        "notes": optional_text(raw.get("notes"), "notes", 500),
        "report_path": optional_text(raw.get("report_path"), "report_path", 1000),
        "source": copy.deepcopy(normalized_source),
        "archived": raw.get("archived") is True,
        "archived_at": optional_text(raw.get("archived_at"), "archived_at", 80),
        "updated_at": utc_now(),
    }


def get_path(value: Any, path: str) -> Any:
    if not path:
        return value
    current = value
    for part in path.split("."):
        if isinstance(current, dict):
            if part not in current:
                return None
            current = current[part]
        elif isinstance(current, list) and part.isdigit():
            index = int(part)
            if index >= len(current):
                return None
            current = current[index]
        else:
            return None
    return current


def normalize_external_rows(
    document: Any,
    array_path: str,
    mapping: Any,
    source_name: str,
    source_url: str,
) -> list[dict[str, Any]]:
    if not isinstance(mapping, dict):
        raise DashboardError("字段映射必须是对象")
    unknown_fields = set(mapping) - IMPORT_FIELDS
    if unknown_fields:
        raise DashboardError(f"不支持的目标字段: {', '.join(sorted(unknown_fields))}")
    if not mapping.get("tool") or not mapping.get("model"):
        raise DashboardError("字段映射必须包含 tool 和 model")

    rows = get_path(document, array_path.strip())
    if not isinstance(rows, list):
        location = array_path.strip() or "根节点"
        raise DashboardError(f"{location} 不是 JSON 数组")
    if len(rows) > 500:
        raise DashboardError("单次最多导入 500 条模型数据")

    models = []
    source = {"type": "third_party", "name": source_name, "url": source_url, "fetched_at": utc_now()}
    for index, row in enumerate(rows, 1):
        if not isinstance(row, dict):
            raise DashboardError(f"第 {index} 条数据不是对象")
        raw: dict[str, Any] = {"scores": {}}
        for target, source_path in mapping.items():
            if not isinstance(source_path, str) or not source_path.strip():
                continue
            field_value = get_path(row, source_path.strip())
            if target.startswith("scores."):
                raw["scores"][target.removeprefix("scores.")] = field_value
            else:
                raw[target] = field_value
        try:
            models.append(normalize_model(raw, source=source))
        except DashboardError as error:
            raise DashboardError(f"第 {index} 条数据无效：{error}") from error
    return models
