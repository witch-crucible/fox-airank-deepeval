from __future__ import annotations

import ipaddress
import base64
import json
import os
import re
import socket
import subprocess
from typing import Any, Callable
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
from .leaderboards import normalize_reasoning_effort, split_model_effort


MAX_BODY_BYTES = 2 * 1024 * 1024
MAX_BINARY_BYTES = 8 * 1024 * 1024
ARENA_WEBDEV_URL = "https://arena.ai/leaderboard/code/webdev"
ARENA_PRICE_CATALOG_URL = "https://raw.githubusercontent.com/lmarena/arena-catalog/main/data/scatterplot-data.json"
ARENA_PRICE_CATALOG_API_URL = "https://api.github.com/repos/lmarena/arena-catalog/contents/data/scatterplot-data.json"
ARENA_DATASET_URL = (
    "https://datasets-server.huggingface.co/rows"
    "?dataset=lmarena-ai%2Fleaderboard-dataset"
    "&config=webdev&split=latest&offset=0&length=100"
)
ARENA_DATASET_URL_TEMPLATE = (
    "https://datasets-server.huggingface.co/rows"
    "?dataset=lmarena-ai%2Fleaderboard-dataset"
    "&config=webdev&split=latest&offset={offset}&length={length}"
)
ARENA_PAGE_SIZE = 100
LEADERBOARD_TOP_LIMIT = 30
ARENA_TOP_LIMIT = LEADERBOARD_TOP_LIMIT
ARTIFICIAL_ANALYSIS_URL = "https://artificialanalysis.ai/agents/coding-agents"
ARTIFICIAL_ANALYSIS_MODELS_URL = "https://artificialanalysis.ai/models"
LLM_STATS_URL = "https://llm-stats.com/"
LLM_STATS_INDEX_URL = "https://api.zeroeval.com/leaderboard/indexes/compact?payloadVersion=2"
ENV_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
HEADER_NAME = re.compile(r"^[A-Za-z0-9-]+$")


def arena_price_key(value: Any) -> str:
    text = str(value or "").strip().casefold()
    text = re.sub(r"\s*\(codex[- ]harness\)\s*$", "", text)
    text = re.sub(r"(?:[-_ ](?:none|minimal|low|medium|high|xhigh|max|thinking)(?:[-_ ]\d+k)?|\s*\((?:none|minimal|low|medium|high|xhigh|max|thinking)\))$", "", text)
    return text.rstrip(" -_")


def model_effort(value: Any) -> str:
    return split_model_effort(value)[1]


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
    limit: int | None = None,
    prices: dict[str, dict[str, Any]] | None = None,
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
    if not ranked_rows:
        raise DashboardError("Arena WebDev 未返回 Overall 排名，本次未更新")
    if limit is not None:
        if limit <= 0:
            raise DashboardError("Arena WebDev 截断条数无效")
        selected = ranked_rows[:limit]
        if len(selected) < limit:
            raise DashboardError(f"Arena WebDev 返回的数据不足 {limit} 条，本次未更新")
    else:
        selected = ranked_rows

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
        price = (prices or {}).get(model_name.casefold()) or (prices or {}).get(arena_price_key(model_name), {})
        notes = f"Arena WebDev 第 {rank} 名"
        if organization:
            notes += f" · {organization}"
        models.append(
            normalize_model(
                {
                    "tool": "Arena WebDev",
                    "model": model_name,
                    "reasoning_effort": optional_text(row.get("reasoning_effort"), "reasoning_effort", 80) or model_effort(model_name),
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
                    "source_id": model_name.casefold(),
                    "organization": organization,
                    "license": license_name,
                    "input_price_per_m": price.get("input"),
                    "output_price_per_m": price.get("output"),
                    "price_source": price.get("source") or ARENA_WEBDEV_URL,
                },
            )
        )
    return models


def arena_dataset_url(offset: int, length: int = ARENA_PAGE_SIZE) -> str:
    return ARENA_DATASET_URL_TEMPLATE.format(offset=offset, length=length)


def merge_arena_pages(documents: list[Any]) -> dict[str, Any]:
    rows: list[Any] = []
    for document in documents:
        if not isinstance(document, dict) or not isinstance(document.get("rows"), list):
            raise DashboardError("Arena WebDev 分页数据格式无效")
        rows.extend(document["rows"])
    return {"rows": rows}


