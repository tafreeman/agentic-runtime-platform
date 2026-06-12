"""Retry-with-jitter utilities for LLM client calls.

Provides :func:`retry_with_jitter` (decorator) and the pure helpers it
delegates to.  Extracted from ``client.py`` so the retry/backoff logic is
independently testable and the coverage gate applies to it.

Public surface:
    ``retry_with_jitter`` — decorator with exponential back-off + jitter
    ``compute_retry_delay`` — pure delay computation (testable seam)
    ``resolve_rate_limit_delay`` — pure rate-limit back-off resolution
"""

from __future__ import annotations

import asyncio
import logging
import random
from functools import wraps
from typing import Any, Callable

logger = logging.getLogger(__name__)


def retry_with_jitter(
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    jitter: float = 0.5,
) -> Callable:
    """Decorator for retrying async callables with exponential back-off and jitter.

    Honours ``Retry-After`` headers for rate limits and aborts immediately on
    permanent (non-retryable) errors detected by :func:`compute_retry_delay`.

    Args:
        max_retries: Maximum number of attempts (includes the first call).
        base_delay: Base delay in seconds for the first retry.
        max_delay: Upper bound on the computed delay before jitter.
        jitter: Uniform jitter fraction applied on top of the computed delay
            (``delay * random.uniform(0, jitter)``).
    """

    def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> Any:
            last_error = None
            for attempt in range(max_retries):
                try:
                    return await func(*args, **kwargs)
                except Exception as e:
                    last_error = e
                    if attempt >= max_retries - 1:
                        break
                    sleep_seconds = compute_retry_delay(
                        e,
                        attempt=attempt,
                        max_retries=max_retries,
                        base_delay=base_delay,
                        max_delay=max_delay,
                        jitter=jitter,
                        func_name=func.__name__,
                    )
                    await asyncio.sleep(sleep_seconds)

            if last_error:
                raise last_error
            raise RuntimeError("Exhausted retries")

        return wrapper

    return decorator


def compute_retry_delay(
    error: Exception,
    *,
    attempt: int,
    max_retries: int,
    base_delay: float,
    max_delay: float,
    jitter: float,
    func_name: str,
) -> float:
    """Compute the jittered back-off delay before the next retry attempt.

    Re-raises *error* for permanent (non-retryable) failures so the caller
    aborts the retry loop.  Honours a parsed ``Retry-After`` for rate limits
    by delegating to :func:`resolve_rate_limit_delay`.

    Args:
        error: The exception that caused this retry.
        attempt: Zero-based attempt index (0 = first retry after first failure).
        max_retries: Total retry cap (for log messages only).
        base_delay: Base delay in seconds.
        max_delay: Upper cap on the un-jittered delay.
        jitter: Uniform jitter fraction.
        func_name: Name of the retried function (for log messages only).

    Returns:
        Seconds to sleep before the next attempt.

    Raises:
        ``error`` when ``classify_error`` marks it non-retryable.
    """
    from ..core.errors import ErrorCode, classify_error

    code, should_retry = classify_error(str(error))
    if not should_retry:
        raise error  # Permanent error — abort the retry loop

    delay = min(base_delay * (2**attempt), max_delay)

    if code == ErrorCode.RATE_LIMITED:
        delay = resolve_rate_limit_delay(error, delay)

    jittered = delay + (delay * random.uniform(0, jitter))
    logger.debug(
        "Retry %d/%d for %s in %.2fs due to %s",
        attempt + 1,
        max_retries,
        func_name,
        jittered,
        code,
    )
    return jittered


def resolve_rate_limit_delay(error: Exception, default_delay: float) -> float:
    """Resolve the back-off delay for a rate-limited error.

    Prefers a provider ``Retry-After`` value parsed from the error headers;
    falls back to the router's default rate-limit cooldown so the caller does
    not wake up before the provider is ready.

    Args:
        error: The rate-limit exception (may carry parsed headers).
        default_delay: Computed exponential delay to use as a floor.

    Returns:
        Seconds to wait before the next attempt.
    """
    # Lazy import to avoid circular dependency on smart_router
    from .smart_router import get_smart_router

    router = get_smart_router()
    headers = router._headers_from_error(error)
    parsed_delay: float | None = None
    if headers:
        parsed_delay = router.rate_limit_tracker.parse_retry_after(headers)

    if parsed_delay is not None:
        return float(parsed_delay)
    return max(
        default_delay,
        float(router.cooldown_config.base_rate_limit_cooldown_seconds),
    )
