from __future__ import annotations

import argparse
import copy
import csv
import io
import ipaddress
import json
import os
import re
import socket
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen


ROOT = Path(__file__).resolve().parent
SEED_PATH = ROOT / "seed_data.json"
DEFAULT_DATA_PATH = ROOT / "data.local.json"
STATIC_ROOT = ROOT / "static"
INDEX_PATH = STATIC_ROOT / "index.html"
MAX_BODY_BYTES = 2 * 1024 * 1024
STATIC_CONTENT_TYPES = {
    ".svg": "image/svg+xml; charset=utf-8",
    ".png": "image/png",
    ".ico": "image/x-icon",
    ".webp": "image/webp",
}
ARENA_WEBDEV_URL = "https://arena.ai/leaderboard/code/webdev"
ARENA_DATASET_URL = (
    "https://datasets-server.huggingface.co/rows"
    "?dataset=lmarena-ai%2Fleaderboard-dataset"
    "&config=webdev&split=latest&offset=0&length=100"
)
LEADERBOARD_TOP_LIMIT = 30
ARENA_TOP_LIMIT = LEADERBOARD_TOP_LIMIT
ARTIFICIAL_ANALYSIS_URL = "https://artificialanalysis.ai/agents/coding-agents"
LLM_STATS_URL = "https://llm-stats.com/"
LLM_STATS_INDEX_URL = "https://api.zeroeval.com/leaderboard/indexes/compact?payloadVersion=2"
MODEL_TEST_WEIGHTS = {
    "correction": 3,
    "generation": 4,
    "logic": 7,
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
    "artificial_analysis_index",
    "aa_deep_swe",
    "aa_terminal_bench_v2",
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
ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
HEADER_NAME = re.compile(r"^[A-Za-z0-9-]+$")


class DashboardError(ValueError):
    """可直接展示给页面的输入错误。"""


def url_origin(url: str) -> tuple[str, str, int | None]:
    parsed = urlparse(url)
    scheme = parsed.scheme.casefold()
    try:
        port = parsed.port
    except ValueError as error:
        raise DashboardError("数据源 URL 端口无效") from error
    if port is None:
        port = 443 if scheme == "https" else 80 if scheme == "http" else None
    return scheme, (parsed.hostname or "").casefold(), port


def reject_private_host(url: str) -> None:
    """Reject literal or DNS-resolved private destinations for user URLs."""
    hostname = urlparse(url).hostname
    if not hostname:
        raise DashboardError("数据源 URL 缺少主机名")
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(hostname, None)}
    except socket.gaierror as error:
        raise DashboardError("无法解析数据源主机") from error
    for address in addresses:
        ip = ipaddress.ip_address(address)
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise DashboardError("数据源不得指向内网或保留地址")


