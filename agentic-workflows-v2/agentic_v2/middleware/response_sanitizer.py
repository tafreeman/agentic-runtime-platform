"""Response-path sanitizer for LLM outputs.

Lighter than the full inbound chain — focuses on detecting leaked
secrets and ensuring Unicode safety in LLM responses.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from ..contracts.sanitization import (
    Classification,
    Finding,
    SanitizationResult,
)
from .detectors.secrets import SecretDetector
from .detectors.unicode import UnicodeSanitizer

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ResponseSanitizationConfig:
    """Configuration for response sanitization."""

    check_secrets: bool = True
    normalize_unicode: bool = True


class ResponseSanitizer:
    """Sanitizes LLM responses on the output path.

    Lighter than the full inbound SanitizationMiddleware — only checks
    for secret leakage and Unicode normalization (no PII/injection
    scanning).
    """

    def __init__(
        self,
        config: ResponseSanitizationConfig | None = None,
    ) -> None:
        self._config = config or ResponseSanitizationConfig()
        self._secret_detector = SecretDetector() if self._config.check_secrets else None
        self._unicode_sanitizer = (
            UnicodeSanitizer() if self._config.normalize_unicode else None
        )

    async def sanitize_response(self, response_text: str) -> SanitizationResult:
        """Scan and clean an LLM response.

        Returns:
            SanitizationResult. Classification will be CLEAN or REDACTED
            (responses are never blocked — they've already been generated).
        """
        all_findings: list[Finding] = []
        current_text = response_text
        detector_versions: dict[str, str] = {}

        # Unicode normalization
        if self._unicode_sanitizer is not None:
            cleaned, unicode_findings = await self._unicode_sanitizer.sanitize(
                current_text
            )
            all_findings.extend(unicode_findings)
            current_text = cleaned
            detector_versions[self._unicode_sanitizer.name] = (
                self._unicode_sanitizer.version
            )

        # Secret leakage check
        if self._secret_detector is not None:
            secret_findings = await self._secret_detector.scan(current_text)
            all_findings.extend(secret_findings)
            detector_versions[self._secret_detector.name] = (
                self._secret_detector.version
            )

        # Responses are never BLOCKED — classify as CLEAN or REDACTED only
        classification = Classification.CLEAN
        if all_findings:
            has_secrets = any(
                f.matched_pattern != "dangerous_unicode_removed"
                and f.matched_pattern != "high_entropy"
                for f in all_findings
            )
            classification = (
                Classification.REDACTED if has_secrets else Classification.CLEAN
            )

        if classification == Classification.REDACTED:
            logger.warning(
                "LLM response contained %d secret findings — marked as redacted",
                len(all_findings),
            )

        return SanitizationResult(
            classification=classification,
            findings=tuple(all_findings),
            sanitized_text=current_text,
            original_hash=SanitizationResult.compute_hash(response_text),
            detector_versions=detector_versions,
        )
