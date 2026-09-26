"""Build a compact, deterministic, allow-listed evidence snapshot for AI analysis."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import defaultdict
from typing import Any

from .leaderboards import build_model_overview, model_configuration, split_model_effort


_MODEL_SCORES = {
    "artificial_analysis_model": ("aa_model_intelligence", "AA Intelligence Index", "分"),
    "arena_webdev": ("arena_webdev", "Arena WebDev rating", "rating"),
    "llm_stats": ("llm_stats_score", "LLM Stats Score", "分"),
}
_AGENT_SCORES = {
    "artificial_analysis_index": ("AA Coding Agent Index", "分"),
    "aa_deep_swe": ("DeepSWE", "分"),
    "aa_deep_swe_v1_1": ("DeepSWE v1.1", "分"),
    "aa_terminal_bench_v2": ("Terminal-Bench v2", "分"),
    "aa_terminal_bench_v4": ("Terminal-Bench v4", "分"),
    "aa_swe_atlas_qna": ("SWE Atlas Q&A", "分"),
}
_MANUAL_SCORES = {
    "skill_call": ("Skill 调用", "原始分"),
    "code_review": ("Code Review", "原始分"),
    "logic_analysis": ("逻辑分析", "原始分"),
    "function_fix": ("功能修复", "原始分"),
    "manual_total": ("人工评分合计", "原始分"),
    "model_test_correction": ("ModelTest 修正", "原始分"),
    "model_test_generation": ("ModelTest 生成", "原始分"),
    "model_test_logic": ("ModelTest 逻辑", "原始分"),
    "model_test_total": ("ModelTest 综合分", "原始分"),
    "arena_webdev": ("Arena WebDev rating", "原始分"),
    "aa_model_intelligence": ("AA Intelligence Index", "原始分"),
    "aa_model_speed": ("AA 输出速度", "tokens/s"),
    "aa_model_cost_per_task": ("AA 单任务成本", "单位未知"),
    "aa_model_terminal_bench_v4": ("AA Terminal-Bench v4", "原始分"),
    "artificial_analysis_index": ("AA Coding Agent Index", "原始分"),
    "aa_deep_swe": ("DeepSWE", "原始分"),
    "aa_deep_swe_v1_1": ("DeepSWE v1.1", "原始分"),
    "aa_terminal_bench_v2": ("Terminal-Bench v2", "原始分"),
    "aa_terminal_bench_v4": ("Terminal-Bench v4", "原始分"),
    "aa_swe_atlas_qna": ("SWE Atlas Q&A", "原始分"),
    "llm_stats_score": ("LLM Stats Score", "原始分"),
    "llm_stats_reasoning": ("LLM Stats Reasoning", "原始分"),
    "llm_stats_code": ("LLM Stats Code", "原始分"),
    "llm_stats_agents": ("LLM Stats Agents", "原始分"),
    "composite_total": ("原表综合分", "原始分"),
}
_MANUAL_SOURCE_TYPES = {"manual", "excel", "third_party"}
_LOCAL_METRICS = (
    "Task Correctness",
    "Robustness, Safety and Regression",
    "Delivery Evidence",
)
_SCORE_FIELDS = frozenset(_MANUAL_SCORES)
_TIMESTAMP = re.compile(
    r"^\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})?)?$"
)
_CASE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,99}$")
_URL = re.compile(r"https?://[^\s]+", re.IGNORECASE)
_ABSOLUTE_PATH = re.compile(r"(?<![A-Za-z0-9])(?:/Users/|/home/|/private/|[A-Za-z]:\\)[^\s,;]+")
_SECRET = re.compile(
    r"\b(?:Bearer\s+\S+|sk-[A-Za-z0-9_-]{8,}|gh[pousr]_[A-Za-z0-9]{8,}|AKIA[0-9A-Z]{16})\b",
    re.IGNORECASE,
)


def _canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _stable_id(prefix: str, identity: Any) -> str:
    digest = hashlib.sha256(_canonical_json(identity).encode("utf-8")).hexdigest()[:20]
    return f"{prefix}_{digest}"


def _number(value: Any) -> int | float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(float(value)):
        return None
    return value


def _public_text(value: Any, *, limit: int = 160) -> str:
    if not isinstance(value, str):
        return ""
    text = "".join(character for character in value if character.isprintable()).strip()
    text = _SECRET.sub("[secret omitted]", text)
    text = _URL.sub("[URL omitted]", text)
    text = _ABSOLUTE_PATH.sub("[path omitted]", text)
    return text[:limit]


def _timestamp(value: Any) -> str:
    if isinstance(value, str) and len(value) <= 64 and _TIMESTAMP.fullmatch(value.strip()):
        return value.strip()
    return ""


def _time_fields(record: dict[str, Any], *, local: bool = False) -> dict[str, str]:
    source = record.get("source") if isinstance(record.get("source"), dict) else {}
    fetched_at = _timestamp(source.get("fetched_at"))
    updated_at = _timestamp(source.get("updated_at"))
    record_updated_at = _timestamp(record.get("updated_at"))
    created_at = _timestamp(record.get("created_at"))
    result = {
        "as_of": fetched_at or updated_at or record_updated_at or created_at,
    }
    if fetched_at:
        result["fetched_at"] = fetched_at
    if updated_at:
        result["updated_at"] = updated_at
    if record_updated_at:
        result["record_updated_at"] = record_updated_at
    if local and created_at:
        result["as_of"] = created_at
    return result


def _evidence(
    candidate: dict[str, Any],
    key: str,
    label: str,
    value: Any,
    unit: str,
    source: str,
    times: dict[str, str] | None = None,
) -> dict[str, Any] | None:
    number = _number(value)
    if number is None:
        return None
    result: dict[str, Any] = {
        "id": _stable_id("e", {"candidate": candidate["id"], "key": key}),
        "label": label,
        "value": number,
        "unit": unit,
        "source": source,
        "as_of": "",
    }
    if times:
        result["as_of"] = times.get("as_of", "")
        for field in ("fetched_at", "updated_at", "record_updated_at"):
            if times.get(field):
                result[field] = times[field]
    return result


def _source_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _normalized_aliases(value: Any) -> dict[str, str] | None:
    if not isinstance(value, dict):
        return None
    aliases = {
        key: target
        for key, target in value.items()
        if isinstance(key, str) and isinstance(target, str) and key.strip() and target.strip()
    }
    return aliases or None


def _clean_for_overview(raw: dict[str, Any]) -> dict[str, Any] | None:
    model = _public_text(raw.get("model"))
    tool = _public_text(raw.get("tool"))
    if not model or not tool:
        return None
    source = _source_dict(raw.get("source"))
    source_type = source.get("type") if isinstance(source.get("type"), str) else ""
    clean_source: dict[str, Any] = {"type": source_type}
    for field in (
        "source_id", "rank", "organization", "creator_name", "fetched_at", "updated_at",
        "input_price_per_m", "output_price_per_m", "price_1m_input", "price_1m_output",
        "price_1m_blended", "intelligence_cost_per_task", "intelligence_time_per_task",
    ):
        value = source.get(field)
        if field == "rank":
            numeric = _number(value)
            if numeric is not None:
                clean_source[field] = numeric
        elif field in {"input_price_per_m", "output_price_per_m", "price_1m_input", "price_1m_output",
                       "price_1m_blended", "intelligence_cost_per_task", "intelligence_time_per_task"}:
            numeric = _number(value)
            if numeric is not None:
                clean_source[field] = numeric
        elif field == "source_id":
            if isinstance(value, str):
                clean_source[field] = value
        elif field in {"fetched_at", "updated_at"}:
            timestamp = _timestamp(value)
            if timestamp:
                clean_source[field] = timestamp
        elif isinstance(value, str):
            clean_source[field] = _public_text(value)

    if isinstance(source.get("release"), dict):
        release_name = _public_text(source["release"].get("name"))
        if release_name:
            clean_source["release"] = {"name": release_name}

    variants = []
    raw_variants = source.get("variants")
    if isinstance(raw_variants, list):
        for variant in raw_variants:
            if not isinstance(variant, dict):
                continue
            clean_variant: dict[str, Any] = {}
            for field in ("id", "slug", "name"):
                value = variant.get(field)
                if isinstance(value, str):
                    clean_variant[field] = _public_text(value)
            for field in (
                "input_price_per_m", "output_price_per_m", "price_1m_blended",
                "cost_usd_per_task", "intelligence_cost_per_task", "intelligence_time_per_task",
                "speed_tokens_per_second",
            ):
                numeric = _number(variant.get(field))
                if numeric is not None:
                    clean_variant[field] = numeric
            if clean_variant:
                variants.append(clean_variant)
    if variants:
        clean_source["variants"] = variants

    raw_scores = raw.get("scores") if isinstance(raw.get("scores"), dict) else {}
    scores = {field: _number(raw_scores.get(field)) for field in _SCORE_FIELDS}
    return {
        "id": raw.get("id") if isinstance(raw.get("id"), str) else "",
        "tool": tool,
        "model": model,
        "reasoning_effort": _public_text(raw.get("reasoning_effort"), limit=80),
        "scores": scores,
        "source": clean_source,
        "updated_at": _timestamp(raw.get("updated_at")),
    }


def _sanitize_local_records(
    records: Any,
    expected_cases: set[str],
) -> tuple[list[dict[str, Any]], int, int]:
    if not isinstance(records, list):
        return [], 0, 0
    cleaned: list[dict[str, Any]] = []
    scored_count = 0
    unscored_count = 0
    for raw in records:
        if not isinstance(raw, dict):
            continue
        tool_value = raw.get("agent") if isinstance(raw.get("agent"), str) and raw.get("agent").strip() else raw.get("tool")
        tool = _public_text(tool_value)
        model = _public_text(raw.get("model"))
        case_id = raw.get("case_id")
        if not tool or not model or not isinstance(case_id, str) or not _CASE_ID.fullmatch(case_id) or case_id in {".", ".."}:
            continue
        raw_metrics = raw.get("metrics") if isinstance(raw.get("metrics"), dict) else {}
        metrics: dict[str, dict[str, Any]] = {}
        complete = True
        for name in _LOCAL_METRICS:
            metric = raw_metrics.get(name) if isinstance(raw_metrics.get(name), dict) else {}
            score = _number(metric.get("score"))
            if score is None or not 0 <= float(score) <= 1:
                complete = False
                metrics[name] = {"score": None}
            else:
                metrics[name] = {"score": score}
        scored_count += int(complete)
        unscored_count += int(not complete)
        elapsed = _number(raw.get("elapsed_seconds"))
        if elapsed is not None and elapsed < 0:
            elapsed = None
        record = {
            "agent": tool,
            "model": model,
            "reasoning_effort": _public_text(raw.get("reasoning_effort"), limit=80),
            "case_id": case_id,
            "metrics": metrics,
            "elapsed_seconds": elapsed,
            "created_at": _timestamp(raw.get("created_at")),
        }
        cleaned.append(record)
    return cleaned, scored_count, unscored_count


def _manual_scores(record: dict[str, Any]) -> dict[str, int | float]:
    scores = record.get("scores") if isinstance(record.get("scores"), dict) else {}
    valid = {field: number for field in _MANUAL_SCORES if (number := _number(scores.get(field))) is not None}

    # These persisted totals are derived with zero-filled missing parts by the legacy
    # import path. Include them only when every contributing field is present.
    manual_parts = ("skill_call", "code_review", "logic_analysis", "function_fix")
    if not all(part in valid for part in manual_parts):
        valid.pop("manual_total", None)
    model_test_parts = ("model_test_correction", "model_test_generation", "model_test_logic")
    if not all(part in valid for part in model_test_parts):
        valid.pop("model_test_total", None)
    if not all(part in valid for part in ("manual_total", "model_test_total", "arena_webdev")):
        valid.pop("composite_total", None)

    # This field's currency is not part of the input schema, so it is not usable
    # as a cost comparison even when the stored value is numeric.
    valid.pop("aa_model_cost_per_task", None)
    return valid


def build_insight_snapshot(data: dict[str, Any], local: dict[str, Any], expected_cases: set[str]) -> dict[str, Any]:
    """Return only stable, finite, allow-listed evidence for one AI analysis."""
    data = data if isinstance(data, dict) else {}
    local = local if isinstance(local, dict) else {}
    expected = {case for case in expected_cases if isinstance(case, str) and _CASE_ID.fullmatch(case) and case not in {".", ".."}}

    raw_models = data.get("models") if isinstance(data.get("models"), list) else []
    active_raw = [row for row in raw_models if isinstance(row, dict) and row.get("archived") is not True]
    archived_count = sum(1 for row in raw_models if isinstance(row, dict) and row.get("archived") is True)
    active_models = [clean for row in active_raw if (clean := _clean_for_overview(row)) is not None]
    local_records, local_scored_count, local_unscored_count = _sanitize_local_records(local.get("records"), expected)
    aliases = _normalized_aliases(data.get("model_aliases"))
    meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
    weights = meta.get("leaderboard_weights") if isinstance(meta.get("leaderboard_weights"), dict) else None
    overview = build_model_overview(active_models, local_records, expected, aliases=aliases, weights=weights)

    candidates: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    support: dict[str, bool] = defaultdict(bool)
    evidence_keys: dict[str, set[str]] = defaultdict(set)

    def candidate_for(
        kind: str,
        identity: dict[str, str],
        model: str,
        tool: str,
        effort: str,
    ) -> dict[str, Any]:
        key = (kind, identity.get("tool_key", ""), identity.get("model_key", ""), identity.get("effort", ""))
        candidate = candidates.get(key)
        if candidate is None:
            candidate = {
                "id": _stable_id(kind, identity),
                "kind": kind,
                "model": model,
                "tool": tool,
                "reasoning_effort": effort,
                "evidence": [],
            }
            candidates[key] = candidate
        else:
            if model and (not candidate["model"] or (model.casefold(), model) < (candidate["model"].casefold(), candidate["model"])):
                candidate["model"] = model
            if tool and (not candidate["tool"] or (tool.casefold(), tool) < (candidate["tool"].casefold(), candidate["tool"])):
                candidate["tool"] = tool
        return candidate

    def add_evidence(
        candidate: dict[str, Any],
        key: str,
        label: str,
        value: Any,
        unit: str,
        source: str,
        times: dict[str, str] | None = None,
        *,
        qualifies: bool = False,
    ) -> None:
        if key in evidence_keys[candidate["id"]]:
            return
        evidence = _evidence(candidate, key, label, value, unit, source, times)
        if evidence is None:
            return
        evidence_keys[candidate["id"]].add(key)
        candidate["evidence"].append(evidence)
        if qualifies:
            support[candidate["id"]] = True

    # A model candidate groups only the model identity and normalized effort,
    # matching the dashboard's existing external-source comparison.
    for row in overview["models"]:
        model_key = row["model_key"]
        effort = row["reasoning_effort"]
        identity = {"model_key": model_key, "effort": effort}
        sources = row.get("sources") if isinstance(row.get("sources"), dict) else {}
        representative = None
        for source_type in ("artificial_analysis_model", "arena_webdev", "llm_stats"):
            source_group = sources.get(source_type)
            if isinstance(source_group, dict) and isinstance(source_group.get("representative"), dict):
                representative = source_group["representative"]
                if source_type == "artificial_analysis_model":
                    break
        model = _public_text(row.get("model") or (representative or {}).get("model"))
        tool = _public_text((representative or {}).get("tool"))
        candidate = candidate_for("model", identity, model, tool, effort)

        for source_type in ("artificial_analysis_model", "arena_webdev", "llm_stats"):
            source_group = sources.get(source_type)
            if not isinstance(source_group, dict) or not isinstance(source_group.get("representative"), dict):
                continue
            record = source_group["representative"]
            times = _time_fields(record)
            raw_score, _, raw_unit = _MODEL_SCORES[source_type]
            add_evidence(
                candidate, f"{source_type}:raw-score", f"{source_type} 原始分", source_group.get("raw_score"),
                raw_unit, source_type, times, qualifies=True,
            )
            add_evidence(
                candidate, f"{source_type}:normalized-score", f"{source_type} 来源内归一化分",
                source_group.get("normalized_score"), "分（来源内 0–100）", source_type, times, qualifies=True,
            )
            scores = record.get("scores") if isinstance(record.get("scores"), dict) else {}
            if source_type == "artificial_analysis_model":
                speed = _number(scores.get("aa_model_speed"))
                add_evidence(candidate, "aa-model:speed", "AA 输出速度", speed, "tokens/s", source_type, times)
                source = _source_dict(record.get("source"))
                for field, label in (
                    ("price_1m_input", "AA 每百万输入 Token 价格"),
                    ("price_1m_output", "AA 每百万输出 Token 价格"),
                    ("price_1m_blended", "AA 每百万 Token 混合价格"),
                    ("intelligence_cost_per_task", "AA Intelligence 单任务成本"),
                    ("intelligence_time_per_task", "AA Intelligence 单任务耗时"),
                ):
                    value = _number(source.get(field))
                    units = "USD / 1M tokens" if field.startswith("price_1m_") else "USD / task" if field.endswith("cost_per_task") else "seconds / task"
                    add_evidence(
                        candidate, f"aa-model:{field}", label, value, units, source_type, times,
                        qualifies=field.startswith("price_1m_") or field.endswith("cost_per_task"),
                    )
                variants = source.get("variants") if isinstance(source.get("variants"), list) else []
                matching_variants = []
                if effort != "unknown":
                    for variant in variants:
                        if not isinstance(variant, dict):
                            continue
                        variant_name = _public_text(variant.get("name") or variant.get("slug"), limit=100)
                        variant_effort = split_model_effort(variant_name)[1]
                        if variant_effort and model_configuration({"model": variant_name, "reasoning_effort": variant_effort})[1] == effort:
                            matching_variants.append((variant_name.casefold(), variant_name, variant))
                for variant_index, (_, variant_name, variant) in enumerate(sorted(matching_variants), 1):
                    variant_key = _stable_id("v", variant.get("id") or variant.get("slug") or variant_name)
                    for field, label, unit, is_cost in (
                        ("input_price_per_m", "输入价格", "USD / 1M tokens", True),
                        ("output_price_per_m", "输出价格", "USD / 1M tokens", True),
                        ("price_1m_blended", "混合价格", "USD / 1M tokens", True),
                        ("cost_usd_per_task", "单任务成本", "USD / task", True),
                        ("intelligence_time_per_task", "单任务耗时", "seconds / task", False),
                        ("speed_tokens_per_second", "输出速度", "tokens/s", False),
                    ):
                        value = _number(variant.get(field))
                        add_evidence(
                            candidate,
                            f"aa-model:variant:{variant_key}:{field}",
                            f"AA 服务配置 {variant_index} {label}", value, unit, source_type, times,
                            qualifies=is_cost,
                        )

        aggregate = _number(row.get("third_party_score"))
        add_evidence(
            candidate, "third-party:aggregate", "三方榜单加权综合分", aggregate,
            "分（0–100）", "leaderboard_aggregate", qualifies=True,
        )

    # AA Agent evidence and local benchmark evidence share a candidate only if
    # the exact tool, canonical model, and reasoning effort all match.
    for record in active_models:
        source = _source_dict(record.get("source"))
        if source.get("type") not in {"artificial_analysis_agent", "artificial_analysis"}:
            continue
        model_key, effort = model_configuration(record, aliases)
        tool = _public_text(record.get("tool"))
        model = _public_text(split_model_effort(record.get("model"))[0] or record.get("model"))
        if not tool or not model_key:
            continue
        identity = {"tool_key": tool.casefold(), "model_key": model_key, "effort": effort}
        candidate = candidate_for("agent", identity, model, tool, effort)
        scores = record.get("scores") if isinstance(record.get("scores"), dict) else {}
        times = _time_fields(record)
        source_identity = source.get("source_id") or record.get("id") or ""
        record_key = _stable_id("r", source_identity or {"tool": tool, "model": model_key, "effort": effort, "scores": scores})
        for field, (label, unit) in _AGENT_SCORES.items():
            add_evidence(
                candidate, f"aa-agent:{record_key}:{field}", label, scores.get(field), unit,
                "artificial_analysis_agent", times, qualifies=True,
            )
        for field, label, unit, qualifies in (
            ("cost_usd_per_task", "AA Agent 单任务成本", "USD / task", True),
            ("wall_time_seconds_per_task", "AA Agent 单任务耗时", "seconds / task", False),
        ):
            add_evidence(
                candidate, f"aa-agent:{record_key}:{field}", label, source.get(field), unit,
                "artificial_analysis_agent", times, qualifies=qualifies,
            )

    local_records_by_identity: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for record in local_records:
        model_key, effort = model_configuration(record, aliases)
        local_records_by_identity[(record["agent"].casefold(), model_key, effort)].append(record)

    local_candidate_count = 0
    local_eligible_count = 0
    insufficient_local_count = 0
    for row in overview["models"]:
        for config in row.get("local_configurations", []):
            tool = _public_text(config.get("agent"))
            model = _public_text(config.get("model"))
            model_key = config.get("model_key", "")
            effort = config.get("reasoning_effort", "unknown")
            if not tool or not model_key:
                continue
            identity = {"tool_key": tool.casefold(), "model_key": model_key, "effort": effort}
            candidate = candidate_for("agent", identity, model, tool, effort)
            local_candidate_count += 1
            local_eligible_count += int(config.get("eligible") is True)
            insufficient_local_count += int(config.get("eligible") is not True)
            records = local_records_by_identity.get((tool.casefold(), model_key, effort), [])
            times = {"as_of": max((entry["created_at"] for entry in records if entry.get("created_at")), default="")}

            add_evidence(
                candidate, "local:score", "本地已测任务综合分", config.get("local_score"),
                "分（0–100）", "local_benchmark", times, qualifies=True,
            )
            case_scores = config.get("case_scores") if isinstance(config.get("case_scores"), dict) else {}
            for case_id, score in sorted(case_scores.items()):
                if not isinstance(case_id, str) or not _CASE_ID.fullmatch(case_id):
                    continue
                case_records = [entry for entry in records if entry.get("case_id") == case_id]
                case_times = {"as_of": max((entry["created_at"] for entry in case_records if entry.get("created_at")), default="")}
                add_evidence(
                    candidate, f"local:case:{case_id}:score", f"本地任务 {case_id} 综合分", score,
                    "分（0–100）", "local_benchmark", case_times, qualifies=True,
                )
                elapsed_values = [entry["elapsed_seconds"] for entry in case_records if _number(entry.get("elapsed_seconds")) is not None]
                if elapsed_values:
                    add_evidence(
                        candidate, f"local:case:{case_id}:elapsed", f"本地任务 {case_id} 平均执行耗时",
                        sum(elapsed_values) / len(elapsed_values), "seconds", "local_benchmark", case_times,
                    )
            for field, label, unit, value in (
                ("coverage", "本地任务覆盖率", "%", config.get("coverage")),
                ("case-count", "本地已测任务数", "cases", config.get("case_count")),
                ("expected-case-count", "预期任务数", "cases", config.get("expected_case_count")),
                ("minimum-repeats", "每任务最少重复次数", "runs", config.get("minimum_repeats")),
                ("eligible", "本地覆盖可比性（1=达标）", "bool", int(config.get("eligible") is True)),
            ):
                add_evidence(candidate, f"local:{field}", label, value, unit, "local_benchmark", times)

    # User-authored measurements are kept as independent raw-score candidates.
    # Saved recommendations are intentionally not read or treated as evidence.
    manual_groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for raw in active_raw:
        raw_source = raw.get("source")
        source = _source_dict(raw_source)
        source_type = source.get("type") if isinstance(source.get("type"), str) else "manual" if raw_source is None else ""
        if source_type not in _MANUAL_SOURCE_TYPES:
            continue
        record = _clean_for_overview(raw)
        if record is None:
            continue
        model_key, effort = model_configuration(record, aliases)
        manual_groups[(record["tool"].casefold(), model_key, effort)].append(record)

    for group_key, records in manual_groups.items():
        records.sort(key=lambda record: (
            record.get("id") or "",
            _canonical_json({field: record["scores"].get(field) for field in sorted(_MANUAL_SCORES)}),
        ))
        for index, record in enumerate(records):
            scores = _manual_scores(record)
            if not scores:
                continue
            model_key, effort = model_configuration(record, aliases)
            record_id = record.get("id")
            manual_identity = {
                "tool_key": group_key[0],
                "model_key": model_key,
                "effort": effort,
                "record_id": record_id if record_id else f"duplicate:{index}",
            }
            model = _public_text(split_model_effort(record.get("model"))[0] or record.get("model"))
            tool = _public_text(record.get("tool"))
            candidate = candidate_for("manual", manual_identity, model, tool, effort)
            times = _time_fields(record)
            source = _source_dict(record.get("source"))
            source_type = source.get("type") if isinstance(source.get("type"), str) else "manual"
            for field, value in scores.items():
                label, unit = _MANUAL_SCORES[field]
                # Do not treat the undocumented-currency cost field as evidence.
                if field == "aa_model_cost_per_task":
                    continue
                add_evidence(
                    candidate, f"manual:{record_id or index}:{field}", label, value,
                    unit, f"manual:{source_type}", times, qualifies=True,
                )

    output_candidates = []
    for candidate in candidates.values():
        if not support[candidate["id"]]:
            continue
        candidate["evidence"].sort(key=lambda item: (item["source"], item["label"], item["id"]))
        output_candidates.append(candidate)
    output_candidates.sort(key=lambda item: (
        item["kind"], item["tool"].casefold(), item["model"].casefold(),
        item["reasoning_effort"], item["id"],
    ))

    all_evidence = [item for candidate in output_candidates for item in candidate["evidence"]]
    kind_counts = {kind: sum(candidate["kind"] == kind for candidate in output_candidates) for kind in ("model", "agent", "manual")}
    source_counts = dict(sorted({
        source: sum(evidence["source"] == source for evidence in all_evidence)
        for source in {evidence["source"] for evidence in all_evidence}
    }.items()))

    warnings: list[str] = []
    if not expected:
        warnings.append("未提供有效的预期本地任务清单，无法判断本地测试覆盖是否可比。")
    if insufficient_local_count:
        warnings.append(f"{insufficient_local_count} 个本地配置未达到完整任务覆盖或每任务最少重复次数要求；其均分只代表已测任务。")
    if local_unscored_count:
        warnings.append(f"{local_unscored_count} 条本地运行记录没有完整有效评分，未纳入本地得分。")
    local_warnings = local.get("warnings")
    local_warning_count = len(local_warnings) if isinstance(local_warnings, list) else 0
    if local_warning_count:
        warnings.append(f"本地数据读取或评分有 {local_warning_count} 条警告；摘要不包含警告内容、路径或日志。")
    if not active_models:
        warnings.append("当前没有可用的 active 模型数据。")
    if not output_candidates:
        warnings.append("当前没有包含有效数值分数或明确单位成本的候选。")

    return {
        "candidates": output_candidates,
        "coverage": {
            "candidate_count": len(output_candidates),
            "evidence_count": len(all_evidence),
            "model_candidate_count": kind_counts["model"],
            "agent_candidate_count": kind_counts["agent"],
            "manual_candidate_count": kind_counts["manual"],
            "local_candidate_count": local_candidate_count,
            "local_eligible_candidate_count": local_eligible_count,
            "active_model_count": len(active_models),
            "archived_model_count": archived_count,
            "local_record_count": len(local_records),
            "local_scored_record_count": local_scored_count,
            "local_unscored_record_count": local_unscored_count,
            "expected_case_count": len(expected),
            "local_warning_count": local_warning_count,
            "evidence_source_counts": source_counts,
        },
        "warnings": warnings,
        "methodology": {
            "grouping": "模型按 canonical model + normalized reasoning_effort 分组；Agent 按精确 tool + canonical model + reasoning_effort 分组。",
            "third_party_normalization": "复用 build_model_overview 的来源内 min-max 归一化与有效来源加权综合分。",
            "third_party_weights": overview["weights"],
            "local_scoring": "复用 build_model_overview 的本地指标权重、按任务平均分、预期任务覆盖和最少重复次数资格。",
            "local_metric_weights": overview["local_metric_weights"],
            "minimum_local_repeats": overview["minimum_local_repeats"],
            "manual_records": "手工或导入分数单独保留原始值；不与外部来源合并，也不读取手工推荐。",
            "missing_values": "缺失或非有限数值不投影；显式数值 0 保留。",
            "field_projection": "仅输出模型与工具身份、允许的数值指标、来源类型和有效时间戳；不投影备注、补充说明、URL、路径或日志。",
        },
    }
