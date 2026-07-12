"""Tests for RAG embedding providers (Sprint 5.2).

TDD — these tests are written FIRST, then the implementation follows.

Verifies:
- InMemoryEmbedder produces deterministic hash-based embeddings.
- InMemoryEmbedder satisfies EmbeddingProtocol.
- FallbackEmbedder tries providers in order and falls back on error.
- FallbackEmbedder raises EmbeddingError when all providers fail.
"""

from __future__ import annotations

import pytest

from agentic_v2.rag.errors import EmbeddingError
from agentic_v2.rag.protocols import EmbeddingProtocol


class _StaticEmbedder:
    """Small test embedder with configurable identity and output."""

    provider: str
    model_name: str

    def __init__(
        self,
        *,
        dimensions: int,
        vector_value: float,
        provider: str = "test",
        model_name: str = "static-v1",
    ) -> None:
        self._dimensions = dimensions
        self._vector_value = vector_value
        self.provider = provider
        self.model_name = model_name

    @property
    def dimensions(self) -> int:
        return self._dimensions

    async def embed(self, texts: list[str]) -> list[list[float]]:
        return [[self._vector_value] * self._dimensions for _ in texts]


class _FailingStaticEmbedder(_StaticEmbedder):
    """Static embedder variant that fails with EmbeddingError."""

    async def embed(self, texts: list[str]) -> list[list[float]]:
        raise EmbeddingError("provider failed")


# ── InMemoryEmbedder ────────────────────────────────────────────────


class TestInMemoryEmbedder:
    """Verify InMemoryEmbedder — deterministic hash-based embedder for testing."""

    def test_satisfies_embedding_protocol(self):
        """InMemoryEmbedder must be recognized as EmbeddingProtocol."""
        from agentic_v2.rag.embeddings import InMemoryEmbedder

        embedder = InMemoryEmbedder()
        assert isinstance(embedder, EmbeddingProtocol)

    def test_exposes_provider_and_model_identity(self):
        """Built-in embedders expose identity without changing the protocol."""
        from agentic_v2.rag.embeddings import InMemoryEmbedder

        embedder = InMemoryEmbedder()
        assert embedder.provider == "local"
        assert embedder.model_name == "in-memory-hash-v1"
        assert isinstance(embedder, EmbeddingProtocol)

    @pytest.mark.asyncio
    async def test_deterministic_embeddings(self):
        """Same input text must produce the same embedding vector."""
        from agentic_v2.rag.embeddings import InMemoryEmbedder

        embedder = InMemoryEmbedder()
        result1 = await embedder.embed(["hello world"])
        result2 = await embedder.embed(["hello world"])
        assert result1 == result2

    @pytest.mark.asyncio
    async def test_different_inputs_produce_different_embeddings(self):
        """Different texts must produce different embedding vectors."""
        from agentic_v2.rag.embeddings import InMemoryEmbedder

        embedder = InMemoryEmbedder()
        result = await embedder.embed(["hello", "goodbye"])
        assert result[0] != result[1]

    @pytest.mark.asyncio
    async def test_correct_dimensions_default(self):
        """Embeddings must have the default dimension count (384)."""
        from agentic_v2.rag.embeddings import InMemoryEmbedder

        embedder = InMemoryEmbedder()
        result = await embedder.embed(["test"])
        assert len(result[0]) == 384
        assert embedder.dimensions == 384

    @pytest.mark.asyncio
    async def test_correct_dimensions_custom(self):
        """Embeddings must respect a custom dimension setting."""
        from agentic_v2.rag.embeddings import InMemoryEmbedder

        embedder = InMemoryEmbedder(dimensions=128)
        result = await embedder.embed(["test"])
        assert len(result[0]) == 128
        assert embedder.dimensions == 128

    @pytest.mark.asyncio
    async def test_batch_inputs(self):
        """Embedding multiple texts returns one vector per input."""
        from agentic_v2.rag.embeddings import InMemoryEmbedder

        embedder = InMemoryEmbedder()
        texts = ["alpha", "beta", "gamma", "delta"]
        result = await embedder.embed(texts)
        assert len(result) == 4
        # Each vector has correct dimensions
        for vec in result:
            assert len(vec) == 384

    @pytest.mark.asyncio
    async def test_empty_input_returns_empty(self):
        """Embedding an empty list returns an empty list."""
        from agentic_v2.rag.embeddings import InMemoryEmbedder

        embedder = InMemoryEmbedder()
        result = await embedder.embed([])
        assert result == []

    @pytest.mark.asyncio
    async def test_embedding_values_are_floats(self):
        """All values in embedding vectors must be floats."""
        from agentic_v2.rag.embeddings import InMemoryEmbedder

        embedder = InMemoryEmbedder()
        result = await embedder.embed(["test"])
        assert all(isinstance(v, float) for v in result[0])

    @pytest.mark.asyncio
    async def test_embedding_values_are_bounded(self):
        """Embedding vector values should be in [-1.0, 1.0] range."""
        from agentic_v2.rag.embeddings import InMemoryEmbedder

        embedder = InMemoryEmbedder()
        result = await embedder.embed(["test text", "another text", "more text"])
        for vec in result:
            for v in vec:
                assert -1.0 <= v <= 1.0


# ── FallbackEmbedder ───────────────────────────────────────────────


