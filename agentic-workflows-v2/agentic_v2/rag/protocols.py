"""RAG protocols — structural interfaces for pluggable RAG components.

Uses ``typing.Protocol`` with ``runtime_checkable`` so implementations
conform by shape, not inheritance.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from .config import ChunkingConfig
from .contracts import Chunk, Document, RetrievalResult


@runtime_checkable
class LoaderProtocol(Protocol):
    """Interface for document loaders.

    Loaders read source files/URLs and produce :class:`Document` objects.
    """

    async def load(self, source: str, **kwargs: Any) -> list[Document]:
        """Load documents from *source*.

        Args:
            source: File path, URL, or other locator.

        Returns:
            List of loaded documents.
        """
        ...

    @property
    def supported_extensions(self) -> list[str]:
        """File extensions this loader handles (e.g. ``[".md", ".txt"]``)."""
        ...


@runtime_checkable
class ChunkerProtocol(Protocol):
    """Interface for document chunkers.

    Chunkers split a :class:`Document` into :class:`Chunk` objects.
    """

    def chunk(
        self, document: Document, config: ChunkingConfig | None = None
    ) -> list[Chunk]:
        """Split *document* into chunks.

        Args:
            document: The document to chunk.
            config: Optional override for chunking settings.

        Returns:
            Ordered list of chunks.
        """
        ...


@runtime_checkable
class EmbeddingProtocol(Protocol):
    """Interface for embedding providers."""

    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts.

        Args:
            texts: Strings to embed.

        Returns:
            List of embedding vectors (one per input text).
        """
        ...

    @property
    def dimensions(self) -> int:
        """Dimensionality of the embedding vectors."""
        ...


@runtime_checkable
class VectorStoreProtocol(Protocol):
    """Interface for vector store backends."""

    async def add(self, chunks: list[Chunk], embeddings: list[list[float]]) -> None:
        """Add chunks with their embeddings to the store."""
        ...

    async def search(
        self,
        query_embedding: list[float],
        top_k: int = 5,
        metadata_filter: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> list[RetrievalResult]:
        """Search for similar chunks.

        Args:
            query_embedding: The query vector.
            top_k: Maximum results to return.
            metadata_filter: Optional key-value filter applied to chunk
                metadata.  Only chunks whose metadata contains all
                specified key-value pairs are returned.

        Returns:
            Ranked list of retrieval results.
        """
        ...

    async def delete(self, document_id: str) -> bool:
        """Delete all chunks for a document.

        Returns:
            True if any chunks were deleted.
        """
        ...


@runtime_checkable
class RerankerProtocol(Protocol):
    """Interface for result rerankers.

    Rerankers rescore and reorder retrieval results using a more
    expensive signal (cross-encoder model, LLM judge, etc.) to improve
    precision after an initial cheap retrieval pass.
    """

    async def rerank(
        self,
        query: str,
        results: list[RetrievalResult],
        *,
        top_k: int = 5,
    ) -> list[RetrievalResult]:
        """Rerank retrieval results for *query*.

        Args:
            query: The original search query.
            results: Candidate results from initial retrieval.
            top_k: Maximum number of results to return.

        Returns:
            Reranked list, ordered by descending relevance.
        """
        ...
