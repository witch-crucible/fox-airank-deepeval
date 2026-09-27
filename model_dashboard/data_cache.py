"""本地实测结果的 SQLite 缓存与各数据源的过期状态汇总。

页面始终展示缓存数据（prompt-only）：缓存过期时仅提示并提供手动更新，
不自动刷新。本地缓存以 `runs/` 与 `cases/*/*/{case.json,TASK.md}` 的
文件指纹判定是否过期；三方榜单以最近一次快照的 `fetched_at` 判定。
"""

from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .domain import utc_now
from .local_results import CASES_ROOT, collect_local_results
from .storage import DashboardStore


#: 三方榜单来源（key, 展示名），顺序即页面展示顺序。
LEADERBOARD_SOURCES: tuple[tuple[str, str], ...] = (
    ("arena_webdev", "Arena"),
    ("artificial_analysis_model", "AA Model"),
    ("artificial_analysis_agent", "AA Agent"),
    ("llm_stats", "LLM Stats"),
)


def _stat_entries(root: Path, prefix: str) -> list[tuple[str, int, int]]:
    """收集 root 下全部文件的 (相对路径, 大小, mtime_ns)；只 stat，不读内容。"""
    entries: list[tuple[str, int, int]] = []
    for dirpath, _dirnames, filenames in os.walk(root):
        for name in filenames:
            path = Path(dirpath) / name
            try:
                stat = path.stat()
                relative = path.relative_to(root).as_posix()
            except (OSError, ValueError):
                continue
            entries.append((f"{prefix}:{relative}", stat.st_size, stat.st_mtime_ns))
    return entries


def local_fingerprint(runs_root: Path, cases_root: Path = CASES_ROOT) -> str:
    """对 collect_local_results 读取的全部输入做指纹。

    只哈希 `runs_root` 下带 `run.json` 的运行目录（跳过 `_archive` 等
    无运行记录的目录）以及 `cases_root/*/*/case.json`、`TASK.md` 的
    路径、大小与 mtime，不读取文件内容。
    """
    entries: list[tuple[str, int, int]] = []
    if runs_root.is_dir():
        for run_dir in sorted(runs_root.iterdir()):
            if not run_dir.is_dir() or not (run_dir / "run.json").is_file():
                continue
            entries.extend(_stat_entries(run_dir, "runs"))
    if cases_root.is_dir():
        for path in sorted(cases_root.glob("*/*/case.json")):
            entries.append(("cases:case.json:" + _relative(path, cases_root), *_file_stat(path)))
        for path in sorted(cases_root.glob("*/*/TASK.md")):
            entries.append(("cases:TASK.md:" + _relative(path, cases_root), *_file_stat(path)))
    digest = hashlib.sha256()
    for name, size, mtime_ns in sorted(entries):
        digest.update(f"{name}\0{size}\0{mtime_ns}\n".encode("utf-8"))
    return digest.hexdigest()


def _file_stat(path: Path) -> tuple[int, int]:
    try:
        stat = path.stat()
    except OSError:
        return (-1, -1)
    return (stat.st_size, stat.st_mtime_ns)


def _relative(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def cached_local_results(
    store: DashboardStore, runs_root: Path, *, refresh: bool = False,
) -> dict[str, Any]:
    """读取缓存的本地实测结果；无缓存或 `refresh=True` 时重建。"""
    if not refresh:
        cached = store.local_results_cache()
        if cached is not None:
            return cached["payload"]
    payload = collect_local_results(runs_root)
    store.save_local_results_cache(local_fingerprint(runs_root), payload)
    return payload


def _parse_timestamp(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed


def _format_hours(max_age_hours: float) -> str:
    return f"{max_age_hours:g}"


def cache_status(
    store: DashboardStore,
    runs_root: Path,
    max_age_hours: float,
    now: datetime | None = None,
) -> dict[str, Any]:
    """汇总本地缓存与三方榜单快照的过期状态。"""
    checked_at = now or datetime.now(timezone.utc)
    sources: list[dict[str, Any]] = []

    cached = store.local_results_cache()
    if cached is None:
        sources.append({
            "key": "local_benchmarks", "label": "本地实测", "kind": "local",
            "cached_at": None, "stale": True, "reason": "尚未建立缓存",
        })
    else:
        stale = cached["fingerprint"] != local_fingerprint(runs_root)
        sources.append({
            "key": "local_benchmarks", "label": "本地实测", "kind": "local",
            "cached_at": cached["built_at"], "stale": stale,
            "reason": "runs/ 有新的运行或评测结果" if stale else "",
        })

    for key, label in LEADERBOARD_SOURCES:
        fetched_at = store.latest_leaderboard_fetch(key)
        row: dict[str, Any] = {
            "key": key, "label": label, "kind": "leaderboard",
            "cached_at": fetched_at, "age_hours": None,
            "max_age_hours": max_age_hours, "stale": True, "reason": "尚未同步",
        }
        if fetched_at is not None:
            parsed = _parse_timestamp(fetched_at)
            if parsed is None:
                row["reason"] = "同步时间未知"
            else:
                age_hours = (checked_at - parsed).total_seconds() / 3600
                row["age_hours"] = round(age_hours, 2)
                row["stale"] = age_hours > max_age_hours
                row["reason"] = (
                    f"已超过 {_format_hours(max_age_hours)} 小时未同步" if row["stale"] else ""
                )
        sources.append(row)

    return {
        "checked_at": utc_now(),
        "stale_count": sum(1 for source in sources if source["stale"]),
        "sources": sources,
    }
