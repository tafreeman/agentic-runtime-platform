"""Live model discovery for Foundry Local, the on-device ONNX runtime.

ARP-IMPROVEMENTS F2: Foundry Local was previously unprobed --
``enumerate_known_models`` covered cloud, Ollama, LM Studio, and ONNX only.
Reads the native REST API directly over ``httpx``, mirroring
:mod:`agentic_v2.models.ollama_discovery`'s best-effort shape (any probe
failure contributes no models; never raises).

**Naming trap -- read before grepping "foundry":**
:mod:`agentic_v2.models.backends` already handles a *different* Foundry --
Azure AI Foundry (``azure-foundry:`` prefix, ``AZURE_FOUNDRY_API_KEY``), a
paid cloud service. **Foundry Local** here is an unrelated on-device ONNX
runtime with no relationship to Azure. This module therefore uses the
``foundry-local:`` prefix, never bare ``foundry:``, so the two cannot collide
in a tier chain, a discovery merge, or a grep.

Source probed:

- ``GET {FOUNDRY_LOCAL_BASE_URL}/v1/models`` -- default
  ``http://127.0.0.1:60160`` (the port observed live; Foundry Local's actual
  listen port can vary by install -- set ``FOUNDRY_LOCAL_BASE_URL`` if this
  default does not match). OpenAI-compatible-shaped listing.

The exact response schema was not re-verified against a live instance as part
of this change (this session has no access to one); the parser tolerates a
``models`` list as a fallback to the documented ``data`` shape, and reads an
optional device/execution-provider hint under a few plausible key names, so a
shape drift degrades to "no models found" (or "no device hint") rather than
raising.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "http://127.0.0.1:60160"
ENV_BASE_URL = "FOUNDRY_LOCAL_BASE_URL"

_MODELS_PATH = "/v1/models"
_TIMEOUT_SECONDS = 5.0
_MODEL_PREFIX = "foundry-local:"
_DEVICE_KEYS = ("device", "executionProvider", "execution_provider")


@dataclass(frozen=True)
class FoundryLocalModelInfo:
    """A single model discovered from a live Foundry Local probe."""

    id: str  # provider-prefixed, e.g. "foundry-local:qwen2.5-coder-7b"
    name: str  # raw upstream alias
    device: str | None = None  # e.g. "NPU", "GPU", "CPU" when the API reports one

    def to_dict(self) -> dict[str, Any]:
        """JSON-serialisable view for API responses."""
        return {"id": self.id, "name": self.name, "device": self.device}


def _get_json(url: str) -> dict[str, Any] | None:
    """GET ``url`` and return a parsed JSON object, or ``None`` on any failure."""
    try:
        response = httpx.get(url, timeout=_TIMEOUT_SECONDS)
        response.raise_for_status()
        data = response.json()
    except Exception as exc:
        logger.debug("Foundry Local probe failed for %s: %s", url, exc)
        return None
    return data if isinstance(data, dict) else None


def _base_url() -> str:
    return os.environ.get(ENV_BASE_URL, DEFAULT_BASE_URL).rstrip("/")


def _device_hint(entry: dict[str, Any]) -> str | None:
    for key in _DEVICE_KEYS:
        value = entry.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _parse_models(data: dict[str, Any]) -> list[FoundryLocalModelInfo]:
    entries = data.get("data") or data.get("models") or []
    if not isinstance(entries, list):
        return []

    discovered: list[FoundryLocalModelInfo] = []
    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        name = entry.get("id") or entry.get("name") or entry.get("alias")
        if not isinstance(name, str) or not name:
            continue
        model_id = name if name.startswith(_MODEL_PREFIX) else f"{_MODEL_PREFIX}{name}"
        if model_id in seen:
            continue
        seen.add(model_id)
        discovered.append(
            FoundryLocalModelInfo(id=model_id, name=name, device=_device_hint(entry))
        )
    return discovered


def discover_foundry_local_models() -> list[FoundryLocalModelInfo]:
    """Discover models Foundry Local currently lists (best-effort).

    Returns an empty list when the service is unreachable, misconfigured, or
    its response does not match the shapes this parser tolerates. Never
    raises.
    """
    data = _get_json(f"{_base_url()}{_MODELS_PATH}")
    if not data:
        return []
    return _parse_models(data)


__all__ = ["FoundryLocalModelInfo", "discover_foundry_local_models"]
