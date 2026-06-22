"""Discovery for local LM Studio and ONNX model providers (ADR-038).

Companion to :mod:`agentic_v2.models.ollama_discovery`. Both feed
``enumerate_known_models`` so the model router lists what is actually runnable
right now, not just the static tier chains.

- **LM Studio** — an OpenAI-compatible local server. ``GET {host}/v1/models``
  lists loaded models. Host from ``LMSTUDIO_HOST`` (default
  ``http://127.0.0.1:12340``) — the exact host the ``lmstudio`` backend sends
  inference to — so a discovered ``lmstudio:<id>`` is always reachable.
- **ONNX** — onnxruntime-genai model folders, identified by a
  ``genai_config.json``. Scanned under ``ONNX_MODEL_DIR`` / ``AIGALLERY_CACHE``
  resolved exactly as ``OnnxBackend.model_dir`` (the *same* root the backend
  joins ``onnx:<relpath>`` against), so a discovered id is always runnable. When
  neither is set the backend resolves relative to the CWD, so there is no
  catalog-wide root and discovery returns nothing.

Best-effort by design: any probe failure contributes no models, so callers
degrade to the static catalog rather than erroring. Bounded timeouts and a
bounded-depth filesystem walk keep the on-demand probe fast.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import httpx

from .secrets import get_first_secret

logger = logging.getLogger(__name__)

# Mirror build_lmstudio_model: the lmstudio backend reads only LMSTUDIO_HOST and
# defaults to 12340. Probing any other host or env var would advertise models
# the backend cannot reach, so discovery resolves the host identically.
_LMSTUDIO_HOST_ENV = "LMSTUDIO_HOST"
_LMSTUDIO_DEFAULT_HOST = "http://127.0.0.1:12340"
_LMSTUDIO_MODELS_PATH = "/v1/models"

# Mirror OnnxBackend.model_dir resolution so discovered relpaths round-trip.
_ONNX_ENV_VARS = ("ONNX_MODEL_DIR", "AIGALLERY_CACHE")
_GENAI_CONFIG = "genai_config.json"
_ONNX_SCAN_MAX_DEPTH = 6

_HTTP_TIMEOUT_SECONDS = 4.0

# LM Studio's /v1/models lists embedding / TTS / etc. alongside chat models with
# no type tag, so filter obvious non-chat ids by name to keep the router clean.
_NON_CHAT_MARKERS = ("embed", "tts", "whisper", "rerank")


def _is_chat_model_id(model_id: str) -> bool:
    """Heuristic: exclude embedding/TTS/etc. ids LM Studio reports as models."""
    lowered = model_id.lower()
    return not any(marker in lowered for marker in _NON_CHAT_MARKERS)


def _lmstudio_hosts() -> list[str]:
    """Resolve the LM Studio base URL exactly as ``build_lmstudio_model`` does.

    Reads ``LMSTUDIO_HOST`` (default ``http://127.0.0.1:12340``) — the single
    host the ``lmstudio`` backend sends inference to — so a discovered
    ``lmstudio:<id>`` is guaranteed reachable rather than advertised from a port
    the backend never queries.
    """
    host = os.environ.get(_LMSTUDIO_HOST_ENV, _LMSTUDIO_DEFAULT_HOST)
    return [host.rstrip("/")]


def discover_lmstudio_models() -> list[str]:
    """Discover models served by a local LM Studio server (best-effort).

    Returns de-duplicated ``lmstudio:<id>`` ids from the first reachable host,
    or ``[]`` if none responds. Never raises.
    """
    discovered: list[str] = []
    seen: set[str] = set()
    for host in _lmstudio_hosts():
        try:
            response = httpx.get(
                f"{host}{_LMSTUDIO_MODELS_PATH}", timeout=_HTTP_TIMEOUT_SECONDS
            )
            response.raise_for_status()
            data = response.json()
        except Exception as exc:
            logger.debug("LM Studio discovery failed for %s: %s", host, exc)
            continue
        if not isinstance(data, dict):
            continue
        for entry in data.get("data", []) or []:
            if not isinstance(entry, dict):
                continue
            model_id = entry.get("id")
            if not isinstance(model_id, str) or not model_id:
                continue
            if not _is_chat_model_id(model_id):
                continue
            full_id = f"lmstudio:{model_id}"
            if full_id not in seen:
                seen.add(full_id)
                discovered.append(full_id)
        # First reachable host wins; don't double-count across candidates.
        if discovered:
            break
    return discovered


def _onnx_roots() -> list[Path]:
    """Resolve the ONNX root the ``OnnxBackend`` also resolves against.

    Mirrors ``OnnxBackend.model_dir`` (``ONNX_MODEL_DIR`` / ``AIGALLERY_CACHE``
    via the shared secret resolver, with ``~`` expanded) so a discovered
    ``onnx:<relpath>`` — taken relative to this root — is exactly what the
    backend joins and loads. When neither is configured the backend resolves
    ``onnx:<name>`` relative to the CWD, so there is no catalog-wide root to
    scan and discovery returns nothing rather than advertising models the
    backend cannot load.
    """
    configured = get_first_secret(*_ONNX_ENV_VARS, default="") or ""
    if configured:
        return [Path(configured).expanduser()]
    return []


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


def discover_onnx_models() -> list[str]:
    """Discover onnxruntime-genai models under the configured ONNX root.

    Returns de-duplicated ``onnx:<relpath>`` ids, where ``relpath`` is the model
    folder relative to the root — exactly what ``OnnxBackend`` resolves against,
    so every discovered id is runnable. Never raises.
    """
    discovered: list[str] = []
    seen: set[str] = set()
    for root in _onnx_roots():
        try:
            if not root.is_dir():
                continue
            for config in _iter_genai_configs(root):
                rel = config.parent.relative_to(root).as_posix()
                model_id = f"onnx:{rel}"
                if model_id not in seen:
                    seen.add(model_id)
                    discovered.append(model_id)
        except Exception as exc:
            logger.debug("ONNX discovery failed for %s: %s", root, exc)
    return discovered


__all__ = ["discover_lmstudio_models", "discover_onnx_models"]
