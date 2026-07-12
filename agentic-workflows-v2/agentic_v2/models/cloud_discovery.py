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
- **NVIDIA NIM** (``nvidia:``) — ``GET https://integrate.api.nvidia.com/v1/models``
  (``NVIDIA_API_KEY``; ``NVIDIA_BASE_URL`` honored for on-prem NIM deployments);
  ids keep their ``publisher/model`` form (e.g.
  ``nvidia:meta/llama-3.1-70b-instruct``).
- **OpenRouter** (``openrouter:``) — ``GET https://openrouter.ai/api/v1/models``
  (``OPENROUTER_API_KEY``; ``OPENROUTER_BASE_URL`` honored for gateways). The
  300-400 model catalog is curated to free-tier + flagship ids, the live result
  is TTL-cached (a deliberate deviation from the no-cache baseline; ADR-050),
  and a missing key yields a small static fallback instead of an empty list.

Best-effort by design: a missing key makes no network call and — OpenRouter's
static fallback aside — contributes nothing, and any probe failure (network,
auth, schema drift) degrades to "no models for this provider" rather than
raising — callers keep the static catalog. The probe is bounded by an 8 s
per-request timeout. API keys are sent as auth headers/params and are never
logged.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any

import httpx

from .discovery_logging import install_redaction_filter

logger = logging.getLogger(__name__)

# Defense in depth: every probe below sends its key as a header (never a URL
# query param), but also scrub credential-like query params from anything httpx
# or this module logs, so a regression cannot write a live key to the logs.
install_redaction_filter(logger, logging.getLogger("httpx"))

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
) -> Any | None:
    """GET ``url`` and return parsed JSON (list or dict), or ``None`` on failure.

    Never raises: any transport/HTTP/parse error logs at debug and yields
    ``None`` so a provider that is down or rejects the key contributes nothing.
    Credentials travel via ``headers`` only — never as URL query parameters —
    so a secret cannot appear in httpx's request-line logs.
    """
    try:
        response = httpx.get(url, headers=headers, timeout=_TIMEOUT_SECONDS)
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
    # Send the key as a header, never as a ``?key=`` query param: httpx
    # INFO-logs the full request URL, so a query-string secret would be written
    # to the backend logs in plaintext. Google's Generative Language API accepts
    # either form, and the runtime's Gemini *backend* already uses this header.
    payload = _get_json(_GEMINI_MODELS_URL, headers={"x-goog-api-key": api_key})
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


# ---------------------------------------------------------------------------
# NVIDIA NIM
# ---------------------------------------------------------------------------

_NVIDIA_DEFAULT_BASE = "https://integrate.api.nvidia.com/v1"


def resolve_nvidia_base_url() -> str:
    """Resolve the NVIDIA NIM OpenAI-compatible ``/v1`` base URL.

    Honors ``NVIDIA_BASE_URL`` for on-prem NIM deployments (e.g. a self-hosted
    Llama NIM on ``http://nim.local:8000``); falls back to the public cloud
    endpoint. The ``/v1`` segment is appended when the operator omits it so
    callers can append ``/models`` or ``/chat/completions`` unconditionally.
    This is the single source of truth shared by discovery and the runtime
    backend, so a discovered id is reachable at the host inference targets.
    """
    base = (os.environ.get("NVIDIA_BASE_URL") or _NVIDIA_DEFAULT_BASE).rstrip("/")
    if not base.endswith("/v1"):
        base = f"{base}/v1"
    return base


def discover_nvidia_models() -> list[CloudModelInfo]:
    """List NVIDIA NIM chat models the configured key can reach (best-effort).

    Honors ``NVIDIA_BASE_URL`` for on-prem NIM deployments (e.g. a self-hosted
    Llama NIM on ``http://nim.local:8000/v1``); falls back to the public cloud
    endpoint. Model ids keep their ``publisher/model`` form so they round-trip
    to the NIM OpenAI-compatible backend without transformation.
    """
    api_key = os.environ.get("NVIDIA_API_KEY")
    if not api_key:
        return []
    url = f"{resolve_nvidia_base_url()}/models"
    payload = _get_json(url, headers={"Authorization": f"Bearer {api_key}"})
    return _dedup_prefixed("nvidia", _data_ids(payload))


# ---------------------------------------------------------------------------
# OpenRouter
# ---------------------------------------------------------------------------

_OPENROUTER_DEFAULT_BASE = "https://openrouter.ai/api/v1"

