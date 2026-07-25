"""CLI helper functions for adapter comparison and RAG operations.

Extracted from ``main.py`` to keep the command module under 800 lines.
These functions encapsulate the business logic called by the Typer
command handlers.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class _NormalizedResult:
    """Lightweight result object normalised for CLI display.

    Adapts the contracts ``WorkflowResult`` returned by the native engine
    into the same attribute shape that ``_show_results`` and the output-file
    block in ``main.py`` consume from the LangChain runner result.
    """

    workflow_name: str
    status: str
    steps: dict[str, Any]
    outputs: dict[str, Any]
    errors: list[str]
    elapsed_seconds: float


# ---------------------------------------------------------------------------
# Private normalisation helpers
# ---------------------------------------------------------------------------


def _as_dict(value: Any) -> dict[str, Any]:
    """Return *value* as a plain dict, or an empty dict for None."""
    if isinstance(value, dict):
        return value
    if value is None:
        return {}
    return {"value": value}


def _status_str(status_val: Any) -> str:
    """Convert a status enum or raw value to a lowercase string."""
    if status_val is None:
        return "unknown"
    if hasattr(status_val, "value"):
        return str(status_val.value)
    return str(status_val)


def _normalise_steps(steps_raw: Any) -> dict[str, Any]:
    """Convert a list of ``StepResult`` objects into a name-keyed dict.

    Args:
        steps_raw: Either a ``list[StepResult]`` (native engine) or an
            already-keyed mapping (pass-through).

    Returns:
        Dict mapping step name to a small status/outputs/error dict.
    """
    if not isinstance(steps_raw, list):
        return dict(steps_raw) if steps_raw else {}

    steps_dict: dict[str, Any] = {}
    for sr in steps_raw:
        name = getattr(sr, "step_name", None) or getattr(sr, "name", str(sr))
        sr_status = getattr(sr, "status", None)
        steps_dict[str(name)] = {
            "status": _status_str(sr_status),
            "outputs": getattr(sr, "output_data", None) or {},
            "error": getattr(sr, "error", None),
        }
    return steps_dict


def _collect_errors(result: Any, steps_raw: Any) -> list[str]:
    """Gather error strings from result metadata and failed steps.

    Args:
        result: Raw engine result object.
        steps_raw: The ``steps`` attribute of *result* (may be a list or
            mapping).

    Returns:
        Deduplicated list of non-empty error strings.
    """
    errors: list[str] = []
    raw_errors = getattr(result, "errors", None)
    if isinstance(raw_errors, list):
        errors.extend(str(err) for err in raw_errors if err)

    metadata = getattr(result, "metadata", {}) or {}
    if isinstance(metadata, dict):
        meta_errors = metadata.get("errors")
        if isinstance(meta_errors, list):
            errors.extend(str(e) for e in meta_errors if e)

    step_list = steps_raw if isinstance(steps_raw, list) else []
    for sr in step_list:
        err = getattr(sr, "error", None)
        if err:
            errors.append(str(err))

    return list(dict.fromkeys(errors))


def _elapsed_seconds(result: Any, wall_clock: float) -> float:
    """Resolve elapsed seconds from result metadata or wall-clock fallback.

    Args:
        result: Raw engine result object.
        wall_clock: Measured wall-clock duration in seconds.

    Returns:
        Best-estimate elapsed seconds.
    """
    duration_ms = getattr(result, "total_duration_ms", None)
    if isinstance(duration_ms, (int, float)) and duration_ms > 0:
        return duration_ms / 1000.0
    elapsed_seconds = getattr(result, "elapsed_seconds", None)
    if isinstance(elapsed_seconds, (int, float)) and elapsed_seconds >= 0:
        return float(elapsed_seconds)
    return wall_clock


def _normalize_result(
    workflow_name: str,
    result: Any,
    wall_clock: float,
) -> _NormalizedResult:
    """Normalize engine-specific workflow results for CLI display/output."""
    overall_status = getattr(result, "overall_status", None)
    status = (
        _status_str(overall_status)
        if overall_status is not None
        else _status_str(getattr(result, "status", None))
    )

    steps_raw = getattr(result, "steps", [])
    outputs = _as_dict(
        getattr(result, "final_output", None) or getattr(result, "outputs", None)
    )

    return _NormalizedResult(
        workflow_name=getattr(result, "workflow_name", workflow_name),
        status=status,
        steps=_normalise_steps(steps_raw),
        outputs=outputs,
        errors=_collect_errors(result, steps_raw),
        elapsed_seconds=round(_elapsed_seconds(result, wall_clock), 3),
    )


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def _run_via_adapter(
    adapter_name: str,
    workflow_name: str,
    input_data: dict[str, Any],
) -> _NormalizedResult:
    """Execute a workflow through the named adapter and return a normalised result.

    Loads the workflow definition via
    :class:`~agentic_v2.workflows.loader.WorkflowLoader`, builds an
    :class:`~agentic_v2.engine.context.ExecutionContext` from *input_data*,
    and calls ``engine.execute(dag, ctx)``.  The raw
    :class:`~agentic_v2.contracts.WorkflowResult` is then normalised into a
    :class:`_NormalizedResult` so the CLI display helpers can consume it
    without knowing about the adapter's internal result shape.

    Args:
        adapter_name: Registered adapter name (e.g. ``"native"``).
        workflow_name: Workflow definition name.
        input_data: Input variables for the workflow.

    Returns:
        A :class:`_NormalizedResult` with ``status``, ``steps``, ``outputs``,
        ``errors``, and ``elapsed_seconds`` attributes.

    Raises:
        AdapterNotFoundError: If *adapter_name* is not registered.
        WorkflowLoadError: If the workflow definition cannot be found.
    """
    from ..adapters import get_registry
    from ..engine.context import ExecutionContext
    from ..workflows.loader import WorkflowLoader

    loader = WorkflowLoader()
    workflow_def = loader.load(workflow_name)
    dag = workflow_def.dag
    ctx = ExecutionContext(variables=dict(input_data))

    engine = get_registry().get_adapter(adapter_name)

    start = time.perf_counter()
    result = asyncio.run(engine.execute(dag, ctx))
    wall_clock = time.perf_counter() - start
    return _normalize_result(workflow_name, result, wall_clock)


def _summarize_for_compare(result: _NormalizedResult) -> dict[str, Any]:
    """Reduce a normalised result to the summary row the compare table shows."""
    return {
        "status": result.status,
        "step_count": len(result.steps),
        "elapsed": round(result.elapsed_seconds, 2),
    }


def _run_adapter(
    adapter_name: str,
    workflow_name: str,
    input_data: dict[str, Any],
) -> dict[str, Any]:
    """Run a workflow through a specific adapter and return summary metrics.

    Each adapter takes a different ``workflow`` argument: the LangChain
    adapter resolves a workflow *name* itself, while the native engine
    needs an already-loaded :class:`~agentic_v2.engine.dag.DAG` plus an
    :class:`~agentic_v2.engine.context.ExecutionContext`.  Non-LangChain
    adapters therefore go through :func:`_run_via_adapter`, which performs
    that resolution; passing the bare name straight to the native engine
    makes it raise ``TypeError`` and report a spurious ``failed`` row.
    (The same name-based split exists in ``main.py::_execute_run``;
    unifying the two loading paths is ADR-001 Phase 2 work.)

    Args:
        adapter_name: Registered adapter name (e.g. ``"native"``, ``"langchain"``).
        workflow_name: Workflow definition name.
        input_data: Input variables for the workflow.

    Returns:
        Dict with ``status``, ``step_count``, and ``elapsed`` keys.  A
        ``status`` of ``"failed"`` with zero steps is returned when the
        adapter raises during execution, so callers must treat that row as
        a failure.

    Raises:
        AdapterNotFoundError: If *adapter_name* is not registered.
    """
    from ..adapters import get_registry

    # Resolved outside the try below: an unregistered adapter name is a
    # user error (usually a typo) and should surface with the registry's
    # "Available: ..." hint rather than be flattened into a failed row.
    engine = get_registry().get_adapter(adapter_name)

    start = time.perf_counter()
    try:
        if adapter_name == "langchain":
            raw_result = asyncio.run(engine.execute(workflow_name, **input_data))
            wall_clock = time.perf_counter() - start
            normalized = _normalize_result(workflow_name, raw_result, wall_clock)
        else:
            normalized = _run_via_adapter(adapter_name, workflow_name, input_data)
        return _summarize_for_compare(normalized)
    except Exception as exc:
        elapsed = time.perf_counter() - start
        logger.debug("Adapter %s failed: %s", adapter_name, exc)
        return {
            "status": "failed",
            "step_count": 0,
            "elapsed": round(elapsed, 2),
        }


# ---------------------------------------------------------------------------
# Module-level RAG state so ingest + search share a session
# ---------------------------------------------------------------------------

_rag_vectorstore = None
_rag_retriever = None


def _rag_ingest_impl(source: str) -> int:
    """Ingest a file into the RAG pipeline and return chunk count.

    Args:
        source: Path to the file to ingest.

    Returns:
        Number of chunks ingested.

    Raises:
        FileNotFoundError: If the source path does not exist.
    """
    global _rag_vectorstore, _rag_retriever

    from ..rag import (
        HybridRetriever,
        IngestionPipeline,
        InMemoryEmbedder,
        InMemoryVectorStore,
        MarkdownLoader,
        RecursiveChunker,
        TextLoader,
    )

    source_path = Path(source)
    if not source_path.exists():
        raise FileNotFoundError(f"Source not found: {source}")

    # Pick loader based on extension
    if source_path.suffix in (".md", ".markdown"):
        loader = MarkdownLoader()
    else:
        loader = TextLoader()

    pipeline = IngestionPipeline(loader=loader, chunker=RecursiveChunker())
    chunks = asyncio.run(pipeline.ingest(str(source_path)))

    if not chunks:
        return 0

    embedder = InMemoryEmbedder()
    if _rag_vectorstore is None:
        _rag_vectorstore = InMemoryVectorStore()

    embeddings = asyncio.run(embedder.embed([c.content for c in chunks]))
    asyncio.run(_rag_vectorstore.add(chunks, embeddings))

    _rag_retriever = HybridRetriever(
        embedder=embedder,
        vectorstore=_rag_vectorstore,
    )
    _rag_retriever.index_chunks(chunks)

    return len(chunks)


def _rag_search_impl(query: str, top_k: int) -> list[dict]:
    """Search the RAG index and return results.

    Args:
        query: Search query string.
        top_k: Maximum number of results.

    Returns:
        List of dicts with ``content`` and ``score`` keys.
    """
    global _rag_retriever

    if _rag_retriever is None:
        return []

    results = asyncio.run(_rag_retriever.retrieve(query, top_k=top_k))
    return [{"content": r.content, "score": r.score} for r in results]
