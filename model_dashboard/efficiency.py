from __future__ import annotations

import math
import re
from typing import Any, Iterable

from .domain import DashboardError
from .sources import finite_number

ARTIFICIAL_ANALYSIS_AGENTS_URL = "https://artificialanalysis.ai/agents/coding-agents"
ARTIFICIAL_ANALYSIS_MODELS_URL = "https://artificialanalysis.ai/models"

# 关注项取自 Artificial Analysis 页面分享链接的选中集合（agents= / models= 参数）。
AA_AGENT_FOCUS = (
    "claude-code-opus-5-5-max",
    "claude-code-fable-5-1-max-with-fallback",
    "codex-gpt-6-sol-max",
    "codex-gpt-6-luna-max",
    "codex-gpt-6-astra-max",
    "muse-code-muse-spark-1-3-max",
    "grok-build-grok-4-6-xhigh",
    "grok-build-grok-4-7-xhigh",
    "kimi-code-cli-kimi-k3",
)
AA_MODEL_FOCUS = (
    "mimo-v2-6-pro",
    "gpt-6-astra",
    "claude-opus-5-5",
    "claude-fable-5-1",
    "gpt-6-sol-high",
    "grok-4-7",
    "gpt-6-luna",
    "gpt-6-sol-medium",
    "gpt-6-luna-high",
    "qwen3-8-max",
    "hy3",
    "k2-horizon-375b-a23b",
    "gpt-6-sol",
    "grok-4-6",
    "glm-5-3",
    "deepseek-v4-1-flash",
    "gpt-6-astra-high",
    "gpt-5-5-pro",
    "gpt-6-astra-medium",
    "claude-opus-5-5-medium",
    "claude-opus-5-5-high",
    "kimi-k3",
    "gpt-6-astra-low",
)

DEFAULT_FOCUS: dict[str, tuple[str, ...]] = {
    "artificial_analysis_agent": AA_AGENT_FOCUS,
    "artificial_analysis_model": AA_MODEL_FOCUS,
}

EFFICIENCY_CHARTS: tuple[dict[str, Any], ...] = (
    {
        "key": "agent_cost",
        "source_type": "artificial_analysis_agent",
        "title": "Coding Agent 指数 vs 单任务成本",
        "subtitle": "Artificial Analysis Coding Agent Index 与每任务平均 API 成本；越靠左上越强且越省。",
        "source_url": ARTIFICIAL_ANALYSIS_AGENTS_URL,
        "x_field": "cost_usd_per_task",
        "x_label": "单任务成本",
        "x_unit": "USD",
        "x_lower_is_better": True,
        "y_score": "artificial_analysis_index",
        "y_label": "Coding Agent Index",
        "y_unit": "分",
    },
    {
        "key": "model_cost",
        "source_type": "artificial_analysis_model",
        "title": "智能度 vs 单任务成本",
        "subtitle": "Intelligence Index 与 Intelligence Index 任务的加权平均成本（USD）；越靠左上越强且越省。",
        "source_url": ARTIFICIAL_ANALYSIS_MODELS_URL,
        "x_field": "intelligence_cost_per_task",
        "x_label": "单任务成本",
        "x_unit": "USD",
        "x_lower_is_better": True,
        "y_score": "aa_model_intelligence",
        "y_label": "Intelligence Index",
        "y_unit": "分",
    },
    {
        "key": "model_time",
        "source_type": "artificial_analysis_model",
        "title": "智能度 vs 单任务耗时",
        "subtitle": "Intelligence Index 与 Intelligence Index 任务的加权平均耗时；越靠左上越强且越快。",
        "source_url": ARTIFICIAL_ANALYSIS_MODELS_URL,
        "x_field": "intelligence_time_per_task",
        "x_label": "单任务耗时",
        "x_unit": "秒",
        "x_lower_is_better": True,
        "y_score": "aa_model_intelligence",
        "y_label": "Intelligence Index",
        "y_unit": "分",
    },
)

EFFICIENCY_SCOPES = ("focus", "all")

