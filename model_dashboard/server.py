from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import threading
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable, Sequence
from urllib.parse import parse_qs, unquote, urlparse
from urllib.request import urlopen  # 兼容既有测试与外部 monkeypatch

from .ai_insights import InsightConfig, normalize_goal, run_sensenova_insight, snapshot_hash, validate_analysis
from .data_cache import cache_status, cached_local_results
from .insight_data import build_insight_snapshot
from .efficiency import build_efficiency_overview, normalize_balance_weights
from .domain import (
    IMPORT_FIELDS,
    MODEL_TEST_WEIGHTS,
    SCORE_FIELDS,
    DashboardError,
    calculate_scores,
    get_path,
    normalize_agent_usage_entry,
    normalize_external_rows,
    normalize_model,
    optional_number,
    optional_text,
    parse_agent_usage_csv,
    utc_now,
)
from .benchmark import normalize_benchmark_models
from .pricing import check_source
from .leaderboards import build_agent_overview, build_model_overview
from .local_results import CASES_ROOT, RUNS_ROOT, resolve_pelican_preview
from .sources import (
    ARENA_DATASET_URL,
    ARENA_PAGE_SIZE,
    ARENA_PRICE_CATALOG_API_URL,
    ARENA_PRICE_CATALOG_URL,
    ARENA_TOP_LIMIT,
    ARENA_WEBDEV_URL,
    ARTIFICIAL_ANALYSIS_MODELS_URL,
    ARTIFICIAL_ANALYSIS_URL,
    ENV_NAME,
    HEADER_NAME,
    LEADERBOARD_TOP_LIMIT,
    LLM_STATS_INDEX_URL,
    LLM_STATS_URL,
    MAX_BODY_BYTES,
    SameOriginRedirectHandler,
    arena_dataset_url,
    fetch_bytes,
    fetch_json,
    fetch_text,
    merge_arena_pages,
    normalize_arena_webdev_rows,
    normalize_arena_webdev_prices,
    normalize_arena_price_catalog,
    normalize_artificial_analysis_html,
    normalize_artificial_analysis_models_html,
    normalize_llm_stats_indexes,
    reject_private_host,
    url_origin,
)
from .storage import DEFAULT_DATA_PATH, SEED_PATH, DashboardStore


ROOT = Path(__file__).resolve().parent
STATIC_ROOT = ROOT / "static"
INDEX_PATH = STATIC_ROOT / "index.html"
STATIC_CONTENT_TYPES = {
    ".svg": "image/svg+xml; charset=utf-8",
    ".png": "image/png",
    ".ico": "image/x-icon",
    ".webp": "image/webp",
}


#: 路由 handler 直接写响应，因此没有返回值。
RouteHandler = Callable[..., None]
CompiledRoutes = tuple[tuple[re.Pattern[str], tuple[str, ...], RouteHandler], ...]


