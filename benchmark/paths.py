"""Benchmark artifact paths, including identity-scoped Pelican workspaces."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

PELICAN_CASE = "draw-pelican-bicycle"


def path_component(value: Any) -> str:
    """Convert an identity value into a stable, filesystem-safe path component."""
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "-", str(value or "unknown")).strip(".-")
    return normalized or "unknown"


def load_identities(run_dir: Path) -> dict[str, Any]:
    manifest = run_dir / "run.json"
    if not manifest.is_file():
        return {}
    try:
        value = json.loads(manifest.read_text(encoding="utf-8")).get("identities", {})
    except (OSError, json.JSONDecodeError, AttributeError):
        return {}
    return value if isinstance(value, dict) else {}


def workspace_path(
    run_dir: Path,
    tool: str,
    case_id: str,
    identities: dict[str, Any] | None = None,
) -> Path:
    """Return the case workspace, scoping Pelican artifacts by execution identity."""
    identity = (identities or {}).get(tool)
    if case_id == PELICAN_CASE and isinstance(identity, dict):
        agent = identity.get("agent")
        model = identity.get("model")
        intelligence = identity.get("intelligence")
        if all(isinstance(value, str) and value.strip() for value in (agent, model, intelligence)):
            return (
                run_dir / "pelican" / path_component(agent) / path_component(model)
                / path_component(intelligence) / path_component(tool) / case_id
            )
    # Compatibility path for direct CLI use and historical runs without identities.
    return run_dir / tool / case_id
