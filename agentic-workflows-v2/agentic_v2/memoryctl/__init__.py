"""Deterministic maintenance core for the agent context system (TIER_0).

Implements the file-based memory operations defined in the design doc
``AGENT_CONTEXT_SYSTEM.md``: schema validation, index generation,
link/budget/staleness checks, verify-command execution, dedupe,
archival, episode stats reduction, and reporting. Everything in this
package is deterministic — no LLM calls.
"""

from __future__ import annotations

from agentic_v2.memoryctl._shared import (
    CommandResult,
    Finding,
    MemoryctlConfig,
    MemoryDoc,
)

__all__ = ["CommandResult", "Finding", "MemoryDoc", "MemoryctlConfig"]
