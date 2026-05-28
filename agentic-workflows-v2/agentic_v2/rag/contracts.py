"""RAG data contracts — Pydantic v2 models for all RAG data boundaries.

All models use ``ConfigDict(extra="forbid")`` to reject unknown fields
and ``frozen=True`` for immutability.
"""

from __future__ import annotations

import hashlib
import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, computed_field


class Document(BaseModel):
    """A source document before chunking.

    Attributes:
        document_id: Unique identifier (auto-generated UUID if omitted).
        source: File path, URL, or other source identifier.
        content: Raw text content of the document.
        metadata: Arbitrary key-value metadata (author, date, etc.).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    document_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    source: str
    content: str = Field(min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)


class Chunk(BaseModel):
    """A chunk of text extracted from a document.

    Attributes:
        chunk_id: Unique identifier for this chunk.
        document_id: ID of the parent document.
        chunk_index: Position of this chunk within the document.
        content: The chunk text.
        content_hash: SHA-256 hash of content for deduplication.
        metadata: Inherited + chunk-specific metadata.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    chunk_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    document_id: str
    chunk_index: int = Field(ge=0)
    content: str = Field(min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def content_hash(self) -> str:
        """SHA-256 hash of the chunk content for deduplication."""
        return hashlib.sha256(self.content.encode()).hexdigest()


class RetrievalResult(BaseModel):
    """A single retrieval result from a vector search.

    Attributes:
        content: The matched chunk text.
        score: Relevance score (0.0 – 1.0+, higher is better).
        document_id: ID of the source document.
        chunk_id: ID of the matched chunk.
        metadata: Chunk metadata.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    content: str
    score: float = Field(ge=0.0)
    document_id: str
    chunk_id: str
    metadata: dict[str, Any] = Field(default_factory=dict)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_high_confidence(self) -> bool:
        """True if score exceeds the high-confidence threshold (0.7)."""
        return self.score >= 0.7


class RAGResponse(BaseModel):
    """Response from a RAG query.

    Attributes:
        query: The original query text.
        results: Ordered list of retrieval results.
        total_results: Total number of results found.
        metadata: Pipeline metadata (latency, model, etc.).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    query: str
    results: list[RetrievalResult] = Field(default_factory=list)
    total_results: int = Field(ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)
