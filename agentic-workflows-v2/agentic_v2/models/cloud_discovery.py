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
  (optional ``OPENROUTER_API_KEY``; ``OPENROUTER_BASE_URL`` honored for
  gateways). The full chat-compatible catalog is requested with
  ``output_modalities=all`` and TTL-cached; a static list is used only when the
  live endpoint cannot be reached.
- **Mistral** (``mistral:``) — ``GET https://api.mistral.ai/v1/models``
  (``MISTRAL_API_KEY``; ``MISTRAL_BASE_URL`` honored, the same variable
  ``langchain-mistralai`` reads). Keeps exactly the entries advertising
  ``capabilities.completion_chat``, so embeddings, OCR, moderation and
  transcription models drop out while Labs models (``labs-…``, same listing,
  same endpoint) stay.

Best-effort by design: a missing key makes no network call for keyed providers
other than OpenRouter's public catalog, and any probe failure (network, auth,
schema drift) degrades to "no models for this provider" rather than raising —
callers keep the static catalog. The probe is bounded by an 8 s per-request
timeout. API keys are sent as auth headers and are never logged.

Price (ARP-IMPROVEMENTS F1/F2): most of these listings carry ids only, so
free-vs-paid is not probeable for them and rests on curation
(``config/defaults/model_registry.yaml``) or a per-source declaration.
OpenRouter is the exception: its public catalog publishes ``pricing.prompt``,
``pricing.completion`` and ``pricing.request`` per model, which
:class:`CloudModelInfo` keeps as ``price_in`` / ``price_out`` (USD per million
tokens) and ``price_request`` (USD per call). ``None`` means "not published",
never 0. :mod:`agentic_v2.models.price_label` turns these, the curated prices
and the declarations into the ``price_label`` the model probe reports. Cost-lane
enforcement is unchanged: it still uses the fail-closed curated
:func:`agentic_v2.models.model_registry.cost_lane_for` and, for NVIDIA NIM
specifically, the curated free-endpoint entries (``tiers: []``, deliberately
not in any tier chain) in ``config/defaults/model_registry.yaml``.
"""

from __future__ import annotations

import logging
import math
import os
import threading
import time
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from urllib.parse import urlsplit

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
    """A model surfaced by a live cloud-provider listing (provider-prefixed id).

    The price fields are what the provider's own listing published, and stay
    ``None`` when it published nothing (every provider except OpenRouter, and
    OpenRouter's static fallback ids). ``None`` is "unknown", never 0 -- see
    :mod:`agentic_v2.models.price_label`. ``price_in`` / ``price_out`` are USD
    per million tokens (the registry's unit); ``price_request`` is USD per call.

    ``capabilities`` are the model's tags in the vocabulary of
    :data:`agentic_v2.ui_settings.KNOWN_MODEL_CAPABILITIES` (``tools``,
    ``vision``, ...) when the provider's listing advertises them -- today only
    Mistral's does -- and ``()`` otherwise, meaning "not published", not "none".
    """

    id: str
    price_in: float | None = None
    price_out: float | None = None
    price_request: float | None = None
    capabilities: tuple[str, ...] = ()


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
    Credentials travel via ``headers`` only — never as URL query parameters —
    so a secret cannot appear in httpx's request-line logs.
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


# (price_in per Mtok, price_out per Mtok, price_request per call); ``None`` = unpublished.
_PriceTriple = tuple[float | None, float | None, float | None]
_NO_PRICES: _PriceTriple = (None, None, None)


def _dedup_prefixed(
    prefix: str,
    names: list[str],
    prices: Mapping[str, _PriceTriple] | None = None,
) -> list[CloudModelInfo]:
    """Wrap bare model names as ``prefix:<name>`` records, de-duplicated.

    ``prices`` maps a bare name to the prices its listing published; a name with
    no entry keeps ``None`` (unknown) for all three.
    """
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
            price_in, price_out, price_request = (prices or {}).get(name, _NO_PRICES)
            discovered.append(
                CloudModelInfo(
                    id=model_id,
                    price_in=price_in,
                    price_out=price_out,
                    price_request=price_request,
                )
            )
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


_OPENAI_DEFAULT_BASE = "https://api.openai.com/v1"


def resolve_openai_base_url() -> str:
    """Resolve the configured OpenAI base URL (``OPENAI_BASE_URL`` /
    ``OPENAI_API_BASE``).

    Callers needing only the *origin* should compare it with
    :func:`openai_base_is_nvidia` rather than echoing the URL: a proxy base can
    embed credentials.
    """
    return (
        os.environ.get("OPENAI_BASE_URL")
        or os.environ.get("OPENAI_API_BASE")
        or _OPENAI_DEFAULT_BASE
    ).rstrip("/")


def _openai_models_url() -> str:
    """Resolve the OpenAI ``/models`` URL, honoring proxy/Azure base overrides."""
    base = resolve_openai_base_url()
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


def _origin(url: str) -> tuple[str, str, int] | None:
    """``(scheme, host, port)`` of ``url``, or ``None`` when it is not http(s)."""
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return None
    host = (parts.hostname or "").lower()
    scheme = parts.scheme.lower()
    if scheme not in ("http", "https") or not host:
        return None
    return scheme, host, port or (443 if scheme == "https" else 80)


def nvidia_base_is_documented() -> bool:
    """Whether ``NVIDIA_BASE_URL`` (or its default) is NVIDIA's documented origin.

    An on-prem NIM behind ``NVIDIA_BASE_URL`` is not the hosted free tier, so
    :mod:`agentic_v2.models.price_label` believes the free-tier declaration
    only while this is true.
    """
    return _origin(resolve_nvidia_base_url()) == _origin(_NVIDIA_DEFAULT_BASE)


def openai_base_is_nvidia() -> bool:
    """Whether the ``openai:`` provider is an alias for NVIDIA's hosted API.

    True when the configured OpenAI base URL has exactly NVIDIA's documented
    origin (an OpenAI-compatible client pointed at ``integrate.api.nvidia.com``),
    so its models are NVIDIA endpoints. Compares origins only and returns a
    bool: the URL itself is never logged or returned.
    """
    return _origin(resolve_openai_base_url()) == _origin(_NVIDIA_DEFAULT_BASE)


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

# Emergency static fallback (bare ids — the ``openrouter:`` prefix is applied
# by ``_dedup_prefixed``). Free-tier ids carry OpenRouter's ``:free`` suffix, so
# a full app id has two colons.
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


def openrouter_base_is_documented() -> bool:
    """Whether the resolved OpenRouter base is OpenRouter's documented origin.

    Prices in the catalog are believed only from the documented origin: a
    gateway behind ``OPENROUTER_BASE_URL`` can publish any number, and a free
    price on a gateway proves nothing about what you are billed.
    """
    return _origin(resolve_openrouter_base_url()) == _origin(_OPENROUTER_DEFAULT_BASE)


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
    blocklist so embeddings/rerankers never enter the chat catalog.
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


def _parse_openrouter_ids(payload: Any) -> list[str] | None:
    """Return every chat-compatible id, or ``None`` for an invalid payload.

    The API request asks for every output modality. The playground
    currently consumes text streams, so image/audio-only and obvious
    non-chat models are excluded while multimodal models that can output
    text remain available.
    """
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        return None
    model_ids: list[str] = []
    for entry in payload["data"]:
        model_id = _openrouter_text_chat_id(entry)
        if model_id is not None:
            model_ids.append(model_id)
    return sorted(set(model_ids))


def _per_million(value: object) -> float | None:
    """USD per token as published (``"0.000003"``) -> USD per million tokens.

    ``None`` unless a finite number, so an unreadable token price reads as
    "not published" and never as 0. A negative value (OpenRouter's ``"-1"``
    marker for dynamically priced routers) is kept: the label rule turns it
    into "unknown".
    """
    if isinstance(value, bool) or not isinstance(value, str | int | float):
        return None
    try:
        price = float(Decimal(str(value).strip()) * 1_000_000)
    except (ArithmeticError, ValueError):
        return None
    return price if math.isfinite(price) else None


def _per_call(value: object) -> float | None:
    """USD per request: ``None`` when absent, NaN when present but unreadable.

    NaN (not ``None``) so a fee that cannot be read makes the label "unknown"
    instead of silently reading as "no fee" and turning a metered model free.
    """
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, str | int | float):
        return math.nan
    try:
        return float(Decimal(str(value).strip()))
    except (ArithmeticError, ValueError):
        return math.nan


def _parse_openrouter_prices(payload: Any) -> dict[str, _PriceTriple]:
    """Map each catalog id to its published ``pricing`` triple (first entry wins)."""
    prices: dict[str, _PriceTriple] = {}
    if not isinstance(payload, dict) or not isinstance(payload.get("data"), list):
        return prices
    for entry in payload["data"]:
        if not isinstance(entry, dict):
            continue
        model_id = entry.get("id")
        if not isinstance(model_id, str) or model_id in prices:
            continue
        pricing = entry.get("pricing")
        pricing = pricing if isinstance(pricing, dict) else {}
        prices[model_id] = (
            _per_million(pricing.get("prompt")),
            _per_million(pricing.get("completion")),
            _per_call(pricing.get("request")),
        )
    return prices


def discover_openrouter_models() -> list[CloudModelInfo]:
    """List the full chat-compatible OpenRouter catalog (best-effort, cached).

    OpenRouter's catalog endpoint is public, so it is queried with or without
    ``OPENROUTER_API_KEY``; a configured key is still sent as bearer auth for
    gateways that require it. Failed fetches reuse the last live listing, then
    the static fallback. Ids retain ``publisher/model[:free]`` so they
    round-trip to the runtime backends. The catalog's published prices ride
    along on each :class:`CloudModelInfo` (and through the cache); the static
    fallback carries none -- a ``:free`` suffix is not read as a price.
    """
    api_key = os.environ.get("OPENROUTER_API_KEY")
    cached = _read_openrouter_cache(allow_expired=False)
    if cached is not None:
        return cached
    url = f"{resolve_openrouter_base_url()}/models"
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else None
    payload = _get_json(
        url,
        headers=headers,
        params={"output_modalities": "all"},
    )
    model_ids = _parse_openrouter_ids(payload)
    if not model_ids:
        # ``None`` (transport failure / bad shape) and ``[]`` (a catalog with
        # no chat-compatible models — e.g. a self-hosted gateway behind
        # OPENROUTER_BASE_URL) both fall back rather than caching an empty
        # listing that would beat the static fallback for a whole TTL.
        stale = _read_openrouter_cache(allow_expired=True)
        if stale is not None:
            return stale
        return _dedup_prefixed("openrouter", list(_OPENROUTER_STATIC_FALLBACK))
    discovered = _dedup_prefixed(
        "openrouter", model_ids, _parse_openrouter_prices(payload)
    )
    _write_openrouter_cache(discovered)
    return discovered


# ---------------------------------------------------------------------------
# Mistral (La Plateforme)
# ---------------------------------------------------------------------------

_MISTRAL_DEFAULT_BASE = "https://api.mistral.ai/v1"

# Mistral ``capabilities`` flag -> the tag the probe rows and pack builder use
# (a subset of KNOWN_MODEL_CAPABILITIES). Flags with no tag there -- fine_tuning,
# completion_fim, classification, ... -- are dropped. Order is the tag order.
_MISTRAL_CAPABILITY_TAGS: tuple[tuple[str, str], ...] = (
    ("function_calling", "tools"),
    ("vision", "vision"),
    ("reasoning", "reasoning"),
    ("audio", "audio"),
)


def resolve_mistral_base_url() -> str:
    """Resolve the Mistral ``/v1`` base URL.

    Honors ``MISTRAL_BASE_URL`` (the variable ``langchain-mistralai`` reads
    itself) for proxies/gateways; falls back to the public endpoint. The ``/v1``
    segment is appended when the operator omits it so callers can append
    ``/models`` unconditionally. This is the single source of truth shared by
    discovery and :func:`agentic_v2.langchain.model_builders.build_mistral_model`,
    so a discovered id is reachable at the host inference targets.
    """
    base = (os.environ.get("MISTRAL_BASE_URL") or _MISTRAL_DEFAULT_BASE).rstrip("/")
    if not base.endswith("/v1"):
        base = f"{base}/v1"
    return base


def mistral_base_is_documented() -> bool:
    """Whether the resolved Mistral base is Mistral's documented origin.

    The free-tier declaration (``MISTRAL_FREE_TIER``) describes the account at
    Mistral's own API, not whatever sits behind a gateway, so
    :mod:`agentic_v2.models.price_label` believes it only while this is true.
    """
    return _origin(resolve_mistral_base_url()) == _origin(_MISTRAL_DEFAULT_BASE)


def _mistral_entries(payload: Any) -> list[Any]:
    """The model cards in a ``/v1/models`` payload (``{"data": [...]}`` or a bare
    array)."""
    if isinstance(payload, dict):
        payload = payload.get("data")
    return payload if isinstance(payload, list) else []


def _mistral_chat_id(entry: Any) -> str | None:
    """Return the card's id when it is a live chat model, else ``None``.

    The listing's own ``capabilities.completion_chat`` flag decides: it is what
    keeps embeddings, OCR (which advertises vision and tools but not chat),
    moderation and transcription out, and the id heuristic used elsewhere would
    be a guess by comparison. A missing flag therefore means "not chat" and
    ``archived`` cards are skipped. ``deprecation`` is deliberately **not** a
    filter: a deprecated model the API still lists is still callable, and a
    retired one is no longer listed at all.
    """
    if not isinstance(entry, dict):
        return None
    model_id = entry.get("id")
    if not isinstance(model_id, str) or not model_id:
        return None
    if entry.get("archived") is True:
        return None
    capabilities = entry.get("capabilities")
    if not isinstance(capabilities, dict):
        return None
    if capabilities.get("completion_chat") is not True:
        return None
    return model_id


def _mistral_capability_tags(entry: Mapping[str, Any]) -> tuple[str, ...]:
    """The probe tags for a chat card's literally-true capability flags."""
    flags = entry.get("capabilities")
    if not isinstance(flags, dict):
        return ()
    return tuple(
        tag for flag, tag in _MISTRAL_CAPABILITY_TAGS if flags.get(flag) is True
    )


def discover_mistral_models() -> list[CloudModelInfo]:
    """List the Mistral chat models the configured key can reach (best-effort).

    Keyed: with no ``MISTRAL_API_KEY`` there is no call. The key travels only as
    a bearer header. Every chat id the API returns is kept as its own entry --
    ``-latest`` aliases next to dated ids, and Labs models -- because a user may
    want a pinned id or a floating one; ids are de-duplicated, never collapsed
    onto a canonical name. Mistral publishes no prices in this listing, so no
    price rides along (see :mod:`agentic_v2.models.price_label`); the listing's
    capability flags ride along as probe tags (see :class:`CloudModelInfo`).
    """
    api_key = os.environ.get("MISTRAL_API_KEY")
    if not api_key:
        return []
    payload = _get_json(
        f"{resolve_mistral_base_url()}/models",
        headers={"Authorization": f"Bearer {api_key}"},
    )
    discovered: list[CloudModelInfo] = []
    seen: set[str] = set()
    for entry in _mistral_entries(payload):
        model_id = _mistral_chat_id(entry)
        if model_id is None or model_id in seen:
            continue
        seen.add(model_id)
        discovered.append(
            CloudModelInfo(
                id=f"mistral:{model_id}", capabilities=_mistral_capability_tags(entry)
            )
        )
    return discovered


def discover_cloud_models() -> list[CloudModelInfo]:
    """Aggregate live cloud-provider listings (best-effort).

    Providers without a configured key make no network call and
    contribute nothing, except OpenRouter's public catalog. The probes
    run concurrently so worst-case latency is a single timeout (~8s)
    rather than the sum of all probes; provider order is preserved.
    Never raises.
    """
    probes = (
        discover_openai_models,
        discover_anthropic_models,
        discover_gemini_models,
        discover_github_models,
        discover_nvidia_models,
        discover_openrouter_models,
        discover_mistral_models,
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
    "discover_mistral_models",
    "discover_nvidia_models",
    "discover_openai_models",
    "discover_openrouter_models",
    "mistral_base_is_documented",
    "nvidia_base_is_documented",
    "openai_base_is_nvidia",
    "openrouter_base_is_documented",
    "resolve_mistral_base_url",
    "resolve_nvidia_base_url",
    "resolve_openai_base_url",
    "resolve_openrouter_base_url",
]
