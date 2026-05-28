"""Graph compiler — turns YAML WorkflowConfig into a LangGraph StateGraph.

This is the public compilation entry point.  All graph topology helpers,
node factories, output-parsing helpers, and edge wiring live in
``graph_wiring.py`` and are re-exported here for backward compatibility.

``_make_step_node`` is a thin shim that delegates to
``graph_wiring.make_step_node`` while forwarding this module's
``create_agent`` and ``get_model_candidates_for_tier`` names.  Evaluated
at call time, this ensures that monkeypatching those names on this module
(``monkeypatch.setattr(graph_module, "create_agent", ...)``) propagates
into the node closures produced by the factory.
"""

from __future__ import annotations

import logging
from typing import Any

try:
    from langgraph.graph import StateGraph
except ImportError as _lg_err:  # pragma: no cover
    raise ImportError(
        "langchain-core and langgraph are required for the LangChain adapter. "
        "Install them with: pip install langchain-core langgraph"
    ) from _lg_err

from ..integrations.base import TraceAdapter
from .agents import create_agent
from .config import StepConfig, WorkflowConfig
from .graph_wiring import (
    add_fan_out_edges,
    add_loop_edge,
    add_loop_edges,
    add_start_edges,
    add_terminal_edges,
    build_graph,
    build_outgoing_map,
    build_task_description,
    coerce_message_content_to_text,
    compile_graph,
    extract_agent_metadata,
    extract_agent_response_text,
    make_step_node,
    map_step_outputs_to_context,
    next_iteration,
    parse_json_dict_from_text,
    parse_step_outputs,
    record_step_result,
    resolve_inputs_into_context,
    validate_dependencies,
    wire_dependency_edges,
    wrap_with_skip_check,
)
from .models import (
    get_model_candidates_for_tier,
)
from .state import WorkflowState

# ---------------------------------------------------------------------------
# Re-export all public helpers from graph_wiring
# ---------------------------------------------------------------------------


logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Private aliases (backward compat for topology helpers)
# ---------------------------------------------------------------------------

_add_fan_out_edges = add_fan_out_edges
_add_loop_edge = add_loop_edge
_add_loop_edges = add_loop_edges
_add_start_edges = add_start_edges
_add_terminal_edges = add_terminal_edges
_build_outgoing_map = build_outgoing_map
_compile_graph = compile_graph
_validate_dependencies = validate_dependencies
_wire_dependency_edges = wire_dependency_edges
_wrap_with_skip_check = wrap_with_skip_check

# Private aliases (backward compat for output-parsing helpers)
_build_task_description = build_task_description
_coerce_message_content_to_text = coerce_message_content_to_text
_extract_agent_metadata = extract_agent_metadata
_extract_agent_response_text = extract_agent_response_text
_map_step_outputs_to_context = map_step_outputs_to_context
_next_iteration = next_iteration
_parse_json_dict_from_text = parse_json_dict_from_text
_parse_step_outputs = parse_step_outputs
_record_step_result = record_step_result
_resolve_inputs_into_context = resolve_inputs_into_context


# ---------------------------------------------------------------------------
# Node-factory shim — delegates to graph_wiring.make_step_node, but reads
# ``create_agent`` and ``get_model_candidates_for_tier`` from *this* module's
# namespace at call time so that monkeypatching those names propagates into
# node closures.
# ---------------------------------------------------------------------------


def _make_step_node(
    step: StepConfig,
    workflow: WorkflowConfig,
    trace_adapter: TraceAdapter | None = None,
    *,
    validate_only: bool = False,
) -> Any:
    """Shim for ``graph_wiring.make_step_node``.

    Reads ``create_agent`` and ``get_model_candidates_for_tier`` from this
    module's globals at call time so that test monkeypatches applied to
    ``graph_module.create_agent`` etc. are seen by the returned node closure.
    """
    return make_step_node(
        step,
        workflow,
        trace_adapter,
        validate_only=validate_only,
        _create_agent_fn=create_agent,
        _get_candidates_fn=get_model_candidates_for_tier,
    )


def _add_step_nodes(
    graph: StateGraph,
    config: WorkflowConfig,
    trace_adapter: TraceAdapter | None = None,
    *,
    validate_only: bool = False,
) -> None:
    """Add one graph node per configured workflow step."""
    for step in config.steps:
        node_fn = _make_step_node(
            step,
            config,
            trace_adapter,
            validate_only=validate_only,
        )
        if step.when:
            node_fn = _wrap_with_skip_check(step, node_fn)
        graph.add_node(step.name, node_fn)


# ---------------------------------------------------------------------------
# Public compilation entry point
# ---------------------------------------------------------------------------


def compile_workflow(
    config: WorkflowConfig,
    checkpointer: Any = None,
    trace_adapter: TraceAdapter | None = None,
    *,
    validate_only: bool = False,
) -> Any:
    """Compile a ``WorkflowConfig`` into a runnable LangGraph.

    Parameters
    ----------
    config:
        Parsed workflow config from YAML.
    checkpointer:
        Optional LangGraph checkpointer for persistence.
    trace_adapter:
        Optional trace adapter for step-level observability.
    validate_only:
        When True, compile graph topology without constructing live agents.

    Returns
    -------
    A compiled ``CompiledGraph`` ready to ``.invoke()`` or ``.stream()``.
    """
    if not config.steps:
        raise ValueError(f"Workflow '{config.name}' has no steps.")

    graph: StateGraph = StateGraph(WorkflowState)
    step_names = {s.name for s in config.steps}
    root_steps = [s.name for s in config.steps if not s.depends_on]

    _add_step_nodes(graph, config, trace_adapter, validate_only=validate_only)
    _add_start_edges(graph, root_steps)
    _validate_dependencies(config, step_names)
    _wire_dependency_edges(graph, _build_outgoing_map(config))
    _add_terminal_edges(graph, config)
    _add_loop_edges(graph, config)

    return _compile_graph(graph, checkpointer)


# ---------------------------------------------------------------------------
# Re-exports — public surface exposed via ``agentic_v2.langchain``
# ---------------------------------------------------------------------------

__all__ = [
    "compile_workflow",
    # topology helpers
    "build_graph",
    "compile_graph",
    "wrap_with_skip_check",
    "add_start_edges",
    "add_fan_out_edges",
    "wire_dependency_edges",
    "add_terminal_edges",
    "add_loop_edge",
    "add_loop_edges",
    "validate_dependencies",
    "build_outgoing_map",
    # output-parsing helpers
    "resolve_inputs_into_context",
    "next_iteration",
    "record_step_result",
    "map_step_outputs_to_context",
    "build_task_description",
    "extract_agent_response_text",
    "coerce_message_content_to_text",
    "parse_json_dict_from_text",
    "parse_step_outputs",
    "extract_agent_metadata",
]
