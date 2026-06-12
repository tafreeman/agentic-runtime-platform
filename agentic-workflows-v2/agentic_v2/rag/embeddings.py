"""RAG embedding providers — in-memory and fallback implementations.

Provides:
- :class:`InMemoryEmbedder`: Deterministic hash-based embedder for testing/dev.
- :class:`FallbackEmbedder`: Ordered fallback across multiple embedding providers.
"""

from __future__ import annotations

import hashlib
import logging
import math
import struct
from dataclasses import dataclass
from typing import Sequence

from .errors import EmbeddingError
from .protocols import EmbeddingProtocol

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class EmbeddingProviderIdentity:
    """Provider/model identity for an embedding semantic space."""

    provider: str
    model_name: str


def _embedding_identity(
    provider: EmbeddingProtocol,
) -> EmbeddingProviderIdentity | None:
    """Return explicit provider/model identity when the provider exposes it."""
    identity = getattr(provider, "embedding_identity", None)
    if isinstance(identity, EmbeddingProviderIdentity):
        return identity

    provider_name = getattr(provider, "provider", None)
    model_name = getattr(provider, "model_name", None)
    if provider_name is None or model_name is None:
        return None

    return EmbeddingProviderIdentity(
        provider=str(provider_name),
        model_name=str(model_name),
    )


def _provider_label(provider: EmbeddingProtocol) -> str:
    """Return a readable provider label for validation errors."""
    identity = _embedding_identity(provider)
    if identity is not None:
        return f"{identity.provider}/{identity.model_name}"
    return f"{type(provider).__module__}.{type(provider).__qualname__}"


def _validate_provider_dimensions(
    providers: tuple[EmbeddingProtocol, ...],
) -> int:
    """Ensure all providers share one positive vector dimensionality."""
    dimensions = tuple(provider.dimensions for provider in providers)
    for dimension in dimensions:
        if dimension <= 0:
            raise ValueError(f"provider dimensions must be positive, got {dimension}")

    expected = dimensions[0]
    if any(dimension != expected for dimension in dimensions):
        formatted = ", ".join(
            f"{_provider_label(provider)}={dimension}"
            for provider, dimension in zip(providers, dimensions, strict=True)
        )
        raise ValueError(
            "FallbackEmbedder providers must share the same dimensions; "
            f"got {formatted}"
        )
    return expected


def _validate_provider_identities(
    providers: tuple[EmbeddingProtocol, ...],
    *,
    allow_mixed_provider_identities: bool,
) -> tuple[EmbeddingProviderIdentity | None, ...]:
    """Ensure provider/model identities are pinned unless explicitly compatible."""
    identities = tuple(_embedding_identity(provider) for provider in providers)
    if len(providers) == 1 or allow_mixed_provider_identities:
        return identities

    missing = [
        _provider_label(provider)
        for provider, identity in zip(providers, identities, strict=True)
        if identity is None
    ]
    if missing:
        formatted = ", ".join(missing)
        raise ValueError(
            "FallbackEmbedder provider/model identity must be pinned; "
            f"missing provider/model identity for {formatted}. "
            "Expose provider and model_name, or set "
            "allow_mixed_provider_identities=True when explicitly compatible."
        )

    expected = identities[0]
    if any(identity != expected for identity in identities[1:]):
        formatted = ", ".join(
            f"{identity.provider}/{identity.model_name}"
            for identity in identities
            if identity is not None
        )
        raise ValueError(
            "FallbackEmbedder providers must share provider/model identity; "
            f"got {formatted}. Set allow_mixed_provider_identities=True "
            "when explicitly compatible."
        )

    return identities


def _fallback_identity(
    identities: tuple[EmbeddingProviderIdentity | None, ...],
    *,
    allow_mixed_provider_identities: bool,
) -> EmbeddingProviderIdentity:
    """Derive the identity exposed by a fallback chain."""
    first = identities[0]
    if first is not None and all(identity == first for identity in identities):
        return first

    model_name = "explicitly-compatible" if allow_mixed_provider_identities else "unknown"
    return EmbeddingProviderIdentity(provider="fallback", model_name=model_name)


