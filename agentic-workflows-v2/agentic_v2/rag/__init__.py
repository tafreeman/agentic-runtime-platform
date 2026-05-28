"""RAG module — Retrieval-Augmented Generation pipeline.

Provides contracts, configuration, protocols, and implementations
for document ingestion, embedding, indexing, and retrieval.

Usage::

    from agentic_v2.rag import Document, Chunk, RAGConfig
    from agentic_v2.rag import InMemoryEmbedder, InMemoryVectorStore
    from agentic_v2.rag import HybridRetriever, BM25Index, TokenBudgetAssembler
    from agentic_v2.rag import RAGMemoryStore
    from agentic_v2.rag import RAGSearchTool, RAGIngestTool, RAGTracer
    from agentic_v2.rag.protocols import LoaderProtocol, EmbeddingProtocol
"""

from .chunking import RecursiveChunker
from .config import ChunkingConfig, EmbeddingConfig, RAGConfig, RerankerConfig
from .context_assembly import TokenBudgetAssembler
from .contracts import Chunk, Document, RAGResponse, RetrievalResult
from .embeddings import FallbackEmbedder, InMemoryEmbedder
from .errors import (
    ChunkingError,
    EmbeddingError,
    IngestionError,
    RAGError,
    RetrievalError,
    VectorStoreError,
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
from .retrieval import BM25Index, HybridRetriever
from .tools import RAGIngestTool, RAGSearchTool
from .tracing import RAGTracer
from .vectorstore import InMemoryVectorStore

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
    # Context Assembly
    "TokenBudgetAssembler",
    # Embeddings
    "InMemoryEmbedder",
    "FallbackEmbedder",
    # Vector Store
    "InMemoryVectorStore",
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
