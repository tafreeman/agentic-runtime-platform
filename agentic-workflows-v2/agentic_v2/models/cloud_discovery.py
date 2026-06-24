"""Live model discovery for keyed cloud providers (ADR-039).

Extends the local discovery story (Ollama — ADR-037; LM Studio + ONNX —
ADR-038) to the hosted providers the runtime already builds backends for, so
the model-router probe lists what each configured **key** can actually reach —
not just the handful of models pinned in the static tier chains.

Providers probed (best-effort, only when their key env var is set):

- **OpenAI** (``openai:``)   — ``GET {base}/models`` (``OPENAI_API_KEY``;
  ``OPENAI_BASE_URL`` / ``OPENAI_API_BASE`` honored for proxies/Azure).
- **Anthropic** (``anthropic:``) — ``GET https://api.anthropic.com/v1/models``
  (``ANTHROPIC_API_KEY``; ``anthropic-version`` header).
- **Google Gemini** (``gemini:``) — ``GET …/v1beta/models`` filtered to models
  advertising ``generateContent`` (``GOOGLE_API_KEY`` / ``GEMINI_API_KEY``).
- **GitHub Models** (``gh:``) — ``GET https://models.github.ai/catalog/models``
  (``GITHUB_TOKEN``); ids keep their ``publisher/model`` form (e.g.
  ``gh:openai/gpt-4.1``) to match the backend's ``gh:`` resolution.

Best-effort by design: a missing key contributes nothing (no network call), and
any probe failure (network, auth, schema drift) degrades to "no models for this
provider" rather than raising — callers keep the static catalog. The probe is
bounded by an 8 s per-request timeout. API keys are sent as auth headers/params
and are never logged.
"""

from __future__ import annotations

import logging
import os
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger(__name__)

_TIMEOUT_SECONDS = 8.0

# Substrings that mark a non-chat model id (embeddings, speech, image, safety
# classifiers, …). Conservative on purpose: a discovery console tolerates an
# over-listed chat model far better than a silently-dropped one.
_NON_CHAT_MARKERS = (
    "embed",
    "embedding",
    "whisper",
    "tts",
    "dall-e",
    "dalle",
    "moderation",
    "rerank",
    "clip",
    "stable-diffusion",
    "davinci-002",
    "babbage-002",
    "text-similarity",
    "text-search",
)


@dataclass(frozen=True)
class CloudModelInfo:
    """A model surfaced by a live cloud-provider listing (provider-prefixed id)."""

    id: str


def _is_chat_model_id(model_id: str) -> bool:
    """Heuristic: exclude obvious non-chat ids (embeddings/speech/image/…)."""
    lowered = model_id.lower()
    return not any(marker in lowered for marker in _NON_CHAT_MARKERS)


def _get_json(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    params: dict[str, str] | None = None,
) -> Any | None:
    """GET ``url`` and return parsed JSON (list or dict), or ``None`` on failure.

    Never raises: any transport/HTTP/parse error logs at debug and yields
    ``None`` so a provider that is down or rejects the key contributes nothing.
    """
    try:
        response = httpx.get(
            url, headers=headers, params=params, timeout=_TIMEOUT_SECONDS
        )
        response.raise_for_status()
        return response.json()
    except Exception as exc:
        logger.debug("Cloud discovery probe failed for %s: %s", url, exc)
        return None


def _dedup_prefixed(prefix: str, names: list[str]) -> list[CloudModelInfo]:
    """Wrap bare model names as ``prefix:<name>`` records, de-duplicated."""
    discovered: list[CloudModelInfo] = []
    seen: set[str] = set()
    for name in names:
        if not isinstance(name, str) or not name:
            continue
        if not _is_chat_model_id(name):
            continue
        model_id = f"{prefix}:{name}"
        if model_id not in seen:
            seen.add(model_id)
            discovered.append(CloudModelInfo(id=model_id))
    return discovered


def _data_ids(payload: Any) -> list[str]:
    """Extract ``data[].id`` strings from an OpenAI-style ``{"data": [...]}``."""
    if not isinstance(payload, dict):
        return []
    ids: list[str] = []
    for entry in payload.get("data", []) or []:
        if isinstance(entry, dict) and isinstance(entry.get("id"), str):
            ids.append(entry["id"])
    return ids


# ---------------------------------------------------------------------------
# OpenAI
# ---------------------------------------------------------------------------