class InMemoryEmbedder:
    """Deterministic hash-based embedder for testing and development.

    Generates embedding vectors by hashing input text with SHA-256, then
    expanding the hash bytes into a float vector of the requested
    dimensionality.  Same input always produces the same output, with
    no external API calls.

    Satisfies :class:`EmbeddingProtocol`.

    Args:
        dimensions: Number of dimensions for embedding vectors (default 384).
    """

    def __init__(self, dimensions: int = 384) -> None:
        if dimensions <= 0:
            raise ValueError(f"dimensions must be positive, got {dimensions}")
        self._dimensions = dimensions

    @property
    def provider(self) -> str:
        """Provider identity for the deterministic local embedder."""
        return "local"

    @property
    def model_name(self) -> str:
        """Model identity for the deterministic local embedder."""
        return "in-memory-hash-v1"

    @property
    def embedding_identity(self) -> EmbeddingProviderIdentity:
        """Provider/model identity for this embedding semantic space."""
        return EmbeddingProviderIdentity(
            provider=self.provider,
            model_name=self.model_name,
        )

    @property
    def dimensions(self) -> int:
        """Dimensionality of the embedding vectors."""
        return self._dimensions

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts using deterministic hashing.

        Args:
            texts: Strings to embed.

        Returns:
            List of embedding vectors (one per input text), each of
            length :attr:`dimensions` with values in [-1.0, 1.0].
        """
        return [self._hash_to_vector(text) for text in texts]

    def _hash_to_vector(self, text: str) -> list[float]:
        """Convert text to a deterministic float vector.

        Uses SHA-256 iteratively to produce enough bytes, then converts
        to floats in [-1.0, 1.0] and L2-normalizes.
        """
        vector: list[float] = []
        seed = text.encode("utf-8")

        # Generate enough floats by chaining hashes
        iteration = 0
        while len(vector) < self._dimensions:
            hash_input = seed + struct.pack(">I", iteration)
            digest = hashlib.sha256(hash_input).digest()
            # Each 4 bytes → one float via unsigned int → [-1, 1]
            for offset in range(0, len(digest), 4):
                if len(vector) >= self._dimensions:
                    break
                uint_val = struct.unpack(">I", digest[offset : offset + 4])[0]
                # Map [0, 2^32) to [-1.0, 1.0)
                float_val = (uint_val / (2**32)) * 2.0 - 1.0
                vector.append(float_val)
            iteration += 1

        # L2-normalize so vectors have unit length
        norm = math.sqrt(sum(v * v for v in vector))
        if norm > 0:
            vector = [v / norm for v in vector]

        return vector


class FallbackEmbedder:
    """Ordered fallback across multiple embedding providers.

    Tries each provider in sequence.  On :class:`EmbeddingError` from
    one provider, falls back to the next.  Other exception types are treated
    as provider bugs and propagated without fallback.  If all providers fail,
    raises :class:`EmbeddingError` listing all collected errors.

    All providers must have identical dimensions.  Provider/model identity
    must also match unless ``allow_mixed_provider_identities`` explicitly
    marks the providers as compatible.

    Satisfies :class:`EmbeddingProtocol`.

    Args:
        providers: Ordered sequence of embedding providers to try.
        allow_mixed_provider_identities: Permit same-dimension providers with
            different provider/model identities when they are explicitly known
            to be compatible.

    Raises:
        ValueError: If *providers* is empty, dimensions differ, or identities
            differ without an explicit compatibility override.
    """

    def __init__(
        self,
        providers: Sequence[EmbeddingProtocol],
        *,
        allow_mixed_provider_identities: bool = False,
    ) -> None:
        if not providers:
            raise ValueError("FallbackEmbedder requires at least one provider")
        self._providers: tuple[EmbeddingProtocol, ...] = tuple(providers)
        self._dimensions = _validate_provider_dimensions(self._providers)
        self._identities = _validate_provider_identities(
            self._providers,
            allow_mixed_provider_identities=allow_mixed_provider_identities,
        )
        self._identity = _fallback_identity(
            self._identities,
            allow_mixed_provider_identities=allow_mixed_provider_identities,
        )

    @property
    def dimensions(self) -> int:
        """Shared dimensionality of the fallback provider chain."""
        return self._dimensions

    @property
    def provider(self) -> str:
        """Provider identity for this fallback chain."""
        return self._identity.provider

    @property
    def model_name(self) -> str:
        """Model identity for this fallback chain."""
        return self._identity.model_name

    @property
    def embedding_identity(self) -> EmbeddingProviderIdentity:
        """Provider/model identity for this fallback chain."""
        return self._identity

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed texts using the first available provider.

        Tries each provider in order.  Falls back on :class:`EmbeddingError`.

        Args:
            texts: Strings to embed.

        Returns:
            List of embedding vectors from the first successful provider.

        Raises:
            EmbeddingError: If all providers fail.
        """
        errors: list[EmbeddingError] = []

        for provider in self._providers:
            try:
                return await provider.embed(texts)
            except EmbeddingError as exc:
                logger.warning(
                    "Embedding provider failed, trying next: %s",
                    exc,
                )
                errors.append(exc)

        error_messages = "; ".join(str(e) for e in errors)
        raise EmbeddingError(
            f"All {len(errors)} embedding providers failed: {error_messages}"
        )
