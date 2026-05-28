"""RAG configuration — frozen Pydantic models for pipeline settings.

All configs are immutable (``frozen=True``) and reject unknown fields
(``extra="forbid"``).  Defaults follow ADR-002 recommendations.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ChunkingConfig(BaseModel):
    """Configuration for document chunking.

    Attributes:
        strategy: Chunking algorithm (``"recursive"`` or ``"semantic"``).
        chunk_size: Target chunk size in tokens.
        chunk_overlap: Overlap between consecutive chunks.
        separators: Custom split separators (for recursive strategy).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    strategy: Literal["recursive", "semantic"] = "recursive"
    chunk_size: int = Field(default=512, gt=0)
    chunk_overlap: int = Field(default=64, ge=0)
    separators: list[str] = Field(default_factory=lambda: ["\n\n", "\n", ". ", " ", ""])

    @model_validator(mode="after")
    def _validate_overlap(self) -> ChunkingConfig:
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError(
                f"chunk_overlap ({self.chunk_overlap}) must be less than "
                f"chunk_size ({self.chunk_size})"
            )
        return self


class EmbeddingConfig(BaseModel):
    """Configuration for embedding generation.

    Attributes:
        provider: Embedding provider name.
        model_name: Specific model identifier.
        dimensions: Embedding vector dimensions.
        batch_size: Max texts per embedding API call.
        max_concurrent: Concurrency limit for API calls.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: Literal["openai", "voyage", "local", "litellm"] = "openai"
    model_name: str = "text-embedding-3-small"
    dimensions: int = Field(default=1536, gt=0)
    batch_size: int = Field(default=100, gt=0)
    max_concurrent: int = Field(default=5, gt=0)


class RerankerConfig(BaseModel):
    """Configuration for optional result reranking.

    Attributes:
        strategy: Reranking approach — ``"none"`` (passthrough),
            ``"cross_encoder"`` (model-based), or ``"llm"`` (LLM judge).
        model_name: Model identifier for cross-encoder or LLM reranker.
        top_k: Number of results to keep after reranking.
        batch_size: Batch size for cross-encoder inference.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    strategy: Literal["none", "cross_encoder", "llm"] = "none"
    model_name: str | None = None
    top_k: int = Field(default=5, gt=0)
    batch_size: int = Field(default=32, gt=0)


class RAGConfig(BaseModel):
    """Top-level RAG pipeline configuration.

    Composes chunking and embedding configs with retrieval settings.

    Attributes:
        chunking: Document chunking settings.
        embedding: Embedding generation settings.
        reranker: Optional reranking settings.
        vectorstore_type: Vector store backend (``"memory"`` or ``"lancedb"``).
        db_path: Filesystem path for persistent stores (required when
            ``vectorstore_type`` is ``"lancedb"``).
        top_k: Default number of results to return.
        score_threshold: Minimum relevance score filter.
        collection_name: Default vector store collection name.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    chunking: ChunkingConfig = Field(default_factory=ChunkingConfig)
    embedding: EmbeddingConfig = Field(default_factory=EmbeddingConfig)
    reranker: RerankerConfig = Field(default_factory=RerankerConfig)
    vectorstore_type: Literal["memory", "lancedb"] = "memory"
    db_path: str | None = None
    top_k: int = Field(default=5, gt=0)
    score_threshold: float = Field(default=0.0, ge=0.0)
    collection_name: str = "default"

    @model_validator(mode="after")
    def _validate_db_path(self) -> RAGConfig:
        if self.vectorstore_type == "lancedb" and self.db_path is None:
            raise ValueError("db_path is required when vectorstore_type is 'lancedb'")
        return self
