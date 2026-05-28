from __future__ import annotations

import re
from typing import Sequence

from agentic_v2.contracts.sanitization import (
    Finding,
    FindingCategory,
    Severity,
)


class PIIDetector:
    """Detects personally identifiable information (PII) patterns."""

    name: str = "pii_detector"
    version: str = "1.0.0"

    PREVIEW_CONTEXT: int = 20

    _EMAIL_RE: re.Pattern[str] = re.compile(
        r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}"
    )
    _PHONE_RE: re.Pattern[str] = re.compile(
        r"(?<!\d)(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}(?!\d)"
    )
    _SSN_RE: re.Pattern[str] = re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)")

    _PATTERNS: tuple[tuple[re.Pattern[str], FindingCategory, str], ...] = (
        (_EMAIL_RE, FindingCategory.PII_EMAIL, "email_address"),
        (_PHONE_RE, FindingCategory.PII_PHONE, "phone_number"),
        (_SSN_RE, FindingCategory.PII_SSN, "ssn"),
    )

    async def scan(self, text: str) -> Sequence[Finding]:
        findings: list[Finding] = []

        for pattern, category, pattern_name in self._PATTERNS:
            for match in pattern.finditer(text):
                start, end = match.start(), match.end()
                findings.append(
                    Finding(
                        category=category,
                        severity=Severity.MEDIUM,
                        location=f"text[{start}:{end}]",
                        matched_pattern=pattern_name,
                        redacted_preview=self._build_preview(text, start, end),
                    )
                )

        return tuple(findings)

    def _build_preview(self, text: str, start: int, end: int) -> str:
        ctx_start = max(0, start - self.PREVIEW_CONTEXT)
        ctx_end = min(len(text), end + self.PREVIEW_CONTEXT)
        prefix = text[ctx_start:start]
        suffix = text[end:ctx_end]
        return f"{prefix}[REDACTED]{suffix}"
