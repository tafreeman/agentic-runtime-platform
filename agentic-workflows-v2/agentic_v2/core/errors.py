"""Core error hierarchy for the agentic workflow system.

All domain-specific exceptions inherit from :class:`AgenticError`,
allowing callers to catch broad or narrow categories.
"""

from __future__ import annotations

import enum
from textwrap import dedent


class AgenticError(Exception):
    """Base exception for all agentic workflow errors."""


class WorkflowError(AgenticError):
    """Error during workflow execution."""


class StepError(AgenticError):
    """Error during a single step execution."""


class SchemaValidationError(AgenticError):
    """Error during input or configuration validation."""


class AdapterError(AgenticError):
    """Error in an execution engine adapter."""


class AdapterNotFoundError(AdapterError):
    """Requested adapter is not registered."""


class ToolError(AgenticError):
    """Error during tool execution."""


class MemoryStoreError(AgenticError):
    """Error in a memory store operation."""


class ConfigurationError(AgenticError):
    """Error in configuration loading or validation."""


_NO_PROVIDER_MSG = dedent("""
    No LLM provider configured.

    To fix this, do ONE of the following:
      1. Set an API key:
         export OPENAI_API_KEY=sk-...
         export ANTHROPIC_API_KEY=sk-ant-...
         export GEMINI_API_KEY=...
         (See docs/ONBOARDING.md for the full list.)

      2. Use no-LLM mode:
         export AGENTIC_NO_LLM=1
         (Returns deterministic placeholder output - good for flow testing.)

    More details: docs/NO_LLM_MODE.md
    """).strip()


class NoProviderConfiguredError(ConfigurationError):
    """Raised when no LLM provider is configured and AGENTIC_NO_LLM is not set."""

    def __init__(self, message: str = _NO_PROVIDER_MSG) -> None:
        """Initialize with a default message prompting provider configuration."""
        super().__init__(message)


class ErrorCode(enum.Enum):
    """Classification codes for LLM API errors used by retry logic."""

    RATE_LIMITED = "rate_limited"
    AUTH_ERROR = "auth_error"
    NOT_FOUND = "not_found"
    TRANSIENT = "transient"
    UNKNOWN = "unknown"


def classify_error(error_message: str) -> tuple[ErrorCode, bool]:
    """Classify an error string into an ErrorCode and whether it is retryable.

    Returns:
        A ``(code, should_retry)`` tuple.  ``should_retry`` is ``False`` for
        permanent errors (auth, not-found) and ``True`` for transient ones.
    """
    msg = error_message.lower()
    if any(
        kw in msg
        for kw in ("rate limit", "rate_limit", "ratelimit", "429", "too many requests")
    ):
        return ErrorCode.RATE_LIMITED, True
    if any(
        kw in msg
        for kw in ("401", "403", "unauthorized", "forbidden", "authentication")
    ):
        return ErrorCode.AUTH_ERROR, False
    if "404" in msg or "not found" in msg:
        return ErrorCode.NOT_FOUND, False
    return ErrorCode.TRANSIENT, True
