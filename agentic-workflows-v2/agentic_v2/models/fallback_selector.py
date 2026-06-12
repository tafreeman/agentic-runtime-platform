"""Model fallback-selection loop for LLM client calls.

Provides :func:`run_with_fallback`, a pure async helper that drives the
router's model-selection + fallback retry loop.  Extracted from
``client.py`` so the fallback logic is independently testable and the
coverage gate applies to it.

Public surface:
    ``run_with_fallback`` — async model-selection loop with caller-defined
    hooks for pre-attempt validation, attempt execution, and error handling.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Callable, TypeVar

from .router import ModelTier
from .smart_router import SmartModelRouter, _CircuitResolvedError

logger = logging.getLogger(__name__)

T = TypeVar("T")


async def run_with_fallback(
    router: SmartModelRouter,
    *,
    tier: ModelTier,
    model: str | None,
    max_retries: int,
    pre_attempt: Callable[[str], None],
    attempt: Callable[[str], Awaitable[T]],
    on_error: Callable[[str, Exception], None],
) -> T:
    """Drive the router's model-selection and fallback retry loop.

    Selects up to *max_retries* distinct models for *tier* (or the forced
    *model*), invoking *attempt* per candidate and returning its first
    success.

    Hooks:
        pre_attempt(selected_model): runs **outside** the try/except so that
            budget exhaustion or other validation errors propagate directly
            rather than being treated as model failures.
        attempt(selected_model): the actual async provider call; its return
            value is forwarded to the caller on success.
        on_error(selected_model, error): bookkeeping for a failed attempt
            (e.g., record router failure, log warning); called before the
            next candidate is tried.

    Args:
        router: The :class:`SmartModelRouter` used for model selection.
        tier: The model tier to draw candidates from.
        model: When not ``None``, forces this specific model for every
            attempt (no tier-based selection, no cycling).
        max_retries: Maximum number of distinct candidates to try.
        pre_attempt: Called synchronously before each attempt.
        attempt: Async callable that executes one provider call.
        on_error: Called synchronously after each failed attempt.

    Returns:
        The result of the first successful *attempt* call.

    Raises:
        The last attempt exception when every candidate failed, or
        :class:`RuntimeError` when no candidate could be selected at all.
    """
    tried: list[str] = []
    last_error: Exception | None = None

    for _ in range(max_retries):
        selected_model: str | None = model or router.get_model_for_tier(tier)
        if selected_model is None or selected_model in tried:
            break

        tried.append(selected_model)
        pre_attempt(selected_model)

        try:
            return await attempt(selected_model)
        except asyncio.CancelledError:
            raise
        except _CircuitResolvedError:
            # A prior probe already resolved the HALF_OPEN circuit before
            # this caller could run its probe. The model is healthy (or
            # freshly re-opened) — skip it without recording a failure and
            # try the next candidate, mirroring call_with_fallback.
            logger.debug(
                "Skipping model %r: circuit resolved by a prior probe",
                selected_model,
            )
            continue
        except Exception as e:
            on_error(selected_model, e)
            last_error = e

    if last_error:
        raise last_error
    raise RuntimeError(
        f"All models failed. Tried: {tried}. No further information available."
    )


# ---------------------------------------------------------------------------
# Convenience type alias — keeps call-site imports readable
# ---------------------------------------------------------------------------

PreAttemptFn = Callable[[str], None]
AttemptFn = Callable[[str], Awaitable[Any]]
OnErrorFn = Callable[[str, Exception], None]
