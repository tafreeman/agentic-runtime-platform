"""Core utilities: configuration, error handling, encoding, and caching.

Modules:
    config: Dataclass-based model and path configuration.
    errors: Canonical ``ErrorCode`` enum and heuristic classifier.
    cache: Disk-backed response cache for LLM calls.
    _encoding: Windows console UTF-8 encoding fix.
"""

from __future__ import annotations
