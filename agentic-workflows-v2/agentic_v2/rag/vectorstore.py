"""RAG vector store implementations.

Provides:
- :class:`InMemoryVectorStore`: Pure-Python cosine similarity vector store
  for testing and small-scale development.
- :class:`LanceDBVectorStore`: Persistent vector store backed by LanceDB.
  Requires the ``lancedb`` optional dependency (``pip install .[rag]``).
  ``LanceDBVectorStore`` is ``None`` when lancedb is not installed.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from .contracts import Chunk, RetrievalResult

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _StoredEntry:
    """Internal storage record pairing a chunk with its embedding."""

    chunk: Chunk
    embedding: tuple[float, ...]


class InMemoryVectorStore:
    """Pure-Python in-memory vector store using cosine similarity.

    Stores chunks and their embeddings in a dict keyed by chunk_id.
    Searches compute cosine similarity against all stored embeddings
    and return the top-k matches.

    Suitable for testing and small-scale development.  Not suitable
    for production workloads.

    Satisfies :class:`VectorStoreProtocol`.
    """

    def __init__(self) -> None:
        self._entries: dict[str, _StoredEntry] = {}
        self._expected_dimensions: int | None = None

    async def add(self, chunks: list[Chunk], embeddings: list[list[float]]) -> None:
        """Add chunks with their embeddings to the store.

        Args:
            chunks: Chunks to store.
            embeddings: Corresponding embedding vectors (one per chunk).

        Raises:
            ValueError: If *chunks* and *embeddings* have different lengths.
        """
        if len(chunks) != len(embeddings):
            raise ValueError(
                f"chunks and embeddings must have the same length, "
                f"got {len(chunks)} chunks and {len(embeddings)} embeddings"
            )
        for chunk, embedding in zip(chunks, embeddings):
            if self._expected_dimensions is None and embedding:
                self._expected_dimensions = len(embedding)
            if (
                self._expected_dimensions is not None
                and len(embedding) != self._expected_dimensions
            ):
                raise ValueError(
                    f"Embedding dimension mismatch: expected "
                    f"{self._expected_dimensions}, got {len(embedding)} "
                    f"for chunk {chunk.chunk_id}"
                )
            self._entries[chunk.chunk_id] = _StoredEntry(
                chunk=chunk,
                embedding=tuple(embedding),
            )

    async def search(
        self,
        query_embedding: list[float],
        top_k: int = 5,
        metadata_filter: dict[str, Any] | None = None,
        **kwargs: object,
    ) -> list[RetrievalResult]:
        """Search for similar chunks using cosine similarity.

        Args:
            query_embedding: The query vector.
            top_k: Maximum number of results to return.
            metadata_filter: Optional key-value filter.  Only chunks
                whose metadata contains all specified key-value pairs
                are included in results.

        Returns:
            Ranked list of :class:`RetrievalResult`, highest score first.
        """
        if not self._entries:
            return []

        # Snapshot to avoid RuntimeError if entries mutate during iteration
        entries_snapshot = list(self._entries.values())

        scored: list[tuple[float, _StoredEntry]] = []
        for entry in entries_snapshot:
            # Apply metadata filter if provided
            if metadata_filter and not _matches_filter(
                entry.chunk.metadata, metadata_filter
            ):
                continue

            similarity = _cosine_similarity(query_embedding, entry.embedding)
            # Clamp to [0.0, 1.0] — negative cosine means opposing vectors
            score = max(0.0, similarity)
            scored.append((score, entry))

        # Sort descending by score
        scored.sort(key=lambda pair: pair[0], reverse=True)

        results: list[RetrievalResult] = []
        for score, entry in scored[:top_k]:
            results.append(
                RetrievalResult(
                    content=entry.chunk.content,
                    score=score,
                    document_id=entry.chunk.document_id,
                    chunk_id=entry.chunk.chunk_id,
                    metadata=dict(entry.chunk.metadata),
                )
            )
        return results

    async def delete(self, document_id: str) -> bool:
        """Delete all chunks for a document.

        Args:
            document_id: The document whose chunks should be removed.

        Returns:
            True if any chunks were deleted, False otherwise.
        """
        to_remove = [
            chunk_id
            for chunk_id, entry in self._entries.items()
            if entry.chunk.document_id == document_id
        ]
        if not to_remove:
            return False
        for chunk_id in to_remove:
            del self._entries[chunk_id]
        logger.info(
            "Deleted %d chunks for document_id=%s",
            len(to_remove),
            document_id,
        )
        return True


def _cosine_similarity(vec_a: Sequence[float], vec_b: Sequence[float]) -> float:
    """Compute cosine similarity between two vectors.

    Returns a value in [-1.0, 1.0].  Returns 0.0 if either vector
    has zero magnitude.

    Raises:
        ValueError: If vectors have different dimensions.
    """
    if len(vec_a) != len(vec_b):
        raise ValueError(f"Vector dimension mismatch: {len(vec_a)} vs {len(vec_b)}")
    dot = sum(a * b for a, b in zip(vec_a, vec_b))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (norm_a * norm_b)


def _matches_filter(metadata: dict[str, Any], filter_dict: dict[str, Any]) -> bool:
    """Check if metadata contains all key-value pairs from filter_dict.

    Supports exact value matching.  A missing key in metadata means the
    filter is not satisfied.
    """
    for key, value in filter_dict.items():
        if key not in metadata or metadata[key] != value:
            return False
    return True


# ---------------------------------------------------------------------------
# LanceDB persistent vector store
# ---------------------------------------------------------------------------

try:
    import lancedb
    import pyarrow as pa

    _LANCEDB_AVAILABLE = True
except ImportError:
    _LANCEDB_AVAILABLE = False

if _LANCEDB_AVAILABLE:

    class LanceDBVectorStore:
        """Persistent vector store backed by LanceDB (cosine similarity).

        Stores chunks and their embeddings in a LanceDB table on disk.
        Searches use cosine distance and return results as
        :class:`RetrievalResult` objects identical to
        :class:`InMemoryVectorStore`.

        Requires the ``lancedb`` optional dependency.

        Satisfies :class:`VectorStoreProtocol`.
        """

        def __init__(
            self,
            db_path: Path | str,
            table_name: str = "chunks",
            embedding_dim: int = 1536,
        ) -> None:
            self._db_path = str(db_path)
            self._table_name = table_name
            self._embedding_dim = embedding_dim
            self._db: lancedb.DBConnection = lancedb.connect(self._db_path)
            self._table: lancedb.table.Table | None = None

            # Reattach if the table already exists (persistence).
            if self._table_name in self._db.list_tables().tables:
                self._table = self._db.open_table(self._table_name)

        def _get_schema(self) -> pa.Schema:
            """Build the PyArrow schema for the chunks table."""
            return pa.schema(
                [
                    pa.field("chunk_id", pa.string()),
                    pa.field("doc_id", pa.string()),
                    pa.field("text", pa.string()),
                    pa.field("content_hash", pa.string()),
                    pa.field("metadata_json", pa.string()),
                    pa.field(
                        "vector",
                        pa.list_(pa.float32(), self._embedding_dim),
                    ),
                ]
            )

        def _ensure_table(self) -> lancedb.table.Table:
            """Create the table lazily on first write."""
            if self._table is None:
                self._table = self._db.create_table(
                    self._table_name, schema=self._get_schema()
                )
            return self._table

        def _existing_hashes(self) -> set[str]:
            """Return the set of content_hash values already stored."""
            if self._table is None:
                return set()
            col = self._table.to_arrow().column("content_hash")
            return set(col.to_pylist())

        # -- public interface (VectorStoreProtocol) -------------------------

        async def add(
            self,
            chunks: list[Chunk],
            embeddings: list[list[float]],
        ) -> None:
            """Add chunks with their embeddings, deduplicating by content_hash.

            Args:
                chunks: Chunks to store.
                embeddings: Corresponding embedding vectors.

            Raises:
                ValueError: If *chunks* and *embeddings* differ in length.
            """
            if len(chunks) != len(embeddings):
                raise ValueError(
                    f"chunks and embeddings must have the same length, "
                    f"got {len(chunks)} chunks and {len(embeddings)} embeddings"
                )

            existing = await asyncio.to_thread(self._existing_hashes)
            records: list[dict[str, Any]] = []
            for chunk, emb in zip(chunks, embeddings):
                if chunk.content_hash in existing:
                    logger.debug(
                        "Skipping duplicate content_hash=%s",
                        chunk.content_hash,
                    )
                    continue
                existing.add(chunk.content_hash)
                records.append(
                    {
                        "chunk_id": chunk.chunk_id,
                        "doc_id": chunk.document_id,
                        "text": chunk.content,
                        "content_hash": chunk.content_hash,
                        "metadata_json": json.dumps(chunk.metadata),
                        "vector": [float(v) for v in emb],
                    }
                )

            if not records:
                return

            def _write() -> None:
                tbl = self._ensure_table()
                tbl.add(records)

            await asyncio.to_thread(_write)
            logger.info("Added %d chunks to LanceDB table.", len(records))

        async def search(
            self,
            query_embedding: list[float],
            top_k: int = 5,
            metadata_filter: dict[str, Any] | None = None,  # protocol-required
            **kwargs: Any,
        ) -> list[RetrievalResult]:
            """Search for similar chunks using cosine distance.

            Args:
                query_embedding: The query vector.
                top_k: Maximum number of results to return.
                metadata_filter: Accepted for VectorStoreProtocol
                    compatibility.  Not yet implemented for LanceDB;
                    pass ``None`` or omit.

            Returns:
                Ranked list of :class:`RetrievalResult`, highest score first.
            """
            if self._table is None:
                return []

            def _query() -> list[dict[str, Any]]:
                return (
                    self._table.search(query_embedding)  # type: ignore[union-attr]
                    .metric("cosine")
                    .limit(top_k)
                    .to_list()
                )

            raw = await asyncio.to_thread(_query)
            results: list[RetrievalResult] = []
            for row in raw:
                score = max(0.0, 1.0 - float(row["_distance"]))
                meta = json.loads(row.get("metadata_json", "{}"))
                results.append(
                    RetrievalResult(
                        content=row["text"],
                        score=score,
                        document_id=row["doc_id"],
                        chunk_id=row["chunk_id"],
                        metadata=meta,
                    )
                )
            return results

        async def delete(self, document_id: str) -> bool:
            """Delete all chunks for a document.

            Args:
                document_id: The document whose chunks should be removed.

            Returns:
                True if any chunks were deleted, False otherwise.
            """
            if self._table is None:
                return False

            count_before = self._table.count_rows()

            def _delete() -> None:
                self._table.delete(f"doc_id = '{document_id}'")  # type: ignore[union-attr]

            await asyncio.to_thread(_delete)
            count_after = self._table.count_rows()
            removed = count_before - count_after
            if removed > 0:
                logger.info(
                    "Deleted %d chunks for document_id=%s",
                    removed,
                    document_id,
                )
                return True
            return False

        def __len__(self) -> int:
            """Return the number of stored chunks."""
            if self._table is None:
                return 0
            return self._table.count_rows()

else:
    LanceDBVectorStore = None  # type: ignore[assignment,misc]
