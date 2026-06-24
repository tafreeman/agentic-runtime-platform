"""Discovery for local LM Studio and ONNX model providers (ADR-038).

Companion to :mod:`agentic_v2.models.ollama_discovery`. Both feed
``enumerate_known_models`` so the model router lists what is actually runnable
right now, not just the static tier chains.

- **LM Studio** — a local server exposing both LM Studio's *native* REST API
  (``GET {host}/api/v0/models``) and an OpenAI-compatible shim
  (``GET {host}/v1/models``). Discovery prefers the native endpoint because it
  lists the **whole downloaded library** with a ``type`` (``llm`` / ``vlm`` /
  ``embeddings``) and a ``state`` (``loaded`` / ``not-loaded``); the OpenAI shim
  only reports models currently *loaded* into memory, so on its own it surfaces
  one or two models even when the library is large. The native payload is parsed
  when present and the OpenAI shim is the fallback for older servers.

  The host is resolved by :func:`resolve_lmstudio_host`: ``LMSTUDIO_HOST`` wins
  when set, otherwise the LM Studio default port (``1234``) is probed first and
  the legacy ARP port (``12340``) second. The ``lmstudio`` backend resolves the
  host the *same* way, so a discovered ``lmstudio:<id>`` is always reachable at
  the host the backend will target.
- **ONNX** — onnxruntime-genai model folders, identified by a
  ``genai_config.json``. Scanned under the roots ``OnnxBackend`` also resolves
  against (``ONNX_MODEL_DIR`` — one or more roots, plus the ``~/.cache/aigallery``
  default), so a discovered ``onnx:<relpath>`` is exactly what the backend joins
  and loads.

Best-effort by design: any probe failure contributes no models, so callers
degrade to the static catalog rather than erroring. Bounded timeouts and a
bounded-depth filesystem walk keep the on-demand probe fast.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

import httpx

from .secrets import get_first_secret

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LocalModelInfo:
    """A model discovered from a local provider (LM Studio or ONNX).

    Mirrors the slice of :class:`~agentic_v2.models.ollama_discovery.OllamaModelInfo`
    the console consumes: a provider-prefixed id, whether it is loaded right now
    (LM Studio's ``state``; always ``False`` for the filesystem-scanned ONNX
    provider), and any capability badges (e.g. ``vision`` for an LM Studio
    ``vlm``).
    """

    id: str  # provider-prefixed, e.g. "lmstudio:google/gemma-3-12b"
    running: bool = False
    capabilities: tuple[str, ...] = field(default=())


# ---------------------------------------------------------------------------
# Shared HTTP helper
# ---------------------------------------------------------------------------

_HTTP_TIMEOUT_SECONDS = 4.0


def _get_json(url: str) -> dict[str, Any] | None:
    """GET ``url`` and return a parsed JSON object, or ``None`` on any failure.

    A ``None`` return means "host unreachable / not this provider"; an empty
    payload still parses to a dict, distinguishing "reachable but no models".
    """
    try:
        response = httpx.get(url, timeout=_HTTP_TIMEOUT_SECONDS)
        response.raise_for_status()
        data = response.json()
    except Exception as exc:
        logger.debug("Local discovery probe failed for %s: %s", url, exc)
        return None
    return data if isinstance(data, dict) else None


# ---------------------------------------------------------------------------
# LM Studio
# ---------------------------------------------------------------------------

_LMSTUDIO_HOST_ENV = "LMSTUDIO_HOST"
# LM Studio's documented default is :1234; ARP historically shipped :12340.
# Probe the standard port first, then the legacy one, so an operator running
# either is discovered without setting LMSTUDIO_HOST. resolve_lmstudio_host()
# (used by the backend) follows the same order, keeping discovered == runnable.
_LMSTUDIO_DEFAULT_PORTS = (1234, 12340)
_LMSTUDIO_NATIVE_PATH = "/api/v0/models"  # full library + type + state
_LMSTUDIO_OPENAI_PATH = "/v1/models"  # fallback: loaded models only, no type

# Native-API model types usable as chat backends. "embeddings" (and any other
# non-chat type) is excluded; "vlm" is chat-capable and gets a vision badge.
_LMSTUDIO_CHAT_TYPES = frozenset({"llm", "vlm"})

# OpenAI-shim fallback has no type field, so filter obvious non-chat ids by name.
_NON_CHAT_MARKERS = ("embed", "tts", "whisper", "rerank")


def _is_chat_model_id(model_id: str) -> bool:
    """Heuristic for the OpenAI-shim fallback (no ``type`` field available)."""
    lowered = model_id.lower()
    return not any(marker in lowered for marker in _NON_CHAT_MARKERS)


def _normalize_lmstudio_host(raw: str) -> str:
    """Strip a trailing ``/`` and ``/v1`` so paths can be appended cleanly.

    ``LMSTUDIO_HOST`` may be given with or without the ``/v1`` suffix the
    backend appends; discovery hits ``/api/v0/...`` and ``/v1/...`` itself, so
    it needs the bare host either way.
    """
    host = raw.rstrip("/")
    if host.endswith("/v1"):
        host = host[: -len("/v1")]
    return host


def _lmstudio_candidate_hosts() -> list[str]:
    """Hosts to probe, honoring ``LMSTUDIO_HOST`` then the default port order."""
    explicit = os.environ.get(_LMSTUDIO_HOST_ENV)
    if explicit:
        return [_normalize_lmstudio_host(explicit)]
    return [f"http://127.0.0.1:{port}" for port in _LMSTUDIO_DEFAULT_PORTS]


def _parse_native_models(data: dict[str, Any]) -> list[LocalModelInfo]:
    """Map an ``/api/v0/models`` payload to records (full library + type/state)."""
    discovered: list[LocalModelInfo] = []
    seen: set[str] = set()
    for entry in data.get("data", []) or []:
        if not isinstance(entry, dict):
            continue
        model_id = entry.get("id")
        if not isinstance(model_id, str) or not model_id:
            continue
        model_type = entry.get("type")
        # Exclude known non-chat types; keep when the type is absent/unknown so
        # an unexpected payload degrades to "list it" rather than "drop it".
        if (
            isinstance(model_type, str)
            and model_type.lower() not in _LMSTUDIO_CHAT_TYPES
        ):
            continue
        full_id = f"lmstudio:{model_id}"
        if full_id in seen:
            continue
        seen.add(full_id)
        is_vision = isinstance(model_type, str) and model_type.lower() == "vlm"
        discovered.append(
            LocalModelInfo(
                id=full_id,
                running=entry.get("state") == "loaded",
                capabilities=("vision",) if is_vision else (),
            )
        )
    return discovered


def _parse_openai_models(data: dict[str, Any]) -> list[LocalModelInfo]:
    """Map a ``/v1/models`` payload to records (loaded only, name-filtered)."""
    discovered: list[LocalModelInfo] = []
    seen: set[str] = set()
    for entry in data.get("data", []) or []:
        if not isinstance(entry, dict):
            continue
        model_id = entry.get("id")
        if not isinstance(model_id, str) or not model_id:
            continue
        if not _is_chat_model_id(model_id):
            continue
        full_id = f"lmstudio:{model_id}"
        if full_id in seen:
            continue
        seen.add(full_id)
        discovered.append(LocalModelInfo(id=full_id))
    return discovered


def _fetch_lmstudio_models(host: str) -> list[LocalModelInfo] | None:
    """Probe one host: native API first, OpenAI shim second.

    Returns the chat models (possibly an empty list when the server is up but
    has no chat models) if the host responds, or ``None`` when the host is
    unreachable / not an LM Studio server.
    """
    native = _get_json(f"{host}{_LMSTUDIO_NATIVE_PATH}")
    if native is not None:
        return _parse_native_models(native)
    openai = _get_json(f"{host}{_LMSTUDIO_OPENAI_PATH}")
    if openai is not None:
        return _parse_openai_models(openai)
    return None


@lru_cache(maxsize=1)
def _probe_lmstudio_host() -> str | None:
    """Return the first reachable default-port host, or None when none respond.

    Only successful results stay in the cache; resolve_lmstudio_host evicts the
    cache on failure so that a server started after the first probe is discovered
    on the next call rather than being permanently shadowed by the cached fallback.
    """
    for host in [f"http://127.0.0.1:{port}" for port in _LMSTUDIO_DEFAULT_PORTS]:
        if _fetch_lmstudio_models(host) is not None:
            return host
    return None


def resolve_lmstudio_host() -> str:
    """Resolve the bare LM Studio base host the backend should target.

    Honors ``LMSTUDIO_HOST`` (no probe — the operator pinned it); otherwise
    returns the first reachable default-port host, falling back to the first
    candidate (``:1234``) so the backend has a deterministic target and clear
    error messages even when no server is up. :func:`discover_lmstudio_models`
    walks the same candidate order, so a discovered id is reachable here.

    Successful resolutions are cached because the backend calls this on every
    inference request; re-probing ``:1234``→``:12340`` each time would add a
    synchronous connection delay per request (up to ~8s when LM Studio is down).
    Failed probes are **not** cached: the cache is evicted on failure so a server
    that starts after the first probe is discovered on the next call. Tests call
    ``cache_clear()`` to reset between cases.
    Discovery (``discover_lmstudio_models``) is intentionally *not* cached, so a
    UI "rescan" still re-probes live.
    """
    explicit = os.environ.get(_LMSTUDIO_HOST_ENV)
    if explicit:
        return _normalize_lmstudio_host(explicit)
    found = _probe_lmstudio_host()
    if found is None:
        _probe_lmstudio_host.cache_clear()  # don't retain the failure; retry on next call
        return f"http://127.0.0.1:{_LMSTUDIO_DEFAULT_PORTS[0]}"
    return found


# Forward cache_clear so callers and test fixtures keep the same API regardless
# of the underlying caching mechanism.
resolve_lmstudio_host.cache_clear = _probe_lmstudio_host.cache_clear  # type: ignore[attr-defined]


def discover_lmstudio_models() -> list[LocalModelInfo]:
    """Discover models served by a local LM Studio server (best-effort).

    Returns records from the first reachable host (native API preferred), or
    ``[]`` if none responds. Never raises.
    """
    for host in _lmstudio_candidate_hosts():
        result = _fetch_lmstudio_models(host)
        if result is not None:
            # First reachable host wins, even when it reports no chat models.
            return result
    return []


# ---------------------------------------------------------------------------
# ONNX
# ---------------------------------------------------------------------------

# Mirror OnnxBackend.model_dir resolution so discovered relpaths round-trip.
_ONNX_ENV_VARS = ("ONNX_MODEL_DIR", "AIGALLERY_CACHE")
# Default root shipped by the AI Dev Gallery; resolved when no env override is
# set. OnnxBackend defaults to the same root so discovered == runnable.
_ONNX_DEFAULT_ROOT = "~/.cache/aigallery"
# Multiple roots may be configured at once (e.g. aigallery + .aitk + .foundry),
# separated by os.pathsep so a single env var can list them all.
_GENAI_CONFIG = "genai_config.json"
_ONNX_SCAN_MAX_DEPTH = 6


def parse_onnx_roots(configured: str) -> list[Path]:
    """Parse a root spec into resolved ONNX roots, widest-compatible order.

    ``configured`` may list several roots separated by ``os.pathsep``; the
    ``~/.cache/aigallery`` default is always appended last (so explicit roots
    win on id collisions) and ``~`` is expanded. The shared parser keeps
    :func:`onnx_roots` (discovery) and ``OnnxBackend`` (loading) resolving the
    *same* roots, so a discovered ``onnx:<relpath>`` is loadable.
    """
    roots: list[Path] = []
    seen: set[Path] = set()

    def _add(raw: str) -> None:
        text = raw.strip()
        if not text:
            return
        resolved = Path(text).expanduser()
        if resolved not in seen:
            seen.add(resolved)
            roots.append(resolved)

    for part in configured.split(os.pathsep):
        _add(part)
    _add(_ONNX_DEFAULT_ROOT)
    return roots


def onnx_roots() -> list[Path]:
    """Resolve the ONNX roots from ``ONNX_MODEL_DIR`` / ``AIGALLERY_CACHE``."""
    configured = get_first_secret(*_ONNX_ENV_VARS, default="") or ""
    return parse_onnx_roots(configured)


def _iter_genai_configs(root: Path, max_depth: int = _ONNX_SCAN_MAX_DEPTH):
    """Yield ``genai_config.json`` paths under ``root`` (bounded-depth walk)."""
    stack: list[tuple[Path, int]] = [(root, 0)]
    while stack:
        directory, depth = stack.pop()
        try:
            entries = list(directory.iterdir())
        except OSError:
            continue
        for entry in entries:
            try:
                if entry.is_file() and entry.name == _GENAI_CONFIG:
                    yield entry
                elif entry.is_dir() and not entry.is_symlink() and depth < max_depth:
                    stack.append((entry, depth + 1))
            except OSError:
                continue


def discover_onnx_models() -> list[LocalModelInfo]:
    """Discover onnxruntime-genai models under the configured ONNX roots.

    Returns de-duplicated ``onnx:<relpath>`` records, where ``relpath`` is the
    model folder relative to the root it was found under — exactly what
    ``OnnxBackend`` resolves against, so every discovered id is runnable. The
    first root to claim a given relpath wins. Never raises.
    """
    discovered: list[LocalModelInfo] = []
    seen: set[str] = set()
    for root in onnx_roots():
        try:
            if not root.is_dir():
                continue
            for config in _iter_genai_configs(root):
                rel = config.parent.relative_to(root).as_posix()
                model_id = f"onnx:{rel}"
                if model_id not in seen:
                    seen.add(model_id)
                    discovered.append(LocalModelInfo(id=model_id))
        except Exception as exc:
            logger.debug("ONNX discovery failed for %s: %s", root, exc)
    return discovered


__all__ = [
    "LocalModelInfo",
    "discover_lmstudio_models",
    "discover_onnx_models",
    "onnx_roots",
    "parse_onnx_roots",
    "resolve_lmstudio_host",
]
