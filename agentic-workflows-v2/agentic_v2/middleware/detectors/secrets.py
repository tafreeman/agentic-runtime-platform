from __future__ import annotations

import math
import re
from collections import Counter
from typing import Sequence

from agentic_v2.contracts.sanitization import (
    Finding,
    FindingCategory,
    Severity,
)
from agentic_v2.middleware.detectors.base import SecretPattern


class SecretDetector:
    """Detects secrets and API keys via regex patterns and entropy analysis."""

    name: str = "secret_detector"
    version: str = "1.0.0"

    ENTROPY_THRESHOLD: float = 4.5
    MIN_ENTROPY_LENGTH: int = 20
    PREVIEW_CONTEXT: int = 20

    PATTERNS: tuple[SecretPattern, ...] = (
        SecretPattern.from_raw(
            "aws_access_key",
            r"AKIA[0-9A-Z]{16}",
            Severity.CRITICAL,
            FindingCategory.API_KEY,
        ),
        SecretPattern.from_raw(
            "aws_secret_key",
            r"(?i)aws_secret_access_key\s*[=:]\s*\S{20,}",
            Severity.CRITICAL,
            FindingCategory.API_KEY,
        ),
        SecretPattern.from_raw(
            "github_token",
            r"gh[pousr]_[A-Za-z0-9_]{36,}",
            Severity.CRITICAL,
            FindingCategory.API_KEY,
        ),
        SecretPattern.from_raw(
            "bearer_token",
            r"(?i)bearer\s+[A-Za-z0-9\-._~+/]+=*",
            Severity.HIGH,
            FindingCategory.BEARER_TOKEN,
        ),
        SecretPattern.from_raw(
            "generic_api_key",
            r"(?i)(?:api[_-]?key|apikey)\s*[=:]\s*\S{16,}",
            Severity.HIGH,
            FindingCategory.API_KEY,
        ),
        SecretPattern.from_raw(
            "private_key_header",
            r"-----BEGIN\s+(?:RSA |EC |DSA |OPENSSH )?PRIVATE KEY-----",
            Severity.CRITICAL,
            FindingCategory.PRIVATE_KEY,
        ),
        SecretPattern.from_raw(
            "env_secret",
            r"(?i)(?:password|secret|token|credential)\s*[=:]\s*\S{8,}",
            Severity.MEDIUM,
            FindingCategory.ENV_VARIABLE,
        ),
        SecretPattern.from_raw(
            "connection_string",
            r"(?i)(?:mongodb|postgres|mysql|redis)://\S+:\S+@\S+",
            Severity.HIGH,
            FindingCategory.PASSWORD,
        ),
    )

    _HIGH_ENTROPY_RE: re.Pattern[str] = re.compile(
        r"(?<![A-Za-z0-9])[A-Za-z0-9+/=_\-]{20,}(?![A-Za-z0-9])"
    )

    async def scan(self, text: str) -> Sequence[Finding]:
        findings: list[Finding] = []
        matched_ranges: list[tuple[int, int]] = []

        # Phase 1: Pattern matching
        for secret_pattern in self.PATTERNS:
            for match in secret_pattern.pattern.finditer(text):
                start, end = match.start(), match.end()
                matched_ranges.append((start, end))
                findings.append(
                    Finding(
                        category=secret_pattern.category,
                        severity=secret_pattern.severity,
                        location=f"text[{start}:{end}]",
                        matched_pattern=secret_pattern.name,
                        redacted_preview=self._build_preview(text, start, end),
                    )
                )

        # Phase 2: Entropy analysis for unmatched tokens
        for match in self._HIGH_ENTROPY_RE.finditer(text):
            start, end = match.start(), match.end()
            if self._overlaps_any(start, end, matched_ranges):
                continue
            token = match.group()
            if len(token) >= self.MIN_ENTROPY_LENGTH:
                entropy = self._shannon_entropy(token)
                if entropy >= self.ENTROPY_THRESHOLD:
                    findings.append(
                        Finding(
                            category=FindingCategory.HIGH_ENTROPY_STRING,
                            severity=Severity.LOW,
                            location=f"text[{start}:{end}]",
                            matched_pattern="high_entropy",
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

    @staticmethod
    def _shannon_entropy(data: str) -> float:
        if not data:
            return 0.0
        counts = Counter(data)
        length = len(data)
        return -sum(
            (count / length) * math.log2(count / length) for count in counts.values()
        )

    @staticmethod
    def _overlaps_any(start: int, end: int, ranges: list[tuple[int, int]]) -> bool:
        return any(not (end <= r_start or start >= r_end) for r_start, r_end in ranges)
