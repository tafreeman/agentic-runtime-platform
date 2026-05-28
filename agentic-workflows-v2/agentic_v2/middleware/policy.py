"""Classification policy that maps detector findings to sanitization outcomes."""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel

if TYPE_CHECKING:
    from collections.abc import Sequence

from ..contracts.sanitization import (
    Classification,
    Finding,
    FindingCategory,
    Severity,
)


class PolicyConfig(BaseModel):
    """Configurable severity-to-classification mapping."""

    critical_action: Classification = Classification.BLOCKED
    high_action: Classification = Classification.BLOCKED
    medium_action: Classification = Classification.REDACTED
    low_action: Classification = Classification.CLEAN
    high_entropy_action: Classification = Classification.REQUIRES_APPROVAL

    model_config = {"frozen": True}


class ClassificationPolicy:
    """Aggregates findings from all detectors into a single classification."""

    def __init__(self, config: PolicyConfig | None = None) -> None:
        self._config = config or PolicyConfig()

    def classify(self, findings: Sequence[Finding]) -> Classification:
        """Determine the overall classification based on all findings."""
        if not findings:
            return Classification.CLEAN

        max_severity = max(f.severity for f in findings)

        # Check for high-entropy-only findings (special case)
        if max_severity == Severity.LOW:
            if any(f.category == FindingCategory.HIGH_ENTROPY_STRING for f in findings):
                return self._config.high_entropy_action
            return self._config.low_action

        severity_map = {
            Severity.CRITICAL: self._config.critical_action,
            Severity.HIGH: self._config.high_action,
            Severity.MEDIUM: self._config.medium_action,
            Severity.LOW: self._config.low_action,
        }
        return severity_map.get(max_severity, Classification.CLEAN)

    @property
    def config(self) -> PolicyConfig:
        return self._config