class SameOriginRedirectHandler(HTTPRedirectHandler):
    """防止带鉴权头的请求在重定向时把密钥发送到其他站点。"""

    def redirect_request(
        self,
        req: Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> Request | None:
        if url_origin(req.full_url) != url_origin(newurl):
            raise DashboardError("带鉴权的数据源不能重定向到其他站点")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def resolve_static_path(request_path: str) -> Path | None:
    """将 /static/... 映射到 STATIC_ROOT；拒绝目录穿越与未允许后缀。"""
    if not request_path.startswith("/static/"):
        return None
    relative = unquote(request_path.removeprefix("/static/"))
    if not relative or relative.endswith("/") or "\\" in relative:
        return None
    candidate = (STATIC_ROOT / relative).resolve()
    try:
        candidate.relative_to(STATIC_ROOT.resolve())
    except ValueError:
        return None
    if candidate.suffix.casefold() not in STATIC_CONTENT_TYPES:
        return None
    if not candidate.is_file():
        return None
    return candidate


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


def normalize_arena_webdev_rows(
    document: Any,
    limit: int = ARENA_TOP_LIMIT,
) -> list[dict[str, Any]]:
    if not isinstance(document, dict) or not isinstance(document.get("rows"), list):
        raise DashboardError("Arena WebDev 数据格式无效")

    ranked_rows = []
    for item in document["rows"]:
        row = item.get("row") if isinstance(item, dict) else None
        if not isinstance(row, dict) or str(row.get("category", "")).casefold() != "overall":
            continue
        try:
            rank = int(row.get("rank"))
        except (TypeError, ValueError):
            continue
        if rank > 0:
            ranked_rows.append((rank, row))

    ranked_rows.sort(key=lambda item: (item[0], str(item[1].get("model_name", "")).casefold()))
    selected = ranked_rows[:limit]
    if len(selected) < limit:
        raise DashboardError(f"Arena WebDev 返回的数据不足 {limit} 条，本次未更新")

    fetched_at = utc_now()
    models = []
    for rank, row in selected:
        model_name = optional_text(row.get("model_name"), "model_name", 160)
        rating = optional_number(row.get("rating"), "rating")
        if not model_name or rating is None:
            raise DashboardError(f"Arena WebDev 第 {rank} 名缺少模型或分数")
        organization = optional_text(row.get("organization"), "organization", 100)
        license_name = optional_text(row.get("license"), "license", 100)
        publish_date = optional_text(row.get("leaderboard_publish_date"), "leaderboard_publish_date", 40)
        notes = f"Arena WebDev 第 {rank} 名"
        if organization:
            notes += f" · {organization}"
        models.append(
            normalize_model(
                {
                    "tool": "Arena WebDev",
                    "model": model_name,
                    "scores": {"arena_webdev": rating},
                    "notes": notes,
                },
                source={
                    "type": "arena_webdev",
                    "name": "Arena WebDev",
                    "url": ARENA_WEBDEV_URL,
                    "dataset_url": ARENA_DATASET_URL,
                    "fetched_at": fetched_at,
                    "leaderboard_publish_date": publish_date,
                    "rank": rank,
                    "organization": organization,
                    "license": license_name,
                },
            )
        )
    return models


def normalize_artificial_analysis_html(
    document: str,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """Parse Artificial Analysis Coding Agents HTML.

    Default product path is select-all (full Coding Agent Index). Pass ``limit``
    only when a caller intentionally wants a truncated subset (e.g. tests).
    """
    if not isinstance(document, str) or "indexScore" not in document:
        raise DashboardError("Artificial Analysis Coding Agents 页面缺少榜单数据")

    version_match = re.search(r"Artificial Analysis Coding Agent Index v([0-9.]+)", document)
    index_version = f"v{version_match.group(1)}" if version_match else "unknown"
    flight_data = []
    for script in re.findall(r"<script[^>]*>(.*?)</script>", document, flags=re.DOTALL | re.IGNORECASE):
        match = re.search(r"self\.__next_f\.push\((\[1,.*\])\)", script, flags=re.DOTALL)
        if not match:
            continue
        try:
            payload = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue
        if len(payload) > 1 and isinstance(payload[1], str):
            flight_data.append(payload[1])

    decoded = "".join(flight_data)
    decoder = json.JSONDecoder()
    rows: dict[str, dict[str, Any]] = {}
    position = 0
    while True:
        position = decoded.find('{"id":', position)
        if position < 0:
            break
        try:
            row, end = decoder.raw_decode(decoded, position)
        except json.JSONDecodeError:
            position += 1
            continue
        position = end
        display = row.get("display") if isinstance(row, dict) else None
        if (
            isinstance(display, dict)
            and isinstance(row.get("id"), str)
            and isinstance(row.get("indexScore"), (int, float))
            and isinstance(display.get("agent"), str)
            and isinstance(display.get("model"), str)
        ):
            rows[row["id"]] = row

    ranked_rows = sorted(rows.values(), key=lambda row: (-float(row["indexScore"]), row["id"]))
    if not ranked_rows:
        raise DashboardError("Artificial Analysis Coding Agents 页面未解析到有效排名")
    if limit is not None:
        if limit <= 0:
            raise DashboardError("Artificial Analysis Coding Agents 截断条数无效")
        ranked_rows = ranked_rows[:limit]

    fetched_at = utc_now()
    models = []
    for rank, row in enumerate(ranked_rows, 1):
        display = row["display"]
        eval_scores = {
            item.get("datasetIndexName"): item.get("mean", {}).get("reward")
            for item in row.get("evals", [])
            if isinstance(item, dict) and isinstance(item.get("mean"), dict)
        }
        index_score = round(float(row["indexScore"]) * 100, 4)
        # Official page currently emits terminal-bench-v2.1; keep v2 as a fallback
        # for older fixtures / cached HTML.
        terminal_bench = eval_scores.get("terminal-bench-v2.1")
        if terminal_bench is None:
            terminal_bench = eval_scores.get("terminal-bench-v2")
        component_scores = {
            "aa_deep_swe": eval_scores.get("deep-swe"),
            "aa_terminal_bench_v2": terminal_bench,
            "aa_swe_atlas_qna": eval_scores.get("swe-atlas-qna"),
        }
        scores = {"artificial_analysis_index": index_score}
        for field, value in component_scores.items():
            scores[field] = round(float(value) * 100, 4) if isinstance(value, (int, float)) else None
        mean = row.get("mean") if isinstance(row.get("mean"), dict) else {}
        models.append(
            normalize_model(
                {
                    "tool": display["agent"],
                    "model": display["model"],
                    "scores": scores,
                    "notes": f"Artificial Analysis Coding Agent Index 第 {rank} 名",
                },
                source={
                    "type": "artificial_analysis",
                    "name": "Artificial Analysis Coding Agents",
                    "url": ARTIFICIAL_ANALYSIS_URL,
                    "fetched_at": fetched_at,
                    "rank": rank,
                    "source_id": row["id"],
                    "index_version": index_version,
                    "creator": display.get("creator", {}),
                    "cost_usd_per_task": mean.get("costUsd"),
                    "wall_time_seconds_per_task": mean.get("agentWallTimeSec"),
                },
            )
        )
    return models


def normalize_llm_stats_indexes(
    document: Any,
    limit: int = LEADERBOARD_TOP_LIMIT,
) -> list[dict[str, Any]]:
    if not isinstance(document, dict):
        raise DashboardError("LLM Stats 数据格式无效")
    general = document.get("general")
    ranked_rows = general.get("models") if isinstance(general, dict) else None
    if not isinstance(ranked_rows, list) or not ranked_rows:
        raise DashboardError("LLM Stats 数据缺少 general 总榜")
    if len(ranked_rows) > 500:
        raise DashboardError("LLM Stats 总榜超过 500 条，本次未更新")

    category_scores: dict[str, dict[str, Any]] = {}
    for category in ("reasoning", "code", "agents"):
        category_data = document.get(category)
        rows = category_data.get("models") if isinstance(category_data, dict) else None
        category_scores[category] = {
            str(row.get("model_id")): row.get("conservative")
            for row in rows or []
            if isinstance(row, dict) and row.get("model_id")
        }

    validated_rows = []
    seen_ids = set()
    for position, row in enumerate(ranked_rows, 1):
        if not isinstance(row, dict):
            raise DashboardError(f"LLM Stats 总榜第 {position} 条数据不是对象")
        source_id = optional_text(row.get("model_id"), "model_id", 160)
        model_name = optional_text(row.get("model_name"), "model_name", 160)
        score = optional_number(row.get("conservative"), "conservative")
        try:
            rank = int(row.get("rank"))
        except (TypeError, ValueError) as error:
            raise DashboardError(f"LLM Stats 总榜第 {position} 条排名无效") from error
        if not source_id or not model_name or score is None or rank <= 0:
            raise DashboardError(f"LLM Stats 总榜第 {position} 条缺少模型、分数或排名")
        if source_id in seen_ids:
            raise DashboardError(f"LLM Stats 总榜包含重复模型 ID：{source_id}")
        seen_ids.add(source_id)
        validated_rows.append((rank, source_id, model_name, score, row))

    validated_rows.sort(key=lambda item: (item[0], item[1]))
    selected = validated_rows[:limit]
    fetched_at = utc_now()
    models = []
    for rank, source_id, model_name, score, row in selected:
        organization = optional_text(row.get("organization_name"), "organization_name", 100)
        scores = {
            "llm_stats_score": score,
            "llm_stats_reasoning": category_scores["reasoning"].get(source_id),
            "llm_stats_code": category_scores["code"].get(source_id),
            "llm_stats_agents": category_scores["agents"].get(source_id),
        }
        models.append(
            normalize_model(
                {
                    "tool": organization or "LLM Stats",
                    "model": model_name,
                    "scores": scores,
                    "notes": f"LLM Stats Score 第 {rank} 名",
                },
                source={
                    "type": "llm_stats",
                    "name": "LLM Stats",
                    "url": LLM_STATS_URL,
                    "api_url": LLM_STATS_INDEX_URL,
                    "fetched_at": fetched_at,
                    "rank": rank,
                    "source_id": source_id,
                    "organization_id": optional_text(row.get("organization_id"), "organization_id", 100),
                    "organization": organization,
                    "rank_delta_14d": optional_number(row.get("rank_delta_14d"), "rank_delta_14d"),
                    "games_played": optional_number(row.get("games_played"), "games_played"),
                },
            )
        )
    return models


def fetch_json(url: str, auth: Any, timeout: float = 12) -> Any:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise DashboardError("数据源 URL 必须是有效的 HTTP 或 HTTPS 地址")
    url_origin(url)
    reject_private_host(url)
    headers = {"Accept": "application/json", "User-Agent": "model-capability-dashboard/1.0"}
    authenticated = False
    if auth:
        if not isinstance(auth, dict):
            raise DashboardError("鉴权配置无效")
        env_name = optional_text(auth.get("env"), "auth.env", 100)
        header = optional_text(auth.get("header") or "Authorization", "auth.header", 100)
        prefix = optional_text(auth.get("prefix"), "auth.prefix", 100)
        if env_name:
            if parsed.scheme != "https":
                raise DashboardError("带鉴权的数据源必须使用 HTTPS")
            if not ENV_NAME.fullmatch(env_name):
                raise DashboardError("密钥环境变量名无效")
            if not HEADER_NAME.fullmatch(header):
                raise DashboardError("鉴权请求头名称无效")
            secret = os.environ.get(env_name)
            if not secret:
                raise DashboardError(f"环境变量 {env_name} 未设置")
            headers[header] = f"{prefix}{secret}"
            authenticated = True
    # Always send an explicit, minimal request.  In particular, never fall
    # back to urlopen(url), which permits ambient credentials/proxy behavior.
    request = Request(url, headers=headers, method="GET")
    try:
        opener = build_opener(SameOriginRedirectHandler()) if authenticated else None
        response_context = opener.open(request, timeout=timeout) if opener else urlopen(request, timeout=timeout)
        with response_context as response:
            final_url = urlparse(response.geturl())
            if final_url.scheme not in {"http", "https"}:
                raise DashboardError("数据源重定向到了不安全的地址")
            content_type = response.headers.get_content_type()
            payload = response.read(MAX_BODY_BYTES + 1)
    except HTTPError as error:
        raise DashboardError(f"第三方接口返回 HTTP {error.code}") from error
    except URLError as error:
        raise DashboardError(f"无法访问第三方接口：{error.reason}") from error
    if len(payload) > MAX_BODY_BYTES:
        raise DashboardError("第三方响应超过 2 MB 限制")
    if content_type not in {"application/json", "text/json", "text/plain"} and not content_type.endswith("+json"):
        raise DashboardError(f"第三方响应不是 JSON（Content-Type: {content_type}）")
    try:
        return json.loads(payload.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise DashboardError("第三方响应不是有效的 UTF-8 JSON") from error


def fetch_text(url: str, timeout: float = 20) -> str:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise DashboardError("页面 URL 必须是有效的 HTTPS 地址")
    request = Request(
        url,
        headers={
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-US,en;q=0.9",
            "User-Agent": "Mozilla/5.0 model-capability-dashboard/1.0",
        },
        method="GET",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            final_url = urlparse(response.geturl())
            if final_url.scheme != "https":
                raise DashboardError("页面重定向到了非 HTTPS 地址")
            payload = response.read(MAX_BODY_BYTES + 1)
    except HTTPError as error:
        raise DashboardError(f"榜单页面返回 HTTP {error.code}") from error
    except URLError as error:
        raise DashboardError(f"无法访问榜单页面：{error.reason}") from error
    if len(payload) > MAX_BODY_BYTES:
        raise DashboardError("榜单页面超过 2 MB 限制")
    try:
        return payload.decode("utf-8")
    except UnicodeDecodeError as error:
        raise DashboardError("榜单页面不是有效的 UTF-8 HTML") from error


class DashboardStore:
    def __init__(self, seed_path: Path = SEED_PATH, data_path: Path = DEFAULT_DATA_PATH):
        self.seed_path = seed_path
        self.data_path = data_path
        self._lock = threading.Lock()

    def read(self) -> dict[str, Any]:
        path = self.data_path if self.data_path.exists() else self.seed_path
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise DashboardError(f"无法读取看板数据：{error}") from error
        if not isinstance(data, dict) or not isinstance(data.get("models"), list):
            raise DashboardError("看板数据格式无效")
        return data

    def write(self, data: dict[str, Any]) -> None:
        self.data_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.data_path.with_suffix(f"{self.data_path.suffix}.tmp")
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(self.data_path)

    def add_model(self, raw: Any) -> dict[str, Any]:
        if not isinstance(raw, dict):
            raise DashboardError("模型数据必须是对象")
        safe_raw = {key: value for key, value in raw.items() if key not in {"id", "source", "archived", "archived_at"}}
        model = normalize_model(safe_raw, source={"type": "manual", "name": "手工录入"})
        with self._lock:
            data = self.read()
            data["models"].append(model)
            data.setdefault("meta", {})["updated_at"] = utc_now()
            self.write(data)
        return model

    def upsert_agent_usage(self, raw: Any) -> tuple[dict[str, Any], bool]:
        entry = normalize_agent_usage_entry(raw)
        with self._lock:
            data = self.read()
            usage = data.get("agent_usage")
            if not isinstance(usage, list):
                usage = []
                data["agent_usage"] = usage
            key = entry["tool"].casefold()
            for index, current in enumerate(usage):
                if isinstance(current, dict) and str(current.get("tool", "")).casefold() == key:
                    usage[index] = entry
                    data.setdefault("meta", {})["updated_at"] = utc_now()
                    self.write(data)
                    return entry, False
            usage.append(entry)
            data.setdefault("meta", {})["updated_at"] = utc_now()
            self.write(data)
        return entry, True

    def import_agent_usage(self, entries: list[dict[str, Any]]) -> dict[str, int]:
        if not entries:
            raise DashboardError("没有可导入的使用人数")
        created = 0
        updated = 0
        with self._lock:
            data = self.read()
            usage = data.get("agent_usage")
            if not isinstance(usage, list):
                usage = []
                data["agent_usage"] = usage
            index_by_tool: dict[str, int] = {}
            for index, current in enumerate(usage):
                if isinstance(current, dict) and current.get("tool"):
                    index_by_tool[str(current["tool"]).casefold()] = index
            for raw in entries:
                entry = normalize_agent_usage_entry(raw)
                key = entry["tool"].casefold()
                if key in index_by_tool:
                    usage[index_by_tool[key]] = entry
                    updated += 1
                else:
                    index_by_tool[key] = len(usage)
                    usage.append(entry)
                    created += 1
            data.setdefault("meta", {})["updated_at"] = utc_now()
            self.write(data)
        return {"created": created, "updated": updated, "received": len(entries)}

    def set_model_archived(self, model_id: str, archived: bool) -> dict[str, Any]:
        with self._lock:
            data = self.read()
            matches = [item for item in data["models"] if item.get("id") == model_id]
            if not matches:
                raise DashboardError("模型记录不存在")
            if len(matches) > 1:
                raise DashboardError("本地数据包含重复的模型 ID，拒绝修改")
            model = matches[0]
            model["archived"] = archived
            model["archived_at"] = utc_now() if archived else ""
            model["updated_at"] = utc_now()
            data.setdefault("meta", {})["updated_at"] = utc_now()
            self.write(data)
        return model

    def import_models(self, models: list[dict[str, Any]], overwrite: bool) -> dict[str, int]:
        created = 0
        updated = 0
        skipped = 0
        with self._lock:
            data = self.read()
            existing = {
                self._model_key(model): index
                for index, model in enumerate(data["models"])
            }
            for model in models:
                key = self._model_key(model)
                if key in existing:
                    if overwrite:
                        current = data["models"][existing[key]]
                        model["id"] = current.get("id", model["id"])
                        self._preserve_archive(current, model)
                        data["models"][existing[key]] = model
                        updated += 1
                    else:
                        skipped += 1
                else:
                    existing[key] = len(data["models"])
                    data["models"].append(model)
                    created += 1
            data.setdefault("meta", {})["updated_at"] = utc_now()
            self.write(data)
        return {"created": created, "updated": updated, "skipped": skipped}

    def sync_arena_webdev(self, models: list[dict[str, Any]]) -> dict[str, int]:
        with self._lock:
            data = self.read()
            previous = {
                str(model.get("model", "")).casefold(): model
                for model in data["models"]
                if self._source_type(model) == "arena_webdev"
            }
            retained = [
                model
                for model in data["models"]
                if self._source_type(model) != "arena_webdev"
            ]
            created = 0
            updated = 0
            synced_keys: set[str] = set()
            for model in models:
                key = str(model.get("model", "")).casefold()
                synced_keys.add(key)
                existing = previous.get(key)
                if existing:
                    model["id"] = existing.get("id", model["id"])
                    self._preserve_archive(existing, model)
                    updated += 1
                else:
                    created += 1
                retained.append(model)
            archived_history = [
                model
                for key, model in previous.items()
                if key not in synced_keys and model.get("archived") is True
            ]
            retained.extend(archived_history)
            removed = len(previous) - updated - len(archived_history)
            data["models"] = retained
            data.setdefault("meta", {})["updated_at"] = utc_now()
            data["meta"]["arena_webdev_updated_at"] = models[0]["source"]["fetched_at"]
            data["meta"]["arena_webdev_publish_date"] = models[0]["source"].get("leaderboard_publish_date", "")
            self.write(data)
        return {"created": created, "updated": updated, "removed": removed}

    def sync_artificial_analysis(self, models: list[dict[str, Any]]) -> dict[str, int]:
        with self._lock:
            data = self.read()
            previous = {
                str(model.get("source", {}).get("source_id", "")): model
                for model in data["models"]
                if self._source_type(model) == "artificial_analysis"
            }
            retained = [
                model
                for model in data["models"]
                if self._source_type(model) != "artificial_analysis"
            ]
            created = 0
            updated = 0
            synced_keys: set[str] = set()
            for model in models:
                source_id = str(model["source"]["source_id"])
                synced_keys.add(source_id)
                existing = previous.get(source_id)
                if existing:
                    model["id"] = existing.get("id", model["id"])
                    self._preserve_archive(existing, model)
                    updated += 1
                else:
                    created += 1
                retained.append(model)
            archived_history = [
                model
                for key, model in previous.items()
                if key not in synced_keys and model.get("archived") is True
            ]
            retained.extend(archived_history)
            removed = len(previous) - updated - len(archived_history)
            data["models"] = retained
            data.setdefault("meta", {})["updated_at"] = utc_now()
            data["meta"]["artificial_analysis_updated_at"] = models[0]["source"]["fetched_at"]
            data["meta"]["artificial_analysis_index_version"] = models[0]["source"]["index_version"]
            self.write(data)
        return {"created": created, "updated": updated, "removed": removed}

    def sync_llm_stats(self, models: list[dict[str, Any]]) -> dict[str, int]:
        with self._lock:
            data = self.read()
            previous = {
                str(model.get("source", {}).get("source_id", "")): model
                for model in data["models"]
                if self._source_type(model) == "llm_stats"
            }
            retained = [
                model
                for model in data["models"]
                if self._source_type(model) != "llm_stats"
            ]
            created = 0
            updated = 0
            synced_keys: set[str] = set()
            for model in models:
                source_id = str(model["source"]["source_id"])
                synced_keys.add(source_id)
                existing = previous.get(source_id)
                if existing:
                    model["id"] = existing.get("id", model["id"])
                    self._preserve_archive(existing, model)
                    updated += 1
                else:
                    created += 1
                retained.append(model)
            archived_history = [
                model
                for key, model in previous.items()
                if key not in synced_keys and model.get("archived") is True
            ]
            retained.extend(archived_history)
            removed = len(previous) - updated - len(archived_history)
            data["models"] = retained
            data.setdefault("meta", {})["updated_at"] = utc_now()
            data["meta"]["llm_stats_updated_at"] = models[0]["source"]["fetched_at"]
            self.write(data)
        return {"created": created, "updated": updated, "removed": removed}

    @staticmethod
    def _source_type(model: dict[str, Any]) -> str:
        source = model.get("source")
        return str(source.get("type", "")) if isinstance(source, dict) else ""

    @staticmethod
    def _preserve_archive(current: dict[str, Any], replacement: dict[str, Any]) -> None:
        replacement["archived"] = current.get("archived") is True
        replacement["archived_at"] = current.get("archived_at", "") if replacement["archived"] else ""

    @staticmethod
    def _model_key(model: dict[str, Any]) -> tuple[str, str, str]:
        return (
            str(model.get("tool", "")).casefold(),
            str(model.get("model", "")).casefold(),
            str(model.get("reasoning_effort", "")).casefold(),
        )


class DashboardHandler(BaseHTTPRequestHandler):
    server_version = "ModelDashboard/1.0"

    @property
    def dashboard_store(self) -> DashboardStore:
        return self.server.store  # type: ignore[attr-defined,no-any-return]

    @property
    def json_fetcher(self) -> Callable[[str, Any], Any]:
        return self.server.json_fetcher  # type: ignore[attr-defined,no-any-return]

    @property
    def text_fetcher(self) -> Callable[[str], str]:
        return self.server.text_fetcher  # type: ignore[attr-defined,no-any-return]

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/":
            self._send_bytes(HTTPStatus.OK, INDEX_PATH.read_bytes(), "text/html; charset=utf-8")
            return
        if path == "/api/models":
            self._send_json(HTTPStatus.OK, self.dashboard_store.read())
            return
        if path == "/api/health":
            self._send_json(HTTPStatus.OK, {"status": "ok"})
            return
        static_path = resolve_static_path(path)
        if static_path is not None:
            content_type = STATIC_CONTENT_TYPES[static_path.suffix.casefold()]
            self._send_bytes(HTTPStatus.OK, static_path.read_bytes(), content_type)
            return
        self._send_json(HTTPStatus.NOT_FOUND, {"error": "页面不存在"})

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        try:
            payload = self._read_json_body()
            if path == "/api/models":
                model = self.dashboard_store.add_model(payload)
                self._send_json(HTTPStatus.CREATED, {"model": model})
                return
            if path == "/api/agent-usage":
                entry, created = self.dashboard_store.upsert_agent_usage(payload)
                status = HTTPStatus.CREATED if created else HTTPStatus.OK
                self._send_json(status, {"entry": entry, "created": created})
                return
            if path == "/api/agent-usage/import":
                self._import_agent_usage(payload)
                return
            if path.startswith("/api/models/") and path.endswith("/archive"):
                model_id = unquote(path.removeprefix("/api/models/").removesuffix("/archive").strip("/"))
                if not model_id:
                    raise DashboardError("模型 ID 不能为空")
                if not isinstance(payload, dict) or not isinstance(payload.get("archived"), bool):
                    raise DashboardError("archived 必须是布尔值")
                model = self.dashboard_store.set_model_archived(model_id, payload["archived"])
                self._send_json(HTTPStatus.OK, {"model": model})
                return
            if path == "/api/import":
                self._import(payload)
                return
            if path == "/api/import/arena-webdev":
                self._import_arena_webdev(payload)
                return
            if path == "/api/import/artificial-analysis":
                self._import_artificial_analysis(payload)
                return
            if path == "/api/import/llm-stats":
                self._import_llm_stats(payload)
                return
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "接口不存在"})
        except DashboardError as error:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(error)})
        except Exception:
            self.log_error("处理请求时发生未预期错误")
            self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "服务器处理失败"})

    def _import(self, payload: Any) -> None:
        if not isinstance(payload, dict):
            raise DashboardError("请求数据必须是对象")
        url = optional_text(payload.get("url"), "url", 2000)
        if not url:
            raise DashboardError("数据源 URL 不能为空")
        name = optional_text(payload.get("name"), "name", 120) or urlparse(url).hostname or "第三方数据源"
        document = self.json_fetcher(url, payload.get("auth"))
        models = normalize_external_rows(
            document,
            optional_text(payload.get("array_path"), "array_path", 300),
            payload.get("mapping"),
            name,
            url,
        )
        result = self.dashboard_store.import_models(models, bool(payload.get("overwrite")))
        self._send_json(HTTPStatus.OK, {**result, "received": len(models)})

    def _import_agent_usage(self, payload: Any) -> None:
        if not isinstance(payload, dict):
            raise DashboardError("请求数据必须是对象")
        csv_text = payload.get("csv")
        if not isinstance(csv_text, str):
            raise DashboardError("csv 必须是字符串")
        entries = parse_agent_usage_csv(csv_text)
        result = self.dashboard_store.import_agent_usage(entries)
        self._send_json(HTTPStatus.OK, result)

    def _import_arena_webdev(self, payload: Any) -> None:
        if not isinstance(payload, dict):
            raise DashboardError("请求数据必须是对象")
        document = self.json_fetcher(ARENA_DATASET_URL, None)
        models = normalize_arena_webdev_rows(document)
        result = self.dashboard_store.sync_arena_webdev(models)
        self._send_json(HTTPStatus.OK, {**result, "received": len(models)})

    def _import_artificial_analysis(self, payload: Any) -> None:
        if not isinstance(payload, dict):
            raise DashboardError("请求数据必须是对象")
        document = self.text_fetcher(ARTIFICIAL_ANALYSIS_URL)
        models = normalize_artificial_analysis_html(document)
        result = self.dashboard_store.sync_artificial_analysis(models)
        self._send_json(HTTPStatus.OK, {**result, "received": len(models)})

    def _import_llm_stats(self, payload: Any) -> None:
        if not isinstance(payload, dict):
            raise DashboardError("请求数据必须是对象")
        document = self.json_fetcher(LLM_STATS_INDEX_URL, None)
        models = normalize_llm_stats_indexes(document)
        result = self.dashboard_store.sync_llm_stats(models)
        self._send_json(HTTPStatus.OK, {**result, "received": len(models)})

    def _read_json_body(self) -> Any:
        content_type = self.headers.get_content_type()
        if content_type != "application/json":
            raise DashboardError("Content-Type 必须是 application/json")
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as error:
            raise DashboardError("Content-Length 无效") from error
        if length <= 0:
            raise DashboardError("请求体不能为空")
        if length > MAX_BODY_BYTES:
            raise DashboardError("请求体超过 2 MB 限制")
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise DashboardError("请求体不是有效的 UTF-8 JSON") from error

    def _send_json(self, status: HTTPStatus, payload: Any) -> None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send_bytes(status, data, "application/json; charset=utf-8")

    def _send_bytes(self, status: HTTPStatus, data: bytes, content_type: str) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; base-uri 'none'; form-action 'self'")
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args: Any) -> None:
        print(f"[{self.log_date_time_string()}] {format % args}")


