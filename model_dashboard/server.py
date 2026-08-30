from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable
from urllib.parse import unquote, urlparse
from urllib.request import urlopen  # 兼容既有测试与外部 monkeypatch

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
from .sources import (
    ARENA_DATASET_URL,
    ARENA_TOP_LIMIT,
    ARENA_WEBDEV_URL,
    ARTIFICIAL_ANALYSIS_URL,
    ENV_NAME,
    HEADER_NAME,
    LEADERBOARD_TOP_LIMIT,
    LLM_STATS_INDEX_URL,
    LLM_STATS_URL,
    MAX_BODY_BYTES,
    SameOriginRedirectHandler,
    fetch_json,
    fetch_text,
    normalize_arena_webdev_rows,
    normalize_artificial_analysis_html,
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