def expected_case_ids(cases_root: Path = CASES_ROOT) -> set[str]:
    case_ids: set[str] = set()
    for path in cases_root.glob("*/*/case.json"):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        case_id = value.get("id") if isinstance(value, dict) else None
        if isinstance(case_id, str) and case_id:
            case_ids.add(case_id)
    return case_ids


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

    @property
    def binary_fetcher(self) -> Callable[[str], bytes]:
        return self.server.binary_fetcher  # type: ignore[attr-defined,no-any-return]

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        try:
            if not self._dispatch(GET_ROUTES, path):
                static_path = resolve_static_path(path)
                if static_path is not None:
                    content_type = STATIC_CONTENT_TYPES[static_path.suffix.casefold()]
                    self._send_bytes(HTTPStatus.OK, static_path.read_bytes(), content_type)
                    return
                self._send_json(HTTPStatus.NOT_FOUND, {"error": "页面不存在"})
        except DashboardError as error:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(error)})
        except Exception:
            self.log_error("处理请求时发生未预期错误")
            self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "服务器处理失败"})

    def _dispatch(self, routes: Sequence[tuple[Any, ...]], path: str, *args: Any) -> bool:
        """按路由表执行 handler；handler 自行写响应，未命中返回 False。"""
        for regex, names, handler in routes:
            matched = regex.match(path)
            if matched is None:
                continue
            handler(self, *args, *(matched.group(name) for name in names))
            return True
        return False

    # --- GET 路由 ---

    def _get_index(self) -> None:
        self._send_bytes(HTTPStatus.OK, INDEX_PATH.read_bytes(), "text/html; charset=utf-8")

    def _get_health(self) -> None:
        self._send_json(HTTPStatus.OK, {"status": "ok"})

    def _get_models(self) -> None:
        self._send_json(HTTPStatus.OK, self.dashboard_store.read())

    def _get_local_benchmarks(self) -> None:
        self._send_json(HTTPStatus.OK, self._local_results())

    def _local_results(self) -> dict[str, Any]:
        return cached_local_results(self.dashboard_store, self.server.runs_root)

    def _cache_status(self) -> dict[str, Any]:
        return cache_status(
            self.dashboard_store, self.server.runs_root, self.server.cache_max_age_hours,
        )

    def _get_cache_status(self) -> None:
        self._send_json(HTTPStatus.OK, self._cache_status())

    def _post_local_benchmarks_refresh(self, payload: Any) -> None:
        payload = cached_local_results(
            self.dashboard_store, self.server.runs_root, refresh=True,
        )
        self._send_json(HTTPStatus.OK, {
            "records": len(payload.get("records", [])),
            "warnings": payload.get("warnings", []),
            "status": self._cache_status(),
        })

    def _get_pricing_sources(self) -> None:
        self._send_json(HTTPStatus.OK, {"sources": self.dashboard_store.pricing_sources()})

    def _post_pricing_refresh(self, payload: Any) -> None:
        tool = optional_text(payload.get("tool"), "tool", 120) if isinstance(payload, dict) else ""
        fetcher = lambda url: check_source(url, text_fetcher=self.text_fetcher)  # noqa: E731
        report = self.dashboard_store.refresh_pricing_sources(fetcher, tool or None)
        report["sources"] = self.dashboard_store.pricing_sources()
        self._send_json(HTTPStatus.OK, report)

    def _insight_snapshot(self) -> dict[str, Any]:
        return build_insight_snapshot(
            self.dashboard_store.read(), self._local_results(),
            expected_case_ids(self.server.cases_root),
        )

    def _insight_response(self, snapshot: dict[str, Any]) -> dict[str, Any]:
        analysis = self.dashboard_store.latest_ai_insight()
        return {
            "config": self.server.insight_config.public(),
            "analysis": analysis,
            "stale": bool(analysis and analysis.get("snapshot_hash") != snapshot_hash(snapshot)),
            "busy": self.server.insight_lock.locked(),
            "coverage": snapshot["coverage"], "warnings": snapshot["warnings"],
        }

    def _get_ai_insights(self) -> None:
        self._send_json(HTTPStatus.OK, self._insight_response(self._insight_snapshot()))

    def _post_ai_insights(self, payload: Any) -> None:
        goal = normalize_goal(payload)
        if not self.server.insight_lock.acquire(blocking=False):
            self._send_json(HTTPStatus.CONFLICT, {"error": "已有 AI 分析正在生成，请稍后刷新结果"})
            return
        try:
            snapshot = self._insight_snapshot()
            if not snapshot["candidates"]:
                raise DashboardError("当前没有可分析的有效模型指标，请先同步榜单或完成本地实测")
            config = self.server.insight_config
            raw = self.server.insight_runner(goal, snapshot, config)
            analysis = validate_analysis(raw, snapshot, goal, config)
            self.dashboard_store.save_ai_insight(analysis)
        finally:
            self.server.insight_lock.release()
        self._send_json(HTTPStatus.OK, self._insight_response(self._insight_snapshot()))

    def _get_efficiency(self) -> None:
        params = self._query()
        scope = params.get("scope", ["focus"])[0]
        try:
            overview = build_efficiency_overview(
                self.dashboard_store.read()["models"],
                focus=params.get("focus", [None])[0],
                scope=scope,
                weights=normalize_balance_weights(params.get("weights", [None])[0]),
            )
        except DashboardError as error:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(error)})
            return
        self._send_json(HTTPStatus.OK, overview)

    def _query(self) -> dict[str, list[str]]:
        return parse_qs(urlparse(self.path).query)

    def _get_model_leaderboard(self) -> None:
        try:
            data = self.dashboard_store.read()
            local = self._local_results()
            overview = build_model_overview(
                data["models"],
                local.get("records", []),
                expected_case_ids(self.server.cases_root),
                aliases=data.get("model_aliases"),
                weights=self.dashboard_store.leaderboard_weights(data),
                recommendations=data.get("recommendations"),
            )
            overview["snapshots"] = {
                source: self.dashboard_store.leaderboard_snapshots(source)
                for source in ("arena_webdev", "artificial_analysis_model", "llm_stats")
            }
            overview["warnings"] = local.get("warnings", [])
            self._send_json(HTTPStatus.OK, overview)
        except DashboardError as error:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(error)})

    def _get_leaderboard_weights(self) -> None:
        try:
            self._send_json(HTTPStatus.OK, {"weights": self.dashboard_store.leaderboard_weights()})
        except DashboardError as error:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(error)})

    def _get_agent_leaderboard(self) -> None:
        try:
            data = self.dashboard_store.read()
            overview = build_agent_overview(
                data["models"],
                recommendations=data.get("recommendations"),
                aliases=data.get("model_aliases"),
            )
            overview["snapshots"] = self.dashboard_store.leaderboard_snapshots("artificial_analysis_agent")
            self._send_json(HTTPStatus.OK, overview)
        except DashboardError as error:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(error)})

    def _get_leaderboard_comparison(self, source_type: str) -> None:
        params = self._query()
        try:
            self._send_json(
                HTTPStatus.OK,
                self.dashboard_store.leaderboard_comparison(
                    source_type,
                    params.get("snapshot", [None])[0],
                    params.get("compare", [None])[0],
                ),
            )
        except DashboardError as error:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(error)})

    def _get_leaderboard_snapshots(self, source_type: str) -> None:
        try:
            limit = int(self._query().get("limit", ["50"])[0])
        except ValueError as error:
            raise DashboardError("快照条数无效") from error
        try:
            self._send_json(
                HTTPStatus.OK,
                {"snapshots": self.dashboard_store.leaderboard_snapshots(source_type, limit)},
            )
        except DashboardError as error:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(error)})

    def _get_recommendation_releases(self) -> None:
        try:
            limit = int(self._query().get("limit", ["50"])[0])
            self._send_json(HTTPStatus.OK, self.dashboard_store.recommendation_releases(limit))
        except (DashboardError, ValueError) as error:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(error)})

    def _get_pelican_preview(self, run: str, tool: str) -> None:
        preview = resolve_pelican_preview(self.server.runs_root, unquote(run), unquote(tool))
        if preview is None:
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "未找到鹈鹕作品"})
            return
        try:
            content = preview.read_bytes()
        except OSError:
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "作品文件无法读取"})
            return
        self._send_bytes(HTTPStatus.OK, content, "text/html; charset=utf-8", preview=True)

    # --- POST 路由 ---

    def _post_model(self, payload: Any) -> None:
        model = self.dashboard_store.add_model(payload)
        self._send_json(HTTPStatus.CREATED, {"model": model})

    def _post_agent_usage(self, payload: Any) -> None:
        entry, created = self.dashboard_store.upsert_agent_usage(payload)
        self._send_json(HTTPStatus.CREATED if created else HTTPStatus.OK, {"entry": entry, "created": created})

    def _post_recommendations(self, payload: Any) -> None:
        recommendations = self.dashboard_store.save_recommendations(payload)
        self._send_json(HTTPStatus.OK, {"recommendations": recommendations})

    def _post_recommendation_publish(self, payload: Any) -> None:
        if not isinstance(payload, dict):
            raise DashboardError("请求数据必须是对象")
        release = self.dashboard_store.publish_recommendations(payload.get("note", ""))
        self._send_json(HTTPStatus.CREATED, {"release": release})

    def _post_model_alias(self, payload: Any) -> None:
        if not isinstance(payload, dict):
            raise DashboardError("请求数据必须是对象")
        alias = self.dashboard_store.save_model_alias(payload.get("alias"), payload.get("canonical"))
        self._send_json(HTTPStatus.OK, {"alias": alias})

    def _post_leaderboard_weights(self, payload: Any) -> None:
        if not isinstance(payload, dict):
            raise DashboardError("请求数据必须是对象")
        weights = self.dashboard_store.save_leaderboard_weights(payload.get("weights"))
        self._send_json(HTTPStatus.OK, {"weights": weights})

    def _post_model_archive(self, payload: Any, model_id: str) -> None:
        # 路径段保留百分号编码，模型 ID 可能含空格或括号，落库前必须先解码。
        model_id = unquote(model_id)
        if not model_id:
            raise DashboardError("模型 ID 不能为空")
        if not isinstance(payload, dict) or not isinstance(payload.get("archived"), bool):
            raise DashboardError("archived 必须是布尔值")
        model = self.dashboard_store.set_model_archived(model_id, payload["archived"])
        self._send_json(HTTPStatus.OK, {"model": model})

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        try:
            payload = self._read_json_body()
        except DashboardError as error:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": str(error)})
            return
        try:
            if not self._dispatch(POST_ROUTES, path, payload):
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
        self._send_json(HTTPStatus.OK, self._sync_leaderboard("arena_webdev"))

    def _fetch_arena_webdev(self) -> list[dict[str, Any]]:
        first = self.json_fetcher(ARENA_DATASET_URL, None)
        if not isinstance(first, dict) or not isinstance(first.get("rows"), list):
            raise DashboardError("Arena WebDev 数据格式无效")
        documents = [first]
        total = first.get("num_rows_total")
        if isinstance(total, int) and total > len(first["rows"]):
            for offset in range(len(first["rows"]), total, ARENA_PAGE_SIZE):
                documents.append(self.json_fetcher(arena_dataset_url(offset), None))
        document = merge_arena_pages(documents)
        prices = {}
        if self.server.arena_price_fetch_enabled:  # type: ignore[attr-defined]
            try:
                prices.update(normalize_arena_price_catalog(self.json_fetcher(ARENA_PRICE_CATALOG_URL, None)))
            except DashboardError:
                try:
                    prices.update(normalize_arena_price_catalog(self.json_fetcher(ARENA_PRICE_CATALOG_API_URL, None)))
                except DashboardError:
                    pass
            try:
                prices.update(normalize_arena_webdev_prices(self.text_fetcher(ARENA_WEBDEV_URL)))
            except DashboardError:
                pass
        return normalize_arena_webdev_rows(document, prices=prices)

    def _import_artificial_analysis(self, payload: Any) -> None:
        if not isinstance(payload, dict):
            raise DashboardError("请求数据必须是对象")
        self._send_json(HTTPStatus.OK, self._sync_leaderboard("artificial_analysis_agent"))

    def _import_artificial_analysis_models(self, payload: Any) -> None:
        if not isinstance(payload, dict):
            raise DashboardError("请求数据必须是对象")
        self._send_json(HTTPStatus.OK, self._sync_leaderboard("artificial_analysis_model"))

    def _import_llm_stats(self, payload: Any) -> None:
        if not isinstance(payload, dict):
            raise DashboardError("请求数据必须是对象")
        self._send_json(HTTPStatus.OK, self._sync_leaderboard("llm_stats"))

    def _sync_leaderboard(self, source: str) -> dict[str, Any]:
        if source == "arena_webdev":
            models = self._fetch_arena_webdev()
            result = self.dashboard_store.sync_arena_webdev(models)
        elif source == "artificial_analysis_agent":
            models = normalize_artificial_analysis_html(self.text_fetcher(ARTIFICIAL_ANALYSIS_URL))
            result = self.dashboard_store.sync_artificial_analysis(models)
        elif source == "artificial_analysis_model":
            models = normalize_artificial_analysis_models_html(
                self.text_fetcher(ARTIFICIAL_ANALYSIS_MODELS_URL), self.binary_fetcher
            )
            result = self.dashboard_store.sync_artificial_analysis_models(models)
        elif source == "llm_stats":
            models = normalize_llm_stats_indexes(self.json_fetcher(LLM_STATS_INDEX_URL, None))
            result = self.dashboard_store.sync_llm_stats(models)
        else:
            raise DashboardError("未知榜单来源")
        return {**result, "received": len(models)}

    def _legion_coverage(self) -> dict[str, Any]:
        data = self.dashboard_store.read()
        options = {"recommendations": data.get("recommendations"), "aliases": data.get("model_aliases")}
        models = build_model_overview(data["models"], [], set(), **options)["models"]
        agents = build_agent_overview(data["models"], **options)["agents"]
        missing_models = []
        for row in models:
            if not row.get("legion", {}).get("matched"):
                continue
            missing = [
                source for source in ("artificial_analysis_model", "arena_webdev", "llm_stats")
                if not isinstance(row["sources"].get(source), dict)
                or row["sources"][source].get("raw_score") is None
            ]
            if missing:
                missing_models.append({"model": row["model"], "reasoning_effort": row["reasoning_effort"], "sources": missing})
        missing_agents = [
            {"tool": row["agent"]["tool"], "model": row["agent"]["model"], "reasoning_effort": row["reasoning_effort"]}
            for row in agents if row.get("legion", {}).get("matched")
            and (row["agent"].get("scores") or {}).get("artificial_analysis_index") is None
        ]
        return {"missing_models": missing_models, "missing_agents": missing_agents}

    def _refresh_legion_leaderboards(self, payload: Any) -> None:
        if not isinstance(payload, dict):
            raise DashboardError("请求数据必须是对象")
        coverage = self._legion_coverage()
        needed = {source for row in coverage["missing_models"] for source in row["sources"]}
        if coverage["missing_agents"]:
            needed.add("artificial_analysis_agent")
        results: list[dict[str, Any]] = []
        # Fetch each missing source once from its complete catalog. Keeping complete
        # snapshots preserves the min-max score population and the published ranks.
        for source in ("artificial_analysis_model", "arena_webdev", "llm_stats", "artificial_analysis_agent"):
            if source not in needed:
                continue
            try:
                results.append({"source": source, "status": "updated", **self._sync_leaderboard(source)})
            except DashboardError as error:
                results.append({"source": source, "status": "failed", "error": str(error)})
        # 重新计算：返回的必须是补齐之后仍然缺失的清单，而不是同步前的快照。
        self._send_json(HTTPStatus.OK, {"sources": results, **self._legion_coverage()})

    def _import_benchmark(self, payload: Any) -> None:
        if not isinstance(payload, dict):
            raise DashboardError("请求数据必须是对象")
        run_dir = payload.get("run_dir")
        if not isinstance(run_dir, str) or not run_dir.strip():
            raise DashboardError("run_dir 不能为空")
        models = normalize_benchmark_models(Path(run_dir.strip()))
        result = self.dashboard_store.sync_benchmark(models)
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

    def _send_bytes(self, status: HTTPStatus, data: bytes, content_type: str, *, preview: bool = False) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        policy = "default-src 'self'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'self'; img-src 'self' data:; base-uri 'none'; form-action 'self'"
        if preview:
            policy = "sandbox allow-scripts; default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; connect-src 'none'; base-uri 'none'; form-action 'none'; frame-ancestors 'self'"
            self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", policy)
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format: str, *args: Any) -> None:
        print(f"[{self.log_date_time_string()}] {format % args}")


