"""智力基线：以 AA 快照中 DeepSeek Flash 最新版本的 Intelligence Index 为参照线。"""

from __future__ import annotations

import math
import re
from typing import Any

INTELLIGENCE_METRIC = "aa_model_intelligence"
BELOW_BASELINE_LABEL = "差"
AT_BASELINE_LABEL = "达标"

_BASELINE_PATTERN = re.compile(r"deepseek", re.I)
_BASELINE_SERIES = re.compile(r"flash", re.I)
_BASELINE_EXCLUDED = re.compile(r"vision|image|audio|tts|ocr", re.I)
_VERSION = re.compile(r"(?:[Vv]|version\s*)(\d+)(?:[.\-_](\d+))?", re.UNICODE)
_DATE_SUFFIX = re.compile(r"(?<!\d)(\d{4})(?!\d)")


def _finite(value: Any) -> float | None:
    """有限数值判定；本模块保持零内部依赖，避免 leaderboards → sources → leaderboards 的循环导入。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _row_name(model: dict[str, Any]) -> str:
    source = model.get("source") if isinstance(model.get("source"), dict) else {}
    release = source.get("release") if isinstance(source.get("release"), dict) else {}
    return " ".join(
        str(value)
        for value in (model.get("model"), release.get("name"), release.get("slug"), source.get("slug"))
        if value
    )


def _version_key(name: str) -> tuple[int, int, int]:
    """把「V4.1 Flash」「V4 Flash 0420」这类名称解析成可比较的版本序。"""
    version = _VERSION.search(name)
    major = int(version.group(1)) if version else -1
    minor = int(version.group(2)) if version and version.group(2) else 0
    date = _DATE_SUFFIX.search(name)
    return (major, minor, int(date.group(1)) if date else 0)


def intelligence_baseline(models: Any) -> dict[str, Any] | None:
    """取 DeepSeek Flash 最新版本中智力最高的配置作为基线；无 AA 数据时返回 None。"""
    candidates: list[tuple[tuple[int, int, int], float, int, dict[str, Any]]] = []
    for index, model in enumerate(models if isinstance(models, list) else []):
        if not isinstance(model, dict) or model.get("archived") is True:
            continue
        source = model.get("source") if isinstance(model.get("source"), dict) else {}
        if str(source.get("type") or "") != "artificial_analysis_model":
            continue
        name = _row_name(model)
        if not (_BASELINE_PATTERN.search(name) and _BASELINE_SERIES.search(name)):
            continue
        if _BASELINE_EXCLUDED.search(name):
            continue
        intelligence = _finite((model.get("scores") or {}).get(INTELLIGENCE_METRIC))
        if intelligence is None:
            continue
        candidates.append((_version_key(name), float(intelligence), index, model))
    if not candidates:
        return None
    newest = max(candidate[0] for candidate in candidates)
    family = [candidate for candidate in candidates if candidate[0] == newest]
    _, intelligence, _, model = max(family, key=lambda candidate: (candidate[1], -candidate[2]))
    source = model.get("source") if isinstance(model.get("source"), dict) else {}
    url = str(source.get("url") or "")
    slug = str(source.get("slug") or "")
    return {
        "label": "智力基线",
        "standard": f"{INTELLIGENCE_METRIC} 低于 DeepSeek Flash 最新版本的配置判为「{BELOW_BASELINE_LABEL}」",
        "model": str(model.get("model") or ""),
        "reasoning_effort": str(model.get("reasoning_effort") or ""),
        "intelligence": round(float(intelligence), 4),
        "configurations": len(family),
        "slug": slug or None,
        "url": f"{url.rstrip('/')}/{slug}" if url and slug else (url or None),
        "fetched_at": str(source.get("fetched_at") or ""),
    }


def grade_intelligence(value: Any, baseline: dict[str, Any] | None) -> dict[str, Any] | None:
    """与基线比较；任一侧缺值时返回 None，不按 0 分处理。"""
    numeric = _finite(value)
    reference = (baseline or {}).get("intelligence")
    if numeric is None or not isinstance(reference, (int, float)):
        return None
    delta = round(float(numeric) - float(reference), 4)
    return {
        "grade": BELOW_BASELINE_LABEL if delta < 0 else AT_BASELINE_LABEL,
        "delta": delta,
        "intelligence": round(float(numeric), 4),
    }