def create_server(
    host: str,
    port: int,
    data_path: Path = DEFAULT_DATA_PATH,
    json_fetcher: Callable[[str, Any], Any] = fetch_json,
    text_fetcher: Callable[[str], str] = fetch_text,
) -> ThreadingHTTPServer:
    server = ThreadingHTTPServer((host, port), DashboardHandler)
    server.store = DashboardStore(data_path=data_path)  # type: ignore[attr-defined]
    server.json_fetcher = json_fetcher  # type: ignore[attr-defined]
    server.text_fetcher = text_fetcher  # type: ignore[attr-defined]
    return server


RELOAD_EXTENSIONS = {".py"}
RELOAD_IGNORE_NAMES = {"data.local.json"}


def collect_watch_snapshot(root: Path = ROOT) -> dict[str, int]:
    """收集热更新监听文件的 mtime 快照；忽略本地数据与缓存。"""
    snapshot: dict[str, int] = {}
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if "__pycache__" in path.parts or path.name.startswith("."):
            continue
        if path.name in RELOAD_IGNORE_NAMES:
            continue
        if path.suffix not in RELOAD_EXTENSIONS:
            continue
        try:
            snapshot[str(path.resolve())] = path.stat().st_mtime_ns
        except OSError:
            continue
    return snapshot