# 三维平衡：能力越高越好、单任务成本越低越好、单任务耗时越低越好。
BALANCE_METRICS = ("capability", "cost", "time")
DEFAULT_BALANCE_WEIGHTS = {"capability": 0.4, "cost": 0.3, "time": 0.3}
BALANCE_PRESETS = (
    {"key": "balanced", "label": "均衡", "weights": {"capability": 0.4, "cost": 0.3, "time": 0.3}},
    {"key": "capability", "label": "能力优先", "weights": {"capability": 0.6, "cost": 0.2, "time": 0.2}},
    {"key": "cost", "label": "省钱优先", "weights": {"capability": 0.2, "cost": 0.5, "time": 0.3}},
    {"key": "speed", "label": "省时优先", "weights": {"capability": 0.2, "cost": 0.3, "time": 0.5}},
)
BALANCE_METRIC_FIELDS = {
    "artificial_analysis_agent": {
        "capability": ("scores", "artificial_analysis_index"),
        "cost": ("source", "cost_usd_per_task"),
        "time": ("source", "wall_time_seconds_per_task"),
    },
    "artificial_analysis_model": {
        "capability": ("scores", "aa_model_intelligence"),
        "cost": ("source", "intelligence_cost_per_task"),
        "time": ("source", "intelligence_time_per_task"),
    },
}
BALANCE_GROUPS = (
    {
        "key": "artificial_analysis_agent",
        "label": "Coding Agent",
        "capability_label": "Coding Agent Index",
        "source_url": ARTIFICIAL_ANALYSIS_AGENTS_URL,
    },
    {
        "key": "artificial_analysis_model",
        "label": "Model",
        "capability_label": "Intelligence Index",
        "source_url": ARTIFICIAL_ANALYSIS_MODELS_URL,
    },
)
_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_AGENT_SOURCE_TYPES = {"artificial_analysis_agent", "artificial_analysis"}


def slugify(value: Any) -> str:
    """生成与 Artificial Analysis URL 参数一致的可读键。"""
    return _NON_ALNUM.sub("-", str(value or "").casefold()).strip("-")


def efficiency_source_type(model: dict[str, Any]) -> str:
    value = str((model.get("source") or {}).get("type") or "")
    return "artificial_analysis_agent" if value == "artificial_analysis" else value


def efficiency_key(model: dict[str, Any]) -> str:
    """Agent 用「工具-模型」可读键，模型用 AA 官方 slug。"""
    source = model.get("source") or {}
    if efficiency_source_type(model) == "artificial_analysis_agent":
        return slugify(f"{model.get('tool', '')}-{model.get('model', '')}")
    return slugify(source.get("slug") or model.get("model"))


def normalize_focus(focus: Any = None) -> dict[str, list[str]]:
    if focus is None:
        return {source: list(keys) for source, keys in DEFAULT_FOCUS.items()}
    if not isinstance(focus, dict):
        raise DashboardError("关注项配置必须是对象")
    normalized: dict[str, list[str]] = {}
    for source, keys in DEFAULT_FOCUS.items():
        value = focus.get(source)
        if value is None:
            normalized[source] = list(keys)
            continue
        if isinstance(value, str) or not isinstance(value, Iterable):
            raise DashboardError("关注项列表必须是数组")
        normalized[source] = [slugify(item) for item in value if str(item or "").strip()]
    return normalized


def _point(model: dict[str, Any], spec: dict[str, Any], focused: bool) -> dict[str, Any] | None:
    source = model.get("source") or {}
    scores = model.get("scores") or {}
    x = finite_number(source.get(spec["x_field"]))
    y = finite_number(scores.get(spec["y_score"]))
    if x is None or y is None:
        return None
    key = efficiency_key(model)
    slug = source.get("slug")
    return {
        "key": key,
        "label": f"{model.get('tool', '')} - {model.get('model', '')}"
        if spec["source_type"] == "artificial_analysis_agent"
        else str(model.get("model") or ""),
        "tool": model.get("tool", ""),
        "effort": model.get("reasoning_effort", ""),
        "rank": source.get("rank"),
        "x": x,
        "y": y,
        "focused": focused,
        "url": f"{ARTIFICIAL_ANALYSIS_MODELS_URL}/{slug}" if slug else None,
    }


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def attractive_quadrant(points: list[dict[str, Any]]) -> dict[str, Any] | None:
    """划分「高性价比象限」：能力高于中位数、代价低于中位数的左上区域。"""
    coordinates = [
        (float(point["x"]), float(point["y"]))
        for point in points
        if isinstance(point.get("x"), (int, float)) and isinstance(point.get("y"), (int, float))
    ]
    if len(coordinates) < 2:
        return None
    x_max = _median([x for x, _ in coordinates])
    y_min = _median([y for _, y in coordinates])
    if x_max is None or y_min is None:
        return None
    return {
        "label": "高性价比象限",
        "hint": "能力高于中位数、代价低于中位数（图上左上区域）",
        "x_max": round(x_max, 6),
        "y_min": round(y_min, 6),
        "count": sum(1 for x, y in coordinates if x <= x_max and y >= y_min),
    }


