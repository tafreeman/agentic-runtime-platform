"""Provider-specific model probing -- dispatcher and re-exports.

This module re-exports all probe functions from the cloud and local
provider modules and provides the top-level ``probe_model`` dispatcher
and ``get_provider`` utility.
"""

from __future__ import annotations

from datetime import datetime
from typing import Callable

from tools.core.errors import ErrorCode
from tools.llm.probe_config import (
    PREFIX_AITK,
    PREFIX_AITK_ALT,
    PREFIX_AZURE_FOUNDRY,
    PREFIX_AZURE_OPENAI,
    PREFIX_CLAUDE,
    PREFIX_GEMINI,
    PREFIX_GITHUB,
    PREFIX_GITHUB_ALT,
    PREFIX_GPT,
    PREFIX_LMSTUDIO,
    PREFIX_LMSTUDIO_ALT,
    PREFIX_LOCAL,
    PREFIX_LOCAL_API,
    PREFIX_OLLAMA,
    PREFIX_OPENAI,
    PREFIX_WINDOWS_AI,
    ProbeResult,
)

# Re-export all provider probe functions for a single import point
from tools.llm.probe_providers_cloud import (
    probe_azure_foundry,
    probe_azure_openai,
    probe_claude,
    probe_gemini,
    probe_github,
    probe_openai,
)
from tools.llm.probe_providers_local import (
    probe_ai_toolkit,
    probe_lmstudio,
    probe_local,
    probe_local_api,
    probe_ollama,
    probe_windows_ai,
)

# Type alias for optional logging callback
LogFn = Callable[[str], None] | None


# =============================================================================
# PROVIDER DETECTION
# =============================================================================


# Ordered (prefixes, provider) pairs; first matching prefix wins.
_PROVIDER_PREFIXES: tuple[tuple[tuple[str, ...], str], ...] = (
    ((PREFIX_LOCAL,), "local"),
    ((PREFIX_WINDOWS_AI,), "windows_ai"),
    ((PREFIX_GITHUB, PREFIX_GITHUB_ALT), "github"),
    ((PREFIX_OPENAI, PREFIX_GPT), "openai"),
    ((PREFIX_AZURE_FOUNDRY,), "azure_foundry"),
    ((PREFIX_AZURE_OPENAI,), "azure_openai"),
    ((PREFIX_OLLAMA,), "ollama"),
    ((PREFIX_GEMINI,), "gemini"),
    ((PREFIX_AITK, PREFIX_AITK_ALT), "ai_toolkit"),
    ((PREFIX_CLAUDE,), "claude"),
    ((PREFIX_LMSTUDIO, PREFIX_LMSTUDIO_ALT), "lmstudio"),
    ((PREFIX_LOCAL_API,), "local_api"),
)


def get_provider(model: str) -> str:
    """Extract provider name from a model identifier string."""
    for prefixes, provider in _PROVIDER_PREFIXES:
        if model.startswith(prefixes):
            return provider
    return "unknown"


# =============================================================================
# DISPATCHER
# =============================================================================


def probe_model(model: str, log: LogFn = None) -> ProbeResult:
    """Probe a model based on its provider prefix.

    Args:
        model: Model identifier (e.g. "gh:gpt-4o-mini", "local:phi4").
        log: Optional logging callback.

    Returns:
        ProbeResult with the probe outcome.
    """
    provider = get_provider(model)

    if provider == "local":
        return probe_local(model, log)
    elif provider == "windows_ai":
        return probe_windows_ai(model, log)
    elif provider == "github":
        return probe_github(model, log)
    elif provider == "azure_foundry":
        return probe_azure_foundry(model, log)
    elif provider == "azure_openai":
        return probe_azure_openai(model, log)
    elif provider == "ollama":
        return probe_ollama(model, log)
    elif provider == "openai":
        return probe_openai(model, log)
    elif provider == "gemini":
        return probe_gemini(model, log)
    elif provider == "claude":
        return probe_claude(model, log)
    elif provider == "ai_toolkit":
        return probe_ai_toolkit(model, log)
    elif provider == "lmstudio":
        return probe_lmstudio(model, log)
    elif provider == "local_api":
        return probe_local_api(model, log)
    else:
        # Unknown provider -- not usable without a probe method
        return ProbeResult(
            model=model,
            provider=provider,
            usable=False,
            error_code=ErrorCode.INVALID_INPUT.value,
            error_message=f"Unknown provider '{provider}' -- no probe available",
            probe_time=datetime.now().isoformat(),
            duration_ms=0,
        )
