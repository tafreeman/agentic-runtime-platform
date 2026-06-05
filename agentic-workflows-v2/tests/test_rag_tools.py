"""Tests for RAG tool bridges — RAGSearchTool and RAGIngestTool.

Covers:
- RAGSearchTool: returns RAGResponse for valid query, handles empty results, respects top_k
- RAGIngestTool: ingests file and returns chunk count, handles errors gracefully
- Both tools can be registered in ToolRegistry
"""

from __future__ import annotations

import pytest

from agentic_v2.rag.chunking import RecursiveChunker
from agentic_v2.rag.contracts import Chunk
from agentic_v2.rag.embeddings import InMemoryEmbedder
from agentic_v2.rag.ingestion import IngestionPipeline
from agentic_v2.rag.loaders import TextLoader
from agentic_v2.rag.retrieval import HybridRetriever
from agentic_v2.rag.tools import RAGIngestTool, RAGSearchTool
from agentic_v2.rag.vectorstore import InMemoryVectorStore
from agentic_v2.tools.base import BaseTool, ToolResult
from agentic_v2.tools.registry import ToolRegistry

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_chunk(
    content: str,
    *,
    chunk_id: str | None = None,
    document_id: str = "doc-1",
    chunk_index: int = 0,
) -> Chunk:
    """Helper to build a Chunk with sensible defaults."""
    kwargs: dict = {
        "document_id": document_id,
        "chunk_index": chunk_index,
        "content": content,
    }
    if chunk_id is not None:
        kwargs["chunk_id"] = chunk_id
    return Chunk(**kwargs)


@pytest.fixture
def embedder() -> InMemoryEmbedder:
    """In-memory embedder for testing."""
    return InMemoryEmbedder(dimensions=64)


@pytest.fixture
def vectorstore() -> InMemoryVectorStore:
    """In-memory vector store for testing."""
    return InMemoryVectorStore()


@pytest.fixture
def retriever(
    embedder: InMemoryEmbedder, vectorstore: InMemoryVectorStore
) -> HybridRetriever:
    """Pre-configured hybrid retriever."""
    return HybridRetriever(embedder=embedder, vectorstore=vectorstore)


@pytest.fixture
async def populated_retriever(
    embedder: InMemoryEmbedder,
    vectorstore: InMemoryVectorStore,
) -> HybridRetriever:
    """Retriever with pre-indexed chunks."""
    chunks = [
        _make_chunk(
            "Python is a popular programming language for data science",
            chunk_id="c1",
            chunk_index=0,
        ),
        _make_chunk(
            "Rust is a systems programming language focused on safety",
            chunk_id="c2",
            chunk_index=1,
        ),
        _make_chunk(
            "Data science uses Python and R for statistical analysis",
            chunk_id="c3",
            chunk_index=2,
        ),
    ]
    embeddings = await embedder.embed([c.content for c in chunks])
    await vectorstore.add(chunks, embeddings)

    retriever = HybridRetriever(embedder=embedder, vectorstore=vectorstore)
    retriever.index_chunks(chunks)
    return retriever


@pytest.fixture
def search_tool(populated_retriever: HybridRetriever) -> RAGSearchTool:
    """RAGSearchTool with a populated retriever."""
    return RAGSearchTool(retriever=populated_retriever)


@pytest.fixture
def ingest_tool(
    embedder: InMemoryEmbedder,
    vectorstore: InMemoryVectorStore,
    retriever: HybridRetriever,
    tmp_path: object,
) -> RAGIngestTool:
    """RAGIngestTool with in-memory components."""
    from pathlib import Path

    loader = TextLoader(allowed_base_dir=Path(str(tmp_path)))
    chunker = RecursiveChunker()
    pipeline = IngestionPipeline(loader=loader, chunker=chunker)
    return RAGIngestTool(
        pipeline=pipeline,
        embedder=embedder,
        vectorstore=vectorstore,
        retriever=retriever,
    )


# ===================================================================
# RAGSearchTool
# ===================================================================


class TestRAGSearchTool:
    """Tests for RAGSearchTool."""

    def test_is_base_tool(self, search_tool: RAGSearchTool) -> None:
        """RAGSearchTool is a BaseTool subclass."""
        assert isinstance(search_tool, BaseTool)

    def test_name(self, search_tool: RAGSearchTool) -> None:
        """Tool name is 'rag_search'."""
        assert search_tool.name == "rag_search"

    def test_description(self, search_tool: RAGSearchTool) -> None:
        """Tool has a non-empty description."""
        assert len(search_tool.description) > 0

    def test_tier(self, search_tool: RAGSearchTool) -> None:
        """RAGSearchTool is tier 1 (requires embeddings)."""
        assert search_tool.tier == 1

    def test_parameters_schema(self, search_tool: RAGSearchTool) -> None:
        """Parameters include query (required) and top_k (optional)."""
        params = search_tool.parameters
        assert "query" in params
        assert params["query"]["required"] is True
        assert "top_k" in params
        assert params["top_k"]["required"] is False

    @pytest.mark.asyncio
    async def test_returns_rag_response(self, search_tool: RAGSearchTool) -> None:
        """Execute returns a ToolResult with RAGResponse data."""
        result = await search_tool.execute(query="Python programming")
        assert isinstance(result, ToolResult)
        assert result.success is True
        assert result.data is not None
        # Data should contain RAGResponse fields
        assert "query" in result.data
        assert "results" in result.data
        assert "total_results" in result.data

    @pytest.mark.asyncio
    async def test_valid_query_returns_results(
        self, search_tool: RAGSearchTool
    ) -> None:
        """A valid query against populated index returns matching results."""
        result = await search_tool.execute(query="Python data science")
        assert result.success is True
        assert result.data["total_results"] > 0
        assert len(result.data["results"]) > 0

    @pytest.mark.asyncio
    async def test_empty_results_for_unmatched_query(
        self,
        embedder: InMemoryEmbedder,
        vectorstore: InMemoryVectorStore,
    ) -> None:
        """Query against empty index returns success with zero results."""
        retriever = HybridRetriever(embedder=embedder, vectorstore=vectorstore)
        tool = RAGSearchTool(retriever=retriever)
        result = await tool.execute(query="something")
        assert result.success is True
        assert result.data["total_results"] == 0

    @pytest.mark.asyncio
    async def test_respects_top_k(self, search_tool: RAGSearchTool) -> None:
        """top_k parameter limits the number of returned results."""
        result = await search_tool.execute(query="programming", top_k=1)
        assert result.success is True
        assert len(result.data["results"]) <= 1

    @pytest.mark.asyncio
    async def test_default_top_k(self, search_tool: RAGSearchTool) -> None:
        """Default top_k is 5."""
        result = await search_tool.execute(query="programming")
        assert result.success is True
        # Should not exceed default of 5
        assert len(result.data["results"]) <= 5

    @pytest.mark.asyncio
    async def test_metadata_includes_query(self, search_tool: RAGSearchTool) -> None:
        """Result metadata includes the original query."""
        result = await search_tool.execute(query="Python")
        assert result.success is True
        assert result.data["query"] == "Python"

    def test_get_schema(self, search_tool: RAGSearchTool) -> None:
        """get_schema() returns a valid ToolSchema."""
        schema = search_tool.get_schema()
        assert schema.name == "rag_search"
        assert schema.tier == 1