def normalize_balance_weights(raw: Any = None) -> dict[str, float]:
    """解析三维权重；接受 ``capability:0.4,cost:0.3,time:0.3`` 或对象。"""
    if raw is None or raw == "":
        return dict(DEFAULT_BALANCE_WEIGHTS)
    if isinstance(raw, str):
        pairs: dict[str, Any] = {}
        for part in raw.split(","):
            if not part.strip():
                continue
            name, _, value = part.partition(":")
            pairs[name.strip().casefold()] = value.strip()
    elif isinstance(raw, dict):
        pairs = {str(name).strip().casefold(): value for name, value in raw.items()}
    else:
        raise DashboardError("平衡权重必须是对象或 capability:cost:time 形式的字符串")
    if set(pairs) != set(BALANCE_METRICS):
        raise DashboardError("平衡权重必须包含 capability、cost 和 time")
    weights: dict[str, float] = {}
    for name in BALANCE_METRICS:
        value = pairs[name]
        if isinstance(value, bool):
            raise DashboardError("平衡权重必须是数字")
        try:
            number = float(value)
        except (TypeError, ValueError) as error:
            raise DashboardError("平衡权重必须是数字") from error
        if not math.isfinite(number) or number < 0 or number > 1:
            raise DashboardError("平衡权重必须在 0 到 1 之间")
        weights[name] = number
    if not math.isclose(sum(weights.values()), 1.0, abs_tol=1e-6):
        raise DashboardError("平衡权重合计必须为 100%")
    return weights


def balance_metrics(model: dict[str, Any]) -> dict[str, float | None] | None:
    """取出某条记录的三维原始值（缺失为 None）。"""
    fields = BALANCE_METRIC_FIELDS.get(efficiency_source_type(model))
    if not fields:
        return None
    return {
        name: finite_number((model.get(section) or {}).get(field))
        for name, (section, field) in fields.items()
    }


def normalized_series(values: list[float]) -> list[float]:
    """把原始序列映射到 0–1（越大越好）；跨度超过 20 倍时按对数归一。"""
    finite = [float(value) for value in values]
    if not finite:
        return []
    low, high = min(finite), max(finite)
    if high == low:
        return [1.0] * len(finite)
    if low > 0 and high / low > 20:
        base = math.log10(low)
        span = math.log10(high) - base
        return [(math.log10(value) - base) / span for value in finite]
    return [(value - low) / (high - low) for value in finite]


def pareto_frontier(entries: list[dict[str, Any]]) -> set[str]:
    """返回非支配解：不存在另一条能力更高、成本更低且耗时更短的记录。"""
    frontier: set[str] = set()
    for candidate in entries:
        dominated = any(
            other is not candidate
            and other["capability"] >= candidate["capability"]
            and other["cost"] <= candidate["cost"]
            and other["time"] <= candidate["time"]
            and (
                other["capability"] > candidate["capability"]
                or other["cost"] < candidate["cost"]
                or other["time"] < candidate["time"]
            )
            for other in entries
        )
        if not dominated:
            frontier.add(candidate["key"])
    return frontier


