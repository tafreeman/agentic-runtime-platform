#!/usr/bin/env python3
"""
Response Cache for LLM Evaluations
===================================

Provides content-hash based caching for LLM responses to avoid redundant API calls.
Uses SHA-256 hash of (prompt_content + model + system_prompt) as cache key.

Features:
- Deterministic caching based on input content
- Configurable TTL per cache type
- Thread-safe operations
- Persistent storage in ~/.cache/prompts-eval/responses/

Usage:
    from response_cache import ResponseCache

    cache = ResponseCache()

    # Check cache before API call
    cached = cache.get(prompt_content, model, system_prompt)
    if cached:
        response = cached
    else:
        response = call_llm(...)
        cache.set(prompt_content, model, system_prompt, response)
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import logging
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

logger = logging.getLogger(__name__)

# =============================================================================
# CONFIGURATION
# =============================================================================

# Cache TTLs
DEFAULT_TTL_HOURS = 24  # How long to keep cached responses
MAX_CACHE_SIZE_MB = 500  # Maximum cache size before cleanup


@dataclass
class CacheEntry:
    """A single cache entry."""

    key: str
    model: str
    response: str
    created_at: str
    prompt_hash: str
    hit_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "CacheEntry":
        return cls(**d)


# =============================================================================
# CACHE MANAGEMENT
# =============================================================================

_cache_lock = threading.Lock()


def get_cache_dir() -> Path:
    """Get the directory for response cache files."""
    cache_dir = Path.home() / ".cache" / "prompts-eval" / "responses"
    cache_dir.mkdir(parents=True, exist_ok=True)
    return cache_dir


def get_cache_index_file() -> Path:
    """Get the cache index file."""
    return get_cache_dir() / "cache_index.json"


def _compute_cache_key(prompt_content: str, model: str, system_prompt: str = "") -> str:
    """Compute a deterministic cache key from input content.

    Uses SHA-256 hash of combined inputs for unique identification.
    """
    combined = f"{model}||{system_prompt}||{prompt_content}"
    return hashlib.sha256(combined.encode("utf-8")).hexdigest()


def _get_entry_file(key: str) -> Path:
    """Get the file path for a cache entry."""
    # Use first 2 chars as subdirectory to avoid too many files in one dir
    subdir = get_cache_dir() / key[:2]
    subdir.mkdir(parents=True, exist_ok=True)
    return subdir / f"{key}.json"


class ResponseCache:
    """LLM Response Cache with content-based hashing.

    Thread-safe, persistent cache that stores LLM responses indexed by a
    hash of (model, system_prompt, prompt_content).
    """

    def __init__(
        self,
        enabled: bool = True,
        ttl_hours: float = DEFAULT_TTL_HOURS,
        verbose: bool = False,
    ):
        self.enabled = enabled
        self.ttl = timedelta(hours=ttl_hours)
        self.verbose = verbose
        self._index: dict[str, dict[str, Any]] = {}
        self._stats = {"hits": 0, "misses": 0, "writes": 0}

        if enabled:
            self._load_index()

    def _log(self, msg: str) -> None:
        if self.verbose:
            logger.debug(msg)

    def _load_index(self) -> None:
        """Load the cache index from disk."""
        index_file = get_cache_index_file()
        if index_file.exists():
            try:
                with open(index_file, encoding="utf-8") as f:
                    data = json.load(f)
                    self._index = data.get("entries", {})
                    self._log(f"Loaded {len(self._index)} cache entries")
            except Exception as e:
                self._log(f"Failed to load cache index: {e}")
                self._index = {}

    def _save_index(self) -> None:
        """Save the cache index to disk."""
        with _cache_lock:
            index_file = get_cache_index_file()
            try:
                data = {
                    "version": "1.0.0",
                    "updated_at": datetime.now().isoformat(),
                    "stats": self._stats,
                    "entries": self._index,
                }
                with open(index_file, "w", encoding="utf-8") as f:
                    json.dump(data, f, indent=2)
            except Exception as e:
                self._log(f"Failed to save cache index: {e}")

    def _is_expired(self, entry_meta: dict[str, Any]) -> bool:
        """Check if a cache entry has expired."""
        try:
            created = datetime.fromisoformat(entry_meta["created_at"])
            return datetime.now() - created > self.ttl
        except Exception:
            return True

    def get(
        self,
        prompt_content: str,
        model: str,
        system_prompt: str = "",
    ) -> str | None:
        """Get a cached response if available.

        Returns:
            The cached response string, or None if not cached/expired.
        """
        if not self.enabled:
            return None

        key = _compute_cache_key(prompt_content, model, system_prompt)

        # Check index first
        with _cache_lock:
            if key not in self._index:
                self._stats["misses"] += 1
                return None

            entry_meta = self._index[key]

            # Check expiration
            if self._is_expired(entry_meta):
                self._log(f"Cache expired for {key[:12]}...")
                del self._index[key]
                self._stats["misses"] += 1
                return None

        # Load full entry from disk
        entry_file = _get_entry_file(key)
        if not entry_file.exists():
            with _cache_lock:
                if key in self._index:
                    del self._index[key]
            self._stats["misses"] += 1
            return None

        try:
            with open(entry_file, encoding="utf-8") as f:
                entry = json.load(f)

            # Update hit count
            with _cache_lock:
                if key in self._index:
                    self._index[key]["hit_count"] = (
                        self._index[key].get("hit_count", 0) + 1
                    )
                self._stats["hits"] += 1

            self._log(f"Cache HIT for {model} ({key[:12]}...)")
            return entry.get("response")

        except Exception as e:
            self._log(f"Failed to read cache entry: {e}")
            self._stats["misses"] += 1
            return None

    def set(
        self,
        prompt_content: str,
        model: str,
        system_prompt: str,
        response: str,
    ) -> None:
        """Store a response in the cache.

        Args:
            prompt_content: The prompt text that was evaluated
            model: The model used for evaluation
            system_prompt: The system prompt used
            response: The LLM response to cache
        """
        if not self.enabled:
            return

        key = _compute_cache_key(prompt_content, model, system_prompt)
        prompt_hash = hashlib.sha256(prompt_content.encode("utf-8")).hexdigest()[:16]

        entry = {
            "key": key,
            "model": model,
            "response": response,
            "created_at": datetime.now().isoformat(),
            "prompt_hash": prompt_hash,
            "hit_count": 0,
        }

        # Save entry to disk
        entry_file = _get_entry_file(key)
        try:
            with open(entry_file, "w", encoding="utf-8") as f:
                json.dump(entry, f, indent=2, ensure_ascii=False)

            # Update index
            with _cache_lock:
                self._index[key] = {
                    "model": model,
                    "created_at": entry["created_at"],
                    "prompt_hash": prompt_hash,
                    "hit_count": 0,
                }
                self._stats["writes"] += 1

            self._log(f"Cache WRITE for {model} ({key[:12]}...)")

        except Exception as e:
            self._log(f"Failed to write cache entry: {e}")

    def invalidate(
        self, prompt_content: str, model: str, system_prompt: str = ""
    ) -> bool:
        """Invalidate a specific cache entry.

        Returns:
            True if an entry was invalidated, False otherwise.
        """
        key = _compute_cache_key(prompt_content, model, system_prompt)

        with _cache_lock:
            if key not in self._index:
                return False

            del self._index[key]

        # Remove file
        entry_file = _get_entry_file(key)
        if entry_file.exists():
            with contextlib.suppress(Exception):
                entry_file.unlink()

        return True

    def clear(self) -> int:
        """Clear all cache entries.

        Returns:
            Number of entries cleared.
        """
        count = len(self._index)

        with _cache_lock:
            self._index = {}
            self._stats = {"hits": 0, "misses": 0, "writes": 0}

        # Remove cache directory contents
        cache_dir = get_cache_dir()
        try:
            import shutil

            for item in cache_dir.iterdir():
                if item.is_dir():
                    shutil.rmtree(item)
                elif item.name != "cache_index.json":
                    item.unlink()
        except Exception:
            pass

        self._save_index()
        self._log(f"Cleared {count} cache entries")
        return count

    def cleanup_expired(self) -> int:
        """Remove expired cache entries.

        Returns:
            Number of entries removed.
        """
        expired_keys = []

        with _cache_lock:
            for key, meta in self._index.items():
                if self._is_expired(meta):
                    expired_keys.append(key)

        for key in expired_keys:
            entry_file = _get_entry_file(key)
            if entry_file.exists():
                with contextlib.suppress(Exception):
                    entry_file.unlink()

            with _cache_lock:
                if key in self._index:
                    del self._index[key]

        if expired_keys:
            self._save_index()
            self._log(f"Cleaned up {len(expired_keys)} expired entries")

        return len(expired_keys)

    def get_stats(self) -> dict[str, Any]:
        """Get cache statistics."""
        total_requests = self._stats["hits"] + self._stats["misses"]
        hit_rate = (
            (self._stats["hits"] / total_requests * 100) if total_requests > 0 else 0
        )

        return {
            "enabled": self.enabled,
            "entries": len(self._index),
            "hits": self._stats["hits"],
            "misses": self._stats["misses"],
            "writes": self._stats["writes"],
            "hit_rate": round(hit_rate, 1),
            "ttl_hours": self.ttl.total_seconds() / 3600,
        }

    def save(self) -> None:
        """Save the cache index to disk."""
        self._save_index()


# =============================================================================
# GLOBAL INSTANCE
# =============================================================================

# Global cache instance (disabled by default, enable with --cache flag)
_global_cache: ResponseCache | None = None


def get_cache(enabled: bool = False, **kwargs) -> ResponseCache:
    """Get or create the global cache instance.

    Args:
        enabled: Whether caching is enabled
        **kwargs: Additional arguments for ResponseCache
    """
    global _global_cache
    if _global_cache is None:
        _global_cache = ResponseCache(enabled=enabled, **kwargs)
    return _global_cache


def enable_cache(
    ttl_hours: float = DEFAULT_TTL_HOURS, verbose: bool = False
) -> ResponseCache:
    """Enable the global cache with specified settings."""
    global _global_cache
    _global_cache = ResponseCache(enabled=True, ttl_hours=ttl_hours, verbose=verbose)
    return _global_cache


def disable_cache() -> None:
    """Disable the global cache."""
    global _global_cache
    if _global_cache:
        _global_cache.save()
    _global_cache = ResponseCache(enabled=False)


# =============================================================================
# CLI
# =============================================================================


def main():
    """CLI for cache management."""
    import argparse

    parser = argparse.ArgumentParser(description="Response Cache Management")
    parser.add_argument("--stats", action="store_true", help="Show cache statistics")
    parser.add_argument("--clear", action="store_true", help="Clear all cache entries")
    parser.add_argument("--cleanup", action="store_true", help="Remove expired entries")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose output")

    args = parser.parse_args()

    cache = ResponseCache(enabled=True, verbose=args.verbose)

    if args.clear:
        count = cache.clear()
        logger.info(f"Cleared {count} cache entries")
    elif args.cleanup:
        count = cache.cleanup_expired()
        logger.info(f"Removed {count} expired entries")
    elif args.stats:
        stats = cache.get_stats()
        logger.info("\nResponse Cache Statistics:")
        logger.info(f"  Entries:   {stats['entries']}")
        logger.info(f"  Hits:      {stats['hits']}")
        logger.info(f"  Misses:    {stats['misses']}")
        logger.info(f"  Writes:    {stats['writes']}")
        logger.info(f"  Hit Rate:  {stats['hit_rate']}%")
        logger.info(f"  TTL:       {stats['ttl_hours']} hours")
        logger.info(f"  Location:  {get_cache_dir()}")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