def compile_routes(routes: dict[str, RouteHandler]) -> CompiledRoutes:
    """把 ``/api/models/{model_id}/archive`` 形式的路由编译成匹配表。

    占位符只匹配单个路径段，因此 ``/api/leaderboards/a/b`` 不会被
    ``/api/leaderboards/{source_type}`` 抢先命中。
    """
    compiled: list[tuple[re.Pattern[str], tuple[str, ...], RouteHandler]] = []
    for pattern, handler in routes.items():
        names: list[str] = []
        segments: list[str] = []
        for segment in pattern.split("/"):
            if segment.startswith("{") and segment.endswith("}"):
                name = segment[1:-1]
                names.append(name)
                segments.append(f"(?P<{name}>[^/]+)")
            else:
                segments.append(re.escape(segment))
        compiled.append((re.compile("^" + "/".join(segments) + "$"), tuple(names), handler))
    return tuple(compiled)


GET_ROUTES = compile_routes(
    {
        "/": DashboardHandler._get_index,
        "/api/health": DashboardHandler._get_health,
        "/api/models": DashboardHandler._get_models,
        "/api/local-benchmarks": DashboardHandler._get_local_benchmarks,
        "/api/cache/status": DashboardHandler._get_cache_status,
        "/api/ai-insights": DashboardHandler._get_ai_insights,
        "/api/efficiency": DashboardHandler._get_efficiency,
        "/api/leaderboards/models": DashboardHandler._get_model_leaderboard,
        "/api/leaderboards/weights": DashboardHandler._get_leaderboard_weights,
        "/api/leaderboards/agents": DashboardHandler._get_agent_leaderboard,
        "/api/leaderboards/{source_type}": DashboardHandler._get_leaderboard_comparison,
        "/api/leaderboards/{source_type}/snapshots": DashboardHandler._get_leaderboard_snapshots,
        "/api/recommendations/releases": DashboardHandler._get_recommendation_releases,
        "/api/local-benchmarks/preview/{run}/{tool}": DashboardHandler._get_pelican_preview,
        "/api/pricing/sources": DashboardHandler._get_pricing_sources,
    }
)