# Curated keyless fallback (bare ids — the ``openrouter:`` prefix is applied by
# ``_dedup_prefixed``). Free-tier ids carry OpenRouter's ``:free`` suffix, so a
# full app id has TWO colons: ``openrouter:meta-llama/llama-3.1-8b-instruct:free``.
_OPENROUTER_STATIC_FALLBACK: tuple[str, ...] = (
    "deepseek/deepseek-chat-v3-0324:free",
    "meta-llama/llama-3.1-8b-instruct:free",
    "mistralai/mistral-7b-instruct:free",
    "qwen/qwen3-14b:free",
    "anthropic/claude-sonnet-4",
    "deepseek/deepseek-chat",
    "google/gemini-2.5-flash",
    "openai/gpt-4o-mini",
)

# Flagship-family id prefixes kept from the live catalog (besides ``:free`` ids).
_OPENROUTER_FLAGSHIP_PREFIXES: tuple[str, ...] = (
    "openai/gpt-5",
    "openai/gpt-4o",
    "openai/o3",
    "openai/o4",
    "anthropic/claude",
    "google/gemini-2",
    "google/gemini-3",
    "meta-llama/llama-3",
    "meta-llama/llama-4",
    "deepseek/deepseek",
    "qwen/qwen3",
    "mistralai/mistral-large",
    "x-ai/grok",
)

# Curation caps keep the 300-400 model catalog readable in the console.
_OPENROUTER_FREE_CAP = 25
_OPENROUTER_FLAGSHIP_CAP = 15

# TTL cache holding the LIVE catalog fetch only (never the static fallback).
# Caching at all is a deliberate deviation from ADR-039's cache-free design,
# justified by the catalog size above (recorded in ADR-050). Lock-guarded
# because ``discover_cloud_models`` runs its probes in a ThreadPoolExecutor.
_OPENROUTER_CACHE_TTL_SECONDS = 300.0
_openrouter_cache_lock = threading.Lock()
_openrouter_cache: tuple[float, tuple[CloudModelInfo, ...]] | None = None


def resolve_openrouter_base_url() -> str:
    """Resolve the OpenRouter OpenAI-compatible ``/v1`` base URL.

    Honors ``OPENROUTER_BASE_URL`` for proxies/gateways; falls back to the
    public aggregator endpoint. The ``/v1`` segment is appended when the
    operator omits it so callers can append ``/models`` or
    ``/chat/completions`` unconditionally. This is the single source of truth
    shared by discovery and the runtime backends, so a discovered id is
    reachable at the host inference targets.
    """
    base = (os.environ.get("OPENROUTER_BASE_URL") or _OPENROUTER_DEFAULT_BASE).rstrip(
        "/"
    )
    if not base.endswith("/v1"):
        base = f"{base}/v1"
    return base


def _read_openrouter_cache(*, allow_expired: bool) -> list[CloudModelInfo] | None:
    """Return the cached live listing as a fresh list, or ``None`` on a miss.

    ``allow_expired=True`` serves a stale entry (used when a re-fetch fails —
    yesterday's live listing beats the static fallback).
    """
    with _openrouter_cache_lock:
        if _openrouter_cache is None:
            return None
        fetched_at, models = _openrouter_cache
        age = time.monotonic() - fetched_at
        if not allow_expired and age >= _OPENROUTER_CACHE_TTL_SECONDS:
            return None
        return list(models)


def _write_openrouter_cache(models: list[CloudModelInfo]) -> None:
    """Store a live listing with its fetch timestamp."""
    global _openrouter_cache
    with _openrouter_cache_lock:
        _openrouter_cache = (time.monotonic(), tuple(models))


def _reset_openrouter_discovery_cache() -> None:
    """Clear the OpenRouter TTL cache.

    For test fixtures only.
    """
    global _openrouter_cache
    with _openrouter_cache_lock:
        _openrouter_cache = None


def _openrouter_text_chat_id(entry: Any) -> str | None:
    """Return the entry's id when it is a text-output chat model, else ``None``.

    Skips entries whose ``architecture.output_modalities`` exists and lacks
    ``"text"`` (image/audio-only models), and reuses the shared non-chat id
    blocklist so embeddings/rerankers never consume a curation slot.
    """
    if not isinstance(entry, dict):
        return None
    model_id = entry.get("id")
    if not isinstance(model_id, str) or not model_id:
        return None
    if not _is_chat_model_id(model_id):
        return None
    architecture = entry.get("architecture")
    if isinstance(architecture, dict):
        modalities = architecture.get("output_modalities")
        if isinstance(modalities, list) and "text" not in modalities:
            return None
    return model_id