def normalize_arena_webdev_prices(document: str) -> dict[str, dict[str, float | None]]:
    """Extract model input/output prices from Arena's page payload when exposed."""
    if not isinstance(document, str):
        raise DashboardError("Arena WebDev 价格页面格式无效")
    prices: dict[str, dict[str, float | None]] = {}
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", document):
        try:
            value, _ = decoder.raw_decode(document, match.start())
        except json.JSONDecodeError:
            continue
        if not isinstance(value, dict):
            continue
        name = value.get("model_name") or value.get("modelName") or value.get("model") or value.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        input_value = value.get("input_price", value.get("inputPrice", value.get("input_cost")))
        output_value = value.get("output_price", value.get("outputPrice", value.get("output_cost")))
        try:
            input_price = float(input_value) if input_value not in (None, "", "N/A") else None
            output_price = float(output_value) if output_value not in (None, "", "N/A") else None
        except (TypeError, ValueError):
            continue
        if input_price is not None or output_price is not None:
            prices[name.strip().casefold()] = {"input": input_price, "output": output_price}
    return prices


def normalize_arena_price_catalog(document: Any) -> dict[str, dict[str, Any]]:
    if isinstance(document, dict) and isinstance(document.get("content"), str):
        try:
            document = json.loads(base64.b64decode(document["content"]).decode("utf-8"))
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise DashboardError("Arena 官方价格目录编码无效") from error
    if not isinstance(document, list):
        raise DashboardError("Arena 官方价格目录格式无效")
    prices: dict[str, dict[str, Any]] = {}
    for row in document:
        if not isinstance(row, dict):
            continue
        try:
            input_price = float(row["input_token_price"]) if row.get("input_token_price") not in (None, "") else None
            output_price = float(row["output_token_price"]) if row.get("output_token_price") not in (None, "") else None
        except (TypeError, ValueError):
            continue
        value = {
            "input": input_price,
            "output": output_price,
            "source": row.get("price_source"),
        }
        for field in ("model_api_name", "model_api_key", "name"):
            name = row.get(field)
            if isinstance(name, str) and name.strip():
                prices[name.strip().casefold()] = value
                prices.setdefault(arena_price_key(name), value)
    return prices


def _next_flight_data(document: str) -> str:
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
    return "".join(flight_data)


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
    decoded = _next_flight_data(document)
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
        terminal_bench_v2 = eval_scores.get("terminal-bench-v2.1")
        if terminal_bench_v2 is None:
            terminal_bench_v2 = eval_scores.get("terminal-bench-v2")
        terminal_bench_v4 = eval_scores.get("terminal-bench-v4")
        deep_swe_v1_1 = eval_scores.get("deep-swe-v1.1")
        component_scores = {
            "aa_deep_swe": deep_swe_v1_1 if deep_swe_v1_1 is not None else eval_scores.get("deep-swe"),
            "aa_deep_swe_v1_1": deep_swe_v1_1,
            "aa_terminal_bench_v2": terminal_bench_v2,
            "aa_terminal_bench_v4": terminal_bench_v4,
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
                    "reasoning_effort": model_effort(display["model"]),
                    "scores": scores,
                    "notes": f"Artificial Analysis Coding Agent Index 第 {rank} 名",
                },
                source={
                    "type": "artificial_analysis_agent",
                    "name": "Artificial Analysis Coding Agents",
                    "url": ARTIFICIAL_ANALYSIS_URL,
                    "fetched_at": fetched_at,
                    "rank": rank,
                    "source_id": row["id"],
                    "index_version": index_version,
                    "creator": display.get("creator", {}),
                    "agent_name": row.get("agentName") or display["agent"],
                    "provider": row.get("provider"),
                    "host_model_slug": row.get("hostModelSlug"),
                    "display_label": row.get("displayLabel"),
                    "variant_of": row.get("variantOf"),
                    "evaluation_datasets": [
                        {
                            "name": item.get("datasetIndexName"),
                            "dataset": item.get("refDatasetName"),
                            "weight": item.get("weight"),
                        }
                        for item in row.get("evals", [])
                        if isinstance(item, dict)
                    ],
                    "cost_usd_per_task": finite_number(mean.get("costUsd")),
                    "wall_time_seconds_per_task": finite_number(mean.get("agentWallTimeSec")),
                },
            )
        )
    return models


