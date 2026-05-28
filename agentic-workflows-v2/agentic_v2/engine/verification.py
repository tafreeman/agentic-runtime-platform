"""Verification loop engine for bounded self-correction.

Provides two classes:

- :class:`VerificationGate` — runs verification commands (pytest, ruff,
  mypy) as subprocesses and reports pass/fail.
- :class:`VerificationLoop` — wraps step execution with a
  verify-correct cycle bounded by ``max_retries`` and token budget.

The loop follows a strict bounded-correction protocol:

1. Execute the step function.
2. Run verification commands via :class:`VerificationGate`.
3. On failure, invoke a correction function (or re-run the step).
4. Re-verify, tracking each :class:`CorrectionAttempt`.
5. Stop when checks pass, retries exhaust, budget depletes,
   or a duplicate-failure loop is detected.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shlex
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Sequence

from ..contracts.messages import StepResult
from ..contracts.verification import (
    CorrectionAttempt,
    CorrectionOutcome,
    VerificationPolicy,
    VerificationResult,
    VerificationStatus,
)
from ..models.client import TokenBudget
from .context import ExecutionContext

logger = logging.getLogger(__name__)

_SHELL_METACHARS = frozenset({"|", "&", ";", "<", ">", "`", "$(", "${", "\n", "\r"})


def _split_verification_command(cmd: str) -> list[str]:
    """Split a verification command without invoking a shell."""
    if any(token in cmd for token in _SHELL_METACHARS):
        raise ValueError(
            f"Shell metacharacters are not supported in verification command: {cmd!r}"
        )
    return shlex.split(cmd, posix=os.name != "nt")


class VerificationGate:
    """Runs verification commands and reports pass/fail."""

    async def run_checks(
        self,
        commands: Sequence[str],
        *,
        stop_on_first_failure: bool = False,
        timeout_seconds: float = 120.0,
    ) -> tuple[VerificationStatus, tuple[str, ...]]:
        """Run verification commands, return (status, failing_check_names).

        Each command is run as a subprocess.  Commands that exit with
        code 0 pass.  Returns ``PASSED`` if all pass, ``FAILED`` if any
        fail, ``ERROR`` on unexpected subprocess errors.

        Args:
            commands: Shell commands to execute.
            stop_on_first_failure: Return immediately on first failure.
            timeout_seconds: Per-command timeout in seconds.

        Returns:
            Tuple of (overall status, tuple of failing command strings).
        """
        failing: list[str] = []

        for cmd in commands:
            try:
                status = await self._run_single(cmd, timeout_seconds=timeout_seconds)
            except OSError as exc:
                logger.error("Subprocess creation failed for %r: %s", cmd, exc)
                return VerificationStatus.ERROR, (cmd,)

            if status != 0:
                failing.append(cmd)
                if stop_on_first_failure:
                    return VerificationStatus.FAILED, tuple(failing)

        if failing:
            return VerificationStatus.FAILED, tuple(failing)
        return VerificationStatus.PASSED, ()

    @staticmethod
    async def _run_single(cmd: str, *, timeout_seconds: float) -> int:
        """Execute a single shell command, returning its exit code.

        Returns ``-1`` on timeout.
        """
        try:
            argv = _split_verification_command(cmd)
        except ValueError as exc:
            logger.warning("%s", exc)
            return -1

        if not argv:
            logger.warning("Empty verification command")
            return -1

        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            await asyncio.wait_for(proc.communicate(), timeout=timeout_seconds)
        except TimeoutError:
            proc.kill()
            await proc.wait()
            logger.warning("Command timed out after %.1fs: %s", timeout_seconds, cmd)
            return -1
        # proc.returncode is guaranteed non-None after communicate()
        return proc.returncode  # type: ignore[return-value]


class VerificationLoop:
    """Bounded self-correction loop around step execution."""

    def __init__(
        self,
        policy: VerificationPolicy,
        token_budget: TokenBudget | None = None,
    ) -> None:
        self._policy = policy
        self._token_budget = token_budget
        self._gate = VerificationGate()
        self._logger = logging.getLogger(__name__)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def execute_with_verification(
        self,
        step_func: Callable[..., Awaitable[StepResult]],
        context: ExecutionContext,
        *,
        correction_func: (
            Callable[[tuple[str, ...], ExecutionContext], Awaitable[StepResult]] | None
        ) = None,
    ) -> tuple[StepResult, VerificationResult]:
        """Execute step, then verify.  If verification fails, attempt correction.

        Args:
            step_func: The step execution function to call.
            context: Current execution context.
            correction_func: Optional function that receives failing checks
                and context: returns a new ``StepResult`` after attempting
                corrections.  If ``None``, re-runs *step_func* on failure.

        Returns:
            Tuple of (final StepResult, VerificationResult with full
            attempt history).
        """
        # --- Fast-path: verification disabled -------------------------
        if not self._policy.enabled:
            self._logger.debug("Verification disabled — skipping gate")
            result = await step_func(context)
            return result, _skipped_result()

        # --- Fast-path: token budget too low --------------------------
        if self._token_budget is not None and (
            self._token_budget.remaining < self._policy.min_token_floor
        ):
            self._logger.warning(
                "Token budget below floor (%d < %d) — skipping verification",
                self._token_budget.remaining,
                self._policy.min_token_floor,
            )
            result = await step_func(context)
            return result, _skipped_result()

        # --- Execute the step -----------------------------------------
        loop_start = time.monotonic()
        step_result = await step_func(context)

        if step_result.is_failed:
            self._logger.info(
                "Step %r failed — skipping verification", step_result.step_name
            )
            return step_result, _skipped_result()

        # --- Initial verification -------------------------------------
        status, failing = await self._gate.run_checks(
            self._policy.verification_commands,
            stop_on_first_failure=self._policy.stop_on_first_failure,
        )

        if status == VerificationStatus.PASSED:
            duration = time.monotonic() - loop_start
            return step_result, VerificationResult(
                final_status=VerificationStatus.PASSED,
                total_duration_seconds=duration,
            )

        # --- Correction loop ------------------------------------------
        attempts: list[CorrectionAttempt] = []
        total_tokens = 0
        previous_failing: tuple[str, ...] = ()

        for attempt_num in range(1, self._policy.max_retries + 1):
            self._logger.info(
                "Verification attempt %d/%d — failing: %s",
                attempt_num,
                self._policy.max_retries,
                ", ".join(failing),
            )

            # Duplicate-failure loop detection
            if failing == previous_failing and attempt_num > 1:
                self._logger.warning(
                    "Duplicate failures detected — aborting correction loop"
                )
                attempts.append(
                    CorrectionAttempt(
                        attempt_number=attempt_num,
                        verification_status=VerificationStatus.FAILED,
                        failing_checks=failing,
                        correction_outcome=CorrectionOutcome.NOT_FIXED,
                        error_summary="Loop detected: same failures as previous attempt",
                    )
                )
                break

            # Budget check
            if not self._can_afford_correction():
                self._logger.warning("Token budget exhausted — stopping corrections")
                attempts.append(
                    CorrectionAttempt(
                        attempt_number=attempt_num,
                        verification_status=VerificationStatus.FAILED,
                        failing_checks=failing,
                        correction_outcome=CorrectionOutcome.BUDGET_EXHAUSTED,
                    )
                )
                break

            previous_failing = failing
            attempt_start = time.monotonic()

            # Correction
            if correction_func is not None:
                step_result = await correction_func(failing, context)
            else:
                step_result = await step_func(context)

            # Re-verify
            status, failing = await self._gate.run_checks(
                self._policy.verification_commands,
                stop_on_first_failure=self._policy.stop_on_first_failure,
            )

            attempt_duration = time.monotonic() - attempt_start
            tokens_this_attempt = self._estimate_tokens_used()
            total_tokens += tokens_this_attempt

            outcome = (
                CorrectionOutcome.FIXED
                if status == VerificationStatus.PASSED
                else CorrectionOutcome.NOT_FIXED
            )

            attempts.append(
                CorrectionAttempt(
                    attempt_number=attempt_num,
                    verification_status=status,
                    failing_checks=failing,
                    tokens_used=tokens_this_attempt,
                    duration_seconds=attempt_duration,
                    correction_outcome=outcome,
                )
            )

            if status == VerificationStatus.PASSED:
                break

        # --- Build final result ---------------------------------------
        total_duration = time.monotonic() - loop_start
        final_status = (
            status
            if status == VerificationStatus.PASSED
            else VerificationStatus.MAX_RETRIES_EXCEEDED
        )

        escalated, escalation_reason = self._resolve_escalation(final_status, failing)

        if final_status != VerificationStatus.PASSED:
            self._logger.warning(
                "Verification exhausted after %d attempts: %s",
                len(attempts),
                ", ".join(failing),
            )

        return step_result, VerificationResult(
            final_status=final_status,
            attempts=tuple(attempts),
            total_tokens_used=total_tokens,
            total_duration_seconds=total_duration,
            escalated=escalated,
            escalation_reason=escalation_reason,
        )

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _can_afford_correction(self) -> bool:
        """Return True if the token budget allows another correction."""
        if self._token_budget is None:
            return True
        allowed = int(self._token_budget.remaining * self._policy.token_budget_pct)
        return allowed > 0

    @staticmethod
    def _estimate_tokens_used() -> int:
        """Placeholder for per-attempt token tracking.

        In production, the correction function should report actual token
        consumption.  Returns ``0`` until wired to a real counter.
        """
        return 0

    def _resolve_escalation(
        self,
        final_status: VerificationStatus,
        failing: tuple[str, ...],
    ) -> tuple[bool, str]:
        """Determine escalation flags from policy and final status."""
        if final_status == VerificationStatus.PASSED:
            return False, ""

        strategy = self._policy.escalation_strategy

        if strategy == "report":
            return False, ""
        if strategy == "block":
            return True, "Verification failed — step blocked by policy"
        if strategy == "ask":
            reason = (
                f"Verification failed — human review required. "
                f"Failing checks: {', '.join(failing)}"
            )
            return True, reason

        # Unknown strategy — treat as report
        self._logger.warning(
            "Unknown escalation strategy %r — defaulting to report", strategy
        )
        return False, ""


# ------------------------------------------------------------------
# Module-level helpers
# ------------------------------------------------------------------


def _skipped_result() -> VerificationResult:
    """Return a minimal SKIPPED verification result."""
    return VerificationResult(final_status=VerificationStatus.SKIPPED)
