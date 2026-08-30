from __future__ import annotations

import ipaddress
import json
import os
import re
import socket
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen

from .domain import (
    DashboardError,
    normalize_model,
    optional_number,
    optional_text,
    utc_now,
)


MAX_BODY_BYTES = 2 * 1024 * 1024
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
ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
HEADER_NAME = re.compile(r"^[A-Za-z0-9-]+$")


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
    reject_private_host(url)
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

