"""Live Ollama model discovery via the raw REST API (ADR-037).

Reads the native Ollama endpoints directly over ``httpx`` rather than through
the typed ``ollama`` client. The pinned client (0.6.1) drops the
``remote_model`` / ``remote_host`` / ``capabilities`` fields from its
``ListResponse`` model, and those are exactly what this module needs to
classify cloud models and surface capabilities — so we parse the raw JSON.

Sources probed (best-effort, in order):

- ``GET {OLLAMA_BASE_URL}/api/tags`` — local server. A signed-in local Ollama
  proxies cloud models here too, stamped with ``remote_host``/``remote_model``.
- ``GET {OLLAMA_BASE_URL}/api/ps``   — locally loaded models (``running`` flag).
- ``GET https://ollama.com/api/tags`` — hosted cloud catalog, only when
  ``OLLAMA_API_KEY`` is set (``Authorization: Bearer``).

Best-effort by design: any probe failure contributes no models, so callers
degrade to their static catalog rather than erroring. The API key is never
logged.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger(__name__)

DEFAULT_LOCAL_HOST = "http://localhost:11434"
CLOUD_HOST = "https://ollama.com"
ENV_BASE_URL = "OLLAMA_BASE_URL"
ENV_API_KEY = "OLLAMA_API_KEY"

_TAGS_PATH = "/api/tags"
_PS_PATH = "/api/ps"
_TIMEOUT_SECONDS = 5.0
_MODEL_PREFIX = "ollama:"
# Cloud models are published with either suffix form (e.g. ``glm-4.7:cloud``
# or ``gpt-oss:120b-cloud``); used only as a fallback when the authoritative
# ``remote_host``/``remote_model`` markers are absent.
_CLOUD_SUFFIXES = (":cloud", "-cloud")


@dataclass(frozen=True)
class OllamaModelInfo:
    """A single Ollama model discovered from a live ``/api/tags`` probe."""

    id: str  # provider-prefixed, e.g. "ollama:gpt-oss:120b-cloud"
    name: str  # raw upstream name, e.g. "gpt-oss:120b-cloud"
    cloud: bool
    capabilities: tuple[str, ...] = ()
    running: bool = False
    size: int | None = None
    remote_host: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """JSON-serialisable view for API responses."""
        return {
            "id": self.id,
            "name": self.name,
            "cloud": self.cloud,
            "capabilities": list(self.capabilities),
            "running": self.running,
            "size": self.size,
            "remote_host": self.remote_host,
        }


def _get_json(url: str, headers: dict[str, str] | None = None) -> dict[str, Any] | None:
    """GET ``url`` and return a parsed JSON object, or ``None`` on any failure."""
    try:
        response = httpx.get(url, headers=headers, timeout=_TIMEOUT_SECONDS)
        response.raise_for_status()
        data = response.json()
    except Exception as exc:
        logger.debug("Ollama probe failed for %s: %s", url, exc)
        return None
    return data if isinstance(data, dict) else None


def _is_cloud(entry: dict[str, Any], name: str) -> bool:
    """Classify a model as cloud-hosted.

    Prefers the authoritative ``remote_host``/``remote_model`` markers a
    signed-in local server stamps on proxied models; falls back to the
    published ``:cloud``/``-cloud`` name suffix.
    """
    if entry.get("remote_host") or entry.get("remote_model"):
        return True
    return any(name.endswith(suffix) for suffix in _CLOUD_SUFFIXES)


def _running_model_names(base_url: str) -> set[str]:
    """Return the set of model names currently loaded (``GET /api/ps``)."""
    data = _get_json(f"{base_url}{_PS_PATH}")
    if not data:
        return set()
    names: set[str] = set()
    for entry in data.get("models", []) or []:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name") or entry.get("model")
        if isinstance(name, str) and name:
            names.add(name)
    return names


def _parse_tags(
    data: dict[str, Any],
    running: set[str],
    *,
    force_cloud: bool = False,
) -> list[OllamaModelInfo]:
    """Map an ``/api/tags`` payload to :class:`OllamaModelInfo` records."""
    models: list[OllamaModelInfo] = []
    for entry in data.get("models", []) or []:
        if not isinstance(entry, dict):
            continue
        name = entry.get("name") or entry.get("model")
        # The wire payload is untrusted: guard the type, not just truthiness, so
        # a malformed ``{"name": 123}`` degrades gracefully instead of raising.
        if not isinstance(name, str) or not name:
            continue
        # ``capabilities`` must be a list of non-empty strings; a bare string
        # would otherwise iterate character-by-character into garbage badges.
        raw_caps = entry.get("capabilities")
        capabilities = (
            tuple(cap for cap in raw_caps if isinstance(cap, str) and cap)
            if isinstance(raw_caps, list)
            else ()
        )
        size = entry.get("size")
        remote_host = entry.get("remote_host")
        models.append(
            OllamaModelInfo(
                id=name if name.startswith(_MODEL_PREFIX) else f"{_MODEL_PREFIX}{name}",
                name=name,
                cloud=force_cloud or _is_cloud(entry, name),
                capabilities=capabilities,
                running=name in running,
                size=size if isinstance(size, int) else None,
                remote_host=remote_host if isinstance(remote_host, str) else None,
            )
        )
    return models


def discover_ollama_models() -> list[OllamaModelInfo]:
    """Discover Ollama models actually available right now (best-effort).

    Probes the local server (tags + ps) and, when ``OLLAMA_API_KEY`` is set,
    the hosted cloud catalog. Returns de-duplicated records in discovery order
    (local first, then cloud); the first occurrence of a given id wins. Never
    raises.
    """
    base_url = os.environ.get(ENV_BASE_URL, DEFAULT_LOCAL_HOST).rstrip("/")

    discovered: list[OllamaModelInfo] = []
    seen: set[str] = set()

    def _add(records: list[OllamaModelInfo]) -> None:
        for info in records:
            if info.id not in seen:
                seen.add(info.id)
                discovered.append(info)

    # Local server — includes proxied cloud models (remote_host) when signed in.
    running = _running_model_names(base_url)
    local_tags = _get_json(f"{base_url}{_TAGS_PATH}")
    if local_tags:
        _add(_parse_tags(local_tags, running))

    # Hosted cloud catalog — only with an API key; /api/ps is local-only so the
    # running set does not apply.
    api_key = os.environ.get(ENV_API_KEY)
    if api_key:
        cloud_tags = _get_json(
            f"{CLOUD_HOST}{_TAGS_PATH}",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        if cloud_tags:
            _add(_parse_tags(cloud_tags, set(), force_cloud=True))

    return discovered


__all__ = ["OllamaModelInfo", "discover_ollama_models"]
