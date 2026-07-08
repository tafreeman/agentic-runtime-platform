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
        """Detect secrets / high-entropy tokens.

        Returns findings (no mutation).
        """
        return tuple(finding for _start, _end, finding in self._detect(text))

    async def scan_and_mask(self, text: str) -> tuple[str, Sequence[Finding]]:
        """Detect *and* redact secrets in a single pass.

        Returns ``(masked_text, findings)`` where every matched span in
        ``masked_text`` has been replaced by a ``[REDACTED:<category>]``
        placeholder. ``findings`` are identical to :meth:`scan`. Text with no
        findings is returned byte-for-byte unchanged.
        """
        detections = self._detect(text)
        findings = tuple(finding for _start, _end, finding in detections)
        spans = [
            (start, end, finding.category.value) for start, end, finding in detections
        ]
        return self._apply_masks(text, spans), findings

    def _detect(self, text: str) -> list[tuple[int, int, Finding]]:
        """Locate secret and high-entropy spans in detection order.

        Returns ``(start, end, Finding)`` tuples so both :meth:`scan` (findings
        only) and :meth:`scan_and_mask` (span-accurate redaction) share one
        detection pass. Pattern matches come first, then non-overlapping
        high-entropy tokens — the same order findings were emitted before.
        """
        detections: list[tuple[int, int, Finding]] = []
        matched_ranges: list[tuple[int, int]] = []

        # Phase 1: Pattern matching
        for secret_pattern in self.PATTERNS:
            for match in secret_pattern.pattern.finditer(text):
                start, end = match.start(), match.end()
                matched_ranges.append((start, end))
                detections.append(
                    (
                        start,
                        end,
                        Finding(
                            category=secret_pattern.category,
                            severity=secret_pattern.severity,
                            location=f"text[{start}:{end}]",
                            matched_pattern=secret_pattern.name,
                            redacted_preview=self._build_preview(text, start, end),
                        ),
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
                    detections.append(
                        (
                            start,
                            end,
                            Finding(
                                category=FindingCategory.HIGH_ENTROPY_STRING,
                                severity=Severity.LOW,
                                location=f"text[{start}:{end}]",
                                matched_pattern="high_entropy",
                                redacted_preview=self._build_preview(text, start, end),
                            ),
                        )
                    )

        return detections

    @staticmethod
    def _apply_masks(text: str, spans: list[tuple[int, int, str]]) -> str:
        """Replace each span with ``[REDACTED:<category>]``; returns new text.

        Overlapping or adjacent spans are merged (first-seen category wins) so a
        region covered by several patterns yields a single placeholder and byte
        offsets never shift mid-rebuild. Immutable: a new string is returned and
        empty ``spans`` returns ``text`` unchanged.
        """
        if not spans:
            return text
        ordered = sorted(spans, key=lambda span: (span[0], -span[1]))
        merged: list[tuple[int, int, str]] = []
        for start, end, category in ordered:
            if merged and start <= merged[-1][1]:
                prev_start, prev_end, prev_category = merged[-1]
                merged[-1] = (prev_start, max(prev_end, end), prev_category)
            else:
                merged.append((start, end, category))

        parts: list[str] = []
        cursor = 0
        for start, end, category in merged:
            parts.append(text[cursor:start])
            parts.append(f"[REDACTED:{category}]")
            cursor = end
        parts.append(text[cursor:])
        return "".join(parts)

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
