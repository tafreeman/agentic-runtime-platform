"""RAG-specific error hierarchy.

All RAG exceptions inherit from :class:`RAGError`, which itself
inherits from the core :class:`AgenticError`.
"""

from __future__ import annotations

from ..core.errors import AgenticError


class RAGError(AgenticError):
    """Base exception for all RAG pipeline errors."""


class IngestionError(RAGError):
    """Error during document ingestion."""


class ChunkingError(RAGError):
    """Error during document chunking."""


class EmbeddingError(RAGError):
    """Error during embedding generation."""


class VectorStoreError(RAGError):
    """Error during vector store operations."""


class RetrievalError(RAGError):
    """Error during retrieval or search."""