def _openai_models_url() -> str:
    """Resolve the OpenAI ``/models`` URL, honoring proxy/Azure base overrides."""
    base = (
        os.environ.get("OPENAI_BASE_URL")
        or os.environ.get("OPENAI_API_BASE")
        or "https://api.openai.com/v1"
    ).rstrip("/")
    # A base already ending in /v1 takes /models directly; a bare host needs /v1.
    return f"{base}/models" if base.endswith("/v1") else f"{base}/v1/models"


def discover_openai_models() -> list[CloudModelInfo]:
    """List OpenAI chat models the configured key can reach (best-effort)."""
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return []
    headers = {"Authorization": f"Bearer {api_key}"}
    org = os.environ.get("OPENAI_ORG_ID")
    if org:
        headers["OpenAI-Organization"] = org
    payload = _get_json(_openai_models_url(), headers=headers)
    return _dedup_prefixed("openai", _data_ids(payload))


# ---------------------------------------------------------------------------
# Anthropic
# ---------------------------------------------------------------------------

_ANTHROPIC_MODELS_URL = "https://api.anthropic.com/v1/models"
_ANTHROPIC_VERSION = "2023-06-01"


def discover_anthropic_models() -> list[CloudModelInfo]:
    """List Anthropic (Claude) models the configured key can reach."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return []
    payload = _get_json(
        _ANTHROPIC_MODELS_URL,
        headers={"x-api-key": api_key, "anthropic-version": _ANTHROPIC_VERSION},
    )
    return _dedup_prefixed("anthropic", _data_ids(payload))


# ---------------------------------------------------------------------------
# Google Gemini
# ---------------------------------------------------------------------------

_GEMINI_MODELS_URL = "https://generativelanguage.googleapis.com/v1beta/models"


def discover_gemini_models() -> list[CloudModelInfo]:
    """List Gemini models advertising ``generateContent`` (chat-capable)."""
    api_key = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return []
    payload = _get_json(_GEMINI_MODELS_URL, params={"key": api_key})
    if not isinstance(payload, dict):
        return []
    names: list[str] = []
    for entry in payload.get("models", []) or []:
        if not isinstance(entry, dict):
            continue
        methods = entry.get("supportedGenerationMethods")
        if not (isinstance(methods, list) and "generateContent" in methods):
            continue  # embeddings / aqa / token-count-only models
        raw_name = entry.get("name")
        if isinstance(raw_name, str) and raw_name:
            # API returns "models/gemini-2.5-flash" — strip the collection prefix.
            names.append(raw_name.removeprefix("models/"))
    return _dedup_prefixed("gemini", names)


# ---------------------------------------------------------------------------
# GitHub Models
# ---------------------------------------------------------------------------

_GITHUB_CATALOG_URL = "https://models.github.ai/catalog/models"


def discover_github_models() -> list[CloudModelInfo]:
    """List the GitHub Models catalog the token can reach (``publisher/model``)."""
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        return []
    payload = _get_json(
        _GITHUB_CATALOG_URL,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
        },
    )
    # The catalog responds with a top-level JSON array of model objects.
    entries = payload if isinstance(payload, list) else []
    names: list[str] = []
    for entry in entries:
        if isinstance(entry, dict) and isinstance(entry.get("id"), str):
            names.append(entry["id"])
    return _dedup_prefixed("gh", names)


def discover_cloud_models() -> list[CloudModelInfo]:
    """Aggregate live listings from every keyed cloud provider (best-effort).

    Providers without a configured key contribute nothing and make no network
    call. The four probes run concurrently so worst-case latency is a single
    timeout (~8s) rather than the sum of all four; provider order is preserved.
    Never raises.
    """
    probes = (
        discover_openai_models,
        discover_anthropic_models,
        discover_gemini_models,
        discover_github_models,
    )
    discovered: list[CloudModelInfo] = []
    with ThreadPoolExecutor(max_workers=len(probes)) as executor:
        # Iterate in submission order so the aggregated list stays deterministic.
        for future in [executor.submit(probe) for probe in probes]:
            try:
                discovered.extend(future.result())
            except Exception as exc:  # defensive — probes are already best-effort
                logger.debug("Cloud discovery probe failed: %s", exc)
    return discovered


__all__ = [
    "CloudModelInfo",
    "discover_anthropic_models",
    "discover_cloud_models",
    "discover_gemini_models",
    "discover_github_models",
    "discover_openai_models",
]
