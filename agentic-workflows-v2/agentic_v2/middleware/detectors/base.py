from __future__ import annotations

import re
from dataclasses import dataclass

from agentic_v2.contracts.sanitization import FindingCategory, Severity


def build_preview(text: str, start: int, end: int, context: int, marker: str) -> str:
    """Return *text* around ``[start:end]`` with the match replaced by *marker*."""
    prefix = text[max(0, start - context) : start]
    suffix = text[end : min(len(text), end + context)]
    return f"{prefix}{marker}{suffix}"


@dataclass(frozen=True)
class SecretPattern:
    """A compiled regex pattern for detecting secrets."""

    name: str
    pattern: re.Pattern[str]
    severity: Severity
    category: FindingCategory

    @classmethod
    def from_raw(
        cls,
        name: str,
        raw_pattern: str,
        severity: Severity,
        category: FindingCategory,
        flags: int = 0,
    ) -> SecretPattern:
        return cls(
            name=name,
            pattern=re.compile(raw_pattern, flags),
            severity=severity,
            category=category,
        )


@dataclass(frozen=True)
class InjectionPattern:
    """A compiled regex pattern for detecting prompt injection markers."""

    name: str
    pattern: re.Pattern[str]
    severity: Severity

    @classmethod
    def from_raw(
        cls,
        name: str,
        raw_pattern: str,
        severity: Severity,
        flags: int = re.IGNORECASE,
    ) -> InjectionPattern:
        return cls(
            name=name,
            pattern=re.compile(raw_pattern, flags),
            severity=severity,
        )
