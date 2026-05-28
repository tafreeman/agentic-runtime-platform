from __future__ import annotations

import unicodedata
from typing import Sequence

from agentic_v2.contracts.sanitization import (
    Finding,
    FindingCategory,
    Severity,
)


class UnicodeSanitizer:
    """Normalizes Unicode and removes dangerous invisible characters."""

    name: str = "unicode_sanitizer"
    version: str = "1.0.0"

    MAX_PASSES: int = 10

    DANGEROUS_CODEPOINTS: frozenset[int] = frozenset(
        {
            0xFEFF,  # BOM
            0x200B,
            0x200C,
            0x200D,  # Zero-width space/non-joiner/joiner
            0x2060,  # Word joiner
            0x2062,
            0x2063,
            0x2064,  # Invisible times/separator/plus
            0xFFF9,
            0xFFFA,
            0xFFFB,  # Interlinear annotation
            0x202A,
            0x202B,
            0x202C,
            0x202D,
            0x202E,  # Bidi overrides
            0x2066,
            0x2067,
            0x2068,
            0x2069,  # Bidi isolates
        }
    )

    DANGEROUS_CATEGORIES: frozenset[str] = frozenset({"Cf", "Co", "Cn"})

    async def scan(self, text: str) -> Sequence[Finding]:
        """Scan-only interface for detector protocol compatibility."""
        _, findings = await self.sanitize(text)
        return findings

    async def sanitize(self, text: str) -> tuple[str, Sequence[Finding]]:
        """Iteratively normalize until stable.

        Returns (cleaned_text, findings).
        """
        findings: list[Finding] = []
        current = text
        removed_count = 0

        for _pass_number in range(self.MAX_PASSES):
            cleaned = self._single_pass(current)
            chars_removed = len(current) - len(cleaned)
            removed_count += chars_removed

            if cleaned == current:
                break
            current = cleaned
        else:
            findings.append(
                Finding(
                    category=FindingCategory.UNICODE_INJECTION,
                    severity=Severity.HIGH,
                    location="full_text",
                    matched_pattern="max_passes_exceeded",
                    redacted_preview=(
                        f"Unicode sanitization hit {self.MAX_PASSES} "
                        f"passes without stabilizing"
                    ),
                )
            )

        if removed_count > 0:
            findings.append(
                Finding(
                    category=FindingCategory.UNICODE_INJECTION,
                    severity=Severity.MEDIUM if removed_count > 5 else Severity.LOW,
                    location="full_text",
                    matched_pattern="dangerous_unicode_removed",
                    redacted_preview=(
                        f"Removed {removed_count} dangerous Unicode " f"character(s)"
                    ),
                )
            )

        return current, tuple(findings)

    def _single_pass(self, text: str) -> str:
        normalized = unicodedata.normalize("NFKC", text)
        return "".join(
            ch
            for ch in normalized
            if ord(ch) not in self.DANGEROUS_CODEPOINTS
            and unicodedata.category(ch) not in self.DANGEROUS_CATEGORIES
        )
