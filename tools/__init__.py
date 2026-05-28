"""
Tools Package
=============

Core utilities for Agentic Workflows v2.

Key modules:
- llm_client: Multi-provider LLM client
- core: Configuration and error handling
- agents.benchmarks: Benchmark dataset definitions

"""

from __future__ import annotations

__version__ = "0.1.0"

# -----------------------------------------------------------------------------
# Backwards-compatible module aliases
# -----------------------------------------------------------------------------
# Some tooling/tests reference `tools.evaluation_agent.*`.
# The implementation lives in `tools.agents.evaluation_agent`.
try:
    from tools.agents import evaluation_agent as evaluation_agent  # type: ignore
except Exception:
    # Avoid import-time failures if optional deps are missing.
    evaluation_agent = None  # type: ignore