def build_balance_ranking(
    models: list[dict[str, Any]],
    focus: Any = None,
    scope: str = "focus",
    weights: Any = None,
) -> dict[str, Any]:
    """三维平衡排名：先取 Pareto 前沿，再按加权归一化得分排序。"""
    if scope not in EFFICIENCY_SCOPES:
        raise DashboardError("效率视图范围必须是 focus 或 all")
    effective_weights = normalize_balance_weights(weights)
    focus_lists = normalize_focus(focus)
    groups: list[dict[str, Any]] = []
    for group in BALANCE_GROUPS:
        focus_set = set(focus_lists.get(group["key"], ()))
        rows = [
            model
            for model in models
            if efficiency_source_type(model) == group["key"] and model.get("archived") is not True
        ]
        entries: list[dict[str, Any]] = []
        incomplete: list[dict[str, Any]] = []
        for model in rows:
            key = efficiency_key(model)
            focused = key in focus_set
            if scope == "focus" and not focused:
                continue
            values = balance_metrics(model) or {}
            missing = [name for name in BALANCE_METRICS if values.get(name) is None]
            label = (
                f"{model.get('tool', '')} - {model.get('model', '')}"
                if group["key"] == "artificial_analysis_agent"
                else str(model.get("model") or "")
            )
            if missing:
                incomplete.append({"key": key, "label": label, "missing": missing})
                continue
            entries.append(
                {
                    "key": key,
                    "label": label,
                    "tool": model.get("tool", ""),
                    "effort": model.get("reasoning_effort", ""),
                    "rank": (model.get("source") or {}).get("rank"),
                    "focused": focused,
                    "capability": float(values["capability"]),
                    "cost": float(values["cost"]),
                    "time": float(values["time"]),
                }
            )
        if not entries:
            groups.append({**group, "rows": [], "best": None, "incomplete": incomplete, "pareto_count": 0})
            continue
        # 成本与耗时越低越好，归一化后取反；能力越高越好。
        capability_scores = normalized_series([entry["capability"] for entry in entries])
        cost_scores = [1 - value for value in normalized_series([entry["cost"] for entry in entries])]
        time_scores = [1 - value for value in normalized_series([entry["time"] for entry in entries])]
        frontier = pareto_frontier(entries)
        for index, entry in enumerate(entries):
            parts = {
                "capability": capability_scores[index],
                "cost": cost_scores[index],
                "time": time_scores[index],
            }
            entry["scores"] = {name: round(value * 100, 2) for name, value in parts.items()}
            entry["balance_score"] = round(
                sum(parts[name] * effective_weights[name] for name in BALANCE_METRICS) * 100, 2
            )
            entry["pareto"] = entry["key"] in frontier
        entries.sort(
            key=lambda item: (-item["balance_score"], -item["capability"], item["cost"], item["key"])
        )
        for position, entry in enumerate(entries, 1):
            entry["balance_rank"] = position
        groups.append(
            {
                **group,
                "rows": entries,
                "best": entries[0],
                "incomplete": incomplete,
                "pareto_count": len(frontier),
            }
        )
    return {
        "weights": effective_weights,
        "presets": [dict(preset) for preset in BALANCE_PRESETS],
        "metrics": {
            "capability": {"label": "能力", "higher_is_better": True},
            "cost": {"label": "单任务成本", "unit": "USD", "higher_is_better": False},
            "time": {"label": "单任务耗时", "unit": "秒", "higher_is_better": False},
        },
        "groups": groups,
    }


def scatter_pareto_keys(points: list[dict[str, Any]]) -> list[str]:
    """二维散点的左上包络线：x 越小越好、y 越大越好时的非支配点（按 x 升序）。"""
    ordered = sorted(points, key=lambda item: (float(item["x"]), -float(item["y"]), item["key"]))
    keys: list[str] = []
    best: float | None = None
    for point in ordered:
        value = float(point["y"])
        if best is None or value > best:
            best = value
            keys.append(point["key"])
    return keys


def build_efficiency_overview(
    models: list[dict[str, Any]],
    focus: Any = None,
    scope: str = "focus",
    weights: Any = None,
) -> dict[str, Any]:
    """把 AA 的 Agent / Model 数据整理成三张「能力 vs 代价」散点图与三维平衡排名。"""
    if scope not in EFFICIENCY_SCOPES:
        raise DashboardError("效率视图范围必须是 focus 或 all")
    focus_lists = normalize_focus(focus)
    charts: list[dict[str, Any]] = []
    updated_at = ""
    for spec in EFFICIENCY_CHARTS:
        focus_set = set(focus_lists.get(spec["source_type"], ()))
        rows = [
            model
            for model in models
            if efficiency_source_type(model) == spec["source_type"] and model.get("archived") is not True
        ]
        points = []
        for model in rows:
            fetched_at = str((model.get("source") or {}).get("fetched_at") or "")
            if fetched_at > updated_at:
                updated_at = fetched_at
            point = _point(model, spec, efficiency_key(model) in focus_set)
            if point is not None:
                points.append(point)
        matched = {point["key"] for point in points}
        missing = [key for key in focus_lists.get(spec["source_type"], ()) if key not in matched]
        points.sort(key=lambda item: (-float(item["y"]), float(item["x"]), item["key"]))
        visible = [point for point in points if point["focused"]] if scope == "focus" else points
        quadrant = attractive_quadrant(visible)
        charts.append(
            {
                **{key: value for key, value in spec.items() if key != "source_type"},
                "points": visible,
                "quadrant": quadrant,
                "pareto_keys": scatter_pareto_keys(visible),
                "focus_total": len(focus_lists.get(spec["source_type"], ())),
                "focus_matched": len(matched & focus_set),
                "total": len(points),
                "missing": missing,
            }
        )
    return {
        "scope": scope,
        "focus": focus_lists,
        "charts": charts,
        "balance": build_balance_ranking(models, focus=focus_lists, scope=scope, weights=weights),
        "updated_at": updated_at,
    }
