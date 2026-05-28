from __future__ import annotations

from typing import Sequence

from agentic_v2.contracts.sanitization import (
    Finding,
    FindingCategory,
    Severity,
)
from agentic_v2.middleware.detectors.base import InjectionPattern


class PromptInjectionDetector:
    """Detects known prompt injection markers and instruction override attempts."""

    name: str = "prompt_injection_detector"
    version: str = "1.0.0"

    PREVIEW_CONTEXT: int = 40

    PATTERNS: tuple[InjectionPattern, ...] = (
        InjectionPattern.from_raw(
            "instruction_override",
            r"(?:ignore|disregard|forget)\s+(?:all\s+)?(?:previous|prior|above|earlier)\s+instructions?",
            Severity.HIGH,
        ),
        InjectionPattern.from_raw(
            "role_hijack",
            r"you\s+are\s+now\s+(?:a|an|the)\s+",
            Severity.MEDIUM,
        ),
        InjectionPattern.from_raw(
            "system_prompt_extract",
            r"(?:print|show|reveal|output|display|repeat)\s+(?:your\s+)?(?:system\s+prompt|instructions|rules|guidelines)",
            Severity.HIGH,
        ),
        InjectionPattern.from_raw(
            "delimiter_escape",
            r"```\s*(?:system|assistant|human|user)\s*\n",
            Severity.MEDIUM,
        ),
        InjectionPattern.from_raw(
            "xml_injection",
            r"<\s*/?\s*(?:system|instructions|rules|prompt)\s*>",
            Severity.HIGH,
        ),
        InjectionPattern.from_raw(
            "new_instructions",
            r"(?:new|updated|revised|override)\s+(?:system\s+)?instructions?\s*:",
            Severity.HIGH,
        ),
        InjectionPattern.from_raw(
            "jailbreak_attempt",
            r"(?:DAN|do\s+anything\s+now|developer\s+mode|unlocked\s+mode)",
            Severity.HIGH,
        ),
    )

    async def scan(self, text: str) -> Sequence[Finding]:
        findings: list[Finding] = []

        for injection_pattern in self.PATTERNS:
            for match in injection_pattern.pattern.finditer(text):
                start, end = match.start(), match.end()
                findings.append(
                    Finding(
                        category=FindingCategory.PROMPT_INJECTION,
                        severity=injection_pattern.severity,
                        location=f"text[{start}:{end}]",
                        matched_pattern=injection_pattern.name,
                        redacted_preview=self._build_preview(text, start, end),
                    )
                )

        return tuple(findings)

    def _build_preview(self, text: str, start: int, end: int) -> str:
        ctx_start = max(0, start - self.PREVIEW_CONTEXT)
        ctx_end = min(len(text), end + self.PREVIEW_CONTEXT)
        prefix = text[ctx_start:start]
        suffix = text[end:ctx_end]
        return f"{prefix}[MATCHED]{suffix}"
