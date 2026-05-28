"""Tests for the RAG document ingestion pipeline (Sprint 4.3).

Verifies:
- MarkdownLoader reads .md files and produces Document objects.
- RecursiveChunker splits documents into Chunk objects respecting config.
- IngestionPipeline orchestrates load → chunk → produce chunks.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from agentic_v2.rag.config import ChunkingConfig
from agentic_v2.rag.contracts import Chunk, Document

# ── RecursiveChunker ─────────────────────────────────────────────────


class TestRecursiveChunker:
    """Verify recursive character text splitting."""

    def test_short_document_single_chunk(self):
        from agentic_v2.rag.chunking import RecursiveChunker

        doc = Document(source="a.md", content="Hello world")
        chunker = RecursiveChunker()
        chunks = chunker.chunk(doc)
        assert len(chunks) == 1
        assert chunks[0].content == "Hello world"
        assert chunks[0].document_id == doc.document_id
        assert chunks[0].chunk_index == 0

    def test_long_document_multiple_chunks(self):
        from agentic_v2.rag.chunking import RecursiveChunker

        # Create content longer than chunk_size
        content = "word " * 200  # ~1000 chars
        doc = Document(source="a.md", content=content.strip())
        config = ChunkingConfig(chunk_size=100, chunk_overlap=20)
        chunker = RecursiveChunker()
        chunks = chunker.chunk(doc, config)
        assert len(chunks) > 1
        # All chunks should have sequential indices
        for i, chunk in enumerate(chunks):
            assert chunk.chunk_index == i
            assert chunk.document_id == doc.document_id

    def test_split_on_paragraph_boundary(self):
        from agentic_v2.rag.chunking import RecursiveChunker

        content = "Paragraph one.\n\nParagraph two.\n\nParagraph three."
        doc = Document(source="a.md", content=content)
        # Config large enough to fit each paragraph but not all
        config = ChunkingConfig(chunk_size=30, chunk_overlap=0)
        chunker = RecursiveChunker()
        chunks = chunker.chunk(doc, config)
        assert len(chunks) >= 2

    def test_metadata_inherited_from_document(self):
        from agentic_v2.rag.chunking import RecursiveChunker

        doc = Document(
            source="a.md", content="Hello world", metadata={"author": "test"}
        )
        chunker = RecursiveChunker()
        chunks = chunker.chunk(doc)
        assert chunks[0].metadata["source"] == "a.md"

    def test_chunk_ids_unique(self):
        from agentic_v2.rag.chunking import RecursiveChunker

        content = "word " * 200
        doc = Document(source="a.md", content=content.strip())
        config = ChunkingConfig(chunk_size=100, chunk_overlap=10)
        chunker = RecursiveChunker()
        chunks = chunker.chunk(doc, config)
        ids = [c.chunk_id for c in chunks]
        assert len(ids) == len(set(ids))

    def test_conforms_to_chunker_protocol(self):
        from agentic_v2.rag.chunking import RecursiveChunker
        from agentic_v2.rag.protocols import ChunkerProtocol

        assert isinstance(RecursiveChunker(), ChunkerProtocol)


# ── MarkdownLoader ───────────────────────────────────────────────────


class TestMarkdownLoader:
    """Verify markdown file loading."""

    @pytest.mark.asyncio
    async def test_load_markdown_file(self, tmp_path: Path):
        from agentic_v2.rag.loaders import MarkdownLoader

        md_file = tmp_path / "test.md"
        md_file.write_text("# Title\n\nSome content here.")

        loader = MarkdownLoader(allowed_base_dir=tmp_path)
        docs = await loader.load(str(md_file))
        assert len(docs) == 1
        assert docs[0].content == "# Title\n\nSome content here."
        assert docs[0].source == str(md_file)

    @pytest.mark.asyncio
    async def test_load_nonexistent_raises(self):
        from agentic_v2.rag.errors import IngestionError
        from agentic_v2.rag.loaders import MarkdownLoader

        loader = MarkdownLoader()
        with pytest.raises(IngestionError):
            await loader.load("/nonexistent/file.md")

    def test_supported_extensions(self):
        from agentic_v2.rag.loaders import MarkdownLoader

        loader = MarkdownLoader()
        assert ".md" in loader.supported_extensions
        assert ".markdown" in loader.supported_extensions

    def test_conforms_to_loader_protocol(self):
        from agentic_v2.rag.loaders import MarkdownLoader
        from agentic_v2.rag.protocols import LoaderProtocol

        assert isinstance(MarkdownLoader(), LoaderProtocol)


# ── IngestionPipeline ────────────────────────────────────────────────


class TestIngestionPipeline:
    """Verify end-to-end ingestion: load → chunk → produce chunks."""

    @pytest.mark.asyncio
    async def test_ingest_markdown_file(self, tmp_path: Path):
        from agentic_v2.rag.chunking import RecursiveChunker
        from agentic_v2.rag.ingestion import IngestionPipeline
        from agentic_v2.rag.loaders import MarkdownLoader

        md_file = tmp_path / "test.md"
        md_file.write_text("# Hello\n\nParagraph one.\n\nParagraph two.")

        pipeline = IngestionPipeline(
            loader=MarkdownLoader(allowed_base_dir=tmp_path),
            chunker=RecursiveChunker(),
        )
        chunks = await pipeline.ingest(str(md_file))
        assert len(chunks) >= 1
        assert all(isinstance(c, Chunk) for c in chunks)

    @pytest.mark.asyncio
    async def test_ingest_with_custom_config(self, tmp_path: Path):
        from agentic_v2.rag.chunking import RecursiveChunker
        from agentic_v2.rag.ingestion import IngestionPipeline
        from agentic_v2.rag.loaders import MarkdownLoader

        md_file = tmp_path / "test.md"
        md_file.write_text("word " * 200)

        config = ChunkingConfig(chunk_size=50, chunk_overlap=10)
        pipeline = IngestionPipeline(
            loader=MarkdownLoader(allowed_base_dir=tmp_path),
            chunker=RecursiveChunker(),
            chunking_config=config,
        )
        chunks = await pipeline.ingest(str(md_file))
        assert len(chunks) > 1
