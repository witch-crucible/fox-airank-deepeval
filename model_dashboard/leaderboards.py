from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from typing import Any, Iterable


THIRD_PARTY_WEIGHTS = {
    "arena_webdev": 0.35,
    "artificial_analysis_model": 0.50,
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

_EFFORT_SUFFIX = re.compile(
    r"(?:\s*\((?:codex[- ]harness(?:,?\s*)?)?(?:none|minimal|low|medium|high|xhigh|max)\)"
    r"|[-_ ](?:none|minimal|low|medium|high|xhigh|max))$",
    re.IGNORECASE,
)
_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def _source_type(model: dict[str, Any]) -> str:
    value = str((model.get("source") or {}).get("type") or "")
    return "artificial_analysis_agent" if value == "artificial_analysis" else value


def split_model_effort(name: Any) -> tuple[str, str]:
    text = unicodedata.normalize("NFKC", str(name or "")).strip()
    text = re.sub(r"\s*\(codex[- ]harness\)\s*$", "", text, flags=re.I)
    effort = ""
    while True:
        match = _EFFORT_SUFFIX.search(text)
        if not match:
            break
        suffix = match.group(0)
        effort_match = re.search(r"(none|minimal|low|medium|high|xhigh|max)", suffix, re.I)
        if effort_match and not effort:
            effort = effort_match.group(1).casefold()
        text = text[: match.start()].rstrip(" -_")
    return text.strip(), effort


def canonical_model_key(
    name: Any,
    *,
    creator: Any = "",
    aliases: dict[str, str] | None = None,
) -> str:
    base, _ = split_model_effort(name)
    normalized = _NON_ALNUM.sub(" ", base.casefold()).strip()
    creator_name = _NON_ALNUM.sub(" ", str(creator or "").casefold()).strip()
    if creator_name in {"anthropic", "anthropic pbc"} and normalized.startswith(("opus ", "sonnet ", "haiku ")):
        normalized = f"claude {normalized}"
    alias_key = _NON_ALNUM.sub(" ", str(name or "").casefold()).strip()
    if aliases:
        target = aliases.get(alias_key) or aliases.get(normalized)
        if target:
            normalized = _NON_ALNUM.sub(" ", target.casefold()).strip()
    return normalized


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


def build_model_overview(
    models: list[dict[str, Any]],
    local_records: list[dict[str, Any]],
    expected_cases: set[str],
    aliases: dict[str, str] | None = None,
) -> dict[str, Any]:
    source_records: dict[str, list[dict[str, Any]]] = {
        source: [model for model in models if _source_type(model) == source]
        for source in THIRD_PARTY_WEIGHTS
    }
    normalized_by_source: dict[str, dict[float, float]] = {}
    for source, records in source_records.items():
        values = [score for record in records if (score := _record_score(record, source)) is not None]
        normalized_by_source[source] = min_max_scores(values)

    groups: dict[str, dict[str, Any]] = {}
    for source, records in source_records.items():
        for record in records:
            source_meta = record.get("source") or {}
            creator = source_meta.get("organization") or source_meta.get("creator_name") or record.get("tool")
            canonical = canonical_model_key(record.get("model"), creator=creator, aliases=aliases)
            if not canonical:
                continue
            group = groups.setdefault(
                canonical,
                {
                    "model_key": canonical,
                    "model": split_model_effort(record.get("model"))[0] or record.get("model"),
                    "sources": {},
                    "third_party_score": None,
                    "third_party_rank": None,
                    "local_configurations": [],
                },
            )
            group["sources"].setdefault(source, []).append(record)

    for group in groups.values():
        weighted = 0.0
        complete = True
        for source, weight in THIRD_PARTY_WEIGHTS.items():
            variants = group["sources"].get(source, [])
            variants.sort(
                key=lambda item: (
                    int((item.get("source") or {}).get("rank") or 10**9),
                    str(item.get("model") or "").casefold(),
                )
            )
            if not variants:
                complete = False
                continue
            representative = variants[0]
            raw_score = _record_score(representative, source)
            if raw_score is None:
                complete = False
                continue
            normalized = normalized_by_source[source].get(float(raw_score))
            if normalized is None:
                complete = False
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
                _, arena_effort = split_model_effort(arena_source["representative"].get("model"))
                candidates = [
                    endpoint for endpoint in endpoints
                    if isinstance(endpoint, dict)
                    and (endpoint.get("input_price_per_m") is not None or endpoint.get("output_price_per_m") is not None)
                ]
                effort_matches = [endpoint for endpoint in candidates if split_model_effort(endpoint.get("name"))[1] == arena_effort]
                if effort_matches or candidates:
                    endpoint = (effort_matches or candidates)[0]
                    arena_source["price_reference"] = {
                        "input_price_per_m": endpoint.get("input_price_per_m"),
                        "output_price_per_m": endpoint.get("output_price_per_m"),
                        "source": "artificial_analysis_model",
                        "variant": endpoint.get("name") or endpoint.get("slug"),
                    }

    local = build_local_scores(local_records, expected_cases, aliases=aliases)
    for configuration in local:
        canonical = configuration["model_key"]
        group = groups.setdefault(
            canonical,
            {
                "model_key": canonical,
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
        "weights": THIRD_PARTY_WEIGHTS,
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
        effort = str(record.get("reasoning_effort") or "unknown")
        key = (agent.casefold(), model.casefold(), effort.casefold())
        score = sum(values[name] * weight for name, weight in LOCAL_METRIC_WEIGHTS.items())
        grouped[key][str(record.get("case_id") or "unknown")].append(score)
        identity[key] = {"agent": agent, "model": model, "reasoning_effort": effort}

    result = []
    for key, cases in grouped.items():
        item = identity[key]
        case_scores = {case_id: round(sum(scores) / len(scores), 2) for case_id, scores in cases.items()}
        local_score = round(sum(case_scores.values()) / len(case_scores), 2)
        tested = set(case_scores)
        missing = sorted(expected_cases - tested)
        minimum_repeats = min((len(scores) for scores in cases.values()), default=0)
        result.append(
            {
                **item,
                "model_key": canonical_model_key(item["model"], aliases=aliases),
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


def build_agent_overview(models: list[dict[str, Any]]) -> dict[str, Any]:
    baselines: dict[str, dict[str, Any]] = {}
    baselines_by_name: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for model in models:
        if _source_type(model) != "artificial_analysis_model":
            continue
        source = model.get("source") or {}
        baselines_by_name[canonical_model_key(model.get("model"), creator=source.get("creator_name") or model.get("tool"))].append(model)
        for variant in source.get("variants") or []:
            if not isinstance(variant, dict):
                continue
            for value in (variant.get("slug"), variant.get("id")):
                if value:
                    baselines[str(value)] = model
    agents = [model for model in models if _source_type(model) == "artificial_analysis_agent"]
    agents.sort(key=lambda model: int((model.get("source") or {}).get("rank") or 10**9))
    rows = []
    for model in agents:
        source = model.get("source") or {}
        creator = source.get("creator") if isinstance(source.get("creator"), dict) else {}
        canonical = canonical_model_key(model.get("model"), creator=creator.get("model"))
        candidates = baselines_by_name.get(canonical, [])
        agent_effort = str(model.get("reasoning_effort") or split_model_effort(model.get("model"))[1]).casefold()
        exact = baselines.get(str(source.get("host_model_slug") or ""))
        effort_matches = [candidate for candidate in candidates if str(candidate.get("reasoning_effort") or split_model_effort(candidate.get("model"))[1]).casefold() == agent_effort]
        baseline = effort_matches[0] if effort_matches else exact or (candidates[0] if candidates else None)
        baseline_effort = str(baseline.get("reasoning_effort") or split_model_effort(baseline.get("model"))[1]).casefold() if baseline else ""
        same_configuration = baseline is not None and agent_effort == baseline_effort
        agent_score = (model.get("scores") or {}).get("aa_terminal_bench_v4")
        baseline_score = (baseline.get("scores") or {}).get("aa_model_terminal_bench_v4") if baseline else None
        uplift = (
            round(float(agent_score) - float(baseline_score), 2)
            if same_configuration and isinstance(agent_score, (int, float)) and isinstance(baseline_score, (int, float))
            else None
        )
        rows.append(
            {
                "agent": model,
                "baseline": baseline,
                "terminal_bench_uplift": uplift,
                "comparison_status": (
                    "comparable_terminal_bench_v4"
                    if uplift is not None
                    else "baseline_not_matched" if baseline is None else "configuration_mismatch" if not same_configuration else "shared_metric_missing"
                ),
            }
        )
    return {"agents": rows, "count": len(rows)}


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
