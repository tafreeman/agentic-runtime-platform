"""High-level sanitization middleware combining detectors, policy, and chain."""

from __future__ import annotations

import logging

from ..contracts.sanitization import SanitizationResult
from .base import MiddlewareChain
from .detectors.injection import PromptInjectionDetector
from .detectors.pii import PIIDetector
from .detectors.secrets import SecretDetector
from .detectors.unicode import UnicodeSanitizer
from .policy import ClassificationPolicy, PolicyConfig

logger = logging.getLogger(__name__)


class SanitizationMiddleware:
    """Main sanitization middleware — orchestrates the full detection pipeline.

    Provides a high-level ``process()`` method and a ``default()`` factory
    for zero-config usage.
    """

    def __init__(
        self,
        chain: MiddlewareChain | None = None,
        *,
        dry_run: bool = False,
    ) -> None:
        """
        Args:
            chain: Pre-configured middleware chain. If None, uses default().
            dry_run: If True, runs all detectors and logs findings but never
                     blocks or redacts. Useful for shadow deployment.
        """
        self._chain = chain or self._build_default_chain()
        self._dry_run = dry_run

    async def process(
        self, content: str, context: dict[str, object] | None = None
    ) -> SanitizationResult:
        """Run the full sanitization pipeline.

        Args:
            content: Raw text to sanitize.
            context: Optional metadata (e.g., {"source": "api_request", "tool": "search"}).

        Returns:
            SanitizationResult with classification, findings, and cleaned text.
        """
        result = await self._chain.process(content, context)

        if self._dry_run and not result.is_safe:
            logger.info(
                "Dry-run: would have classified as %s with %d findings",
                result.classification.value,
                len(result.findings),
            )
            # In dry-run mode, always return CLEAN with the original text
            return SanitizationResult(
                classification=result.classification,
                findings=result.findings,
                sanitized_text=content,
                original_hash=result.original_hash,
                timestamp=result.timestamp,
                detector_versions=result.detector_versions,
            )

        return result

    @classmethod
    def default(cls, *, dry_run: bool = False) -> SanitizationMiddleware:
        """Create a middleware with the default detector chain."""
        return cls(chain=cls._build_default_chain(), dry_run=dry_run)

    @classmethod
    def with_policy(
        cls, config: PolicyConfig, *, dry_run: bool = False
    ) -> SanitizationMiddleware:
        """Create a middleware with a custom policy configuration."""
        policy = ClassificationPolicy(config)
        chain = cls._build_default_chain(policy=policy)
        return cls(chain=chain, dry_run=dry_run)

    @staticmethod
    def _build_default_chain(
        policy: ClassificationPolicy | None = None,
    ) -> MiddlewareChain:
        """Build the default detection chain.

        Order: Unicode normalization -> Secrets -> PII -> Injection
        """
        return MiddlewareChain(
            detectors=[
                SecretDetector(),
                PIIDetector(),
                PromptInjectionDetector(),
            ],
            policy=policy,
            unicode_sanitizer=UnicodeSanitizer(),
        )
