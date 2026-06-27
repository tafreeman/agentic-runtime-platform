"""Model provider registry for the LangChain workflow engine.

Supported providers:
- GitHub Models          (prefix ``gh:``)            via OpenAI-compatible API
- Ollama                 (prefix ``ollama:``)        local or remote Ollama
- OpenAI                 (prefix ``openai:``)        direct OpenAI API
- Anthropic              (prefix ``anthropic:`` / ``claude:``)
- Gemini                 (prefix ``gemini:``)
- NotebookLM alias       (prefix ``notebooklm:``)    routes to Gemini model
- Local ONNX             (prefix ``local:``)         via repo ``LLMClient``
- LM Studio              (prefix ``lmstudio:``)      via OpenAI-compatible API
- Local API              (prefix ``local-api:``)     via OpenAI-compatible API

Environment variables
---------------------
GITHUB_TOKEN
    Personal access token for GitHub Models API.
OLLAMA_BASE_URL
    Override Ollama server URL (default: ``http://localhost:11434``).
OPENAI_API_KEY
    API key for OpenAI provider.
ANTHROPIC_API_KEY
    API key for Anthropic provider.
GOOGLE_API_KEY / GEMINI_API_KEY
    API key for Gemini provider.
NOTEBOOKLM_MODEL / NOTEBOOKLM_GEMINI_MODEL
    Optional default Gemini model used by ``notebooklm:`` alias.
AGENTIC_MODEL_TIER_{N}
    Force a specific model ID for tier N (e.g. ``AGENTIC_MODEL_TIER_2=gh:openai/gpt-4o``).
DEEP_RESEARCH_* (optional)
    Can be used with ``env:VAR|fallback`` per-step overrides in workflow YAML.

Implementation notes
--------------------
Builder functions live in :mod:`agentic_v2.langchain.model_builders`.
Provider detection utilities live in :mod:`agentic_v2.langchain.model_utils`.
Both are re-exported here so that ``from agentic_v2.langchain.models import X``
continues to work unchanged.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..models.router import FallbackChain, ModelRouter, ModelTier

from ..models.cloud_discovery import discover_cloud_models
from ..models.local_discovery import (
    LocalModelInfo,
    discover_lmstudio_models,
    discover_onnx_models,
)
from ..models.ollama_discovery import discover_ollama_models
from .model_builders import (
    _resolve_notebooklm_model_name,
    build_anthropic_model,
    build_gemini_model,
    build_github_model,
    build_lmstudio_model,
    build_local_api_model,
    build_local_onnx_model,
    build_notebooklm_model,
    build_nvidia_model,
    build_ollama_model,
    build_openai_model,
    build_placeholder_model,
)
from .model_utils import (
    GH_BACKUP_MODELS,
    PROVIDER_ENV_KEYS,
    dedupe_keep_order,
    is_provider_available,
    is_retryable_model_error,
    provider_prefix,
    resolve_model_override,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# String constants (extracted to satisfy python:S1192 — define once, reuse)
# ---------------------------------------------------------------------------

MODEL_GEMINI_FLASH = "gemini:gemini-2.5-flash"
MODEL_GH_GPT4O = "gh:openai/gpt-4o"
MODEL_OPENAI_GPT4O = "openai:gpt-4o"
MODEL_ANTHROPIC_CLAUDE_SONNET = "anthropic:claude-sonnet-4-6-20260219"
MODEL_OLLAMA_QWEN3 = "ollama:qwen3-coder:30b"

# ---------------------------------------------------------------------------
# Load .env so API keys are available when invoked via uvicorn directly
# (the CLI entry point already does this, but server startup may bypass it)
# ---------------------------------------------------------------------------

try:
    from dotenv import load_dotenv as _load_dotenv

    for _p in Path(__file__).resolve().parents:
        _env = _p / ".env"
        if _env.is_file():
            _load_dotenv(_env, override=False)
            break
except ImportError:
    pass

# ---------------------------------------------------------------------------
# Tier defaults (updated dynamically by probe_and_update_tier_defaults)
# ---------------------------------------------------------------------------

_TIER_DEFAULTS: dict[int, str] = {
    1: "gemini:gemini-2.0-flash-lite",
    2: "gemini:gemini-2.0-flash",
    3: MODEL_GEMINI_FLASH,
    4: MODEL_GEMINI_FLASH,
    5: MODEL_GEMINI_FLASH,
}

# Models ranked by reasoning capability per tier.
# First available provider wins during probe.
_TIER_FALLBACK_CHAINS: dict[int, list[str]] = {
    # Tier 1: fast / cheap -- summarisation, extraction, simple tasks
    1: [
        "gemini:gemini-2.0-flash-lite",
        "gh:openai/gpt-4o-mini",
        "openai:gpt-4o-mini",
        "anthropic:claude-haiku-4-5-20251001",
        "ollama:gemma3:4b",
    ],
    # Tier 2: balanced -- code review, moderate reasoning
    2: [
        "gemini:gemini-2.0-flash",
        MODEL_GH_GPT4O,
        MODEL_OPENAI_GPT4O,
        MODEL_ANTHROPIC_CLAUDE_SONNET,
        "ollama:qwen3:8b",
    ],
    # Tier 3: strong reasoning -- architecture, complex code gen
    3: [
        MODEL_GEMINI_FLASH,
        MODEL_ANTHROPIC_CLAUDE_SONNET,
        MODEL_OPENAI_GPT4O,
        MODEL_GH_GPT4O,
        MODEL_OLLAMA_QWEN3,
    ],
    # Tier 4: top-tier -- hard problems, multi-step planning
    4: [
        MODEL_GEMINI_FLASH,
        MODEL_ANTHROPIC_CLAUDE_SONNET,
        MODEL_OPENAI_GPT4O,
        MODEL_GH_GPT4O,
        MODEL_OLLAMA_QWEN3,
    ],
    # Tier 5: best available -- research, deep analysis
    5: [
        MODEL_GEMINI_FLASH,
        MODEL_ANTHROPIC_CLAUDE_SONNET,
        MODEL_OPENAI_GPT4O,
        MODEL_GH_GPT4O,
        MODEL_OLLAMA_QWEN3,
    ],
}

# NOTE: probe_and_update_tier_defaults() is intentionally NOT called here.
# It is called once from the FastAPI lifespan handler in server/app.py so that
# it runs at server startup only -- not on every test import, which would mutate
# global _TIER_DEFAULTS and cause test-order dependencies.

# ---------------------------------------------------------------------------
# Private aliases for backward compatibility
# (tests that imported the underscore-prefixed private names)
# ---------------------------------------------------------------------------

_provider_prefix = provider_prefix
_is_provider_available = is_provider_available
_dedupe_keep_order = dedupe_keep_order
_resolve_model_override = resolve_model_override

# ---------------------------------------------------------------------------
# Provider availability probe
# ---------------------------------------------------------------------------


def probe_available_providers() -> dict[str, bool]:
    """Probe which LLM providers have credentials configured."""
    return {prov: is_provider_available(prov) for prov in PROVIDER_ENV_KEYS}


def probe_and_update_tier_defaults() -> dict[str, Any]:
    """Probe providers and update ``_TIER_DEFAULTS`` to the best available model per
    tier.

    Called on module import and can be re-called at server startup to pick up
    env changes.  Also installs a health-checker on the native ``ModelRouter``
    so both engines benefit from the same availability data.

    Returns a summary dict with provider availability and resolved tier defaults.
    """
    availability = probe_available_providers()

    available_providers = [p for p, ok in availability.items() if ok]
    unavailable_providers = [p for p, ok in availability.items() if not ok]

    resolved: dict[int, str] = {}
    for tier, chain in _TIER_FALLBACK_CHAINS.items():
        for model_id in chain:
            p = provider_prefix(model_id)
            if is_provider_available(p):
                resolved[tier] = model_id
                break
        else:
            resolved[tier] = _TIER_DEFAULTS.get(tier, chain[-1])

    _TIER_DEFAULTS.update(resolved)

    # Also configure the native engine router with the same env-var checker
    _configure_native_router(availability)

    summary = {
        "available_providers": available_providers,
        "unavailable_providers": unavailable_providers,
        "tier_defaults": dict(_TIER_DEFAULTS),
    }

    logger.info(
        "Model probe complete: available=%s, unavailable=%s",
        available_providers,
        unavailable_providers,
    )
    for tier, model_id in sorted(_TIER_DEFAULTS.items()):
        logger.info("  Tier %d -> %s", tier, model_id)

    return summary


def _merge_ollama_models(models: list[dict[str, Any]]) -> None:
    """Enrich/append live Ollama discovery into ``models`` in place.

    Models already in the catalog get marked available and enriched with cloud /
    capability / running metadata from the raw ``/api/tags`` + ``/api/ps``
    payloads; models absent from every tier chain are appended at tier 0 so the
    console reflects everything currently runnable.
    """
    discovered = discover_ollama_models()
    by_id = {info.id: info for info in discovered}
    catalog_ids = {m["id"] for m in models}
    for model in models:
        info = by_id.get(model["id"])
        if info is not None:
            model["available"] = True
            model["cloud"] = info.cloud
            model["capabilities"] = list(info.capabilities)
            model["running"] = info.running
    for info in discovered:
        if info.id in catalog_ids:
            continue
        models.append(
            {
                "id": info.id,
                "provider": provider_prefix(info.id),
                "tier": 0,
                "available": True,
                "cloud": info.cloud,
                "capabilities": list(info.capabilities),
                "running": info.running,
            }
        )


def _enrich_local_model(model: dict[str, Any], info: LocalModelInfo) -> None:
    """Mark a catalog ``model`` available and copy LM Studio / ONNX metadata."""
    model["available"] = True
    if info.running:
        model["running"] = True
    if info.capabilities:
        model["capabilities"] = list(info.capabilities)


def _merge_local_models(models: list[dict[str, Any]]) -> None:
    """Enrich/append LM Studio + ONNX discovery into ``models`` in place.

    LM Studio's native API supplies the full downloaded library plus running /
    vision metadata; ONNX supplies filesystem-scanned folders. Catalog entries
    that are discovered get enriched; the rest are appended at tier 0 (ADR-038).
    """
    local_infos = [*discover_lmstudio_models(), *discover_onnx_models()]
    local_by_id = {info.id: info for info in local_infos}
    for model in models:
        info = local_by_id.get(model["id"])
        if info is not None:
            _enrich_local_model(model, info)
    known_ids = {m["id"] for m in models}
    for info in local_infos:
        if info.id in known_ids:
            continue
        known_ids.add(info.id)
        entry: dict[str, Any] = {
            "id": info.id,
            "provider": provider_prefix(info.id),
            "tier": 0,
            "available": True,
        }
        if info.running:
            entry["running"] = True
        if info.capabilities:
            entry["capabilities"] = list(info.capabilities)
        models.append(entry)


def _merge_cloud_models(models: list[dict[str, Any]]) -> None:
    """Append live cloud-provider listings (OpenAI/Anthropic/Gemini/GitHub).

    Skipped entirely in no-LLM mode: that mode routes every tier to the
    deterministic placeholder, so a live cloud listing would be both misleading
    and a needless network/cost liability (it also keeps the unit suite — which
    runs with ``AGENTIC_NO_LLM=1`` — hermetic). Discovered ids absent from the
    static chains are appended at tier 0; only keyed providers make a call.
    """
    from ..settings import is_agentic_no_llm_enabled

    if is_agentic_no_llm_enabled():
        return
    known_ids = {m["id"] for m in models}
    for info in discover_cloud_models():
        if info.id in known_ids:
            continue
        known_ids.add(info.id)
        models.append(
            {
                "id": info.id,
                "provider": provider_prefix(info.id),
                "tier": 0,
                "available": True,
            }
        )


def enumerate_known_models() -> list[dict[str, Any]]:
    """Return every tier-chain model plus live-discovered local/cloud models.

    Each entry carries the model id, its provider prefix, the lowest tier the
    model appears in (``0`` for live-discovered models not in any chain), and
    whether that provider currently has credentials configured. Unlike
    :func:`probe_and_update_tier_defaults` (which returns one resolved default
    per tier), this surfaces the *full* catalog plus whatever the local Ollama /
    LM Studio servers, the ONNX cache, and (when keyed) the Ollama cloud expose
    right now, so the console shows everything currently runnable — not just the
    static fallback chains.
    """
    lowest_tier: dict[str, int] = {}
    for tier, chain in _TIER_FALLBACK_CHAINS.items():
        for model_id in chain:
            existing = lowest_tier.get(model_id)
            if existing is None or tier < existing:
                lowest_tier[model_id] = tier

    models: list[dict[str, Any]] = [
        {
            "id": model_id,
            "provider": provider_prefix(model_id),
            "tier": tier,
            "available": is_provider_available(provider_prefix(model_id)),
        }
        for model_id, tier in lowest_tier.items()
    ]

    _merge_ollama_models(models)
    _merge_local_models(models)
    _merge_cloud_models(models)

    models.sort(key=lambda m: (m["tier"], str(m["provider"]), str(m["id"])))
    return models


def _make_env_health_checker(
    availability: dict[str, bool],
) -> Callable[[str], bool]:
    """Build a router health-checker closing over the probed availability map.

    The returned callable resolves a model ID to its provider prefix and reports
    availability from ``availability``, falling back to a live env-var probe for
    providers not present in the map.
    """

    def _env_health_checker(model_id: str) -> bool:
        p = provider_prefix(model_id)
        return availability.get(p, is_provider_available(p))

    return _env_health_checker


def _iter_default_chain_models(
    model_tier_enum: type[ModelTier],
    default_chains: dict[ModelTier, FallbackChain],
) -> Iterator[str]:
    """Yield every model ID in the default chains, skipping the no-LLM tier.

    Iterates tiers in enum order and each chain in priority order so the yield
    sequence matches the original nested-loop traversal.
    """
    for tier_enum in model_tier_enum:
        if tier_enum == model_tier_enum.TIER_0:
            continue
        chain = default_chains.get(tier_enum)
        if chain:
            yield from chain


def _premark_unavailable_models(
    router: ModelRouter,
    availability: dict[str, bool],
    model_tier_enum: type[ModelTier],
    default_chains: dict[ModelTier, FallbackChain],
) -> None:
    """Mark every default-chain model from an unavailable provider as unavailable.

    Lets the native router skip providers with no configured credentials instead
    of probing them at request time.
    """
    for provider, available in availability.items():
        if available:
            continue
        for model in _iter_default_chain_models(model_tier_enum, default_chains):
            if provider_prefix(model) == provider:
                router.mark_unavailable(model)


def _configure_native_router(availability: dict[str, bool]) -> None:
    """Set a health-checker on the native ModelRouter so it skips unavailable
    providers."""
    try:
        from ..models.router import get_router
    except ImportError:
        return

    router = get_router()
    router.set_health_checker(_make_env_health_checker(availability))

    # Pre-mark unavailable models so the router doesn't try them
    try:
        from ..models.router import DEFAULT_CHAINS, ModelTier
    except ImportError:
        return

    _premark_unavailable_models(router, availability, ModelTier, DEFAULT_CHAINS)

    logger.debug("Native ModelRouter configured with env-var health checker")


# ---------------------------------------------------------------------------
# Provider dispatch
# ---------------------------------------------------------------------------


# Prefix -> builder dispatch table. Each builder receives the model name
# (model_id with the prefix stripped) and the temperature.  Order matters
# only for documentation; matching strips the leading ``prefix``.
_PREFIX_BUILDERS: tuple[tuple[str, Any], ...] = (
    ("gh:", build_github_model),
    ("ollama:", build_ollama_model),
    ("openai:", build_openai_model),
    ("nvidia:", build_nvidia_model),
    ("anthropic:", build_anthropic_model),
    ("claude:", build_anthropic_model),
    ("gemini:", build_gemini_model),
    ("notebooklm:", build_notebooklm_model),
    # "local-api:" MUST precede "local:" — startswith() matches the first entry,
    # and "local:" is a prefix of "local-api:", so the longer prefix must win.
    ("local-api:", build_local_api_model),
    ("local:", build_local_onnx_model),
    ("lmstudio:", build_lmstudio_model),
)

# Prefixes that are recognized provider namespaces.  A bare name that does not
# start with any of these is treated as an Ollama local model.
_KNOWN_PREFIXES: tuple[str, ...] = (
    "openai:",
    "nvidia:",
    "azure:",
    "local:",
    "windows-ai:",
    "anthropic:",
    "claude:",
    "gemini:",
    "notebooklm:",
    "lmstudio:",
    "local-api:",
)


def _build_model_by_prefix(model_id: str, temperature: float) -> Any | None:
    """Dispatch a prefixed model ID to its builder, or return None if unmatched."""
    if model_id == "notebooklm":
        return build_notebooklm_model("", temperature)

    for prefix, builder in _PREFIX_BUILDERS:
        if model_id.startswith(prefix):
            return builder(model_id[len(prefix) :], temperature)

    # Bare name without prefix -- treat as Ollama local model
    if not any(model_id.startswith(p) for p in _KNOWN_PREFIXES):
        return build_ollama_model(model_id, temperature)

    return None


def get_chat_model(model_id: str, temperature: float = 0.0) -> Any:
    """Resolve a model ID string to a LangChain ``BaseChatModel`` instance.

    Parameters
    ----------
    model_id:
        A prefixed model ID such as ``gh:openai/gpt-4o`` or
        ``ollama:qwen2.5-coder``.
    temperature:
        Sampling temperature passed to the model.

    Returns
    -------
    A LangChain ``BaseChatModel`` instance.

    Raises
    ------
    ValueError
        If the provider prefix is not supported.
    ImportError
        If the required LangChain integration package is not installed.
    """
    model_id = (model_id or "").strip()
    if not model_id:
        raise ValueError("Model ID must be a non-empty string.")

    from ..settings import is_agentic_no_llm_enabled

    if is_agentic_no_llm_enabled():
        return build_placeholder_model(temperature)

    model = _build_model_by_prefix(model_id, temperature)
    if model is not None:
        return model

    raise ValueError(
        f"Unsupported model provider in '{model_id}'. "
        "Supported prefixes: gh:, ollama:, openai:, anthropic:/claude:, "
        "gemini:, notebooklm:, local:, lmstudio:, local-api:."
    )


def get_model_for_tier(tier: int, model_override: str | None = None) -> Any:
    """Return a chat model for the given agent tier.

    Resolution order:
    1. ``model_override`` argument
    2. Env var ``AGENTIC_MODEL_TIER_{tier}``
    3. Tier default from ``_TIER_DEFAULTS`` (set by probe)
    4. Walk the fallback chain trying each available provider
    """
    chain = get_model_candidates_for_tier(
        tier,
        model_override,
        include_unavailable=False,
        include_gh_backup=True,
    )
    last_err: Exception | None = None
    for model_id in chain:
        try:
            return get_chat_model(model_id)
        except (ValueError, ImportError) as exc:
            last_err = exc
            logger.debug("Fallback %s failed: %s", model_id, exc)
            continue

    raise ValueError(
        f"No available model for tier {tier}. Checked: {chain}. Last error: {last_err}"
    )


def get_model_candidates_for_tier(
    tier: int,
    model_override: str | None = None,
    *,
    include_unavailable: bool = False,
    include_gh_backup: bool = True,
) -> list[str]:
    """Return ordered candidate model IDs for a tier, including fallbacks.

    Resolution order:
    1. Per-step ``model_override`` (resolved, supports ``env:VAR|fallback``)
    2. Env var ``AGENTIC_MODEL_TIER_{tier}``
    3. Probed tier default from ``_TIER_DEFAULTS``
    4. Tier fallback chain from ``_TIER_FALLBACK_CHAINS``
    5. GitHub backup models (when ``GITHUB_TOKEN`` is configured)
    """
    pinned: list[str] = []

    if model_override:
        pinned.append(resolve_model_override(model_override))

    env_key = f"AGENTIC_MODEL_TIER_{tier}"
    env_val = (os.environ.get(env_key) or "").strip()
    if env_val:
        pinned.append(env_val)

    default_id = _TIER_DEFAULTS.get(tier, _TIER_DEFAULTS.get(2, "ollama:qwen3:8b"))
    if default_id:
        pinned.append(default_id)

    fallback = list(_TIER_FALLBACK_CHAINS.get(tier, _TIER_FALLBACK_CHAINS.get(2, [])))

    if include_gh_backup and os.environ.get("GITHUB_TOKEN"):
        fallback.extend(GH_BACKUP_MODELS)

    ordered_pinned = dedupe_keep_order(pinned)
    ordered_fallback = dedupe_keep_order(fallback)
    if include_unavailable:
        return dedupe_keep_order(ordered_pinned + ordered_fallback)

    filtered_fallback = [
        m for m in ordered_fallback if is_provider_available(provider_prefix(m))
    ]
    return dedupe_keep_order(ordered_pinned + filtered_fallback)


# ---------------------------------------------------------------------------
# Re-exports for backward compatibility
# ---------------------------------------------------------------------------

__all__ = [
    # core dispatch
    "get_chat_model",
    "get_model_for_tier",
    "get_model_candidates_for_tier",
    # probe helpers
    "probe_available_providers",
    "probe_and_update_tier_defaults",
    "enumerate_known_models",
    "discover_ollama_models",
    # re-exported from model_builders
    "build_github_model",
    "build_openai_model",
    "build_nvidia_model",
    "build_anthropic_model",
    "build_gemini_model",
    "build_notebooklm_model",
    "build_ollama_model",
    "build_lmstudio_model",
    "build_local_api_model",
    "build_local_onnx_model",
    "_resolve_notebooklm_model_name",
    # re-exported from model_utils
    "is_retryable_model_error",
    "provider_prefix",
    "is_provider_available",
    "dedupe_keep_order",
    "resolve_model_override",
    "PROVIDER_ENV_KEYS",
    "GH_BACKUP_MODELS",
]
