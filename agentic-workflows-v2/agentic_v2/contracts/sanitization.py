from __future__ import annotations

import enum
import hashlib
from datetime import datetime, timezone

from pydantic import BaseModel, Field


class Classification(enum.StrEnum):
    CLEAN = "clean"
    REDACTED = "redacted"
    BLOCKED = "blocked"
    REQUIRES_APPROVAL = "requires_approval"


class Severity(enum.StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class FindingCategory(enum.StrEnum):
    API_KEY = "api_key"
    BEARER_TOKEN = "bearer_token"
    PASSWORD = "password"
    ENV_VARIABLE = "env_variable"
    PRIVATE_KEY = "private_key"
    PII_EMAIL = "pii_email"
    PII_PHONE = "pii_phone"
    PII_SSN = "pii_ssn"
    UNICODE_INJECTION = "unicode_injection"
    PROMPT_INJECTION = "prompt_injection"
    HIGH_ENTROPY_STRING = "high_entropy_string"


class Finding(BaseModel):
    """A single detected issue in the input."""

    category: FindingCategory
    severity: Severity
    location: str = Field(
        description="Approximate location: 'message[2].content', 'tool_input.query'"
    )
    matched_pattern: str = Field(
        description="Pattern name/ID, NEVER the matched text itself"
    )
    redacted_preview: str = Field(
        default="",
        description="Surrounding context with secret replaced by [REDACTED]",
    )

    model_config = {"frozen": True}


class SanitizationResult(BaseModel):
    """Immutable result of running the sanitization pipeline."""

    classification: Classification
    findings: tuple[Finding, ...] = Field(default_factory=tuple)
    sanitized_text: str | None = Field(
        default=None,
        description="The cleaned text (with redactions applied). None if blocked.",
    )
    original_hash: str = Field(
        description="SHA-256 of original input for audit trail, NOT the input itself"
    )
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    detector_versions: dict[str, str] = Field(default_factory=dict)

    model_config = {"frozen": True}

    @property
    def is_safe(self) -> bool:
        """Return True when the content is safe to use (clean or redacted)."""
        return self.classification in (Classification.CLEAN, Classification.REDACTED)

    @staticmethod
    def compute_hash(text: str) -> str:
        """Return the SHA-256 hex digest of the given text."""
        return hashlib.sha256(text.encode("utf-8")).hexdigest()