def _interleave_flagship_families(flagship: list[str]) -> list[str]:
    """Fill the flagship slots fairly across families, newest-ish first.

    A single global alphabetical sort lets one prolific publisher consume the
    whole cap (anthropic alone ships 15+ ``claude`` ids, starving every other
    declared family). Instead the slots are filled round-robin across the
    families in :data:`_OPENROUTER_FLAGSHIP_PREFIXES` declaration order, taking
    each family's reverse-sorted (highest version sorts first) ids one rank at
    a time, so every family with a live id survives the cap. Deterministic for
    a given catalog.
    """
    by_family: dict[str, list[str]] = {}
    for model_id in sorted(flagship, reverse=True):
        family = next(
            p for p in _OPENROUTER_FLAGSHIP_PREFIXES if model_id.startswith(p)
        )
        by_family.setdefault(family, []).append(model_id)
    families = [p for p in _OPENROUTER_FLAGSHIP_PREFIXES if p in by_family]
    picks: list[str] = []
    rank = 0
    while len(picks) < _OPENROUTER_FLAGSHIP_CAP:
        rank_had_ids = False
        for family in families:
            ids = by_family[family]
            if rank >= len(ids):
                continue
            rank_had_ids = True
            picks.append(ids[rank])
            if len(picks) == _OPENROUTER_FLAGSHIP_CAP:
                break
        if not rank_had_ids:
            break
        rank += 1
    return picks


def _curate_openrouter_ids(payload: Any) -> list[str] | None:
    """Curate the raw catalog to free + flagship ids, or ``None`` on a bad shape.

    OpenRouter lists 300-400 models; dumping them all would drown the console,
    so only ``:free`` ids (alphabetical, capped) and flagship-family ids
    (family-fair round-robin, see :func:`_interleave_flagship_families`) are
    kept. Deterministic output for a given catalog.
    """
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        return None
    free: list[str] = []
    flagship: list[str] = []
    for entry in payload["data"]:
        model_id = _openrouter_text_chat_id(entry)
        if model_id is None:
            continue
        if model_id.endswith(":free"):
            free.append(model_id)
        elif model_id.startswith(_OPENROUTER_FLAGSHIP_PREFIXES):
            flagship.append(model_id)
    return sorted(free)[:_OPENROUTER_FREE_CAP] + _interleave_flagship_families(
        flagship
    )


def discover_openrouter_models() -> list[CloudModelInfo]:
    """List a curated slice of the OpenRouter catalog (best-effort, TTL-cached).

    Unlike the other keyed providers, a missing ``OPENROUTER_API_KEY`` returns
    the small static fallback — still with no network call — so the console can
    advertise the aggregator's free tier; the catalog entry's availability flag
    (derived from the key env by the merge layer) tells the UI the key is
    absent. With a key, the live listing is fetched, curated, and cached for
    :data:`_OPENROUTER_CACHE_TTL_SECONDS`; a failed fetch falls back to the
    last live result, then to the static list. Ids keep their
    ``publisher/model[:free]`` form so they round-trip to the backends.
    """
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        return _dedup_prefixed("openrouter", list(_OPENROUTER_STATIC_FALLBACK))
    cached = _read_openrouter_cache(allow_expired=False)
    if cached is not None:
        return cached
    url = f"{resolve_openrouter_base_url()}/models"
    payload = _get_json(url, headers={"Authorization": f"Bearer {api_key}"})
    curated = _curate_openrouter_ids(payload)
    if not curated:
        # ``None`` (transport failure / bad shape) and ``[]`` (a catalog with
        # nothing matching the curation — e.g. a self-hosted gateway behind
        # OPENROUTER_BASE_URL) both fall back rather than caching an empty
        # listing that would beat the static fallback for a whole TTL.
        stale = _read_openrouter_cache(allow_expired=True)
        if stale is not None:
            return stale
        return _dedup_prefixed("openrouter", list(_OPENROUTER_STATIC_FALLBACK))
    discovered = _dedup_prefixed("openrouter", curated)
    _write_openrouter_cache(discovered)
    return discovered


def discover_cloud_models() -> list[CloudModelInfo]:
    """Aggregate live listings from every keyed cloud provider (best-effort).

    Providers without a configured key make no network call and
    contribute nothing (except OpenRouter, which contributes its static
    fallback). The probes run concurrently so worst-case latency is a
    single timeout (~8s) rather than the sum of all probes; provider
    order is preserved. Never raises.
    """
    probes = (
        discover_openai_models,
        discover_anthropic_models,
        discover_gemini_models,
        discover_github_models,
        discover_nvidia_models,
        discover_openrouter_models,
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
    "discover_nvidia_models",
    "discover_openai_models",
    "discover_openrouter_models",
    "resolve_nvidia_base_url",
    "resolve_openrouter_base_url",
]
