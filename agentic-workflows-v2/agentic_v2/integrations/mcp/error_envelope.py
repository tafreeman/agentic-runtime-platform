"""MCP-standard tool-result error envelope.

The MCP ``tools/call`` contract distinguishes two failure surfaces:

1. **Protocol errors** (JSON-RPC ``error`` field) — surfaced by the client
   stack as :class:`McpProtocolError` / :class:`McpTimeoutError` exceptions.
2. **Tool-execution errors** (``isError: true`` inside a *successful* JSON-RPC
   result) — these are the model-facing failures the LLM must reason about.

The wrapping :class:`McpToolAdapter` previously collapsed every failure into an
opaque ``"Error: ..."`` string, which is invisible to any retry/escalation
logic the *model* runs. This module defines a structured, MCP-correct envelope
so the result the model sees carries:

* ``isError`` — true only for genuine failures (never for a valid-empty result),
* ``errorCategory`` — one of ``transient`` / ``validation`` / ``business`` /
  ``permission``,
* ``isRetryable`` — whether re-invoking the tool unchanged could succeed,
* human-readable ``text`` — a friendly message embedded in the model context.

Categories are derived by reusing the existing string-based
:func:`agentic_v2.core.errors.classify_error` heuristic (the same engine the
LLM-API retry path uses) rather than introducing a parallel classifier.
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from agentic_v2.core.errors import ErrorCode, classify_error


class ErrorCategory(str, Enum):
    """MCP-facing error categories surfaced to the model.

    These are coarser than the internal :class:`ErrorCode` taxonomy and map
    onto the four buckets a model can act on:

    * ``TRANSIENT`` — retry may succeed (rate limit, timeout, network blip).
    * ``VALIDATION`` — caller supplied bad/malformed arguments; fix the input.
    * ``PERMISSION`` — access/auth/entitlement failure; escalate, do not retry.
    * ``BUSINESS`` — a domain/logic failure reported by the tool itself.
    """

    TRANSIENT = "transient"
    VALIDATION = "validation"
    BUSINESS = "business"
    PERMISSION = "permission"


# Map the *positively matched* internal LLM-API error codes onto the
# model-facing categories. ``ErrorCode.TRANSIENT`` / ``ErrorCode.UNKNOWN`` are
# intentionally absent: the underlying ``classify_error`` uses ``TRANSIENT`` as
# its catch-all default (sensible for LLM-API retry, wrong for a tool result
# where an unrecognized message is more likely a real domain failure), so we
# do NOT trust them and fall through to BUSINESS / not-retryable instead.
_CODE_TO_CATEGORY: dict[ErrorCode, ErrorCategory] = {
    ErrorCode.RATE_LIMITED: ErrorCategory.TRANSIENT,
    ErrorCode.AUTH_ERROR: ErrorCategory.PERMISSION,
    ErrorCode.NOT_FOUND: ErrorCategory.BUSINESS,
}

# Substrings that signal a *transient* failure (worth an unchanged retry).
# Checked explicitly here so that an *unrecognized* message maps to BUSINESS
# rather than inheriting ``classify_error``'s transient-by-default behaviour.
_TRANSIENT_MARKERS: tuple[str, ...] = (
    "timeout",
    "timed out",
    "deadline exceeded",
    "connection refused",
    "connection reset",
    "connection error",
    "network",
    "unreachable",
    "no route",
    "temporarily unavailable",
    "503",
    "502",
    "504",
)

# Substrings that signal a *validation* failure (bad caller input). These are
# checked before the generic classifier because ``classify_error`` has no
# validation bucket — it predates the four-category MCP envelope.
_VALIDATION_MARKERS: tuple[str, ...] = (
    "validation",
    "invalid argument",
    "invalid arguments",
    "invalid parameter",
    "invalid input",
    "invalid_params",
    "missing required",
    "required field",
    "schema",
    "malformed",
    "bad request",
    "-32602",  # JSON-RPC "Invalid params"
)

# Additional permission markers not already covered by classify_error's
# auth heuristics (which look for 401/403/unauthorized/forbidden).
_PERMISSION_MARKERS: tuple[str, ...] = (
    "permission denied",
    "access denied",
    "access is denied",
    "not permitted",
    "not allowed",
)


def classify_tool_error(message: str) -> tuple[ErrorCategory, bool]:
    """Classify a tool-error message into an MCP category + retryability.

    Reuses :func:`agentic_v2.core.errors.classify_error` for the transient /
    permission / transport buckets, then layers a validation check on top
    (the underlying classifier has no validation category).

    Args:
        message: Raw human-readable error text from the tool or transport.

    Returns:
        A ``(category, is_retryable)`` tuple. ``is_retryable`` is ``True`` only
        for transient failures — validation, permission, and business errors
        will not succeed on a blind retry.
    """
    # An empty/whitespace-only message carries no signal. Treat it conservatively
    # as transient/retryable rather than telling the model "do not retry" for a
    # detail-less failure (the BUSINESS default would suppress a valid retry).
    if not message.strip():
        return ErrorCategory.TRANSIENT, True

    lowered = message.lower()

    # Validation is checked first: a bad-input error must never be reported as
    # retryable, even if the message happens to contain a transient-looking
    # keyword.
    if any(marker in lowered for marker in _VALIDATION_MARKERS):
        return ErrorCategory.VALIDATION, False

    if any(marker in lowered for marker in _PERMISSION_MARKERS):
        return ErrorCategory.PERMISSION, False

    if any(marker in lowered for marker in _TRANSIENT_MARKERS):
        return ErrorCategory.TRANSIENT, True

    # Defer to the shared LLM-API classifier for the remaining recognized
    # buckets (rate-limit, auth, not-found). Anything it can only place in its
    # transient/unknown default is treated as a genuine, non-retryable BUSINESS
    # failure here — see ``_CODE_TO_CATEGORY``.
    code, _ = classify_error(message)
    if code in _CODE_TO_CATEGORY:
        category = _CODE_TO_CATEGORY[code]
        return category, category is ErrorCategory.TRANSIENT

    return ErrorCategory.BUSINESS, False


class ToolResultEnvelope(BaseModel):
    """MCP-correct tool-result contract surfaced to the model.

    Serializes to the canonical MCP shape via field aliases so the
    model-facing payload uses ``isError`` / ``errorCategory`` / ``isRetryable``
    while Python code reads ``snake_case`` attributes.

    Instances are immutable (``frozen=True``); transformations return new
    objects via :meth:`with_text`.
    """

    model_config = ConfigDict(frozen=True)

    text: str = Field(
        ..., description="Human-readable result/error text the model sees."
    )
    is_error: bool = Field(
        default=False,
        serialization_alias="isError",
        description="True only for genuine failures (never a valid-empty result).",
    )
    error_category: ErrorCategory | None = Field(
        default=None,
        serialization_alias="errorCategory",
        description="MCP error category (None on success).",
    )
    is_retryable: bool = Field(
        default=False,
        serialization_alias="isRetryable",
        description="Whether an unchanged retry could plausibly succeed.",
    )
    is_empty: bool = Field(
        default=False,
        serialization_alias="isEmpty",
        description=(
            "True for a valid result that legitimately carried no content "
            "(distinct from an access failure)."
        ),
    )

    @classmethod
    def success(cls, text: str, *, is_empty: bool = False) -> ToolResultEnvelope:
        """Build a successful envelope.

        Args:
            text: The model-facing result text.
            is_empty: Mark this as a *valid* empty result (e.g. a query that
                ran fine but matched nothing). This is explicitly NOT an error.
        """
        return cls(text=text, is_error=False, is_empty=is_empty)

    @classmethod
    def failure(
        cls,
        message: str,
        *,
        category: ErrorCategory | None = None,
        is_retryable: bool | None = None,
    ) -> ToolResultEnvelope:
        """Build a failure envelope, classifying the message if needed.

        Args:
            message: Raw error text.
            category: Explicit category; inferred from ``message`` when ``None``.
            is_retryable: Explicit retryability; inferred when ``None``.
        """
        if category is None or is_retryable is None:
            inferred_category, inferred_retryable = classify_tool_error(message)
            category = category or inferred_category
            is_retryable = inferred_retryable if is_retryable is None else is_retryable

        text = format_model_error_text(message, category, is_retryable)
        return cls(
            text=text,
            is_error=True,
            error_category=category,
            is_retryable=is_retryable,
            is_empty=False,
        )

    def with_text(self, text: str) -> ToolResultEnvelope:
        """Return a copy of this envelope with replaced text (immutable update)."""
        return self.model_copy(update={"text": text})

    def to_mcp_result(self) -> dict[str, Any]:
        """Serialize to the MCP ``tools/call`` result shape (alias keys)."""
        return self.model_dump(by_alias=True, exclude_none=True)


def format_model_error_text(
    message: str,
    category: ErrorCategory,
    is_retryable: bool,
) -> str:
    """Render the human-readable error block the model reads.

    The structured fields are embedded inline so they survive the
    ``envelope -> str`` collapse that the legacy ``execute()`` return type
    forces — the model can parse category/retryability straight from context.
    """
    retry_hint = "retryable" if is_retryable else "not retryable"
    return f"Error [{category.value}, {retry_hint}]: {message}"


__all__ = [
    "ErrorCategory",
    "ToolResultEnvelope",
    "classify_tool_error",
    "format_model_error_text",
]
