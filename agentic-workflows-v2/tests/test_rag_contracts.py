"""Tests for RAG module contracts, config, and error hierarchy (Sprint 4.2).

TDD — these tests are written FIRST, then the implementation follows.

Verifies:
- Pydantic v2 contracts (Document, Chunk, RetrievalResult, RAGResponse)
- Frozen configs (EmbeddingConfig, ChunkingConfig, RAGConfig)
- Error hierarchy (RAGError and sub-types)
- Protocol definitions (LoaderProtocol, ChunkerProtocol, EmbeddingProtocol, VectorStoreProtocol)
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

# ── Document ─────────────────────────────────────────────────────────


class TestDocument:
    """Verify Document contract."""

    def test_create_document(self):
        from agentic_v2.rag.contracts import Document

        doc = Document(
            source="README.md",
            content="# Hello\nWorld",
            metadata={"author": "test"},
        )
        assert doc.source == "README.md"
        assert doc.content == "# Hello\nWorld"
        assert doc.metadata["author"] == "test"
        assert doc.document_id  # auto-generated

    def test_document_id_auto_generated(self):
        from agentic_v2.rag.contracts import Document

        doc1 = Document(source="a.md", content="a")
        doc2 = Document(source="b.md", content="b")
        assert doc1.document_id != doc2.document_id

    def test_empty_content_rejected(self):
        from agentic_v2.rag.contracts import Document

        with pytest.raises(ValidationError):
            Document(source="a.md", content="")

    def test_extra_fields_forbidden(self):
        from agentic_v2.rag.contracts import Document

        with pytest.raises(ValidationError):
            Document(source="a.md", content="text", unknown_field="bad")


# ── Chunk ────────────────────────────────────────────────────────────


class TestChunk:
    """Verify Chunk contract."""

    def test_create_chunk(self):
        from agentic_v2.rag.contracts import Chunk

        chunk = Chunk(
            content="some text",
            document_id="doc-1",
            chunk_index=0,
            metadata={"section": "intro"},
        )
        assert chunk.content == "some text"
        assert chunk.document_id == "doc-1"
        assert chunk.chunk_index == 0
        assert chunk.chunk_id  # auto-generated

    def test_content_hash_computed(self):
        from agentic_v2.rag.contracts import Chunk

        c1 = Chunk(content="abc", document_id="d1", chunk_index=0)
        c2 = Chunk(content="abc", document_id="d1", chunk_index=1)
        c3 = Chunk(content="xyz", document_id="d1", chunk_index=0)
        assert c1.content_hash == c2.content_hash  # same content
        assert c1.content_hash != c3.content_hash  # different content

    def test_empty_content_rejected(self):
        from agentic_v2.rag.contracts import Chunk

        with pytest.raises(ValidationError):
            Chunk(content="", document_id="d1", chunk_index=0)


# ── RetrievalResult ──────────────────────────────────────────────────


class TestRetrievalResult:
    """Verify RetrievalResult contract."""

    def test_create_retrieval_result(self):
        from agentic_v2.rag.contracts import RetrievalResult

        rr = RetrievalResult(
            content="matched text",
            score=0.95,
            document_id="doc-1",
            chunk_id="chunk-1",
            metadata={"source": "readme.md"},
        )
        assert rr.score == 0.95
        assert rr.is_high_confidence is True

    def test_low_score_not_high_confidence(self):
        from agentic_v2.rag.contracts import RetrievalResult

        rr = RetrievalResult(
            content="text",
            score=0.3,
            document_id="d1",
            chunk_id="c1",
        )
        assert rr.is_high_confidence is False

    def test_score_must_be_non_negative(self):
        from agentic_v2.rag.contracts import RetrievalResult

        with pytest.raises(ValidationError):
            RetrievalResult(
                content="text",
                score=-0.1,
                document_id="d1",
                chunk_id="c1",
            )


# ── RAGResponse ──────────────────────────────────────────────────────


class TestRAGResponse:
    """Verify RAGResponse contract."""

    def test_create_rag_response(self):
        from agentic_v2.rag.contracts import RAGResponse, RetrievalResult

        results = [
            RetrievalResult(content="a", score=0.9, document_id="d1", chunk_id="c1"),
            RetrievalResult(content="b", score=0.7, document_id="d2", chunk_id="c2"),
        ]
        resp = RAGResponse(
            query="what is X?",
            results=results,
            total_results=2,
        )
        assert resp.query == "what is X?"
        assert len(resp.results) == 2
        assert resp.total_results == 2


# ── ChunkingConfig ───────────────────────────────────────────────────


class TestChunkingConfig:
    """Verify frozen ChunkingConfig."""

    def test_defaults(self):
        from agentic_v2.rag.config import ChunkingConfig

        cfg = ChunkingConfig()
        assert cfg.chunk_size == 512
        assert cfg.chunk_overlap == 64
        assert cfg.strategy == "recursive"

    def test_frozen(self):
        from agentic_v2.rag.config import ChunkingConfig

        cfg = ChunkingConfig()
        with pytest.raises(ValidationError):
            cfg.chunk_size = 1024

    def test_overlap_less_than_chunk_size(self):
        from agentic_v2.rag.config import ChunkingConfig

        with pytest.raises(ValidationError):
            ChunkingConfig(chunk_size=100, chunk_overlap=200)

    def test_extra_fields_forbidden(self):
        from agentic_v2.rag.config import ChunkingConfig

        with pytest.raises(ValidationError):
            ChunkingConfig(unknown=True)


# ── EmbeddingConfig ──────────────────────────────────────────────────


class TestEmbeddingConfig:
    """Verify frozen EmbeddingConfig."""

    def test_defaults(self):
        from agentic_v2.rag.config import EmbeddingConfig

        cfg = EmbeddingConfig()
        assert cfg.provider == "openai"
        assert cfg.dimensions > 0

    def test_frozen(self):
        from agentic_v2.rag.config import EmbeddingConfig

        cfg = EmbeddingConfig()
        with pytest.raises(ValidationError):
            cfg.provider = "voyage"


# ── RAGConfig ────────────────────────────────────────────────────────


class TestRAGConfig:
    """Verify top-level frozen RAGConfig."""

    def test_defaults(self):
        from agentic_v2.rag.config import RAGConfig

        cfg = RAGConfig()
        assert cfg.chunking.chunk_size == 512
        assert cfg.embedding.provider == "openai"
        assert cfg.top_k == 5

    def test_frozen(self):
        from agentic_v2.rag.config import RAGConfig

        cfg = RAGConfig()
        with pytest.raises(ValidationError):
            cfg.top_k = 10


# ── RAG Error Hierarchy ──────────────────────────────────────────────


class TestRAGErrors:
    """Verify error hierarchy."""

    def test_rag_error_is_agentic_error(self):
        from agentic_v2.core.errors import AgenticError
        from agentic_v2.rag.errors import RAGError

        assert issubclass(RAGError, AgenticError)

    def test_sub_errors(self):
        from agentic_v2.rag.errors import (
            ChunkingError,
            EmbeddingError,
            IngestionError,
            RAGError,
            RetrievalError,
            VectorStoreError,
        )

        assert issubclass(ChunkingError, RAGError)
        assert issubclass(EmbeddingError, RAGError)
        assert issubclass(IngestionError, RAGError)
        assert issubclass(RetrievalError, RAGError)
        assert issubclass(VectorStoreError, RAGError)


# ── RAG Protocols ────────────────────────────────────────────────────


class TestRAGProtocols:
    """Verify RAG Protocol shapes."""

    def test_loader_protocol_conforming(self):
        from agentic_v2.rag.protocols import LoaderProtocol

        class _TestLoader:
            async def load(self, source, **kwargs):
                return []

            @property
            def supported_extensions(self):
                return [".md"]

        assert isinstance(_TestLoader(), LoaderProtocol)

    def test_chunker_protocol_conforming(self):
        from agentic_v2.rag.protocols import ChunkerProtocol

        class _TestChunker:
            def chunk(self, document, config=None):
                return []

        assert isinstance(_TestChunker(), ChunkerProtocol)

    def test_embedding_protocol_conforming(self):
        from agentic_v2.rag.protocols import EmbeddingProtocol

        class _TestEmbedder:
            async def embed(self, texts):
                return [[0.0] * 768]

            @property
            def dimensions(self):
                return 768

        assert isinstance(_TestEmbedder(), EmbeddingProtocol)

    def test_vector_store_protocol_conforming(self):
        from agentic_v2.rag.protocols import VectorStoreProtocol

        class _TestStore:
            async def add(self, chunks, embeddings):
                pass

            async def search(self, query_embedding, top_k=5, **kwargs):
                return []

            async def delete(self, document_id):
                return True

        assert isinstance(_TestStore(), VectorStoreProtocol)
