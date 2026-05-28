"""Provider detection utilities and shared helpers for the LangChain model registry.

This module contains stateless utilities that operate on model ID strings, provider
environment variables, and transient-failure classification.  It has no dependency
on any LangChain package and can be imported without side effects.

Public API
----------
provider_prefix(model_id)
    Extract the provider prefix from a prefixed model ID string.

is_provider_available(provider)
    Return True when the required env vars for a provider are set.

is_retryable_model_error(exc)
    Heuristic: return True for transient provider / network errors.

dedupe_keep_order(items)
    Deduplicate a list of strings while preserving first-seen order.

resolve_model_override(model_override)
    Resolve a model override string (supports ``env:VAR|fallback`` syntax).

PROVIDER_ENV_KEYS
    Mapping of provider name to list of env-var keys that gate it.

TRANSIENT_HTTP_STATUS_CODES
    Set of HTTP status codes treated as transient failures.

GH_BACKUP_MODELS
    Tuple of GitHub Models fallback model IDs.
"""

from __future__ import annotations

import logging
import os
from typing import Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Provider gate — env-var keys required per provider
# ---------------------------------------------------------------------------

PROVIDER_ENV_KEYS: dict[str, list[str]] = {
    "gemini": ["GOOGLE_API_KEY", "GEMINI_API_KEY"],
    "anthropic": ["ANTHROPIC_API_KEY"],
    "openai": ["OPENAI_API_KEY"],
    "gh": ["GITHUB_TOKEN"],
    "ollama": [],  # always available (local)
    "local": [],  # always available (ONNX)
    "lmstudio": [],  # always available (local server)
    "local_api": [],  # always available (local server)
}

# ---------------------------------------------------------------------------
# Transient failure constants
# ---------------------------------------------------------------------------

TRANSIENT_HTTP_STATUS_CODES: frozenset[int] = frozenset(
    {408, 409, 425, 429, 500, 502, 503, 504}
)

GH_BACKUP_MODELS: tuple[str, ...] = (
    "gh:openai/gpt-4o-mini",
    "gh:openai/gpt-4o",
)

# ---------------------------------------------------------------------------
# Provider detection
# ---------------------------------------------------------------------------


def provider_prefix(model_id: str) -> str:
    """Extract the provider prefix from a model ID.

    Parameters
    ----------
    model_id:
        A prefixed model ID such as ``gh:openai/gpt-4o`` or ``ollama:qwen3:8b``.
        When no colon is present the string is treated as an Ollama model name.

    Returns
    -------
    The portion of *model_id* before the first colon, or ``"ollama"`` when no
    colon is present.

    Examples
    --------
    >>> provider_prefix("gh:openai/gpt-4o")
    'gh'
    >>> provider_prefix("gemini:gemini-2.0-flash")
    'gemini'
    >>> provider_prefix("qwen3:8b")
    'qwen3'
    """
    return model_id.split(":")[0] if ":" in model_id else "ollama"


def is_provider_available(provider: str) -> bool:
    """Check whether a provider's required environment variables are present.

    Parameters
    ----------
    provider:
        Provider name key as used in :data:`PROVIDER_ENV_KEYS`, e.g.
        ``"gemini"``, ``"anthropic"``, ``"gh"``.

    Returns
    -------
    ``True`` when at least one of the required env vars is non-empty, or when
    the provider has no env-var requirements (e.g. Ollama, local ONNX).
    ``False`` when all required vars are absent.
    """
    keys = PROVIDER_ENV_KEYS.get(provider, [])
    if not keys:
        return True  # ollama / local -- no key required
    return any(os.environ.get(k) for k in keys)


def probe_available_providers() -> dict[str, bool]:
    """Probe which LLM providers have credentials configured."""
    return {prov: is_provider_available(prov) for prov in PROVIDER_ENV_KEYS}


# ---------------------------------------------------------------------------
# Retryable error classification
# ---------------------------------------------------------------------------


def is_retryable_model_error(exc: Exception) -> bool:
    """Heuristic classification for transient model / provider failures.

    Returns ``True`` for errors that are likely transient and worth retrying:
    rate limits, timeouts, service unavailability, and connection resets.

    Parameters
    ----------
    exc:
        The exception to classify.

    Returns
    -------
    ``True`` when the error is classified as transient, ``False`` otherwise.
    """
    status_code: Any = getattr(exc, "status_code", None)
    if status_code is None:
        response = getattr(exc, "response", None)
        status_code = getattr(response, "status_code", None)
    try:
        if int(status_code) in TRANSIENT_HTTP_STATUS_CODES:
            return True
    except (TypeError, ValueError):
        pass

    cls = exc.__class__.__name__.lower()
    msg = str(exc).lower()

    if any(
        token in cls
        for token in (
            "ratelimit",
            "timeout",
            "apiconnection",
            "serviceunavailable",
            "temporar",
        )
    ):
        return True

    return any(
        token in msg
        for token in (
            "429",
            "too many requests",
            "rate limit",
            "quota exceeded",
            "resource exhausted",
            "temporarily unavailable",
            "service unavailable",
            "overloaded",
            "timeout",
            "timed out",
            "connection reset",
            "connection error",
            "upstream error",
            "try again later",
        )
    )


# ---------------------------------------------------------------------------
# List helpers
# ---------------------------------------------------------------------------


def dedupe_keep_order(items: list[str]) -> list[str]:
    """Return a deduplicated list preserving first-seen order.

    Empty strings and strings that consist solely of whitespace are discarded.

    Parameters
    ----------
    items:
        Input list of strings, may contain duplicates or blank entries.

    Returns
    -------
    A new list with duplicates removed, order preserved.
    """
    out: list[str] = []
    seen: set[str] = set()
    for item in items:
        val = (item or "").strip()
        if not val or val in seen:
            continue
        seen.add(val)
        out.append(val)
    return out


# ---------------------------------------------------------------------------
# Model override resolution
# ---------------------------------------------------------------------------


def resolve_model_override(model_override: str) -> str:
    """Resolve a model override string.

    Supported forms:

    - ``gh:openai/gpt-4o``          — returned as-is (direct model ID)
    - ``ollama:deepseek-r1``        — returned as-is (direct model ID)
    - ``env:VAR_NAME``              — required environment variable; raises if absent
    - ``env:VAR_NAME|gh:openai/gpt-4o-mini`` — env var with inline fallback

    Parameters
    ----------
    model_override:
        A model ID string or ``env:``-prefixed override expression.

    Returns
    -------
    The resolved model ID string.

    Raises
    ------
    ValueError
        When the ``env:`` prefix is malformed or the env var is absent and no
        fallback is provided.
    """
    if not model_override.startswith("env:"):
        return model_override

    raw = model_override[4:].strip()
    if not raw:
        raise ValueError("Invalid model override 'env:' (missing variable name).")

    if "|" in raw:
        env_key, fallback = raw.split("|", 1)
        env_key = env_key.strip()
        fallback = fallback.strip()
    else:
        env_key, fallback = raw, ""

    if not env_key:
        raise ValueError("Invalid model override: missing env var name.")

    env_val = os.environ.get(env_key, "").strip()
    if env_val:
        return env_val
    if fallback:
        return fallback

    raise ValueError(
        f"Model override requires environment variable '{env_key}', "
        "but it is not set."
    )
