"""Tests for sanitization and verification contracts."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from agentic_v2.contracts.sanitization import (
    Classification,
    Finding,
    FindingCategory,
    SanitizationResult,
    Severity,
)
from agentic_v2.contracts.verification import (
    CorrectionAttempt,
    VerificationPolicy,
    VerificationResult,
    VerificationStatus,
)


class TestFinding:
    def test_frozen(self) -> None:
        finding = Finding(
            category=FindingCategory.API_KEY,
            severity=Severity.HIGH,
            location="text[0:20]",
            matched_pattern="test_pattern",
        )
        with pytest.raises(ValidationError):
            finding.category = FindingCategory.PASSWORD  # type: ignore[misc]

    def test_default_preview(self) -> None:
        finding = Finding(
            category=FindingCategory.API_KEY,
            severity=Severity.HIGH,
            location="text[0:20]",
            matched_pattern="test",
        )
        assert finding.redacted_preview == ""


class TestSanitizationResult:
    def test_is_safe_clean(self) -> None:
        result = SanitizationResult(
            classification=Classification.CLEAN,
            original_hash="abc123",
        )
        assert result.is_safe is True

    def test_is_safe_redacted(self) -> None:
        result = SanitizationResult(
            classification=Classification.REDACTED,
            original_hash="abc123",
            sanitized_text="cleaned",
        )
        assert result.is_safe is True

    def test_is_not_safe_blocked(self) -> None:
        result = SanitizationResult(
            classification=Classification.BLOCKED,
            original_hash="abc123",
        )
        assert result.is_safe is False

    def test_compute_hash_deterministic(self) -> None:
        hash1 = SanitizationResult.compute_hash("test")
        hash2 = SanitizationResult.compute_hash("test")
        assert hash1 == hash2

    def test_compute_hash_different_input(self) -> None:
        hash1 = SanitizationResult.compute_hash("test1")
        hash2 = SanitizationResult.compute_hash("test2")
        assert hash1 != hash2


class TestVerificationPolicy:
    def test_defaults(self) -> None:
        policy = VerificationPolicy()
        assert policy.max_retries == 3
        assert policy.token_budget_pct == 0.25
        assert policy.enabled is True
        assert policy.min_token_floor == 1000

    def test_validation_max_retries(self) -> None:
        with pytest.raises(ValidationError):
            VerificationPolicy(max_retries=-1)
        with pytest.raises(ValidationError):
            VerificationPolicy(max_retries=11)

    def test_frozen(self) -> None:
        policy = VerificationPolicy()
        with pytest.raises(ValidationError):
            policy.max_retries = 5  # type: ignore[misc]


class TestVerificationResult:
    def test_attempt_count(self) -> None:
        result = VerificationResult(
            final_status=VerificationStatus.PASSED,
            attempts=(
                CorrectionAttempt(
                    attempt_number=1, verification_status=VerificationStatus.FAILED
                ),
                CorrectionAttempt(
                    attempt_number=2, verification_status=VerificationStatus.PASSED
                ),
            ),
        )
        assert result.attempt_count == 2

    def test_empty_attempts(self) -> None:
        result = VerificationResult(final_status=VerificationStatus.SKIPPED)
        assert result.attempt_count == 0
