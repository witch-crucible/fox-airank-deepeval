from __future__ import annotations

import re
import unicodedata
import math
from collections import defaultdict
from typing import Any, Iterable

from .domain import DashboardError


THIRD_PARTY_WEIGHTS = {
    "artificial_analysis_model": 0.50,
    "arena_webdev": 0.35,
    "llm_stats": 0.15,
}
LOCAL_METRIC_WEIGHTS = {
    "Task Correctness": 0.70,
    "Robustness, Safety and Regression": 0.20,
    "Delivery Evidence": 0.10,
}
THIRD_PARTY_SHARE = 0.70
LOCAL_SHARE = 0.30
MIN_LOCAL_REPEATS = 3

SOURCE_SCORE_FIELDS = {
    "arena_webdev": "arena_webdev",
    "artificial_analysis_model": "aa_model_intelligence",
    "llm_stats": "llm_stats_score",
}

_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_EFFORT_WORD = r"(?:none|minimal|low|medium|xhigh|high|max|ultra)"

_EFFORT_ALIASES = {
    "无": "none", "无推理": "none", "non reasoning": "none", "non-reasoning": "none",
    "none": "none", "minimal": "minimal", "最低": "minimal", "低": "low", "low": "low",
    "中": "medium", "中等": "medium", "medium": "medium", "高": "high", "high": "high",
    "xhigh": "xhigh", "extra high": "xhigh", "极高": "xhigh", "max": "max", "maximum": "max",
    "ultra": "ultra", "超高": "ultra", "最高": "max", "non thinking": "none",
}