class TestFallbackEmbedder:
    """Verify FallbackEmbedder — ordered fallback across providers."""

    def test_satisfies_embedding_protocol(self):
        """FallbackEmbedder must be recognized as EmbeddingProtocol."""
        from agentic_v2.rag.embeddings import FallbackEmbedder, InMemoryEmbedder

        primary = InMemoryEmbedder(dimensions=128)
        fallback = FallbackEmbedder(providers=[primary])
        assert isinstance(fallback, EmbeddingProtocol)

    @pytest.mark.asyncio
    async def test_uses_first_provider_on_success(self):
        """FallbackEmbedder should use the first provider when it succeeds."""
        from agentic_v2.rag.embeddings import FallbackEmbedder

        primary = _StaticEmbedder(dimensions=64, vector_value=1.0)
        secondary = _StaticEmbedder(dimensions=64, vector_value=2.0)
        fallback = FallbackEmbedder(providers=[primary, secondary])
        result = await fallback.embed(["test"])
        assert result == [[1.0] * 64]

    @pytest.mark.asyncio
    async def test_falls_back_on_first_provider_failure(self):
        """If the first provider raises EmbeddingError, fall back to the next."""
        from agentic_v2.rag.embeddings import FallbackEmbedder

        failing = _FailingStaticEmbedder(dimensions=64, vector_value=0.0)
        backup = _StaticEmbedder(dimensions=64, vector_value=2.0)
        fallback = FallbackEmbedder(providers=[failing, backup])
        result = await fallback.embed(["test"])
        assert result == [[2.0] * 64]

    @pytest.mark.asyncio
    async def test_raises_when_all_providers_fail(self):
        """If all providers fail, raise EmbeddingError with all collected errors."""
        from agentic_v2.rag.embeddings import FallbackEmbedder

        fallback = FallbackEmbedder(
            providers=[
                _FailingStaticEmbedder(dimensions=64, vector_value=0.0),
                _FailingStaticEmbedder(dimensions=64, vector_value=0.0),
            ]
        )
        with pytest.raises(EmbeddingError, match="All.*providers failed"):
            await fallback.embed(["test"])

    def test_dimensions_returns_first_provider_dimensions(self):
        """The dimensions property should reflect the shared provider dimensions."""
        from agentic_v2.rag.embeddings import FallbackEmbedder, InMemoryEmbedder

        primary = InMemoryEmbedder(dimensions=256)
        secondary = InMemoryEmbedder(dimensions=256)
        fallback = FallbackEmbedder(providers=[primary, secondary])
        assert fallback.dimensions == 256

    def test_rejects_providers_with_mixed_dimensions(self):
        """Fallback providers must not silently switch vector dimensions."""
        from agentic_v2.rag.embeddings import FallbackEmbedder, InMemoryEmbedder

        primary = InMemoryEmbedder(dimensions=256)
        secondary = InMemoryEmbedder(dimensions=512)

        with pytest.raises(ValueError, match="same dimensions"):
            FallbackEmbedder(providers=[primary, secondary])

    def test_rejects_mixed_identities_without_compatibility_override(self):
        """Equal dimensions are insufficient when provider/model identities differ."""
        from agentic_v2.rag.embeddings import FallbackEmbedder

        primary = _StaticEmbedder(
            dimensions=64,
            vector_value=1.0,
            provider="openai",
            model_name="text-embedding-3-small",
        )
        secondary = _StaticEmbedder(
            dimensions=64,
            vector_value=2.0,
            provider="voyage",
            model_name="voyage-3",
        )

        with pytest.raises(ValueError, match="provider/model identity"):
            FallbackEmbedder(providers=[primary, secondary])

    @pytest.mark.asyncio
    async def test_allows_mixed_identities_with_compatibility_override(self):
        """Explicit compatibility override allows same-dimension identity fallback."""
        from agentic_v2.rag.embeddings import FallbackEmbedder

        primary = _FailingStaticEmbedder(
            dimensions=64,
            vector_value=0.0,
            provider="openai",
            model_name="text-embedding-3-small",
        )
        secondary = _StaticEmbedder(
            dimensions=64,
            vector_value=2.0,
            provider="proxy",
            model_name="text-embedding-3-small-compatible",
        )
        fallback = FallbackEmbedder(
            providers=[primary, secondary],
            allow_mixed_provider_identities=True,
        )

        assert await fallback.embed(["test"]) == [[2.0] * 64]

    @pytest.mark.asyncio
    async def test_unexpected_provider_exception_does_not_fall_back(self):
        """Fallback only handles EmbeddingError; programming errors propagate."""
        from agentic_v2.rag.embeddings import FallbackEmbedder

        class _ExplodingEmbedder(_StaticEmbedder):
            async def embed(self, texts: list[str]) -> list[list[float]]:
                raise RuntimeError("bug")

        fallback = FallbackEmbedder(
            providers=[
                _ExplodingEmbedder(dimensions=64, vector_value=0.0),
                _StaticEmbedder(dimensions=64, vector_value=2.0),
            ]
        )

        with pytest.raises(RuntimeError, match="bug"):
            await fallback.embed(["test"])

    @pytest.mark.asyncio
    async def test_requires_at_least_one_provider(self):
        """FallbackEmbedder with empty providers should raise ValueError."""
        from agentic_v2.rag.embeddings import FallbackEmbedder

        with pytest.raises(ValueError, match="at least one"):
            FallbackEmbedder(providers=[])
