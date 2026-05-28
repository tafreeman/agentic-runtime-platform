"""Core memory abstractions -- protocol and in-memory implementation.

Provides:
- :class:`MemoryStoreProtocol`: Async interface for persistent memory backends.
- :class:`InMemoryStore`: Simple dict-backed implementation for testing/dev.

The ``MemoryStoreProtocol`` is designed for **cross-session persistent memory**,
distinct from :class:`ConversationMemory` in ``agents/base.py`` which handles
ephemeral conversation-scoped message history.

Usage::

    from agentic_v2.core.memory import MemoryStoreProtocol, InMemoryStore

    store = InMemoryStore()
    await store.store("fact:1", "Python was created by Guido", metadata={"source": "wiki"})
    result = await store.retrieve("fact:1")
    matches = await store.search("Python", top_k=5)
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@runtime_checkable
class MemoryStoreProtocol(Protocol):
    """Interface for memory storage backends.

    All methods are async to support both in-memory and remote backends
    (databases, vector stores, etc.) through the same interface.

    Implementations must support:
    - Key-value CRUD (store, retrieve, delete)
    - Query-based search with ranked results
    - Key enumeration with optional prefix filtering
    """

    async def store(
        self,
        key: str,
        value: Any,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Store a value with optional metadata.

        Args:
            key: Unique identifier for the memory entry.
            value: The value to store (any serializable type).
            metadata: Optional key-value metadata for the entry.
        """
        ...

    async def retrieve(self, key: str) -> Any | None:
        """Retrieve a value by key.

        Args:
            key: The key to look up.

        Returns:
            The stored value, or ``None`` if the key does not exist.
        """
        ...

    async def search(
        self,
        query: str,
        *,
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        """Search memory by query string.

        Args:
            query: Search query (substring or semantic, depending on backend).
            top_k: Maximum number of results to return.

        Returns:
            List of dicts with keys: ``key``, ``value``, ``score``, ``metadata``.
        """
        ...

    async def delete(self, key: str) -> bool:
        """Delete a memory entry.

        Args:
            key: The key to delete.

        Returns:
            ``True`` if the entry existed and was deleted, ``False`` otherwise.
        """
        ...

    async def list_keys(self, *, prefix: str | None = None) -> list[str]:
        """List all keys, optionally filtered by prefix.

        Args:
            prefix: If provided, only return keys starting with this prefix.

        Returns:
            List of matching keys.
        """
        ...


@dataclass(frozen=True)
class _MemoryEntry:
    """Internal storage record for InMemoryStore."""

    value: Any
    metadata: dict[str, Any]
    timestamp: float
    order: int


class InMemoryStore:
    """Simple in-memory implementation of MemoryStoreProtocol.

    Uses dict storage with basic substring search.  All methods are async
    to satisfy :class:`MemoryStoreProtocol`, even though the underlying
    operations are synchronous.

    Search performs case-insensitive substring matching on ``str(value)``
    and returns matches sorted by timestamp descending (newest first).

    Suitable for testing and development.  Not suitable for production
    workloads requiring persistence or semantic search.
    """

    def __init__(self) -> None:
        """Initialize an empty in-memory store with a monotonic sequence counter."""
        self._entries: dict[str, _MemoryEntry] = {}
        self._sequence = 0

    async def store(
        self,
        key: str,
        value: Any,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Store a value with optional metadata.

        If the key already exists, it is overwritten.

        Args:
            key: Unique identifier for the memory entry.
            value: The value to store.
            metadata: Optional key-value metadata.
        """
        self._sequence += 1
        self._entries[key] = _MemoryEntry(
            value=value,
            metadata=metadata if metadata is not None else {},
            timestamp=time.time(),
            order=self._sequence,
        )
        logger.debug("Stored memory entry: key=%s", key)

    async def retrieve(self, key: str) -> Any | None:
        """Retrieve a value by key.

        Args:
            key: The key to look up.

        Returns:
            The stored value, or ``None`` if not found.
        """
        entry = self._entries.get(key)
        if entry is None:
            return None
        return entry.value

    async def search(
        self,
        query: str,
        *,
        top_k: int = 5,
    ) -> list[dict[str, Any]]:
        """Search memory by case-insensitive substring on str(value).

        Args:
            query: Substring to search for in stored values.
            top_k: Maximum number of results to return.

        Returns:
            List of dicts ``{key, value, score, metadata}`` sorted by
            timestamp descending (newest first).
        """
        query_lower = query.lower()
        matches: list[tuple[str, _MemoryEntry]] = []

        for key, entry in self._entries.items():
            value_str = str(entry.value).lower()
            if query_lower in value_str:
                matches.append((key, entry))

        # Sort by timestamp descending (newest first)
        matches.sort(key=lambda pair: (pair[1].timestamp, pair[1].order), reverse=True)

        results: list[dict[str, Any]] = []
        for key, entry in matches[:top_k]:
            results.append(
                {
                    "key": key,
                    "value": entry.value,
                    "score": 1.0,
                    "metadata": dict(entry.metadata),
                }
            )

        return results

    async def delete(self, key: str) -> bool:
        """Delete a memory entry.

        Args:
            key: The key to delete.

        Returns:
            ``True`` if the entry existed and was deleted.
        """
        if key in self._entries:
            del self._entries[key]
            logger.debug("Deleted memory entry: key=%s", key)
            return True
        return False

    async def list_keys(self, *, prefix: str | None = None) -> list[str]:
        """List all keys, optionally filtered by prefix.

        Args:
            prefix: If provided, only return keys starting with this prefix.

        Returns:
            List of matching keys.
        """
        keys = list(self._entries.keys())
        if prefix is not None:
            keys = [k for k in keys if k.startswith(prefix)]
        return keys
