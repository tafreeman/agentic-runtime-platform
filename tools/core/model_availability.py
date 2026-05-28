"""Model availability checks without importing tools.llm internals."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _load_discovery_results() -> dict[str, Any]:
    discovery_file = _repo_root() / "discovery_results.json"
    if not discovery_file.exists():
        return {}
    try:
        data = json.loads(discovery_file.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _discovered_models() -> set[str]:
    data = _load_discovery_results()
    providers = data.get("providers")
    if not isinstance(providers, dict):
        return set()

    discovered: set[str] = set()
    for provider_data in providers.values():
        if isinstance(provider_data, dict):
            available = provider_data.get("available", [])
        elif isinstance(provider_data, list):
            available = provider_data
        else:
            available = []
        if isinstance(available, list):
            discovered.update(str(item) for item in available if isinstance(item, str))
    return discovered


def is_model_available(model_id: str) -> bool:
    """Return True when a model appears available from local discovery data.

    If no discovery data exists, return True to avoid false negatives in
    lightweight script contexts.
    """
    model_id = (model_id or "").strip()
    if not model_id:
        return False

    discovered = _discovered_models()
    if not discovered:
        return True
    return model_id in discovered
