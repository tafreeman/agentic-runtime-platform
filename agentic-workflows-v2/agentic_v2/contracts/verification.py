from __future__ import annotations

import enum

from pydantic import BaseModel, Field


class VerificationStatus(enum.StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"
    ERROR = "error"
    MAX_RETRIES_EXCEEDED = "max_retries_exceeded"


class CorrectionOutcome(enum.StrEnum):
    FIXED = "fixed"
    PARTIALLY_FIXED = "partially_fixed"
    NOT_FIXED = "not_fixed"
    ESCALATED = "escalated"
    BUDGET_EXHAUSTED = "budget_exhausted"


class VerificationPolicy(BaseModel):
    """Policy governing how verification loops behave for a step."""

    enabled: bool = True
    max_retries: int = Field(default=3, ge=0, le=10)
    token_budget_pct: float = Field(
        default=0.25,
        ge=0.0,
        le=1.0,
        description="Max fraction of remaining run token budget to spend on corrections",
    )
    verification_commands: tuple[str, ...] = Field(
        default=("pytest", "ruff check", "mypy"),
        description="Ordered commands to run for verification",
    )
    stop_on_first_failure: bool = Field(
        default=False,
        description="If True, stop verification at first failing command",
    )
    escalation_strategy: str = Field(
        default="report",
        description="'report' = log + continue, 'block' = fail the step, 'ask' = require human input",
    )
    min_token_floor: int = Field(
        default=1000,
        ge=0,
        description="Skip verification if remaining budget is below this floor",
    )

    model_config = {"frozen": True}


class CorrectionAttempt(BaseModel):
    """Record of a single correction attempt."""

    attempt_number: int
    verification_status: VerificationStatus
    failing_checks: tuple[str, ...] = Field(default_factory=tuple)
    tokens_used: int = 0
    duration_seconds: float = 0.0
    correction_outcome: CorrectionOutcome | None = None
    error_summary: str = ""

    model_config = {"frozen": True}


class VerificationResult(BaseModel):
    """Final result of the verification loop for a step."""

    final_status: VerificationStatus
    attempts: tuple[CorrectionAttempt, ...] = Field(default_factory=tuple)
    total_tokens_used: int = 0
    total_duration_seconds: float = 0.0
    escalated: bool = False
    escalation_reason: str = ""

    model_config = {"frozen": True}

    @property
    def attempt_count(self) -> int:
        """Return the number of verification attempts recorded."""
        return len(self.attempts)
