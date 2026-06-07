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
from pathlib import Path
from typing import Any

from .model_builders import (
    _resolve_notebooklm_model_name,
    build_anthropic_model,
    build_gemini_model,
    build_github_model,
    build_lmstudio_model,
    build_local_api_model,
    build_local_onnx_model,
    build_notebooklm_model,
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


def _configure_native_router(availability: dict[str, bool]) -> None:
    """Set a health-checker on the native ModelRouter so it skips unavailable
    providers."""
    try:
        from ..models.router import get_router
    except ImportError:
        return

    router = get_router()

    def _env_health_checker(model_id: str) -> bool:
        p = provider_prefix(model_id)
        return availability.get(p, is_provider_available(p))

    router.set_health_checker(_env_health_checker)

    # Pre-mark unavailable models so the router doesn't try them
    try:
        from ..models.router import DEFAULT_CHAINS, ModelTier
    except ImportError:
        return

    for p, available in availability.items():
        if not available:
            for tier_enum in ModelTier:
                if tier_enum == ModelTier.TIER_0:
                    continue
                chain = DEFAULT_CHAINS.get(tier_enum)
                if chain:
                    for m in chain:
                        if provider_prefix(m) == p:
                            router.mark_unavailable(m)

    logger.debug("Native ModelRouter configured with env-var health checker")


# ---------------------------------------------------------------------------
# Provider dispatch
# ---------------------------------------------------------------------------


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

    if model_id.startswith("gh:"):
        return build_github_model(model_id[3:], temperature)

    if model_id.startswith("ollama:"):
        return build_ollama_model(model_id[7:], temperature)

    if model_id.startswith("openai:"):
        return build_openai_model(model_id[7:], temperature)

    if model_id.startswith("anthropic:"):
        return build_anthropic_model(model_id[10:], temperature)

    if model_id.startswith("claude:"):
        return build_anthropic_model(model_id[7:], temperature)

    if model_id.startswith("gemini:"):
        return build_gemini_model(model_id[7:], temperature)

    if model_id == "notebooklm":
        return build_notebooklm_model("", temperature)

    if model_id.startswith("notebooklm:"):
        return build_notebooklm_model(model_id[11:], temperature)

    if model_id.startswith("local:"):
        return build_local_onnx_model(model_id[6:], temperature)

    if model_id.startswith("lmstudio:"):
        return build_lmstudio_model(model_id[9:], temperature)

    if model_id.startswith("local-api:"):
        return build_local_api_model(model_id[10:], temperature)

    # Bare name without prefix -- treat as Ollama local model
    if not any(
        model_id.startswith(p)
        for p in (
            "openai:",
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
    ):
        return build_ollama_model(model_id, temperature)

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
        f"No available model for tier {tier}. "
        f"Checked: {chain}. "
        f"Last error: {last_err}"
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
    # re-exported from model_builders
    "build_github_model",
    "build_openai_model",
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
