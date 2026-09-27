"""归档历史 run：默认只预演，显式 --apply 才移动目录。

每个 run 都包含完整的隔离工作区、代理日志和评测产物，`runs/` 会持续单向增长。
归档把整个 run 目录移动到 `runs/_archive/<run-id>`：不删除任何文件，随时可移回，
且 `_archive` 自身不含 `deepeval/`，因此历史报告与稳定性分析会自动跳过已归档的 run。
"""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Sequence

ARCHIVE_DIR_NAME = "_archive"


@dataclass(frozen=True)
class ArchiveItem:
    """一条归档计划：源目录、目标目录和被选中的原因。"""

    run_id: str
    source: Path
    destination: Path
    reason: str


def _safe_component(value: Any) -> bool:
    return (
        isinstance(value, str)
        and bool(value)
        and value not in {".", ".."}
        and not any(character in value for character in ("/", "\\", "\x00"))
    )


def _read_manifest(run_dir: Path) -> dict[str, Any]:
    manifest_path = run_dir / "run.json"
    if not manifest_path.is_file():
        return {}
    try:
        value = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def run_created_at(run_dir: Path) -> datetime | None:
    """优先使用 run.json 的 created_at，缺失时回退到目录修改时间。"""
    created = _read_manifest(run_dir).get("created_at")
    if isinstance(created, str) and created:
        try:
            parsed = datetime.fromisoformat(created)
        except ValueError:
            parsed = None
        if parsed is not None:
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    try:
        return datetime.fromtimestamp(run_dir.stat().st_mtime, tz=timezone.utc)
    except OSError:
        return None


def directory_size(path: Path) -> int:
    """统计目录占用字节数；无法读取的文件跳过，避免个别坏文件中断统计。"""
    total = 0
    for root, _directories, files in os.walk(path):
        for name in files:
            try:
                total += (Path(root) / name).stat().st_size
            except OSError:
                continue
    return total


def list_runs(runs_root: Path) -> list[Path]:
    """列出可归档的 run 目录（必须含 run.json，且排除归档目录本身）。"""
    if not runs_root.is_dir():
        return []
    return sorted(
        path
        for path in runs_root.iterdir()
        if path.is_dir() and path.name != ARCHIVE_DIR_NAME and (path / "run.json").is_file()
    )


def plan_archive(
    runs_root: Path,
    run_ids: Sequence[str] = (),
    older_than_days: int | None = None,
    keep: int | None = None,
) -> list[ArchiveItem]:
    """计算归档计划。多个筛选条件同时生效（AND）；不传任何条件时归档全部 run。

    只做计算，不触碰文件系统，便于 --apply 之前完整预演。
    """
    if not runs_root.is_dir():
        raise ValueError(f"运行目录不存在: {runs_root}")
    if older_than_days is not None and (not isinstance(older_than_days, int) or older_than_days < 0):
        raise ValueError("--older-than 必须是非负整数")
    if keep is not None and (not isinstance(keep, int) or keep < 0):
        raise ValueError("--keep 必须是非负整数")

    candidates = list_runs(runs_root)
    by_name = {path.name: path for path in candidates}
    if run_ids:
        unknown = [name for name in run_ids if name not in by_name]
        if unknown:
            raise ValueError(f"找不到 run: {', '.join(sorted(unknown))}")
        candidates = [by_name[name] for name in dict.fromkeys(run_ids)]

    kept: set[str] = set()
    if keep is not None:
        ordered = sorted(
            list_runs(runs_root),
            key=lambda path: (run_created_at(path) or datetime.min.replace(tzinfo=timezone.utc), path.name),
            reverse=True,
        )
        kept = {path.name for path in ordered[:keep]}

    now = datetime.now(timezone.utc)
    archive_root = runs_root / ARCHIVE_DIR_NAME
    items: list[ArchiveItem] = []
    for path in candidates:
        if path.name in kept:
            continue
        reasons: list[str] = []
        if run_ids and path.name in set(run_ids):
            reasons.append("命令行显式指定")
        if older_than_days is not None:
            created = run_created_at(path)
            if created is None:
                continue
            age_days = (now - created).days
            if age_days < older_than_days:
                continue
            reasons.append(f"创建于 {older_than_days} 天前或更早（约 {age_days} 天）")
        if keep is not None:
            reasons.append(f"不在最新保留的 {keep} 个 run 内")
        if not reasons:
            reasons.append("未指定筛选条件，归档全部 run")
        destination = archive_root / path.name
        if destination.exists():
            raise ValueError(f"归档目标已存在，请先处理: {destination}")
        items.append(ArchiveItem(path.name, path, destination, "；".join(reasons)))
    return items


def apply_archive(items: Sequence[ArchiveItem]) -> list[Path]:
    """执行归档移动；目标必须位于归档目录内，避免误移动到 runs/ 之外。"""
    moved: list[Path] = []
    for item in items:
        archive_root = item.source.parent / ARCHIVE_DIR_NAME
        if item.destination.parent.resolve() != archive_root.resolve():
            raise ValueError(f"归档目标超出归档目录: {item.destination}")
        if not item.source.is_dir():
            raise ValueError(f"run 目录已不存在: {item.source}")
        if item.destination.exists():
            raise ValueError(f"归档目标已存在: {item.destination}")
        item.destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(item.source), str(item.destination))
        moved.append(item.destination)
    return moved


def restore_run(runs_root: Path, run_id: str) -> Path:
    """把已归档的 run 移回 runs/ 根目录；目标已存在时拒绝覆盖。"""
    if not _safe_component(run_id):
        raise ValueError(f"非法的 run id: {run_id}")
    source = runs_root / ARCHIVE_DIR_NAME / run_id
    if not source.is_dir():
        raise ValueError(f"归档目录中不存在该 run: {source}")
    destination = runs_root / run_id
    if destination.exists():
        raise ValueError(f"运行目录已存在，拒绝覆盖: {destination}")
    shutil.move(str(source), str(destination))
    return destination


def describe_plan(items: Sequence[ArchiveItem]) -> str:
    if not items:
        return "没有符合筛选条件的 run。"
    lines = [f"将要归档 {len(items)} 个 run（目标目录 runs/{ARCHIVE_DIR_NAME}）："]
    total = 0
    for item in items:
        size = directory_size(item.source)
        total += size
        lines.append(f"  - {item.run_id}：{size / 1024 / 1024:.1f} MB，{item.reason}")
    lines.append(f"合计 {total / 1024 / 1024:.1f} MB（仅移动到归档目录，不删除任何文件）。")
    return "\n".join(lines)
