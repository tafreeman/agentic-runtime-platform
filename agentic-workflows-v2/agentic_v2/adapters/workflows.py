"""Shared loading and execution for adapter-owned workflow definitions.

Adapters own their definition format, input validation and output resolution.
Entry points pass the loaded object through unchanged and keep workflow data
separate from execution controls.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Awaitable, Callable, Mapping

from ..contracts import WorkflowResult
from ..engine.context import ExecutionContext
from .registry import get_registry


def load_workflow(
    adapter_name: str,
    workflow_name: str,
    *,
    definitions_dir: Path | None = None,
) -> Any:
    """Load a named definition using the selected adapter's loader."""
    registry = get_registry()
    registry.validate_selected(adapter_name)
    engine = registry.get_adapter(adapter_name)
    loader = getattr(engine, "load_workflow", None)
    if not callable(loader):
        raise TypeError(f"Adapter '{adapter_name}' does not support named workflows")
    return loader(workflow_name, definitions_dir=definitions_dir)


async def execute_workflow(
    adapter_name: str,
    definition: Any,
    input_data: Mapping[str, Any],
    *,
    run_id: str | None = None,
    on_update: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
) -> WorkflowResult:
    """Execute a loaded definition without reloading it or splatting input keys."""
    registry = get_registry()
    registry.validate_selected(adapter_name)
    engine = registry.get_adapter(adapter_name)
    ctx = ExecutionContext(workflow_id=run_id or f"wf-{definition.name}")
    if run_id is not None:
        ctx.run_id = run_id
    return await engine.execute(
        definition,
        ctx,
        on_update=on_update,
        thread_id=run_id,
        workflow_inputs=dict(input_data),
    )