# ===================================================================
# RAGIngestTool
# ===================================================================


class TestRAGIngestTool:
    """Tests for RAGIngestTool."""

    def test_is_base_tool(self, ingest_tool: RAGIngestTool) -> None:
        """RAGIngestTool is a BaseTool subclass."""
        assert isinstance(ingest_tool, BaseTool)

    def test_name(self, ingest_tool: RAGIngestTool) -> None:
        """Tool name is 'rag_ingest'."""
        assert ingest_tool.name == "rag_ingest"

    def test_description(self, ingest_tool: RAGIngestTool) -> None:
        """Tool has a non-empty description."""
        assert len(ingest_tool.description) > 0

    def test_tier(self, ingest_tool: RAGIngestTool) -> None:
        """RAGIngestTool is tier 1 (requires embeddings)."""
        assert ingest_tool.tier == 1

    def test_parameters_schema(self, ingest_tool: RAGIngestTool) -> None:
        """Parameters include source (required)."""
        params = ingest_tool.parameters
        assert "source" in params
        assert params["source"]["required"] is True

    @pytest.mark.asyncio
    async def test_ingests_file(
        self, ingest_tool: RAGIngestTool, tmp_path: object
    ) -> None:
        """Ingesting a valid file returns success with chunk count."""
        from pathlib import Path

        tmp = Path(str(tmp_path))
        test_file = tmp / "test.txt"
        test_file.write_text(
            "This is a test document with enough content to be chunked. "
            "It contains multiple sentences for the chunker to split.",
            encoding="utf-8",
        )

        result = await ingest_tool.execute(source=str(test_file))
        assert isinstance(result, ToolResult)
        assert result.success is True
        assert result.data is not None
        assert result.data["chunks_ingested"] > 0
        assert result.data["source"] == str(test_file)

    @pytest.mark.asyncio
    async def test_handles_missing_file(self, ingest_tool: RAGIngestTool) -> None:
        """Ingesting a non-existent file returns failure gracefully."""
        result = await ingest_tool.execute(source="/nonexistent/file.txt")
        assert result.success is False
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_handles_empty_file(
        self, ingest_tool: RAGIngestTool, tmp_path: object
    ) -> None:
        """Ingesting an empty file returns success with zero chunks."""
        from pathlib import Path

        tmp = Path(str(tmp_path))
        test_file = tmp / "empty.txt"
        test_file.write_text("", encoding="utf-8")

        result = await ingest_tool.execute(source=str(test_file))
        assert result.success is True
        assert result.data["chunks_ingested"] == 0

    def test_get_schema(self, ingest_tool: RAGIngestTool) -> None:
        """get_schema() returns a valid ToolSchema."""
        schema = ingest_tool.get_schema()
        assert schema.name == "rag_ingest"
        assert schema.tier == 1


# ===================================================================
# Registry Integration
# ===================================================================


class TestRAGToolRegistration:
    """Test that RAG tools can be registered in ToolRegistry."""

    def test_search_tool_registers(self, search_tool: RAGSearchTool) -> None:
        """RAGSearchTool can be registered and retrieved."""
        registry = ToolRegistry()
        registry.register(search_tool)
        assert "rag_search" in registry
        retrieved = registry.get("rag_search")
        assert retrieved is search_tool

    def test_ingest_tool_registers(self, ingest_tool: RAGIngestTool) -> None:
        """RAGIngestTool can be registered and retrieved."""
        registry = ToolRegistry()
        registry.register(ingest_tool)
        assert "rag_ingest" in registry
        retrieved = registry.get("rag_ingest")
        assert retrieved is ingest_tool

    def test_both_tools_listed(
        self,
        search_tool: RAGSearchTool,
        ingest_tool: RAGIngestTool,
    ) -> None:
        """Both RAG tools appear in registry listing."""
        registry = ToolRegistry()
        registry.register(search_tool)
        registry.register(ingest_tool)

        tools = registry.list_tools(tier=1)
        tool_names = [t.name for t in tools]
        assert "rag_search" in tool_names
        assert "rag_ingest" in tool_names