def _stop_process(process: subprocess.Popen[Any]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def _format_changed_paths(paths: list[str]) -> str:
    labels: list[str] = []
    for path in paths:
        try:
            labels.append(str(Path(path).relative_to(ROOT)))
        except ValueError:
            labels.append(path)
    return ", ".join(labels) or "未知文件"


def run_with_reload(child_argv: list[str], poll_interval: float = 0.5) -> None:
    """父进程监听代码变更，自动重启子服务进程。"""
    env = os.environ.copy()
    env.setdefault("PYTHONUNBUFFERED", "1")
    command = [sys.executable, "-m", "model_dashboard.server", *child_argv]
    print("热更新已启用：监听 model_dashboard/**/*.py（改动后自动重启）", flush=True)
    process = subprocess.Popen(command, env=env)
    snapshot = collect_watch_snapshot(ROOT)
    try:
        while True:
            time.sleep(poll_interval)
            current = collect_watch_snapshot(ROOT)
            if current != snapshot:
                changed = sorted(
                    path
                    for path in set(current) | set(snapshot)
                    if current.get(path) != snapshot.get(path)
                )
                print(
                    f"检测到代码变更，正在重启… ({_format_changed_paths(changed)})",
                    flush=True,
                )
                _stop_process(process)
                process = subprocess.Popen(command, env=env)
                snapshot = current
                continue
            if process.poll() is None:
                continue
            exit_code = process.returncode
            if exit_code == 0:
                return
            print(
                f"服务进程异常退出（code={exit_code}），等待下次代码变更后重启…",
                flush=True,
            )
            while True:
                time.sleep(poll_interval)
                current = collect_watch_snapshot(ROOT)
                if current != snapshot:
                    snapshot = current
                    process = subprocess.Popen(command, env=env)
                    break
    except KeyboardInterrupt:
        print("\n看板已停止", flush=True)
    finally:
        _stop_process(process)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="模型能力台")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA_PATH)
    parser.add_argument(
        "--reload",
        action="store_true",
        help="开发模式：监听代码变更并自动重启服务",
    )
    args = parser.parse_args(argv)
    if args.reload:
        run_with_reload(
            [
                "--host",
                args.host,
                "--port",
                str(args.port),
                "--data",
                str(args.data),
            ]
        )
        return

    server = create_server(args.host, args.port, args.data)
    print(f"模型能力台：http://{args.host}:{server.server_port}")
    print(f"本地数据：{args.data}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n看板已停止")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