def normalize_reasoning_effort(value: Any) -> str:
    """Return one stable effort name; undisclosed values are ``unknown``."""
    if value is None or isinstance(value, bool):
        return "unknown"
    text = unicodedata.normalize("NFKC", str(value)).strip().casefold()
    if text in {"", "unknown", "not disclosed", "undisclosed", "n/a", "na", "未知", "未注明", "未记录", "—"}:
        return "unknown"
    budget = re.fullmatch(r"(?:budget[ _-]*)?(\d+(?:\.\d+)?k?)(?:\s*tokens?)?", text)
    if budget:
        return f"budget_{budget.group(1)}"
    combined = re.fullmatch(rf"({_EFFORT_WORD})/budget[ _-]*(\d+k?)", text)
    if combined:
        return f"{combined.group(1)}/budget_{combined.group(2)}"
    text = re.sub(r"[_-]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    text = re.sub(r"^(?:reasoning|thinking) effort\s*[:=]?\s*", "", text)
    text = re.sub(r"\s+(?:reasoning |thinking )?effort$", "", text)
    return _EFFORT_ALIASES.get(text, text)


def _source_type(model: dict[str, Any]) -> str:
    value = str((model.get("source") or {}).get("type") or "")
    return "artificial_analysis_agent" if value == "artificial_analysis" else value


def split_model_effort(name: Any) -> tuple[str, str]:
    text = unicodedata.normalize("NFKC", str(name or "")).strip()
    if "+" in text and len(re.findall(rf"\b{_EFFORT_WORD}\b", text, re.I)) > 1:
        return text, ""
    text = re.sub(r"(?:\s*\((?:codex[- ]harness|with fallback)\))+$", "", text, flags=re.I)
    effort = ""
    match = re.search(r"\s*\(([^()]*)\)$", text)
    if match:
        content = match.group(1).strip()
        tokens = re.findall(rf"\b{_EFFORT_WORD}\b|极高|超高|最高|最低|高|中|低|无", content, re.I)
        normalized = {normalize_reasoning_effort(token) for token in tokens}
        candidate = normalize_reasoning_effort(content)
        if len(normalized) == 1:
            effort = normalized.pop()
        elif candidate in {"none", "thinking", "reasoning", "adaptive reasoning"} or (
            candidate.startswith("budget_") and re.search(r"\b(?:budget|tokens?)\b", content, re.I)
        ):
            effort = candidate
        if effort:
            text = text[:match.start()].rstrip(" -_")
    # Max is a product tier in Qwen names, not an effort setting.
    product_max = re.fullmatch(r"qwen[\d. -]+[-_ ]max", text, re.I)
    match = re.search(rf"[-_ ]+(?P<effort>{_EFFORT_WORD}|non[-_ ](?:reasoning|thinking)|thinking|reasoning)(?:[-_ ](?P<budget>\d+k))?$", text, re.I)
    if match and not product_max:
        if not effort:
            effort = normalize_reasoning_effort(match.group("effort"))
            if match.group("budget"):
                effort = f"{effort}/budget_{match.group('budget').casefold()}"
        text = text[:match.start()].rstrip(" -_")
    return text.strip(), effort


def model_configuration(record: dict[str, Any], aliases: dict[str, str] | None = None) -> tuple[str, str]:
    """Return ``(canonical model family, normalized reasoning effort)``."""
    family = _model_family_name(record, aliases)
    creator = (record.get("source") or {}).get("organization") or (record.get("source") or {}).get("creator_name") or record.get("tool")
    canonical = canonical_model_key(family, creator=creator, aliases=aliases)
    explicit = record.get("reasoning_effort")
    if explicit is None and isinstance(record.get("source"), dict) and "reasoning_effort" in record["source"]:
        explicit = record["source"].get("reasoning_effort")
    suffix_effort = normalize_reasoning_effort(split_model_effort(record.get("model"))[1])
    effort = normalize_reasoning_effort(explicit) if explicit is not None else suffix_effort
    # Normalizers historically materialize a literal ``unknown`` field. Treat
    # that sentinel as undisclosed and retain an informative name suffix.
    if effort == "unknown" and suffix_effort != "unknown":
        effort = suffix_effort
    return canonical, effort


def _recommendation_entries(recommendations: Any) -> list[dict[str, Any]]:
    """Accept the persisted plan object as well as a flat list."""
    if isinstance(recommendations, list):
        return [item for item in recommendations if isinstance(item, dict)]
    if isinstance(recommendations, dict):
        entries: list[dict[str, Any]] = []
        for group in ("agent_plan", "coding_plan"):
            value = recommendations.get(group)
            if isinstance(value, list):
                entries.extend(item for item in value if isinstance(item, dict))
        return entries
    return []


def canonical_model_key(
    name: Any,
    *,
    creator: Any = "",
    aliases: dict[str, str] | None = None,
) -> str:
    base, _ = split_model_effort(name)
    normalized = _NON_ALNUM.sub(" ", base.casefold()).strip()
    if normalized.startswith(("opus ", "sonnet ", "haiku ", "fable ")):
        normalized = f"claude {normalized}"
    alias_key = _NON_ALNUM.sub(" ", str(name or "").casefold()).strip()
    if aliases:
        target = aliases.get(alias_key) or aliases.get(normalized)
        if target:
            normalized = _NON_ALNUM.sub(" ", target.casefold()).strip()
    return normalized


def _model_family_name(model: dict[str, Any], aliases: dict[str, str] | None = None) -> Any:
    """Use AA's release identity while keeping explicit legacy aliases authoritative."""
    raw_name = model.get("model")
    raw_alias_key = _NON_ALNUM.sub(" ", str(raw_name or "").casefold()).strip()
    if aliases and raw_alias_key in aliases:
        return raw_name
    if _source_type(model) == "artificial_analysis_model":
        release = (model.get("source") or {}).get("release")
        release_name = release.get("name") if isinstance(release, dict) else None
        if isinstance(release_name, str) and release_name.strip():
            return release_name.strip()
    return raw_name


def min_max_scores(values: Iterable[float]) -> dict[float, float]:
    numeric = [float(value) for value in values]
    if not numeric:
        return {}
    low, high = min(numeric), max(numeric)
    if low == high:
        return {value: 100.0 for value in numeric}
    return {value: round((value - low) / (high - low) * 100, 4) for value in numeric}


def _record_score(model: dict[str, Any], source_type: str) -> float | None:
    field = SOURCE_SCORE_FIELDS.get(source_type)
    value = (model.get("scores") or {}).get(field) if field else None
    return float(value) if isinstance(value, (int, float)) else None


def normalize_third_party_weights(raw: Any = None) -> dict[str, float]:
    if raw is None:
        return dict(THIRD_PARTY_WEIGHTS)
    if not isinstance(raw, dict):
        raise DashboardError("三方榜单权重必须是对象")
    expected = set(THIRD_PARTY_WEIGHTS)
    if set(raw) != expected:
        raise DashboardError("三方榜单权重必须包含 AA、Arena 和 LLM Stats")
    weights: dict[str, float] = {}
    for source in THIRD_PARTY_WEIGHTS:
        value = raw[source]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
            raise DashboardError("三方榜单权重必须是有效数字")
        numeric = float(value)
        if numeric < 0 or numeric > 1:
            raise DashboardError("三方榜单权重必须在 0 到 1 之间")
        weights[source] = numeric
    if not math.isclose(sum(weights.values()), 1.0, abs_tol=1e-9):
        raise DashboardError("三方榜单权重合计必须为 100%")
    return weights


def build_model_overview(
    models: list[dict[str, Any]],
    local_records: list[dict[str, Any]],
    expected_cases: set[str],
    aliases: dict[str, str] | None = None,
    weights: dict[str, float] | None = None,
    recommendations: list[dict[str, Any]] | dict[str, Any] | None = None,
) -> dict[str, Any]:
    effective_weights = normalize_third_party_weights(weights)
    source_records: dict[str, list[dict[str, Any]]] = {
        source: [model for model in models if _source_type(model) == source]
        for source in effective_weights
    }
    normalized_by_source: dict[str, dict[float, float]] = {}
    for source, records in source_records.items():
        values = [score for record in records if (score := _record_score(record, source)) is not None]
        normalized_by_source[source] = min_max_scores(values)

    groups: dict[str, dict[str, Any]] = {}
    for source, records in source_records.items():
        for record in records:
            family_name = _model_family_name(record, aliases)
            canonical, effort = model_configuration(record, aliases)
            if not canonical:
                continue
            configuration_key = f"{canonical}:{effort}"
            group = groups.setdefault(
                configuration_key,
                {
                    "model_key": canonical,
                    "configuration_key": configuration_key,
                    "reasoning_effort": effort,
                    "model": split_model_effort(family_name)[0] or family_name,
                    "sources": {},
                    "third_party_score": None,
                    "third_party_rank": None,
                    "local_configurations": [],
                },
            )
            if family_name != record.get("model"):
                group["model"] = split_model_effort(family_name)[0] or family_name
            group["sources"].setdefault(source, []).append(record)

    for group in groups.values():
        weighted = 0.0
        complete = True
        for source, weight in effective_weights.items():
            variants = group["sources"].get(source, [])
            variants.sort(
                key=lambda item: (
                    int((item.get("source") or {}).get("rank") or 10**9),
                    str(item.get("model") or "").casefold(),
                )
            )
            if not variants:
                if weight > 0:
                    complete = False
                continue
            representative = variants[0]
            raw_score = _record_score(representative, source)
            if raw_score is None:
                if weight > 0:
                    complete = False
                group["sources"][source] = {
                    "representative": representative,
                    "variants": variants,
                    "raw_score": None,
                    "normalized_score": None,
                    "weight": weight,
                }
                continue
            normalized = normalized_by_source.get(source, {}).get(float(raw_score))
            if normalized is None:
                if weight > 0:
                    complete = False
                group["sources"][source] = {
                    "representative": representative,
                    "variants": variants,
                    "raw_score": raw_score,
                    "normalized_score": None,
                    "weight": weight,
                }
                continue
            weighted += normalized * weight
            group["sources"][source] = {
                "representative": representative,
                "variants": variants,
                "raw_score": raw_score,
                "normalized_score": normalized,
                "weight": weight,
            }
        if complete:
            group["third_party_score"] = round(weighted, 2)

        arena_source = group["sources"].get("arena_webdev")
        aa_source = group["sources"].get("artificial_analysis_model")
        if isinstance(arena_source, dict) and isinstance(aa_source, dict):
            arena_meta = arena_source["representative"].get("source") or {}
            if arena_meta.get("input_price_per_m") is None and arena_meta.get("output_price_per_m") is None:
                endpoints = (aa_source["representative"].get("source") or {}).get("variants") or []
                arena_effort = model_configuration(arena_source["representative"], aliases)[1]
                candidates = [
                    endpoint for endpoint in endpoints
                    if isinstance(endpoint, dict)
                    and (endpoint.get("input_price_per_m") is not None or endpoint.get("output_price_per_m") is not None)
                ]
                effort_matches = [endpoint for endpoint in candidates if normalize_reasoning_effort(split_model_effort(endpoint.get("name"))[1]) == arena_effort]
                if effort_matches:
                    endpoint = effort_matches[0]
                    arena_source["price_reference"] = {
                        "input_price_per_m": endpoint.get("input_price_per_m"),
                        "output_price_per_m": endpoint.get("output_price_per_m"),
                        "source": "artificial_analysis_model",
                        "variant": endpoint.get("name") or endpoint.get("slug"),
                    }

    local = build_local_scores(local_records, expected_cases, aliases=aliases)
    for configuration in local:
        canonical = configuration["model_key"]
        configuration_key = configuration.get("configuration_key") or f"{canonical}:{configuration.get('reasoning_effort', 'unknown')}"
        group = groups.setdefault(
            configuration_key,
            {
                "model_key": canonical,
                "configuration_key": configuration_key,
                "reasoning_effort": configuration.get("reasoning_effort", "unknown"),
                "model": configuration["model"],
                "sources": {},
                "third_party_score": None,
                "third_party_rank": None,
                "local_configurations": [],
            },
        )
        configuration["third_party_score"] = group["third_party_score"]
        configuration["battle_score"] = (
            round(group["third_party_score"] * THIRD_PARTY_SHARE + configuration["local_score"] * LOCAL_SHARE, 2)
            if configuration["eligible"] and group["third_party_score"] is not None
            else None
        )
        configuration["provisional_battle_score"] = (
            round(group["third_party_score"] * THIRD_PARTY_SHARE + configuration["local_score"] * LOCAL_SHARE, 2)
            if group["third_party_score"] is not None
            else None
        )
        group["local_configurations"].append(configuration)

    # Recommendations are configuration identities, never a score wildcard.
    for recommendation in _recommendation_entries(recommendations):
        canonical, effort = model_configuration(recommendation, aliases)
        if not canonical:
            continue
        configuration_key = f"{canonical}:{effort}"
        group = groups.setdefault(configuration_key, {
            "model_key": canonical, "configuration_key": configuration_key,
            "reasoning_effort": effort, "model": recommendation.get("model") or canonical,
            "sources": {}, "third_party_score": None, "third_party_rank": None,
            "local_configurations": [],
        })
        group.setdefault("legion", {"matched": False, "is_core": False, "entries": []})
        group["legion"]["entries"].append(recommendation)
        group["legion"]["matched"] = True
        purposes = recommendation.get("core_purpose_types")
        group["legion"]["is_core"] = group["legion"]["is_core"] or (bool(purposes) if isinstance(purposes, list) else bool(recommendation.get("is_core")))

    for group in groups.values():
        group.setdefault("legion", {"matched": False, "is_core": False, "entries": []})
        group.setdefault("supplemental", not bool(group["sources"]) and bool(group["legion"]["entries"]))

    ranked = [group for group in groups.values() if group["third_party_score"] is not None]
    ranked.sort(key=lambda item: (-item["third_party_score"], item["model_key"]))
    for rank, group in enumerate(ranked, 1):
        group["third_party_rank"] = rank

    battle_configs = [
        config
        for group in groups.values()
        for config in group["local_configurations"]
        if config["battle_score"] is not None
    ]
    battle_configs.sort(key=lambda item: (-item["battle_score"], item["model_key"], item["agent"].casefold()))
    for rank, config in enumerate(battle_configs, 1):
        config["battle_rank"] = rank

    rows = sorted(
        groups.values(),
        key=lambda item: (
            item["third_party_rank"] is None,
            item["third_party_rank"] or 10**9,
            item["model_key"],
        ),
    )
    return {
        "weights": effective_weights,
        "local_metric_weights": LOCAL_METRIC_WEIGHTS,
        "third_party_share": THIRD_PARTY_SHARE,
        "local_share": LOCAL_SHARE,
        "minimum_local_repeats": MIN_LOCAL_REPEATS,
        "expected_cases": sorted(expected_cases),
        "models": rows,
    }


def build_local_scores(
    records: list[dict[str, Any]],
    expected_cases: set[str],
    *,
    aliases: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str], dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    identity: dict[tuple[str, str, str], dict[str, str]] = {}
    for record in records:
        metrics = record.get("metrics") or {}
        values: dict[str, float] = {}
        for name in LOCAL_METRIC_WEIGHTS:
            score = (metrics.get(name) or {}).get("score")
            if not isinstance(score, (int, float)):
                values = {}
                break
            values[name] = float(score) * 100
        if not values:
            continue
        agent = str(record.get("agent") or record.get("tool") or "unknown")
        model = str(record.get("model") or "unknown")
        canonical, effort = model_configuration(record, aliases)
        key = (agent.casefold(), canonical, effort)
        score = sum(values[name] * weight for name, weight in LOCAL_METRIC_WEIGHTS.items())
        grouped[key][str(record.get("case_id") or "unknown")].append(score)
        identity[key] = {"agent": agent, "model": split_model_effort(model)[0], "reasoning_effort": effort}

    result = []
    for key, cases in grouped.items():
        item = identity[key]
        canonical, effort = model_configuration(item, aliases)
        case_scores = {case_id: round(sum(scores) / len(scores), 2) for case_id, scores in cases.items()}
        local_score = round(sum(case_scores.values()) / len(case_scores), 2)
        tested = set(case_scores)
        missing = sorted(expected_cases - tested)
        minimum_repeats = min((len(scores) for scores in cases.values()), default=0)
        result.append(
            {
                **item,
                "model_key": canonical,
                "configuration_key": f"{canonical}:{effort}",
                "reasoning_effort": effort,
                "local_score": local_score,
                "case_scores": case_scores,
                "case_count": len(tested),
                "expected_case_count": len(expected_cases),
                "coverage": round(len(tested) / len(expected_cases) * 100, 2) if expected_cases else 0,
                "minimum_repeats": minimum_repeats,
                "missing_cases": missing,
                "eligible": bool(expected_cases) and not missing and minimum_repeats >= MIN_LOCAL_REPEATS,
                "battle_rank": None,
            }
        )
    return sorted(result, key=lambda item: (-item["local_score"], item["model_key"], item["agent"].casefold()))


def _tool_key(value: Any) -> str:
    text = _NON_ALNUM.sub(" ", str(value or "").casefold()).strip()
    if text in {"codex", "codex cli", "codex harness"}:
        return "codex"
    if text in {"claude", "claude code"}:
        return "claude"
    return text


def build_agent_overview(
    models: list[dict[str, Any]],
    recommendations: list[dict[str, Any]] | dict[str, Any] | None = None,
    aliases: dict[str, str] | None = None,
) -> dict[str, Any]:
    # One overview pass feeds both indexes: the agent rows and Legion coverage
    # share the same min-max normalizations.
    model_sources_index = {
        (row["model_key"], row["reasoning_effort"]): row["sources"]
        for row in build_model_overview(models, [], set(), aliases=aliases)["models"]
    }
    agents = [model for model in models if _source_type(model) == "artificial_analysis_agent"]
    agents.sort(key=lambda model: int((model.get("source") or {}).get("rank") or 10**9))
    rows = []
    for model in agents:
        canonical, effort = model_configuration(model, aliases)
        sources = model_sources_index.get((canonical, effort), {})
        baseline = (sources.get("artificial_analysis_model") or {}).get("representative")
        agent_score = (model.get("scores") or {}).get("aa_terminal_bench_v4")
        baseline_score = (baseline.get("scores") or {}).get("aa_model_terminal_bench_v4") if baseline else None
        uplift = (
            round(float(agent_score) - float(baseline_score), 2)
            if isinstance(agent_score, (int, float)) and isinstance(baseline_score, (int, float))
            else None
        )
        rows.append({
            "agent": model,
            "model_key": canonical,
            "reasoning_effort": effort,
            "baseline": baseline,
            "model_sources": sources,
            "terminal_bench_uplift": uplift,
            "comparison_status": (
                "comparable_terminal_bench_v4" if uplift is not None
                else "baseline_not_matched" if baseline is None else "shared_metric_missing"
            ),
            "supplemental": False,
            "legion": {"matched": False, "is_core": False, "entries": []},
        })

    for recommendation in _recommendation_entries(recommendations):
        canonical, effort = model_configuration(recommendation, aliases)
        if not canonical:
            continue
        tool = _tool_key(recommendation.get("tool"))
        purposes = recommendation.get("core_purpose_types")
        is_core = bool(purposes) if isinstance(purposes, list) else bool(recommendation.get("is_core"))
        matches = [
            entry for entry in rows
            if entry["model_key"] == canonical and entry["reasoning_effort"] == effort
            and _tool_key(entry["agent"].get("tool")) == tool
        ]
        if not matches:
            sources = model_sources_index.get((canonical, effort), {})
            entry = {
                "agent": {
                    "tool": recommendation.get("tool") or "",
                    "model": recommendation["model"],
                    "reasoning_effort": effort,
                    "scores": {},
                    "source": {"type": "legion"},
                },
                "model_key": canonical,
                "reasoning_effort": effort,
                "baseline": (sources.get("artificial_analysis_model") or {}).get("representative"),
                "terminal_bench_uplift": None,
                "comparison_status": "supplemental",
                "supplemental": True,
                "model_sources": sources,
                "legion": {"matched": False, "is_core": False, "entries": []},
            }
            rows.append(entry)
            matches = [entry]
        for entry in matches:
            entry["legion"]["matched"] = True
            entry["legion"]["is_core"] = entry["legion"]["is_core"] or is_core
            entry["legion"]["entries"].append(recommendation)
    # Keep the historical flat representation above: clients use it for
    # configuration-level details.  The grouped view is deliberately derived
    # from those rows so its Legion matching cannot broaden the old identity
    # (tool + model + effort) semantics.
    purpose_order = list((recommendations or {}).get("purpose_types", [])) if isinstance(recommendations, dict) else []
    if not purpose_order:
        purpose_order = ["Ask", "Plan", "Build", "Review", "Ship"]
    purpose_rank = {purpose: index for index, purpose in enumerate(purpose_order)}

    groups: dict[str, dict[str, Any]] = {}
    for configuration in rows:
        tool_key = _tool_key(configuration["agent"].get("tool"))
        group = groups.setdefault(
            tool_key,
            {
                "agent_key": tool_key,
                "agent": configuration["agent"].get("tool") or tool_key,
                "configurations": [],
                "configuration_count": 0,
                "legion": {
                    "matched": False,
                    "is_core": False,
                    "entries": [],
                    "primary_purpose_types": [],
                    "secondary_purpose_types": [],
                    "core_purpose_types": [],
                },
            },
        )
        group["configurations"].append(configuration)

    def config_order(item: dict[str, Any]) -> tuple[int, int, str, str]:
        source_type = str((item["agent"].get("source") or {}).get("type") or "")
        supplemental = bool(item.get("supplemental")) or source_type == "legion"
        rank = (item["agent"].get("source") or {}).get("rank")
        numeric_rank = int(rank) if isinstance(rank, (int, float)) else 10**9
        return (1 if supplemental else 0, numeric_rank, item["model_key"], item["reasoning_effort"])

    def ordered_unique(values: Iterable[str]) -> list[str]:
        seen: set[str] = set()
        return [value for value in sorted((str(value) for value in values if value), key=lambda value: (purpose_rank.get(value, 10**9), value)) if not (value in seen or seen.add(value))]

    def row_score(item: dict[str, Any]) -> float | None:
        value = (item["agent"].get("scores") or {}).get("artificial_analysis_index")
        return float(value) if isinstance(value, (int, float)) else None

    def best_configuration(configurations: list[dict[str, Any]], value_getter: Any) -> tuple[float | None, dict[str, Any] | None]:
        candidates = [(value_getter(item), item) for item in configurations]
        candidates = [(value, item) for value, item in candidates if value is not None]
        if not candidates:
            return None, None
        candidates.sort(key=lambda pair: (-pair[0], config_order(pair[1])))
        return candidates[0]

    for group in groups.values():
        configurations = sorted(group["configurations"], key=config_order)
        group["configurations"] = configurations
        group["configuration_count"] = len(configurations)
        score, score_configuration = best_configuration(configurations, row_score)
        uplift, uplift_configuration = best_configuration(
            configurations,
            lambda item: item.get("terminal_bench_uplift")
            if isinstance(item.get("terminal_bench_uplift"), (int, float))
            else None,
        )
        group["score_sort_value"] = score
        group["score_sort_configuration"] = score_configuration
        group["uplift_sort_value"] = uplift
        group["uplift_sort_configuration"] = uplift_configuration

        legion = group["legion"]
        matched_entries: list[dict[str, Any]] = []
        for configuration in configurations:
            config_legion = configuration.get("legion") or {}
            if not config_legion.get("matched"):
                continue
            legion["matched"] = True
            legion["is_core"] = legion["is_core"] or bool(config_legion.get("is_core"))
            matched_entries.extend(config_legion.get("entries") or [])
        legion["entries"] = matched_entries
        primary: list[str] = []
        secondary: list[str] = []
        core: list[str] = []
        for entry in matched_entries:
            entry_primary = entry.get("primary_purpose_types")
            entry_secondary = entry.get("secondary_purpose_types")
            entry_core = entry.get("core_purpose_types")
            if isinstance(entry_primary, list):
                primary.extend(str(value) for value in entry_primary)
            if isinstance(entry_secondary, list):
                secondary.extend(str(value) for value in entry_secondary)
            if isinstance(entry_core, list):
                core.extend(str(value) for value in entry_core)
            if not isinstance(entry_core, list) and entry.get("is_core"):
                legion["is_core"] = True
        primary_values = set(primary)
        legion["primary_purpose_types"] = ordered_unique(primary)
        legion["secondary_purpose_types"] = ordered_unique(value for value in secondary if value not in primary_values)
        legion["core_purpose_types"] = ordered_unique(core)

    def group_order(group: dict[str, Any]) -> tuple[Any, ...]:
        score = group["score_sort_value"]
        uplift = group["uplift_sort_value"]
        score_rank = config_order(group["score_sort_configuration"])[1] if group["score_sort_configuration"] else 10**9
        return (score is None, -(score or 0), score_rank, group["agent"].casefold())

    grouped = sorted(groups.values(), key=group_order)
    return {"agents": rows, "count": len(rows), "agent_groups": grouped, "group_count": len(grouped)}


def snapshot_row_key(row: dict[str, Any]) -> str:
    source = row.get("source") or {}
    return str(source.get("source_id") or source.get("canonical_model_id") or row.get("model") or row.get("id") or "").casefold()


def compare_snapshot_rows(
    current: list[dict[str, Any]],
    previous: list[dict[str, Any]],
    *,
    comparable: bool = True,
) -> list[dict[str, Any]]:
    metric_fields = {
        "arena_webdev": {"arena_webdev"},
        "artificial_analysis_model": {"aa_model_intelligence", "aa_model_speed", "aa_model_cost_per_task", "aa_model_terminal_bench_v4"},
        "artificial_analysis_agent": {"artificial_analysis_index", "aa_deep_swe", "aa_deep_swe_v1_1", "aa_terminal_bench_v2", "aa_terminal_bench_v4", "aa_swe_atlas_qna"},
        "artificial_analysis": {"artificial_analysis_index", "aa_deep_swe", "aa_deep_swe_v1_1", "aa_terminal_bench_v2", "aa_terminal_bench_v4", "aa_swe_atlas_qna"},
        "llm_stats": {"llm_stats_score", "llm_stats_reasoning", "llm_stats_code", "llm_stats_agents"},
    }
    old = {snapshot_row_key(row): row for row in previous if snapshot_row_key(row)}
    seen: set[str] = set()
    result: list[dict[str, Any]] = []
    for row in current:
        key = snapshot_row_key(row)
        seen.add(key)
        before = old.get(key)
        current_rank = (row.get("source") or {}).get("rank")
        previous_rank = (before.get("source") or {}).get("rank") if before else None
        deltas: dict[str, float] = {}
        if before and comparable:
            source_type = str((row.get("source") or {}).get("type") or "")
            for field in metric_fields.get(source_type, set()):
                value = (row.get("scores") or {}).get(field)
                old_value = (before.get("scores") or {}).get(field)
                if isinstance(value, (int, float)) and isinstance(old_value, (int, float)):
                    deltas[field] = round(float(value) - float(old_value), 4)
            for field in ("cost_usd_per_task", "wall_time_seconds_per_task", "input_price_per_m", "output_price_per_m"):
                value = (row.get("source") or {}).get(field)
                old_value = (before.get("source") or {}).get(field)
                if isinstance(value, (int, float)) and isinstance(old_value, (int, float)):
                    deltas[field] = round(float(value) - float(old_value), 4)
        result.append(
            {
                "status": "existing" if before else "new",
                "row": row,
                "previous": before,
                "rank_delta": (
                    int(previous_rank) - int(current_rank)
                    if before and comparable and isinstance(current_rank, (int, float)) and isinstance(previous_rank, (int, float))
                    else None
                ),
                "metric_deltas": deltas,
                "comparable": comparable,
            }
        )
    for key, row in old.items():
        if key not in seen:
            result.append({"status": "exited", "row": None, "previous": row, "rank_delta": None, "metric_deltas": {}, "comparable": comparable})
    return result
