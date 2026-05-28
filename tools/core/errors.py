"""Standardized error codes and heuristic classification for the tools ecosystem.

Provides a canonical ``ErrorCode`` enum, two membership sets
(``TRANSIENT_ERRORS`` and ``PERMANENT_ERRORS``), and a
``classify_error`` function that maps free-text error messages to
structured codes with a retry recommendation.

Usage::

    from tools.core.errors import ErrorCode, classify_error

    code, should_retry = classify_error("Rate limit exceeded")
    if should_retry:
        # Implement back-off / retry logic
        ...
"""

from __future__ import annotations

from enum import Enum, StrEnum


class ErrorCode(StrEnum):
    """Standardized error codes aligned with EVALUATION_SCHEMA.md.

    Each member doubles as a plain ``str`` so it can be serialized
    directly into JSON evaluation reports.
    """

    SUCCESS = "success"
    UNAVAILABLE_MODEL = "unavailable_model"
    PERMISSION_DENIED = "permission_denied"
    RATE_LIMITED = "rate_limited"
    TIMEOUT = "timeout"
    PARSE_ERROR = "parse_error"
    FILE_NOT_FOUND = "file_not_found"
    INVALID_INPUT = "invalid_input"
    NETWORK_ERROR = "network_error"
    INTERNAL_ERROR = "internal_error"


# Errors that should NOT be retried (permanent failures)
PERMANENT_ERRORS: set[ErrorCode] = {
    ErrorCode.UNAVAILABLE_MODEL,
    ErrorCode.PERMISSION_DENIED,
    ErrorCode.FILE_NOT_FOUND,
    ErrorCode.INVALID_INPUT,
}

# Errors that CAN be retried (transient failures)
TRANSIENT_ERRORS: set[ErrorCode] = {
    ErrorCode.RATE_LIMITED,
    ErrorCode.TIMEOUT,
    ErrorCode.NETWORK_ERROR,
    ErrorCode.PARSE_ERROR,  # Model gave bad output, might work on retry
}


def classify_error(
    error_message: str, return_code: int | None = None
) -> tuple[ErrorCode, bool]:
    """Classify an error message into a standard error code.

    Args:
        error_message: The error message to classify
        return_code: Optional return code from subprocess (not currently used)

    Returns:
        Tuple of (ErrorCode, should_retry: bool)

    Examples:
        >>> classify_error("Rate limit exceeded")
        (ErrorCode.RATE_LIMITED, True)
        >>> classify_error("Model not found")
        (ErrorCode.UNAVAILABLE_MODEL, False)
    """
    msg = error_message.lower() if error_message else ""

    # Permission/entitlement errors (403, 401, access denied)
    if "403" in msg or "forbidden" in msg:
        return ErrorCode.PERMISSION_DENIED, False
    if "401" in msg or "unauthorized" in msg:
        return ErrorCode.PERMISSION_DENIED, False
    if "access denied" in msg or "access is denied" in msg:
        return ErrorCode.PERMISSION_DENIED, False
    if "limited access feature" in msg or ("laf" in msg and "token" in msg):
        return ErrorCode.PERMISSION_DENIED, False
    if "systemaimodels" in msg or "package identity" in msg:
        return ErrorCode.PERMISSION_DENIED, False

    # Model availability
    if "unavailable_model" in msg or "unavailable model" in msg:
        return ErrorCode.UNAVAILABLE_MODEL, False
    if "model not found" in msg or "unknown model" in msg:
        return ErrorCode.UNAVAILABLE_MODEL, False
    if "does not exist" in msg and "model" in msg:
        return ErrorCode.UNAVAILABLE_MODEL, False
    if "not found" in msg and ("model" in msg or "resource" in msg):
        return ErrorCode.UNAVAILABLE_MODEL, False

    # Rate limiting (429)
    if "429" in msg or "rate limit" in msg or "too many requests" in msg:
        return ErrorCode.RATE_LIMITED, True
    if "quota" in msg and ("exceeded" in msg or "limit" in msg):
        return ErrorCode.RATE_LIMITED, True

    # Timeouts
    if "timeout" in msg or "timed out" in msg:
        return ErrorCode.TIMEOUT, True
    if "deadline exceeded" in msg:
        return ErrorCode.TIMEOUT, True

    # Network errors
    if "connection" in msg and ("refused" in msg or "reset" in msg or "error" in msg):
        return ErrorCode.NETWORK_ERROR, True
    if "network" in msg and ("error" in msg or "unreachable" in msg):
        return ErrorCode.NETWORK_ERROR, True
    if "dns" in msg or "resolve" in msg:
        return ErrorCode.NETWORK_ERROR, True
    if "unreachable" in msg or "no route" in msg:
        return ErrorCode.NETWORK_ERROR, True

    # Parse errors (usually transient - model gave bad output)
    if "json" in msg and ("parse" in msg or "decode" in msg or "invalid" in msg):
        return ErrorCode.PARSE_ERROR, True
    if "yaml" in msg and ("parse" in msg or "invalid" in msg):
        return ErrorCode.PARSE_ERROR, True

    # File not found
    if "file not found" in msg or "no such file" in msg:
        return ErrorCode.FILE_NOT_FOUND, False
    if "filenotfounderror" in msg:
        return ErrorCode.FILE_NOT_FOUND, False

    # Invalid input
    if "invalid" in msg and ("input" in msg or "parameter" in msg or "argument" in msg):
        return ErrorCode.INVALID_INPUT, False
    if "validation" in msg and ("failed" in msg or "error" in msg):
        return ErrorCode.INVALID_INPUT, False

    # Default to internal error (non-retryable by default)
    return ErrorCode.INTERNAL_ERROR, False


def is_retryable(code: ErrorCode) -> bool:
    """Check if an error code indicates a retryable error."""
    return code in TRANSIENT_ERRORS


def is_permanent(code: ErrorCode) -> bool:
    """Check if an error code indicates a permanent failure."""
    return code in PERMANENT_ERRORS


__all__ = [
    "PERMANENT_ERRORS",
    "TRANSIENT_ERRORS",
    "ErrorCode",
    "classify_error",
    "is_permanent",
    "is_retryable",
]