POST_ROUTES = compile_routes(
    {
        "/api/cache/local-benchmarks/refresh": DashboardHandler._post_local_benchmarks_refresh,
        "/api/leaderboards/legion/refresh": DashboardHandler._refresh_legion_leaderboards,
        "/api/models": DashboardHandler._post_model,
        "/api/models/{model_id}/archive": DashboardHandler._post_model_archive,
        "/api/agent-usage": DashboardHandler._post_agent_usage,
        "/api/agent-usage/import": DashboardHandler._import_agent_usage,
        "/api/recommendations": DashboardHandler._post_recommendations,
        "/api/ai-insights": DashboardHandler._post_ai_insights,
        "/api/recommendations/publish": DashboardHandler._post_recommendation_publish,
        "/api/leaderboards/model-aliases": DashboardHandler._post_model_alias,
        "/api/leaderboards/weights": DashboardHandler._post_leaderboard_weights,
        "/api/import": DashboardHandler._import,
        "/api/import/arena-webdev": DashboardHandler._import_arena_webdev,
        "/api/import/artificial-analysis": DashboardHandler._import_artificial_analysis,
        "/api/import/artificial-analysis-models": DashboardHandler._import_artificial_analysis_models,
        "/api/import/llm-stats": DashboardHandler._import_llm_stats,
        "/api/import/benchmark": DashboardHandler._import_benchmark,
        "/api/pricing/refresh": DashboardHandler._post_pricing_refresh,
    }
)


