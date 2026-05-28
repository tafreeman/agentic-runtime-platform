"""Tests for UnicodeSanitizer."""

from __future__ import annotations

import pytest
from agentic_v2.middleware.detectors.unicode import UnicodeSanitizer
from tests.fixtures.unicode_corpus import (
    DANGEROUS_UNICODE,
    NORMALIZATION_CASES,
    SAFE_UNICODE,
)


@pytest.fixture
def sanitizer() -> UnicodeSanitizer:
    return UnicodeSanitizer()


class TestDangerousUnicode:
    """Verify dangerous characters are removed."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("text,min_removals", DANGEROUS_UNICODE)
    async def test_removes_dangerous_chars(
        self, sanitizer: UnicodeSanitizer, text: str, min_removals: int
    ) -> None:
        cleaned, _findings = await sanitizer.sanitize(text)
        removed_count = len(text) - len(cleaned)
        assert (
            removed_count >= min_removals
        ), f"Expected at least {min_removals} removals, got {removed_count}"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("text,min_removals", DANGEROUS_UNICODE)
    async def test_findings_reported(
        self, sanitizer: UnicodeSanitizer, text: str, min_removals: int
    ) -> None:
        _, findings = await sanitizer.sanitize(text)
        assert len(findings) >= 1


class TestSafeUnicode:
    """Verify safe text passes through unchanged."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("text", SAFE_UNICODE)
    async def test_safe_text_unchanged(
        self, sanitizer: UnicodeSanitizer, text: str
    ) -> None:
        cleaned, _ = await sanitizer.sanitize(text)
        # NFKC may change some chars, but the meaning should be preserved
        assert len(cleaned) > 0
        # Safe text should not lose significant content
        assert len(cleaned) >= len(text) * 0.8


class TestNormalization:
    """Verify NFKC normalization works correctly."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("input_text,expected", NORMALIZATION_CASES)
    async def test_nfkc_normalization(
        self, sanitizer: UnicodeSanitizer, input_text: str, expected: str
    ) -> None:
        cleaned, _ = await sanitizer.sanitize(input_text)
        assert cleaned == expected


class TestIterativeStability:
    """Verify sanitization converges."""

    @pytest.mark.asyncio
    async def test_idempotent(self, sanitizer: UnicodeSanitizer) -> None:
        text = "hello\u200b\u200cworld\ufeff"
        cleaned1, _ = await sanitizer.sanitize(text)
        cleaned2, _ = await sanitizer.sanitize(cleaned1)
        assert cleaned1 == cleaned2, "Sanitization should be idempotent"

    @pytest.mark.asyncio
    async def test_scan_delegates_to_sanitize(
        self, sanitizer: UnicodeSanitizer
    ) -> None:
        text = "test\u200btext"
        findings = await sanitizer.scan(text)
        _, sanitize_findings = await sanitizer.sanitize(text)
        assert findings == sanitize_findings
