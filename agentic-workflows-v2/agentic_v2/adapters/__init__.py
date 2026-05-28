"""Adapter layer — pluggable execution engine backends.

Provides :func:`get_registry` for discovering and instantiating
execution engine adapters.  Built-in adapters are auto-registered
on import.

Two engines are registered by default:

``"langchain"`` (default for YAML-defined workflows)
    Compiles YAML workflow definitions into a LangGraph ``StateGraph``.
    Supports streaming, checkpointing, HITL interrupts, and time-travel
    debugging.  Requires the ``[langchain]`` extra.

``"native"`` (used by the Orchestrator for dynamic DAG construction)
    Executes runtime-generated :class:`~agentic_v2.engine.dag.DAG` and
    :class:`~agentic_v2.engine.pipeline.Pipeline` objects via Kahn's
    algorithm.  Zero external dependencies; used when the Orchestrator
    decomposes a task into subtasks at runtime.

Usage::

    from agentic_v2.adapters import get_registry

    # Named YAML workflow — use the LangGraph adapter
    registry = get_registry()
    engine = registry.get_adapter("langchain")
    result = await engine.execute("code_review", code_file="main.py")

    # Dynamic DAG (e.g. Orchestrator) — use the native adapter
    engine = registry.get_adapter("native")
    result = await engine.execute(dag, ctx)
"""

from ..langchain.dependencies import (
    is_missing_langchain_dependency_error,
)

# Auto-register built-in adapters (side-effect imports — trigger adapter registration)
from . import native as _native_adapter  # noqa: F401
from .registry import AdapterRegistry, get_registry

try:
    from . import langchain as _langchain_adapter  # noqa: F401
except ImportError as exc:  # pragma: no cover — optional dependency
    if not is_missing_langchain_dependency_error(exc):
        raise

__all__ = [
    "AdapterRegistry",
    "get_registry",
]