def finite_number(value: Any) -> float | int | None:
    """只保留有限数字，避免 NaN/Infinity 破坏 JSON 序列化。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return int(number) if number.is_integer() else round(number, 6)


def artificial_analysis_manifest_references(document: str) -> list[dict[str, str]]:
    decoded = _next_flight_data(document)
    decoder = json.JSONDecoder()
    references: list[dict[str, str]] = []
    for match in re.finditer(r'"manifest":', decoded):
        try:
            value, _ = decoder.raw_decode(decoded, match.end())
        except json.JSONDecodeError:
            continue
        if not isinstance(value, dict):
            continue
        path, key = value.get("path"), value.get("key")
        if isinstance(path, str) and path.startswith("/data/") and isinstance(key, str):
            reference = {"path": path, "key": key}
            if reference not in references:
                references.append(reference)
    if not references:
        raise DashboardError("Artificial Analysis Models 页面缺少全量数据 manifest")
    return references


def decrypt_artificial_analysis_manifest(payload: bytes, key: str) -> Any:
    script = r"""
const crypto = require('node:crypto');
const zlib = require('node:zlib');
let raw = '';
process.stdin.setEncoding('utf8');
process.stdin.on('data', chunk => raw += chunk);
process.stdin.on('end', () => {
  const input = JSON.parse(raw);
  const key = Buffer.from(input.key, 'hex');
  const encrypted = Buffer.from(input.payload, 'base64');
  const iv = crypto.createHash('sha256').update(key).digest().subarray(0, 12);
  const decipher = crypto.createDecipheriv('aes-256-gcm', key, iv);
  decipher.setAuthTag(encrypted.subarray(-16));
  const compressed = Buffer.concat([decipher.update(encrypted.subarray(0, -16)), decipher.final()]);
  process.stdout.write(zlib.gunzipSync(compressed, { maxOutputLength: 32 * 1024 * 1024 }));
});
"""
    request = json.dumps({"key": key, "payload": base64.b64encode(payload).decode("ascii")})
    try:
        result = subprocess.run(
            ["node", "-e", script],
            input=request,
            text=True,
            capture_output=True,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise DashboardError("无法解码 Artificial Analysis Models 全量数据") from error
    if result.returncode != 0:
        raise DashboardError("Artificial Analysis Models 全量数据解码失败")
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise DashboardError("Artificial Analysis Models manifest 不是有效 JSON") from error


def normalize_artificial_analysis_models_html(
    document: str,
    binary_fetcher: Callable[[str], bytes],
) -> list[dict[str, Any]]:
    if not isinstance(document, str) or "Intelligence Index" not in document:
        raise DashboardError("Artificial Analysis Models 页面缺少榜单数据")
    manifests = []
    for reference in artificial_analysis_manifest_references(document):
        payload = binary_fetcher(f"https://artificialanalysis.ai{reference['path']}")
        manifests.append(decrypt_artificial_analysis_manifest(payload, reference["key"]))

    canonical_rows: list[dict[str, Any]] | None = None
    host_rows: list[dict[str, Any]] = []
    for manifest in manifests:
        if isinstance(manifest, dict) and isinstance(manifest.get("models"), list):
            candidate = manifest["models"]
            if any(isinstance(row, dict) and "intelligenceIndex" in row for row in candidate):
                canonical_rows = candidate
        elif isinstance(manifest, list) and any(
            isinstance(row, dict) and row.get("modelId") and row.get("modelSlug") for row in manifest
        ):
            host_rows.extend(row for row in manifest if isinstance(row, dict))
    if not canonical_rows:
        raise DashboardError("Artificial Analysis Models manifest 缺少模型总榜")

    hosts_by_model: dict[str, list[dict[str, Any]]] = {}
    for row in host_rows:
        model_id = row.get("modelId")
        if isinstance(model_id, str):
            hosts_by_model.setdefault(model_id, []).append(row)

    version_match = re.search(r"Intelligence Index v([0-9.]+)", document)
    index_version = f"v{version_match.group(1)}" if version_match else "unknown"
    scored = [row for row in canonical_rows if isinstance(row, dict) and isinstance(row.get("intelligenceIndex"), (int, float))]
    scored.sort(key=lambda row: (-float(row["intelligenceIndex"]), str(row.get("id") or "")))
    rank_by_id = {str(row.get("id")): rank for rank, row in enumerate(scored, 1)}
    fetched_at = utc_now()
    models = []
    for row in canonical_rows:
        if not isinstance(row, dict):
            continue
        source_id = optional_text(row.get("id"), "id", 160)
        model_name = optional_text(row.get("name"), "name", 160)
        if not source_id or not model_name:
            continue
        creator = row.get("creator") if isinstance(row.get("creator"), dict) else {}
        variants = []
        for variant in hosts_by_model.get(source_id, []):
            cost = variant.get("intelligenceIndexCostPerTask")
            cost = cost.get("cost") if isinstance(cost, dict) else None
            speed = variant.get("timescaleData") if isinstance(variant.get("timescaleData"), dict) else {}
            variants.append(
                {
                    "id": variant.get("id"),
                    "slug": variant.get("slug"),
                    "host": variant.get("host"),
                    "name": variant.get("name"),
                    "input_price_per_m": variant.get("price1mInputTokens"),
                    "output_price_per_m": variant.get("price1mOutputTokens"),
                    "price_1m_blended": finite_number(variant.get("price1mBlended0To3To1")),
                    "cost_usd_per_task": finite_number(cost.get("total")) if isinstance(cost, dict) else None,
                    "intelligence_cost_per_task": finite_number(cost.get("total")) if isinstance(cost, dict) else None,
                    "intelligence_time_per_task": finite_number(variant.get("intelligenceIndexTimePerTask")),
                    "speed_tokens_per_second": speed.get("medianOutputSpeed"),
                    "prompt_speeds": variant.get("performanceByPromptType"),
                }
            )
        timescale = row.get("timescaleData") if isinstance(row.get("timescaleData"), dict) else {}
        intelligence = row.get("intelligenceIndex")
        terminal_bench = row.get("terminalBench40")
        intelligence_cost = row.get("intelligenceIndexCostPerTask")
        intelligence_cost = (
            intelligence_cost.get("cost") if isinstance(intelligence_cost, dict) else None
        )
        models.append(
            normalize_model(
                {
                    "tool": optional_text(creator.get("name"), "creator.name", 100) or "Artificial Analysis",
                    "model": model_name,
                    "reasoning_effort": optional_text(
                        (row.get("effort") or {}).get("slug") if isinstance(row.get("effort"), dict) else "",
                        "effort.slug",
                        80,
                    ),
                    "scores": {
                        "aa_model_intelligence": intelligence,
                        "aa_model_speed": timescale.get("medianOutputSpeed"),
                        "aa_model_cost_per_task": None,
                        "aa_model_terminal_bench_v4": round(float(terminal_bench) * 100, 4)
                        if isinstance(terminal_bench, (int, float))
                        else None,
                    },
                    "notes": "Artificial Analysis Models 全量榜",
                },
                source={
                    "type": "artificial_analysis_model",
                    "name": "Artificial Analysis Models",
                    "url": ARTIFICIAL_ANALYSIS_MODELS_URL,
                    "fetched_at": fetched_at,
                    "rank": rank_by_id.get(source_id),
                    "source_id": source_id,
                    "canonical_model_id": source_id,
                    "slug": row.get("slug"),
                    "release": row.get("release"),
                    "creator_name": creator.get("name"),
                    "index_version": index_version,
                    "is_estimated": row.get("intelligenceIndexIsEstimated") is True,
                    "price_1m_input": finite_number(row.get("price1mInputTokens")),
                    "price_1m_output": finite_number(row.get("price1mOutputTokens")),
                    "price_1m_blended": finite_number(row.get("price1mBlended0To3To1")),
                    "intelligence_cost_per_task": (
                        finite_number(intelligence_cost.get("total")) if isinstance(intelligence_cost, dict) else None
                    ),
                    "intelligence_time_per_task": finite_number(row.get("intelligenceIndexTimePerTask")),
                    "variants": variants,
                },
            )
        )
    if not models:
        raise DashboardError("Artificial Analysis Models 未解析到有效模型")
    return models


def normalize_llm_stats_indexes(
    document: Any,
    limit: int | None = None,
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
    if limit is not None and limit <= 0:
        raise DashboardError("LLM Stats 截断条数无效")
    selected = validated_rows[:limit] if limit is not None else validated_rows
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
                    "reasoning_effort": normalize_reasoning_effort(
                        optional_text(row.get("reasoning_effort"), "reasoning_effort", 80) or model_effort(model_name)
                    ),
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


def fetch_bytes(url: str, timeout: float = 20) -> bytes:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise DashboardError("数据文件 URL 必须是有效的 HTTPS 地址")
    request = Request(
        url,
        headers={"User-Agent": "Mozilla/5.0 model-capability-dashboard/1.0"},
        method="GET",
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            final_url = urlparse(response.geturl())
            if final_url.scheme != "https" or final_url.hostname != parsed.hostname:
                raise DashboardError("数据文件不能重定向到其他站点")
            payload = response.read(MAX_BINARY_BYTES + 1)
    except HTTPError as error:
        raise DashboardError(f"数据文件返回 HTTP {error.code}") from error
    except URLError as error:
        raise DashboardError(f"无法访问数据文件：{error.reason}") from error
    if len(payload) > MAX_BINARY_BYTES:
        raise DashboardError("数据文件超过 8 MB 限制")
    return payload
