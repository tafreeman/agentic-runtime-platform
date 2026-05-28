"""Protocol conformance tests — verify all runtime_checkable protocols.

Tests every concrete implementation against its structural protocol via
``isinstance``, following the TDD conformance pattern established in
``test_core_protocols.py``.

Covered protocols:
- Core: AgentProtocol, ToolProtocol, MemoryStoreProtocol (MemoryStore alias)
- RAG:  LoaderProtocol, ChunkerProtocol, EmbeddingProtocol, VectorStoreProtocol

Each section has:
1. Positive tests — concrete implementations satisfy the protocol.
2. Negative tests — near-miss classes that are missing one required method
   or property do NOT satisfy the protocol.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# TestRAGProtocolConformance
# ---------------------------------------------------------------------------


class TestRAGProtocolConformance:
    """Verify RAG protocol conformance for all concrete RAG implementations."""

    # -- LoaderProtocol -------------------------------------------------------

    def test_markdown_loader_satisfies_loader_protocol(self):
        from agentic_v2.rag import MarkdownLoader
        from agentic_v2.rag.protocols import LoaderProtocol

        assert isinstance(MarkdownLoader(), LoaderProtocol)

    def test_text_loader_satisfies_loader_protocol(self):
        from agentic_v2.rag import TextLoader
        from agentic_v2.rag.protocols import LoaderProtocol

        assert isinstance(TextLoader(), LoaderProtocol)

    # -- ChunkerProtocol -------------------------------------------------------

    def test_recursive_chunker_satisfies_chunker_protocol(self):
        from agentic_v2.rag import RecursiveChunker
        from agentic_v2.rag.protocols import ChunkerProtocol

        assert isinstance(RecursiveChunker(), ChunkerProtocol)

    # -- EmbeddingProtocol ----------------------------------------------------

    def test_in_memory_embedder_satisfies_embedding_protocol(self):
        from agentic_v2.rag import InMemoryEmbedder
        from agentic_v2.rag.protocols import EmbeddingProtocol

        assert isinstance(InMemoryEmbedder(), EmbeddingProtocol)

    def test_in_memory_embedder_custom_dims_satisfies_embedding_protocol(self):
        """Dimensionality change must not break protocol conformance."""
        from agentic_v2.rag import InMemoryEmbedder
        from agentic_v2.rag.protocols import EmbeddingProtocol

        assert isinstance(InMemoryEmbedder(dimensions=128), EmbeddingProtocol)

    def test_fallback_embedder_satisfies_embedding_protocol(self):
        from agentic_v2.rag import FallbackEmbedder, InMemoryEmbedder
        from agentic_v2.rag.protocols import EmbeddingProtocol

        primary = InMemoryEmbedder(dimensions=64)
        fallback = FallbackEmbedder(providers=[primary])
        assert isinstance(fallback, EmbeddingProtocol)

    def test_fallback_embedder_multi_provider_satisfies_embedding_protocol(self):
        """FallbackEmbedder with two providers must still satisfy the protocol."""
        from agentic_v2.rag import FallbackEmbedder, InMemoryEmbedder
        from agentic_v2.rag.protocols import EmbeddingProtocol

        providers = [InMemoryEmbedder(dimensions=256), InMemoryEmbedder(dimensions=256)]
        assert isinstance(FallbackEmbedder(providers=providers), EmbeddingProtocol)

    # -- VectorStoreProtocol --------------------------------------------------

    def test_in_memory_vector_store_satisfies_vectorstore_protocol(self):
        from agentic_v2.rag import InMemoryVectorStore
        from agentic_v2.rag.protocols import VectorStoreProtocol

        assert isinstance(InMemoryVectorStore(), VectorStoreProtocol)


# ---------------------------------------------------------------------------
# TestAgentProtocolConformance
# ---------------------------------------------------------------------------


class TestAgentProtocolConformance:
    """Verify AgentProtocol is satisfied by a minimal concrete subclass."""

    def test_minimal_agent_subclass_satisfies_agent_protocol(self):
        """A class with `name` property and async `run` satisfies AgentProtocol."""
        from agentic_v2.core.protocols import AgentProtocol

        class _MinimalAgent:
            @property
            def name(self) -> str:
                return "minimal-agent"

            async def run(self, input_data, ctx=None):
                return {"status": "ok"}

        assert isinstance(_MinimalAgent(), AgentProtocol)

    def test_agent_with_extra_methods_satisfies_agent_protocol(self):
        """Extra public methods must not break structural conformance."""
        from agentic_v2.core.protocols import AgentProtocol

        class _RichAgent:
            @property
            def name(self) -> str:
                return "rich-agent"

            async def run(self, input_data, ctx=None):
                return {}

            async def health_check(self) -> bool:
                return True

        assert isinstance(_RichAgent(), AgentProtocol)

    def test_agent_missing_name_fails(self):
        """An agent without `name` property must not satisfy AgentProtocol."""
        from agentic_v2.core.protocols import AgentProtocol

        class _NoName:
            async def run(self, input_data, ctx=None):
                return {}

        assert not isinstance(_NoName(), AgentProtocol)

    def test_agent_missing_run_fails(self):
        """An agent without `run` method must not satisfy AgentProtocol."""
        from agentic_v2.core.protocols import AgentProtocol

        class _NoRun:
            @property
            def name(self) -> str:
                return "no-run"

        assert not isinstance(_NoRun(), AgentProtocol)


# ---------------------------------------------------------------------------
# TestToolProtocolConformance
# ---------------------------------------------------------------------------


class TestToolProtocolConformance:
    """Verify ToolProtocol is satisfied by built-in tool classes."""

    def test_file_read_tool_satisfies_tool_protocol(self):
        from agentic_v2.core.protocols import ToolProtocol
        from agentic_v2.tools.builtin.file_ops import FileReadTool

        assert isinstance(FileReadTool(), ToolProtocol)

    def test_file_write_tool_satisfies_tool_protocol(self):
        from agentic_v2.core.protocols import ToolProtocol
        from agentic_v2.tools.builtin.file_ops import FileWriteTool

        assert isinstance(FileWriteTool(), ToolProtocol)

    def test_http_tool_satisfies_tool_protocol(self):
        from agentic_v2.core.protocols import ToolProtocol
        from agentic_v2.tools.builtin.http_ops import HttpTool

        assert isinstance(HttpTool(), ToolProtocol)

    def test_search_tool_satisfies_tool_protocol(self):
        from agentic_v2.core.protocols import ToolProtocol
        from agentic_v2.tools.builtin.search_ops import SearchTool

        assert isinstance(SearchTool(), ToolProtocol)

    def test_git_status_tool_satisfies_tool_protocol(self):
        from agentic_v2.core.protocols import ToolProtocol
        from agentic_v2.tools.builtin.git_ops import GitStatusTool

        assert isinstance(GitStatusTool(), ToolProtocol)

    def test_tool_missing_description_fails(self):
        from agentic_v2.core.protocols import ToolProtocol

        class _NoDescription:
            @property
            def name(self) -> str:
                return "no-desc"

            async def execute(self, **kwargs):
                return "done"

        assert not isinstance(_NoDescription(), ToolProtocol)

    def test_tool_missing_execute_fails(self):
        from agentic_v2.core.protocols import ToolProtocol

        class _NoExecute:
            @property
            def name(self) -> str:
                return "no-exec"

            @property
            def description(self) -> str:
                return "missing execute"

        assert not isinstance(_NoExecute(), ToolProtocol)


# ---------------------------------------------------------------------------
# TestMemoryStoreConformance
# ---------------------------------------------------------------------------


class TestMemoryStoreConformance:
    """Verify MemoryStoreProtocol conformance for InMemoryStore and RAGMemoryStore."""

    def test_in_memory_store_satisfies_memory_store_protocol(self):
        from agentic_v2.core.memory import InMemoryStore, MemoryStoreProtocol

        assert isinstance(InMemoryStore(), MemoryStoreProtocol)

    def test_in_memory_store_satisfies_memory_store_alias(self):
        """The MemoryStore alias exported from core.protocols must match."""
        from agentic_v2.core.memory import InMemoryStore
        from agentic_v2.core.protocols import MemoryStore

        assert isinstance(InMemoryStore(), MemoryStore)

    def test_rag_memory_store_satisfies_memory_store_protocol(self):
        from agentic_v2.core.memory import MemoryStoreProtocol
        from agentic_v2.rag import InMemoryEmbedder, InMemoryVectorStore
        from agentic_v2.rag.memory import RAGMemoryStore

        store = RAGMemoryStore(
            embedder=InMemoryEmbedder(),
            vectorstore=InMemoryVectorStore(),
        )
        assert isinstance(store, MemoryStoreProtocol)

    def test_rag_memory_store_satisfies_memory_store_alias(self):
        """RAGMemoryStore must also satisfy the backward-compat MemoryStore alias."""
        from agentic_v2.core.protocols import MemoryStore
        from agentic_v2.rag import InMemoryEmbedder, InMemoryVectorStore
        from agentic_v2.rag.memory import RAGMemoryStore

        store = RAGMemoryStore(
            embedder=InMemoryEmbedder(dimensions=64),
            vectorstore=InMemoryVectorStore(),
            namespace="test",
        )
        assert isinstance(store, MemoryStore)

    def test_memory_store_missing_list_keys_fails(self):
        from agentic_v2.core.memory import MemoryStoreProtocol

        class _Incomplete:
            async def store(self, key, value, *, metadata=None):
                pass

            async def retrieve(self, key):
                return None

            async def search(self, query, *, top_k=5):
                return []

            async def delete(self, key):
                return False

            # list_keys deliberately omitted

        assert not isinstance(_Incomplete(), MemoryStoreProtocol)

    def test_memory_store_missing_delete_fails(self):
        from agentic_v2.core.memory import MemoryStoreProtocol

        class _NoDelete:
            async def store(self, key, value, *, metadata=None):
                pass

            async def retrieve(self, key):
                return None

            async def search(self, query, *, top_k=5):
                return []

            async def list_keys(self, *, prefix=None):
                return []

            # delete deliberately omitted

        assert not isinstance(_NoDelete(), MemoryStoreProtocol)


# ---------------------------------------------------------------------------
# TestNegativeCases
# ---------------------------------------------------------------------------


class TestNegativeCases:
    """Near-miss classes that are one method/property short of a protocol.

    One negative test per RAG protocol to confirm the protocol boundary
    is enforced precisely.
    """

    def test_loader_missing_supported_extensions_fails(self):
        """LoaderProtocol requires both `load` and `supported_extensions`."""
        from agentic_v2.rag.protocols import LoaderProtocol

        class _LoadOnly:
            async def load(self, source: str, **kwargs):
                return []

            # supported_extensions deliberately omitted

        assert not isinstance(_LoadOnly(), LoaderProtocol)

    def test_loader_missing_load_fails(self):
        """LoaderProtocol without `load` must not conform."""
        from agentic_v2.rag.protocols import LoaderProtocol

        class _ExtensionsOnly:
            @property
            def supported_extensions(self):
                return [".md"]

            # load deliberately omitted

        assert not isinstance(_ExtensionsOnly(), LoaderProtocol)

    def test_chunker_missing_chunk_fails(self):
        """ChunkerProtocol requires the `chunk` method."""
        from agentic_v2.rag.protocols import ChunkerProtocol

        class _NotAChunker:
            def split(self, document, config=None):
                return []

            # chunk deliberately omitted — wrong name

        assert not isinstance(_NotAChunker(), ChunkerProtocol)

    def test_embedding_missing_dimensions_fails(self):
        """EmbeddingProtocol requires both `embed` and `dimensions`."""
        from agentic_v2.rag.protocols import EmbeddingProtocol

        class _EmbedOnly:
            async def embed(self, texts):
                return [[0.0] * 4 for _ in texts]

            # dimensions property deliberately omitted

        assert not isinstance(_EmbedOnly(), EmbeddingProtocol)

    def test_embedding_missing_embed_fails(self):
        """EmbeddingProtocol without `embed` must not conform."""
        from agentic_v2.rag.protocols import EmbeddingProtocol

        class _DimensionsOnly:
            @property
            def dimensions(self) -> int:
                return 128

            # embed deliberately omitted

        assert not isinstance(_DimensionsOnly(), EmbeddingProtocol)

    def test_vectorstore_missing_add_fails(self):
        """VectorStoreProtocol requires `add`, `search`, and `delete`."""
        from agentic_v2.rag.protocols import VectorStoreProtocol

        class _NoAdd:
            async def search(
                self, query_embedding, top_k=5, metadata_filter=None, **kw
            ):
                return []

            async def delete(self, document_id: str) -> bool:
                return False

            # add deliberately omitted

        assert not isinstance(_NoAdd(), VectorStoreProtocol)

    def test_vectorstore_missing_delete_fails(self):
        """VectorStoreProtocol without `delete` must not conform."""
        from agentic_v2.rag.protocols import VectorStoreProtocol

        class _NoDelete:
            async def add(self, chunks, embeddings):
                pass

            async def search(
                self, query_embedding, top_k=5, metadata_filter=None, **kw
            ):
                return []

            # delete deliberately omitted

        assert not isinstance(_NoDelete(), VectorStoreProtocol)

    def test_vectorstore_missing_search_fails(self):
        """VectorStoreProtocol without `search` must not conform."""
        from agentic_v2.rag.protocols import VectorStoreProtocol

        class _NoSearch:
            async def add(self, chunks, embeddings):
                pass

            async def delete(self, document_id: str) -> bool:
                return False

            # search deliberately omitted

        assert not isinstance(_NoSearch(), VectorStoreProtocol)
