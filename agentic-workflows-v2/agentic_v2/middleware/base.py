"""Base middleware chain that processes content through an ordered detector pipeline."""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

from ..contracts.sanitization import (
    Classification,
    Finding,
    SanitizationResult,
)
from .policy import ClassificationPolicy

logger = logging.getLogger(__name__)


class SanitizationDetectorError(RuntimeError):
    """Raised when a sanitizer detector fails during scanning."""


class MiddlewareChain:
    """Ordered chain of detectors.

    Processes content through each, aggregates findings.
    """

    def __init__(
        self,
        detectors: Sequence[object],
        policy: ClassificationPolicy | None = None,
        unicode_sanitizer: object | None = None,
    ) -> None:
        """
        Args:
            detectors: Objects with async scan(text) -> Sequence[Finding].
            policy: Classification policy. Defaults to ClassificationPolicy().
            unicode_sanitizer: If provided, must have async sanitize(text) -> (str, findings).
                             Used for text normalization before scanning.
        """
        self._detectors = tuple(detectors)
        self._policy = policy or ClassificationPolicy()
        self._unicode_sanitizer = unicode_sanitizer

    async def process(
        self, content: str, context: dict[str, object] | None = None
    ) -> SanitizationResult:
        """Run all detectors.

        Short-circuit on BLOCKED classification.
        """
        all_findings: list[Finding] = []
        current_text = content
        detector_versions: dict[str, str] = {}

        # Step 1: Unicode normalization (if sanitizer provided)
        if self._unicode_sanitizer is not None:
            sanitized_text, unicode_findings = await self._unicode_sanitizer.sanitize(
                current_text
            )
            all_findings.extend(unicode_findings)
            current_text = sanitized_text
            detector_versions[self._unicode_sanitizer.name] = (
                self._unicode_sanitizer.version
            )

        # Step 2: Run each detector
        for detector in self._detectors:
            try:
                findings = await detector.scan(current_text)
                all_findings.extend(findings)
                detector_versions[detector.name] = detector.version
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                detector_name = getattr(detector, "name", "unknown")
                logger.exception(
                    "Detector %s failed during sanitization", detector_name
                )
                raise SanitizationDetectorError(
                    f"Sanitization detector {detector_name} failed"
                ) from exc

            # Early exit check: if current findings already warrant blocking
            interim_classification = self._policy.classify(tuple(all_findings))
            if interim_classification == Classification.BLOCKED:
                logger.warning("Content blocked by %s", detector.name)
                return SanitizationResult(
                    classification=Classification.BLOCKED,
                    findings=tuple(all_findings),
                    sanitized_text=None,
                    original_hash=SanitizationResult.compute_hash(content),
                    detector_versions=detector_versions,
                )

        # Step 3: Final classification
        final_classification = self._policy.classify(tuple(all_findings))

        # Step 4: Apply redactions if needed
        sanitized_text = current_text
        if final_classification == Classification.BLOCKED:
            sanitized_text = None

        return SanitizationResult(
            classification=final_classification,
            findings=tuple(all_findings),
            sanitized_text=sanitized_text,
            original_hash=SanitizationResult.compute_hash(content),
            detector_versions=detector_versions,
        )
