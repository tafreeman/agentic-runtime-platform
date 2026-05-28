"""Tests for PIIDetector."""

from __future__ import annotations

import pytest
from agentic_v2.contracts.sanitization import FindingCategory
from agentic_v2.middleware.detectors.pii import PIIDetector


@pytest.fixture
def detector() -> PIIDetector:
    return PIIDetector()


class TestEmailDetection:
    @pytest.mark.asyncio
    async def test_detects_email(self, detector: PIIDetector) -> None:
        findings = await detector.scan("Contact us at support@example.com for help")
        assert len(findings) == 1
        assert findings[0].category == FindingCategory.PII_EMAIL
        assert "[REDACTED]" in findings[0].redacted_preview

    @pytest.mark.asyncio
    async def test_detects_multiple_emails(self, detector: PIIDetector) -> None:
        findings = await detector.scan("Email alice@test.com or bob@test.com")
        email_findings = [
            f for f in findings if f.category == FindingCategory.PII_EMAIL
        ]
        assert len(email_findings) == 2


class TestPhoneDetection:
    @pytest.mark.asyncio
    async def test_detects_us_phone(self, detector: PIIDetector) -> None:
        findings = await detector.scan("Call me at 555-123-4567")
        phone_findings = [
            f for f in findings if f.category == FindingCategory.PII_PHONE
        ]
        assert len(phone_findings) >= 1

    @pytest.mark.asyncio
    async def test_detects_phone_with_area_code(self, detector: PIIDetector) -> None:
        findings = await detector.scan("Phone: (555) 123-4567")
        phone_findings = [
            f for f in findings if f.category == FindingCategory.PII_PHONE
        ]
        assert len(phone_findings) >= 1


class TestSSNDetection:
    @pytest.mark.asyncio
    async def test_detects_ssn(self, detector: PIIDetector) -> None:
        findings = await detector.scan("SSN: 123-45-6789")
        ssn_findings = [f for f in findings if f.category == FindingCategory.PII_SSN]
        assert len(ssn_findings) == 1

    @pytest.mark.asyncio
    async def test_no_false_positive_on_date(self, detector: PIIDetector) -> None:
        findings = await detector.scan("Date: 2024-01-15")
        ssn_findings = [f for f in findings if f.category == FindingCategory.PII_SSN]
        assert len(ssn_findings) == 0


class TestCleanText:
    @pytest.mark.asyncio
    async def test_no_pii_in_code(self, detector: PIIDetector) -> None:
        findings = await detector.scan(
            "def calculate_sum(a: int, b: int) -> int: return a + b"
        )
        assert len(findings) == 0
