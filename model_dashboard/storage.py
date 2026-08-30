from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any

from .domain import (
    DashboardError,
    normalize_agent_usage_entry,
    normalize_model,
    utc_now,
)


ROOT = Path(__file__).resolve().parent
SEED_PATH = ROOT / "seed_data.json"
DEFAULT_DATA_PATH = ROOT / "data.local.json"


class DashboardStore:
    def __init__(self, seed_path: Path = SEED_PATH, data_path: Path = DEFAULT_DATA_PATH):
        self.seed_path = seed_path
        self.data_path = data_path
        self._lock = threading.Lock()

    def read(self) -> dict[str, Any]:
        path = self.data_path if self.data_path.exists() else self.seed_path
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise DashboardError(f"无法读取看板数据：{error}") from error
        if not isinstance(data, dict) or not isinstance(data.get("models"), list):
            raise DashboardError("看板数据格式无效")
        return data

    def write(self, data: dict[str, Any]) -> None:
        self.data_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.data_path.with_suffix(f"{self.data_path.suffix}.tmp")
        temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(self.data_path)

    def add_model(self, raw: Any) -> dict[str, Any]:
        if not isinstance(raw, dict):
            raise DashboardError("模型数据必须是对象")
        safe_raw = {key: value for key, value in raw.items() if key not in {"id", "source", "archived", "archived_at"}}
        model = normalize_model(safe_raw, source={"type": "manual", "name": "手工录入"})
        with self._lock:
            data = self.read()
            data["models"].append(model)
            data.setdefault("meta", {})["updated_at"] = utc_now()
            self.write(data)
        return model

    def upsert_agent_usage(self, raw: Any) -> tuple[dict[str, Any], bool]:
        entry = normalize_agent_usage_entry(raw)
        with self._lock:
            data = self.read()
            usage = data.get("agent_usage")
            if not isinstance(usage, list):
                usage = []
                data["agent_usage"] = usage
            key = entry["tool"].casefold()
            for index, current in enumerate(usage):
                if isinstance(current, dict) and str(current.get("tool", "")).casefold() == key:
                    usage[index] = entry
                    data.setdefault("meta", {})["updated_at"] = utc_now()
                    self.write(data)
                    return entry, False
            usage.append(entry)
            data.setdefault("meta", {})["updated_at"] = utc_now()
            self.write(data)
        return entry, True

    def import_agent_usage(self, entries: list[dict[str, Any]]) -> dict[str, int]:
        if not entries:
            raise DashboardError("没有可导入的使用人数")
        created = 0
        updated = 0
        with self._lock:
            data = self.read()
            usage = data.get("agent_usage")
            if not isinstance(usage, list):
                usage = []
                data["agent_usage"] = usage
            index_by_tool: dict[str, int] = {}
            for index, current in enumerate(usage):
                if isinstance(current, dict) and current.get("tool"):
                    index_by_tool[str(current["tool"]).casefold()] = index
            for raw in entries:
                entry = normalize_agent_usage_entry(raw)
                key = entry["tool"].casefold()
                if key in index_by_tool:
                    usage[index_by_tool[key]] = entry
                    updated += 1
                else:
                    index_by_tool[key] = len(usage)
                    usage.append(entry)
                    created += 1
            data.setdefault("meta", {})["updated_at"] = utc_now()
            self.write(data)
        return {"created": created, "updated": updated, "received": len(entries)}

    def set_model_archived(self, model_id: str, archived: bool) -> dict[str, Any]:
        with self._lock:
            data = self.read()
            matches = [item for item in data["models"] if item.get("id") == model_id]
            if not matches:
                raise DashboardError("模型记录不存在")
            if len(matches) > 1:
                raise DashboardError("本地数据包含重复的模型 ID，拒绝修改")
            model = matches[0]
            model["archived"] = archived
            model["archived_at"] = utc_now() if archived else ""
            model["updated_at"] = utc_now()
            data.setdefault("meta", {})["updated_at"] = utc_now()
            self.write(data)
        return model

    def import_models(self, models: list[dict[str, Any]], overwrite: bool) -> dict[str, int]:
        created = 0
        updated = 0
        skipped = 0
        with self._lock:
            data = self.read()
            existing = {
                self._model_key(model): index
                for index, model in enumerate(data["models"])
            }
            for model in models:
                key = self._model_key(model)
                if key in existing:
                    if overwrite:
                        current = data["models"][existing[key]]
                        model["id"] = current.get("id", model["id"])
                        self._preserve_archive(current, model)
                        data["models"][existing[key]] = model
                        updated += 1
                    else:
                        skipped += 1
                else:
                    existing[key] = len(data["models"])
                    data["models"].append(model)
                    created += 1
            data.setdefault("meta", {})["updated_at"] = utc_now()
            self.write(data)
        return {"created": created, "updated": updated, "skipped": skipped}

    def sync_arena_webdev(self, models: list[dict[str, Any]]) -> dict[str, int]:
        with self._lock:
            data = self.read()
            previous = {
                str(model.get("model", "")).casefold(): model
                for model in data["models"]
                if self._source_type(model) == "arena_webdev"
            }
            retained = [
                model
                for model in data["models"]
                if self._source_type(model) != "arena_webdev"
            ]
            created = 0
            updated = 0
            synced_keys: set[str] = set()
            for model in models:
                key = str(model.get("model", "")).casefold()
                synced_keys.add(key)
                existing = previous.get(key)
                if existing:
                    model["id"] = existing.get("id", model["id"])
                    self._preserve_archive(existing, model)
                    updated += 1
                else:
                    created += 1
                retained.append(model)
            archived_history = [
                model
                for key, model in previous.items()
                if key not in synced_keys and model.get("archived") is True
            ]
            retained.extend(archived_history)
            removed = len(previous) - updated - len(archived_history)
            data["models"] = retained
            data.setdefault("meta", {})["updated_at"] = utc_now()
            data["meta"]["arena_webdev_updated_at"] = models[0]["source"]["fetched_at"]
            data["meta"]["arena_webdev_publish_date"] = models[0]["source"].get("leaderboard_publish_date", "")
            self.write(data)
        return {"created": created, "updated": updated, "removed": removed}

    def sync_artificial_analysis(self, models: list[dict[str, Any]]) -> dict[str, int]:
        with self._lock:
            data = self.read()
            previous = {
                str(model.get("source", {}).get("source_id", "")): model
                for model in data["models"]
                if self._source_type(model) == "artificial_analysis"
            }
            retained = [
                model
                for model in data["models"]
                if self._source_type(model) != "artificial_analysis"
            ]
            created = 0
            updated = 0
            synced_keys: set[str] = set()
            for model in models:
                source_id = str(model["source"]["source_id"])
                synced_keys.add(source_id)
                existing = previous.get(source_id)
                if existing:
                    model["id"] = existing.get("id", model["id"])
                    self._preserve_archive(existing, model)
                    updated += 1
                else:
                    created += 1
                retained.append(model)
            archived_history = [
                model
                for key, model in previous.items()
                if key not in synced_keys and model.get("archived") is True
            ]
            retained.extend(archived_history)
            removed = len(previous) - updated - len(archived_history)
            data["models"] = retained
            data.setdefault("meta", {})["updated_at"] = utc_now()
            data["meta"]["artificial_analysis_updated_at"] = models[0]["source"]["fetched_at"]
            data["meta"]["artificial_analysis_index_version"] = models[0]["source"]["index_version"]
            self.write(data)
        return {"created": created, "updated": updated, "removed": removed}

    def sync_llm_stats(self, models: list[dict[str, Any]]) -> dict[str, int]:
        with self._lock:
            data = self.read()
            previous = {
                str(model.get("source", {}).get("source_id", "")): model
                for model in data["models"]
                if self._source_type(model) == "llm_stats"
            }
            retained = [
                model
                for model in data["models"]
                if self._source_type(model) != "llm_stats"
            ]
            created = 0
            updated = 0
            synced_keys: set[str] = set()
            for model in models:
                source_id = str(model["source"]["source_id"])
                synced_keys.add(source_id)
                existing = previous.get(source_id)
                if existing:
                    model["id"] = existing.get("id", model["id"])
                    self._preserve_archive(existing, model)
                    updated += 1
                else:
                    created += 1
                retained.append(model)
            archived_history = [
                model
                for key, model in previous.items()
                if key not in synced_keys and model.get("archived") is True
            ]
            retained.extend(archived_history)
            removed = len(previous) - updated - len(archived_history)
            data["models"] = retained
            data.setdefault("meta", {})["updated_at"] = utc_now()
            data["meta"]["llm_stats_updated_at"] = models[0]["source"]["fetched_at"]
            self.write(data)
        return {"created": created, "updated": updated, "removed": removed}

    @staticmethod
    def _source_type(model: dict[str, Any]) -> str:
        source = model.get("source")
        return str(source.get("type", "")) if isinstance(source, dict) else ""

    @staticmethod
    def _preserve_archive(current: dict[str, Any], replacement: dict[str, Any]) -> None:
        replacement["archived"] = current.get("archived") is True
        replacement["archived_at"] = current.get("archived_at", "") if replacement["archived"] else ""

    @staticmethod
    def _model_key(model: dict[str, Any]) -> tuple[str, str, str]:
        return (
            str(model.get("tool", "")).casefold(),
            str(model.get("model", "")).casefold(),
            str(model.get("reasoning_effort", "")).casefold(),
        )


