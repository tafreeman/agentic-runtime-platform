"""Execution engine protocol — backward-compatibility shim.

Canonical definitions now live in ``agentic_v2.core.protocols``.
This module re-exports them for existing import paths.
"""

from agentic_v2.core.protocols import (
    ExecutionEngine,
    SupportsCheckpointing,
    SupportsStreaming,
)

__all__ = [
    "ExecutionEngine",
    "SupportsCheckpointing",
    "SupportsStreaming",
]
