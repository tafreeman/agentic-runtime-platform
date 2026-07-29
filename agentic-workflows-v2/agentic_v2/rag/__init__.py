"""RAG module — Retrieval-Augmented Generation pipeline.

Provides contracts, configuration, protocols, and implementations
for document ingestion, embedding, indexing, and retrieval.

Usage::

    from agentic_v2.rag import Document, Chunk, RAGConfig
    from agentic_v2.rag import InMemoryEmbedder, InMemoryVectorStore
    from agentic_v2.rag import HybridRetriever, BM25Index, TokenBudgetAssembler
    from agentic_v2.rag import RAGMemoryStore
    from agentic_v2.rag import RAGSearchTool, RAGIngestTool, RAGTracer
    from agentic_v2.rag import build_rag_components, RAGComponents
    from agentic_v2.rag.protocols import LoaderProtocol, EmbeddingProtocol

Optional backends:
    ``LiteLLMEmbedder`` and ``LanceDBVectorStore`` need the ``rag`` extra
    (``pip install -e ".[rag]"``).  Importing this package never requires it.
    ``LiteLLMEmbedder`` imports ``litellm`` lazily inside :meth:`embed`, and
    ``LanceDBVectorStore`` is exported as ``None`` when ``lancedb`` is absent
    (mirroring :mod:`agentic_v2.rag.vectorstore`).  Build components through
    :func:`build_vectorstore` / :func:`build_rag_components` to get a typed
    :class:`VectorStoreError` naming the missing extra instead of a
    ``TypeError`` from calling ``None``.
"""

from .chunking import RecursiveChunker
from .config import ChunkingConfig, EmbeddingConfig, RAGConfig, RerankerConfig
from .context_assembly import TokenBudgetAssembler
from .contracts import Chunk, Document, RAGResponse, RetrievalResult
from .embeddings import FallbackEmbedder, InMemoryEmbedder, LiteLLMEmbedder
from .errors import (
    ChunkingError,
    EmbeddingError,
    IngestionError,
    RAGError,
    RetrievalError,
    VectorStoreError,
)
from .factory import (
    RAGComponents,
    build_embedder,
    build_rag_components,
    build_reranker,
    build_vectorstore,
)
from .ingestion import IngestionPipeline
from .loaders import MarkdownLoader, TextLoader
from .memory import RAGMemoryStore
from .protocols import (
    ChunkerProtocol,
    EmbeddingProtocol,
    LoaderProtocol,
    RerankerProtocol,
    VectorStoreProtocol,
)
from .reranking import CrossEncoderReranker, LLMReranker, NoOpReranker
from .retrieval import BM25Index, HybridRetriever
from .tools import RAGIngestTool, RAGSearchTool
from .tracing import RAGTracer
from .vectorstore import InMemoryVectorStore, LanceDBVectorStore

__all__ = [
    # Contracts
    "Document",
    "Chunk",
    "RetrievalResult",
    "RAGResponse",
    # Config
    "ChunkingConfig",
    "EmbeddingConfig",
    "RAGConfig",
    "RerankerConfig",
    # Ingestion
    "IngestionPipeline",
    "RecursiveChunker",
    "MarkdownLoader",
    "TextLoader",
    # Retrieval
    "BM25Index",
    "HybridRetriever",
    # Reranking
    "NoOpReranker",
    "CrossEncoderReranker",
    "LLMReranker",
    # Context Assembly
    "TokenBudgetAssembler",
    # Embeddings
    "InMemoryEmbedder",
    "FallbackEmbedder",
    "LiteLLMEmbedder",
    # Vector Store
    "InMemoryVectorStore",
    # ``None`` when the optional ``lancedb`` dependency is not installed.
    "LanceDBVectorStore",
    # Factory
    "RAGComponents",
    "build_embedder",
    "build_vectorstore",
    "build_reranker",
    "build_rag_components",
    # Memory
    "RAGMemoryStore",
    # Tools
    "RAGSearchTool",
    "RAGIngestTool",
    # Tracing
    "RAGTracer",
    # Protocols
    "LoaderProtocol",
    "ChunkerProtocol",
    "EmbeddingProtocol",
    "RerankerProtocol",
    "VectorStoreProtocol",
    # Errors
    "RAGError",
    "IngestionError",
    "ChunkingError",
    "EmbeddingError",
    "VectorStoreError",
    "RetrievalError",
]
