"""
LLM Response Cache - Unified Interface
=======================================

This module provides a simple, function-based API for caching LLM responses.
It wraps the more feature-rich ResponseCache class from response_cache.py.

Usage:
    from tools.core.cache import get_cached_response, cache_response, clear_cache

    # Check for cached response first
    cached = get_cached_response("gh:gpt-4o-mini", "Hello world")
    if cached:
        return cached

    # Generate and cache
    response = LLMClient.generate_text(model, prompt)
    cache_response(model, prompt, response)

    # Clear cache
    clear_cache()  # All
    clear_cache(max_age_hours=24)  # Older than 24 hours

Author: Prompts Library Team
Version: 2.0.0 (consolidated with response_cache.py)

NOTE: This module delegates to response_cache.ResponseCache for the actual
implementation. Both modules now use the same underlying cache storage.
"""

from __future__ import annotations

import logging
import os
from typing import Any

# Import the canonical implementation
from response_cache import DEFAULT_TTL_HOURS, ResponseCache, get_cache_dir

logger = logging.getLogger(__name__)

# =============================================================================
# GLOBAL CACHE INSTANCE
# =============================================================================

# Lazily initialized global cache
_cache: ResponseCache | None = None


def _get_cache() -> ResponseCache:
    """Get or create the global cache instance."""
    global _cache
    if _cache is None:
        # Check if caching is enabled via environment
        enabled = os.environ.get("PROMPTS_CACHE_ENABLED", "1").lower() in (
            "1",
            "true",
            "yes",
        )
        _cache = ResponseCache(enabled=enabled, ttl_hours=DEFAULT_TTL_HOURS)
    return _cache


# =============================================================================
# SIMPLE API (backward compatible)
# =============================================================================


def get_cached_response(
    model: str,
    prompt: str,
    system_instruction: str | None = None,
    max_age_hours: float = 24.0,
    **kwargs,
) -> str | None:
    """Get a cached response if available and not expired.

    Args:
        model: Model identifier (e.g., "gh:gpt-4o-mini")
        prompt: The user prompt
        system_instruction: Optional system prompt
        max_age_hours: Maximum age of cached response in hours (default: 24)
        **kwargs: Additional parameters (temperature, max_tokens) - used for cache key

    Returns:
        Cached response string, or None if not cached/expired
    """
    cache = _get_cache()
    if not cache.enabled:
        return None

    # Build a combined prompt that includes relevant kwargs for cache key
    # This ensures different temperatures/max_tokens get different cache entries
    cache_prompt = prompt
    if kwargs:
        cache_prompt = f"{prompt}||temp={kwargs.get('temperature', 0.7)}||max={kwargs.get('max_tokens', 4096)}"

    return cache.get(cache_prompt, model, system_instruction or "")


def cache_response(
    model: str,
    prompt: str,
    response: str,
    system_instruction: str | None = None,
    **kwargs,
) -> None:
    """Cache an LLM response.

    Args:
        model: Model identifier
        prompt: The user prompt
        response: The LLM response to cache
        system_instruction: Optional system prompt
        **kwargs: Additional parameters (temperature, max_tokens)
    """
    cache = _get_cache()
    if not cache.enabled:
        return

    # Match the cache key computation from get_cached_response
    cache_prompt = prompt
    if kwargs:
        cache_prompt = f"{prompt}||temp={kwargs.get('temperature', 0.7)}||max={kwargs.get('max_tokens', 4096)}"

    cache.set(cache_prompt, model, system_instruction or "", response)


def clear_cache(max_age_hours: float | None = None) -> int:
    """Clear cached responses.

    Args:
        max_age_hours: If provided, only clear entries older than this.
                       If None, clear all entries.

    Returns:
        Number of entries cleared
    """
    cache = _get_cache()

    if max_age_hours is not None:
        # Clean up entries older than specified age
        return cache.cleanup_expired()
    else:
        # Clear all
        return cache.clear()


def get_cache_stats() -> dict[str, Any]:
    """Get statistics about the cache."""
    cache = _get_cache()
    return cache.get_stats()


def invalidate_cache(
    model: str, prompt: str, system_instruction: str | None = None, **kwargs
) -> bool:
    """Invalidate a specific cache entry.

    Returns:
        True if an entry was invalidated, False otherwise.
    """
    cache = _get_cache()

    cache_prompt = prompt
    if kwargs:
        cache_prompt = f"{prompt}||temp={kwargs.get('temperature', 0.7)}||max={kwargs.get('max_tokens', 4096)}"

    return cache.invalidate(cache_prompt, model, system_instruction or "")


# =============================================================================
# CONVENIENCE EXPORTS
# =============================================================================

# Re-export CACHE_ENABLED for backward compatibility
CACHE_ENABLED = os.environ.get("PROMPTS_CACHE_ENABLED", "1").lower() in (
    "1",
    "true",
    "yes",
)


# =============================================================================
# CLI
# =============================================================================

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Manage LLM response cache")
    parser.add_argument("--stats", action="store_true", help="Show cache statistics")
    parser.add_argument("--clear", action="store_true", help="Clear all cache entries")
    parser.add_argument(
        "--clear-old",
        type=float,
        metavar="HOURS",
        help="Clear entries older than HOURS",
    )

    args = parser.parse_args()

    if args.stats:
        stats = get_cache_stats()
        logger.info(f"Cache entries: {stats.get('entries', 0)}")
        logger.info(f"Hits: {stats.get('hits', 0)}")
        logger.info(f"Misses: {stats.get('misses', 0)}")
        logger.info(f"Hit rate: {stats.get('hit_rate', 0)}%")
        logger.info(f"Cache location: {get_cache_dir()}")
    elif args.clear:
        cleared = clear_cache()
        logger.info(f"Cleared {cleared} cache entries")
    elif args.clear_old:
        cleared = clear_cache(max_age_hours=args.clear_old)
        logger.info(
            f"Cleared {cleared} cache entries older than {args.clear_old} hours"
        )
    else:
        parser.print_help()
