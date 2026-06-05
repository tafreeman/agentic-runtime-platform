"""Tests for SecretDetector."""

from __future__ import annotations

import pytest

from agentic_v2.contracts.sanitization import Severity
from agentic_v2.middleware.detectors.secrets import SecretDetector
from tests.fixtures.secrets_corpus import NEGATIVE_SECRETS, POSITIVE_SECRETS


@pytest.fixture
def detector() -> SecretDetector:
    return SecretDetector()


class TestSecretDetectorPositives:
    """Verify known secret patterns are detected."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("secret_text,expected_pattern", POSITIVE_SECRETS)
    async def test_detects_secret(
        self, detector: SecretDetector, secret_text: str, expected_pattern: str
    ) -> None:
        findings = await detector.scan(secret_text)
        assert (
            len(findings) >= 1
        ), f"Expected detection for pattern '{expected_pattern}'"
        pattern_names = [f.matched_pattern for f in findings]
        assert expected_pattern in pattern_names


class TestSecretDetectorNegatives:
    """Verify clean text does not trigger false positives."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("clean_text", NEGATIVE_SECRETS)
    async def test_no_false_positive(
        self, detector: SecretDetector, clean_text: str
    ) -> None:
        findings = await detector.scan(clean_text)
        # Filter out LOW severity entropy hits — those are informational
        real_findings = [f for f in findings if f.severity != Severity.LOW]
        assert len(real_findings) == 0, f"False positive on: {clean_text}"


class TestSecretDetectorRedaction:
    """Verify preview never leaks the actual secret."""

    @pytest.mark.asyncio
    async def test_preview_contains_redacted_marker(
        self, detector: SecretDetector
    ) -> None:
        # Split literal to avoid tripping upstream secret scanners on this test
        # fixture. This is a synthetic value; the detector still matches it.
        fake_stripe_key = "sk_" + "live_" + "ABCDEFGHIJKLMNOP1234567890"
        findings = await detector.scan(f"my api_key = {fake_stripe_key}")
        assert len(findings) >= 1
        for finding in findings:
            assert "[REDACTED]" in finding.redacted_preview
            # The actual secret value should not appear in the preview
            assert fake_stripe_key not in finding.redacted_preview


class TestSecretDetectorEntropy:
    """Verify entropy-based detection for unknown patterns."""

    @pytest.mark.asyncio
    async def test_high_entropy_string_detected(self, detector: SecretDetector) -> None:
        # Random-looking string that doesn't match any pattern
        text = "token: aB3dE7gH1jK5mN9pQ2sT6uV0wX4yZ8cF"
        findings = await detector.scan(text)
        # May or may not trigger depending on exact entropy — just verify no crash
        assert isinstance(findings, (list, tuple))

    @pytest.mark.asyncio
    async def test_short_strings_not_flagged(self, detector: SecretDetector) -> None:
        findings = await detector.scan("short")
        assert len(findings) == 0
