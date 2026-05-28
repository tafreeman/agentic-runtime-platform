"""RAG-backed memory store -- semantic search powered by vector embeddings.

Provides :class:`RAGMemoryStore`, a :class:`MemoryStoreProtocol` implementation
that uses a vector store and embedding provider for semantic similarity search
over stored memories.

Usage::

    from agentic_v2.rag import InMemoryEmbedder, InMemoryVectorStore
    from agentic_v2.rag.memory import RAGMemoryStore

    store = RAGMemoryStore(
        embedder=InMemoryEmbedder(dimensions=384),
        vectorstore=InMemoryVectorStore(),
        namespace="agent-memory",
    )
    await store.store("fact1", "Python was created by Guido van Rossum")
    results = await store.search("Who created Python?", top_k=3)
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from .contracts import Chunk, RetrievalResult
from .protocols import EmbeddingProtocol, VectorStoreProtocol

logger = logging.getLogger(__name__)


class RAGMemoryStore:
    """Semantic search backed memory store using RAG vectorstore.

    Satisfies :class:`MemoryStoreProtocol`.  Stores values as chunks in a
    vectorstore and uses embedding-based search for retrieval.

    Each stored entry becomes a :class:`Chunk` in the vectorstore.  The
    key-to-chunk mapping is maintained internally so that ``retrieve()``
    can look up entries by key without a vector search.

    Args:
        embedder: Embedding provider for encoding text to vectors.
        vectorstore: Vector store backend for storing and searching embeddings.
        namespace: Namespace prefix for document IDs (default ``"memory"``).
    """

    def __init__(
        self,
        embedder: EmbeddingProtocol,
        vectorstore: VectorStoreProtocol,
        *,
        namespace: str = "memory",
    ) -> None:
        self._embedder = embedder
        self._vectorstore = vectorstore
        self._namespace = namespace
        # key -> (document_id, value, metadata)
        self._key_map: dict[str, tuple[str, Any, dict[str, Any]]] = {}

    async def store(
        self,
        key: str,
        value: Any,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Store a value by embedding it into the vector store.

        Creates a :class:`Chunk` from the value text, embeds it, and
        adds it to the vector store.  If the key already exists, the
        old entry is deleted first.

        Args:
            key: Unique identifier for the memory entry.
            value: The value to store (converted to string for embedding).
            metadata: Optional key-value metadata.
        """
        resolved_metadata = metadata if metadata is not None else {}

        # Delete existing entry if overwriting
        if key in self._key_map:
            await self.delete(key)

        doc_id = f"{self._namespace}:{uuid.uuid4().hex}"
        chunk = Chunk(
            document_id=doc_id,
            chunk_index=0,
            content=str(value),
            metadata={**resolved_metadata, "_memory_key": key},
        )

        embeddings = await self._embedder.embed([chunk.content])
        await self._vectorstore.add([chunk], embeddings)

        self._key_map[key] = (doc_id, value, resolved_metadata)
        logger.debug("Stored RAG memory entry: key=%s, doc_id=%s", key, doc_id)

    async def retrieve(self, key: str) -> Any | None:
        """Retrieve a value by key from the internal mapping.

        Args:
            key: The key to look up.

        Returns:
            The stored value, or ``None`` if the key does not exist.
        """
        entry = self._key_map.get(key)
        if entry is None:
            return None
        return entry[1]  # value

    async def search(
        self,
        query: str,
        *,
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        """Search memory using semantic similarity.

        Embeds the query and searches the vector store for the most
        similar stored entries.

        Args:
            query: Search query text.
            top_k: Maximum number of results to return.

        Returns:
            List of dicts ``{key, value, score, metadata}`` ranked by
            similarity score (highest first).
        """
        if not self._key_map:
            return []

        query_embedding = (await self._embedder.embed([query]))[0]
        retrieval_results: list[RetrievalResult] = await self._vectorstore.search(
            query_embedding, top_k=top_k
        )

        results: list[dict[str, Any]] = []
        for rr in retrieval_results:
            memory_key = rr.metadata.get("_memory_key")
            if memory_key is None:
                continue

            entry = self._key_map.get(memory_key)
            if entry is None:
                continue

            _, value, entry_metadata = entry
            results.append(
                {
                    "key": memory_key,
                    "value": value,
                    "score": rr.score,
                    "metadata": dict(entry_metadata),
                }
            )

        return results

    async def delete(self, key: str) -> bool:
        """Delete a memory entry from both the vector store and internal mapping.

        Args:
            key: The key to delete.

        Returns:
            ``True`` if the entry existed and was deleted.
        """
        entry = self._key_map.get(key)
        if entry is None:
            return False

        doc_id = entry[0]
        await self._vectorstore.delete(doc_id)
        del self._key_map[key]
        logger.debug("Deleted RAG memory entry: key=%s, doc_id=%s", key, doc_id)
        return True

    async def list_keys(self, *, prefix: str | None = None) -> list[str]:
        """List all keys from the internal mapping.

        Args:
            prefix: If provided, only return keys starting with this prefix.

        Returns:
            List of matching keys.
        """
        keys = list(self._key_map.keys())
        if prefix is not None:
            keys = [k for k in keys if k.startswith(prefix)]
        return keys