def create_server(
    host: str,
    port: int,
    data_path: Path = DEFAULT_DATA_PATH,
    json_fetcher: Callable[[str, Any], Any] = fetch_json,
    text_fetcher: Callable[[str], str] = fetch_text,
    binary_fetcher: Callable[[str], bytes] = fetch_bytes,
    runs_root: Path = RUNS_ROOT,
    cases_root: Path = CASES_ROOT,
    insight_runner: Callable[[str, dict[str, Any], InsightConfig], Any] = run_sensenova_insight,
    insight_config: InsightConfig | None = None,
    cache_max_age_hours: float = 24,
) -> ThreadingHTTPServer:
    config = insight_config if insight_config is not None else InsightConfig.from_env()
    server = ThreadingHTTPServer((host, port), DashboardHandler)
    server.store = DashboardStore(data_path=data_path)  # type: ignore[attr-defined]
    server.json_fetcher = json_fetcher  # type: ignore[attr-defined]
    server.text_fetcher = text_fetcher  # type: ignore[attr-defined]
    server.binary_fetcher = binary_fetcher  # type: ignore[attr-defined]
    server.arena_price_fetch_enabled = json_fetcher is fetch_json or text_fetcher is not fetch_text  # type: ignore[attr-defined]
    server.runs_root = runs_root  # type: ignore[attr-defined]
    server.cases_root = cases_root  # type: ignore[attr-defined]
    server.insight_config = config  # type: ignore[attr-defined]
    server.insight_runner = insight_runner  # type: ignore[attr-defined]
    server.insight_lock = threading.Lock()  # type: ignore[attr-defined]
    server.cache_max_age_hours = cache_max_age_hours  # type: ignore[attr-defined]
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
    parser.add_argument(
        "--cache-max-age-hours",
        type=float,
        default=24,
        help="三方榜单快照视为过期的最大时长（小时，需大于 0）",
    )
    args = parser.parse_args(argv)
    if args.cache_max_age_hours <= 0:
        parser.error("缓存最大时效（--cache-max-age-hours）必须大于 0")
    if args.reload:
        run_with_reload(
            [
                "--host",
                args.host,
                "--port",
                str(args.port),
                "--data",
                str(args.data),
                "--cache-max-age-hours",
                str(args.cache_max_age_hours),
            ]
        )
        return

    server = create_server(args.host, args.port, args.data, cache_max_age_hours=args.cache_max_age_hours)
    dashboard_url = f"http://{args.host}:{server.server_port}"
    print(f"模型能力台：{dashboard_url}（按住 ⌘ 并双击打开）")
    print(f"本地数据：{args.data}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n看板已停止")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
