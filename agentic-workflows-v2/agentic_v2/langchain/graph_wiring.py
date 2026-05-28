"""Graph topology/wiring — node factories and edge assembly for LangGraph.

This module owns everything required to turn a ``WorkflowConfig`` into a
populated (but not yet compiled) ``StateGraph``:

- Deterministic tier-0 step implementations
- LLM-backed node factory (``make_step_node``) with multi-model failover
- Conditional self-skip wrapper (``wrap_with_skip_check``)
- All ``add_*`` / ``wire_*`` / ``build_*`` helpers that populate nodes
  and edges
- The low-level ``compile_graph`` wrapper

The public entry point used by ``graph.py`` is ``build_graph``, which calls
the helpers in the right order and returns a fully wired (uncompiled)
``StateGraph``.  Compilation (adding a checkpointer, calling
``graph.compile()``) is left to the caller so that ``compile_workflow`` in
``graph.py`` remains the single orchestration point.
"""

from __future__ import annotations

import ast as python_ast
import json
import logging
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from langchain_core.messages import AIMessage, HumanMessage
    from langgraph.graph import END, START, StateGraph
except ImportError as _lg_err:  # pragma: no cover
    raise ImportError(
        "langchain-core and langgraph are required for the LangChain adapter. "
        "Install them with: pip install langchain-core langgraph"
    ) from _lg_err

from ..integrations.base import TraceAdapter
from ..integrations.tracing import NullTraceAdapter
from .agents import create_agent, parse_agent_tier
from .config import StepConfig, WorkflowConfig
from .expressions import evaluate_condition, resolve_expression
from .models import get_model_candidates_for_tier, is_retryable_model_error
from .state import WorkflowState

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tier-0 deterministic step implementations
# ---------------------------------------------------------------------------


def _coerce_text_input(value: Any) -> str:
    """Normalize workflow text inputs for deterministic tier-0 handlers."""
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return str(value)


def _tier0_process_text(state: WorkflowState) -> dict[str, Any]:
    """Deterministically echo the provided text for first-run smoke tests."""
    ctx = dict(state.get("context", {}))
    inputs = state.get("inputs", {})
    text = _coerce_text_input(ctx.get("text") or inputs.get("input_text"))

    result = {"result": text}
    return {
        "context": {**ctx, **result},
        "steps": {
            **state.get("steps", {}),
            "__current__": {"status": "success", "outputs": result},
        },
    }


def _tier0_count_text(state: WorkflowState) -> dict[str, Any]:
    """Count characters in the provided text without any LLM involvement."""
    ctx = dict(state.get("context", {}))
    inputs = state.get("inputs", {})
    text = _coerce_text_input(ctx.get("text") or inputs.get("input_text"))

    result = {"count": len(text)}
    return {
        "context": {**ctx, **result},
        "steps": {
            **state.get("steps", {}),
            "__current__": {"status": "success", "outputs": result},
        },
    }


def _tier0_parse_code(state: WorkflowState) -> dict[str, Any]:
    """Deterministic code parsing (no LLM)."""
    ctx = dict(state.get("context", {}))
    file_path = ctx.get("file_path") or state.get("inputs", {}).get("code_file", "")

    result: dict[str, Any] = {
        "parsed_ast": "{}",
        "code_metrics": "{}",
    }

    if not file_path:
        return {
            "context": {**ctx, **result},
            "steps": {
                **state.get("steps", {}),
                "__current__": {"status": "success", "outputs": result},
            },
        }

    p = Path(file_path)
    if p.exists() and p.suffix == ".py":
        try:
            code = p.read_text(encoding="utf-8")
            tree = python_ast.parse(code)
            functions = [
                n.name
                for n in python_ast.walk(tree)
                if isinstance(n, python_ast.FunctionDef | python_ast.AsyncFunctionDef)
            ]
            classes = [
                n.name
                for n in python_ast.walk(tree)
                if isinstance(n, python_ast.ClassDef)
            ]
            result["parsed_ast"] = json.dumps(
                {"functions": functions, "classes": classes}
            )
            result["code_metrics"] = json.dumps(
                {"lines": len(code.splitlines()), "functions": len(functions)}
            )
        except Exception as e:
            result["parsed_ast"] = json.dumps({"error": str(e)})

    return {
        "context": {**ctx, **result},
        "steps": {
            **state.get("steps", {}),
            "__current__": {"status": "success", "outputs": result},
        },
    }


_TIER0_REGISTRY: dict[str, Any] = {
    "tier0_parser": _tier0_parse_code,
    "tier0_process": _tier0_process_text,
    "tier0_counter": _tier0_count_text,
}


class _AwaitableStateUpdate(dict):
    """Dict update that also supports direct ``await node(state)`` tests."""

    def __await__(self):
        async def _result() -> "_AwaitableStateUpdate":
            return self

        return _result().__await__()


# ---------------------------------------------------------------------------
# Step execution helpers (consumed by the node factory closures)
# ---------------------------------------------------------------------------


def resolve_inputs_into_context(
    step: StepConfig,
    state: WorkflowState,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Resolve step input expressions into context and return both."""
    ctx = dict(state.get("context", {}))
    resolved_inputs: dict[str, Any] = {}
    for key, expr in step.inputs.items():
        value = resolve_expression(expr, state)
        resolved_inputs[key] = value
        ctx[key] = value
    return ctx, resolved_inputs


def next_iteration(state: WorkflowState, step_name: str) -> int:
    """Compute next loop iteration number for a step."""
    existing = state.get("steps", {}).get(step_name, {})
    return existing.get("loop_iteration", 0) + 1


def resolve_loop_max(step: StepConfig, state: WorkflowState) -> int:
    """Resolve a loop bound from runtime state, falling back to parsed default."""
    loop_max_expr = getattr(step, "loop_max_expr", None)
    if loop_max_expr:
        try:
            return max(1, int(resolve_expression(loop_max_expr, state)))
        except (TypeError, ValueError):
            logger.warning(
                "Step %s loop_max expression %r did not resolve to an integer; "
                "using parsed fallback %s.",
                step.name,
                loop_max_expr,
                step.loop_max,
            )
    return max(1, int(step.loop_max or 3))


def record_step_result(
    state: WorkflowState,
    step_name: str,
    status: str,
    outputs: dict[str, Any],
    *,
    error: str | None = None,
    inputs: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    start_time: datetime | None = None,
    end_time: datetime | None = None,
) -> dict[str, dict]:
    """Return updated steps dict for a completed/failed step."""
    steps = dict(state.get("steps", {}))
    payload: dict[str, Any] = {
        "status": status,
        "outputs": outputs,
        "loop_iteration": next_iteration(state, step_name),
    }
    if inputs is not None:
        payload["inputs"] = inputs
    if error:
        payload["error"] = error
    if metadata:
        payload["metadata"] = metadata
    if start_time:
        payload["start_time"] = start_time.isoformat()
    if end_time:
        payload["end_time"] = end_time.isoformat()
        if start_time:
            payload["duration_ms"] = (end_time - start_time).total_seconds() * 1000
    steps[step_name] = payload
    return steps


def map_step_outputs_to_context(
    step: StepConfig,
    step_outputs: dict[str, Any],
    ctx: dict[str, Any],
) -> dict[str, Any]:
    """Map declared step outputs into context keys."""
    final_ctx = dict(ctx)
    for out_key, ctx_key in step.outputs.items():
        if out_key in step_outputs:
            final_ctx[ctx_key] = step_outputs[out_key]
    return final_ctx


def build_task_description(step: StepConfig, resolved_inputs: dict[str, Any]) -> str:
    """Create an LLM task prompt payload for a workflow step."""
    task_description = (
        f"Step: {step.name}\n"
        f"Description: {step.description}\n"
        f"Inputs:\n{json.dumps(resolved_inputs, indent=2, default=str)}\n\n"
        f"Please complete this task and return your result."
    )
    if step.outputs:
        output_keys = list(step.outputs.keys())
        task_description += (
            f"\n\nReturn your result as JSON with these keys: {output_keys}"
        )
    return task_description


def extract_agent_response_text(agent_result: dict[str, Any]) -> str:
    """Extract the final AIMessage text from an agent response payload."""
    ai_messages = [
        m for m in agent_result.get("messages", []) if isinstance(m, AIMessage)
    ]
    if not ai_messages:
        return ""
    return coerce_message_content_to_text(ai_messages[-1].content)


def coerce_message_content_to_text(content: Any) -> str:
    """Normalize provider-specific message content into plain text."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, (int, float, bool)):
        return str(content)
    if isinstance(content, list):
        parts = [coerce_message_content_to_text(item) for item in content]
        return "\n".join(part for part in parts if part and part.strip())
    if isinstance(content, dict):
        # Common LangChain/OpenAI/Gemini message block shapes.
        for key in ("text", "output_text", "content", "message"):
            if key in content:
                text = coerce_message_content_to_text(content.get(key))
                if text:
                    return text
        try:
            return json.dumps(content, ensure_ascii=False, default=str)
        except TypeError:
            return str(content)
    return str(content)


def parse_json_dict_from_text(text: str) -> dict[str, Any] | None:
    """Best-effort JSON object extraction from model text output."""
    raw = text.strip()
    if not raw:
        return None

    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
    except Exception:
        pass

    fenced = re.findall(
        r"```(?:json)?\s*(\{.*?\})\s*```", raw, flags=re.DOTALL | re.IGNORECASE
    )
    for candidate in fenced:
        try:
            parsed = json.loads(candidate)
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            continue

    start = raw.find("{")
    end = raw.rfind("}")
    if start != -1 and end != -1 and end > start:
        try:
            parsed = json.loads(raw[start : end + 1])
            if isinstance(parsed, dict):
                return parsed
        except Exception:
            pass

    return None


def parse_step_outputs(response_text: Any) -> dict[str, Any]:
    """Parse structured output from model response text when possible."""
    normalized = coerce_message_content_to_text(response_text)
    step_outputs: dict[str, Any] = {"raw_response": normalized}
    parsed = parse_json_dict_from_text(normalized)
    if isinstance(parsed, dict):
        step_outputs.update(parsed)
    return step_outputs


def extract_agent_metadata(agent_result: dict[str, Any]) -> dict[str, Any]:
    """Extract token usage and model info from agent response."""
    metadata: dict[str, Any] = {}

    # Try to find the last AIMessage
    messages = agent_result.get("messages", [])
    if not messages:
        return metadata

    last_msg = messages[-1]
    if not isinstance(last_msg, AIMessage):
        # Look backwards for the last AIMessage
        for msg in reversed(messages):
            if isinstance(msg, AIMessage):
                last_msg = msg
                break
        else:
            return metadata

    # 1. Token usage from usage_metadata (standard LangChain)
    if hasattr(last_msg, "usage_metadata") and last_msg.usage_metadata:
        usage = last_msg.usage_metadata
        metadata["input_tokens"] = usage.get("input_tokens")
        metadata["output_tokens"] = usage.get("output_tokens")
        metadata["total_tokens"] = usage.get("total_tokens")

    # 2. Token usage from response_metadata (provider specific)
    elif hasattr(last_msg, "response_metadata"):
        rm = last_msg.response_metadata
        # OpenAI/Azure often put it in 'token_usage'
        if "token_usage" in rm:
            usage = rm["token_usage"]
            metadata["input_tokens"] = usage.get("prompt_tokens")
            metadata["output_tokens"] = usage.get("completion_tokens")
            metadata["total_tokens"] = usage.get("total_tokens")
        # Anthropic often puts it in 'usage'
        elif "usage" in rm:
            usage = rm["usage"]
            metadata["input_tokens"] = usage.get("input_tokens")
            metadata["output_tokens"] = usage.get("output_tokens")

        # Model name
        if "model_name" in rm:
            metadata["model"] = rm["model_name"]
        elif "model" in rm:
            metadata["model"] = rm["model"]

    return metadata


# ---------------------------------------------------------------------------
# Node factory
# ---------------------------------------------------------------------------


def make_step_node(
    step: StepConfig,
    workflow: WorkflowConfig,
    trace_adapter: TraceAdapter | None = None,
    *,
    validate_only: bool = False,
    _create_agent_fn: Any = None,
    _get_candidates_fn: Any = None,
) -> Any:
    """Create a graph node function for a workflow step.

    Returns a callable ``(state) -> state_update`` suitable for
    ``graph.add_node()``.

    Parameters
    ----------
    _create_agent_fn:
        Override for ``create_agent``.  Supplied by ``graph.py`` so that
        ``monkeypatch.setattr(graph_module, "create_agent", ...)`` in tests
        propagates into node closures created by this factory.
    _get_candidates_fn:
        Override for ``get_model_candidates_for_tier``.  Same rationale.
    """
    _create_agent = _create_agent_fn if _create_agent_fn is not None else create_agent
    _get_candidates = (
        _get_candidates_fn
        if _get_candidates_fn is not None
        else get_model_candidates_for_tier
    )

    tier = parse_agent_tier(step.agent)
    _trace = trace_adapter or NullTraceAdapter()

    # Tier 0: deterministic
    if tier == 0:
        deterministic_fn = _TIER0_REGISTRY.get(step.agent)

        def _tier0_node(state: WorkflowState) -> dict[str, Any]:
            run_id = state.get("context", {}).get("workflow_run_id", "")
            start_time = datetime.now(timezone.utc)

            ctx, resolved_inputs = resolve_inputs_into_context(step, state)
            _trace.emit_step_start(step.name, run_id, resolved_inputs)

            updated = {**state, "context": ctx}
            if deterministic_fn:
                result = deterministic_fn(updated)
            else:
                # Unknown tier0 agent — noop
                result = {"context": ctx}

            # Move step outputs from __current__ into named step
            step_outputs = (
                result.get("steps", {}).get("__current__", {}).get("outputs", {})
            )
            end_time = datetime.now(timezone.utc)
            steps = record_step_result(
                state,
                step.name,
                "success",
                step_outputs,
                inputs=resolved_inputs,
                start_time=start_time,
                end_time=end_time,
            )

            # Map outputs to context
            final_ctx = map_step_outputs_to_context(
                step,
                step_outputs,
                dict(result.get("context", ctx)),
            )

            _trace.emit_step_complete(step.name, run_id, "success", step_outputs)

            return {
                "context": final_ctx,
                "steps": steps,
                "current_step": step.name,
            }

        return _tier0_node

    # Validation mode: compile graph shape without requiring provider/model setup.
    if validate_only:

        def _validation_noop(state: WorkflowState) -> dict[str, Any]:
            return {
                "context": dict(state.get("context", {})),
                "steps": {
                    **state.get("steps", {}),
                    step.name: {
                        "status": "validation",
                        "outputs": {},
                        "loop_iteration": next_iteration(state, step.name),
                    },
                },
                "current_step": step.name,
            }

        return _validation_noop

    # Tier 1+: LLM-backed agent with runtime failover chain
    model_candidates = _get_candidates(
        tier,
        step.model_override,
        include_unavailable=False,
        include_gh_backup=True,
    )
    agent_cache: dict[str, Any] = {}

    def _get_agent_for_model(model_id: str) -> Any:
        cached = agent_cache.get(model_id)
        if cached is not None:
            return cached
        agent = _create_agent(
            step.agent,
            tool_names=step.tools,
            prompt_file=step.prompt_file,
            model_override=model_id,
        )
        agent_cache[model_id] = agent
        return agent

    def _llm_node(state: WorkflowState) -> dict[str, Any]:
        run_id = state.get("context", {}).get("workflow_run_id", "")
        start_time = datetime.now(timezone.utc)
        ctx, resolved_inputs = resolve_inputs_into_context(step, state)
        _trace.emit_step_start(step.name, run_id, resolved_inputs)

        task_description = build_task_description(step, resolved_inputs)

        attempt_errors: list[dict[str, Any]] = []
        attempted_models: list[str] = []
        agent_result: dict[str, Any] | None = None
        response_text = ""
        metadata: dict[str, Any] = {}

        # Invoke the react agent with failover across candidate models.
        for model_id in model_candidates:
            attempted_models.append(model_id)
            try:
                agent = _get_agent_for_model(model_id)
                agent_result = agent.invoke(
                    {"messages": [HumanMessage(content=task_description)]}
                )
                response_text = extract_agent_response_text(agent_result)
                metadata = extract_agent_metadata(agent_result)
                metadata.setdefault("model", model_id)
                break
            except Exception as e:
                retryable = is_retryable_model_error(e)
                attempt_errors.append(
                    {
                        "model": model_id,
                        "error": str(e),
                        "retryable": retryable,
                    }
                )
                logger.warning(
                    "Step %s model attempt failed (%s, retryable=%s): %s",
                    step.name,
                    model_id,
                    retryable,
                    e,
                )

        if agent_result is None:
            err_text = "All model attempts failed"
            if attempt_errors:
                last = attempt_errors[-1]
                err_text = (
                    f"{err_text} (last model={last.get('model')}: {last.get('error')})"
                )
            end_time = datetime.now(timezone.utc)
            steps = record_step_result(
                state,
                step.name,
                "failed",
                {},
                error=err_text,
                inputs=resolved_inputs,
                start_time=start_time,
                end_time=end_time,
            )
            _trace.emit_step_complete(
                step.name,
                run_id,
                "failed",
                {
                    "error": err_text,
                    "attempted_models": attempted_models,
                    "attempt_errors": attempt_errors,
                },
            )
            return _AwaitableStateUpdate(
                {
                    "context": ctx,
                    "steps": steps,
                    "current_step": step.name,
                    "errors": [f"Step {step.name} failed: {err_text}"],
                }
            )

        if attempt_errors:
            metadata["attempted_models"] = attempted_models
            metadata["attempt_errors"] = attempt_errors

        step_outputs = parse_step_outputs(response_text)

        # Map outputs to context
        ctx = map_step_outputs_to_context(step, step_outputs, ctx)

        end_time = datetime.now(timezone.utc)
        steps = record_step_result(
            state,
            step.name,
            "success",
            step_outputs,
            inputs=resolved_inputs,
            metadata=metadata,
            start_time=start_time,
            end_time=end_time,
        )

        _trace.emit_step_complete(step.name, run_id, "success", step_outputs)

        return _AwaitableStateUpdate(
            {
                "context": ctx,
                "steps": steps,
                "current_step": step.name,
                "messages": [AIMessage(content=response_text)],
                "metadata": metadata,
            }
        )

    return _llm_node


# ---------------------------------------------------------------------------
# Graph topology / wiring helpers
# ---------------------------------------------------------------------------


def wrap_with_skip_check(step: StepConfig, node_fn: Any) -> Any:
    """Wrap a node function with a self-skip check for conditional steps.

    When the step's ``when`` condition evaluates to False, the node
    returns immediately with ``status: "skipped"`` and empty outputs.
    This ensures the node still "completes" in LangGraph, firing its
    outgoing edges so downstream join-nodes are not orphaned.
    """
    when_expr = step.when

    def _self_skip_node(state: WorkflowState) -> dict[str, Any]:
        if not evaluate_condition(when_expr, dict(state)):
            logger.info("Step '%s' self-skipped (when condition not met)", step.name)
            return {
                "context": dict(state.get("context", {})),
                "steps": {
                    **state.get("steps", {}),
                    step.name: {
                        "status": "skipped",
                        "outputs": {},
                        "loop_iteration": 0,
                    },
                },
                "current_step": step.name,
            }
        return node_fn(state)

    return _self_skip_node


def add_step_nodes(
    graph: StateGraph,
    config: WorkflowConfig,
    trace_adapter: TraceAdapter | None = None,
    *,
    validate_only: bool = False,
    _create_agent_fn: Any = None,
    _get_candidates_fn: Any = None,
) -> None:
    """Add one graph node per configured workflow step."""
    for step in config.steps:
        node_fn = make_step_node(
            step,
            config,
            trace_adapter,
            validate_only=validate_only,
            _create_agent_fn=_create_agent_fn,
            _get_candidates_fn=_get_candidates_fn,
        )
        if step.when:
            node_fn = wrap_with_skip_check(step, node_fn)
        graph.add_node(step.name, node_fn)


def add_start_edges(graph: StateGraph, root_steps: list[str]) -> None:
    """Wire START to all root steps."""
    if len(root_steps) == 1:
        graph.add_edge(START, root_steps[0])
        return
    for root in root_steps:
        graph.add_edge(START, root)


def validate_dependencies(config: WorkflowConfig, step_names: set[str]) -> None:
    """Validate all depends_on references exist in workflow steps."""
    for step in config.steps:
        for dep in step.depends_on:
            if dep not in step_names:
                raise ValueError(f"Step '{step.name}' depends on unknown step '{dep}'")


def build_outgoing_map(config: WorkflowConfig) -> dict[str, list[StepConfig]]:
    """Build mapping of source-step to dependents."""
    outgoing: dict[str, list[StepConfig]] = defaultdict(list)
    for step in config.steps:
        for dep in step.depends_on:
            outgoing[dep].append(step)
    return outgoing


def add_fan_out_edges(
    graph: StateGraph,
    source: str,
    unconditional: list[StepConfig],
    conditional: list[StepConfig],
) -> None:
    """Wire fan-out edges from one source to multiple dependents.

    All targets are always routed to.  Conditional targets self-skip
    inside their node function (via ``wrap_with_skip_check``) when
    their ``when`` expression evaluates to False.  This ensures that
    skipped nodes still fire their outgoing edges so downstream
    join-nodes are never orphaned.
    """
    all_names = [s.name for s in unconditional] + [s.name for s in conditional]

    path_map: dict[str, str] = {n: n for n in all_names}

    def _route(_state: WorkflowState) -> list[str]:
        return list(all_names)

    graph.add_conditional_edges(source, _route, path_map)


def wire_dependency_edges(
    graph: StateGraph,
    outgoing: dict[str, list[StepConfig]],
) -> None:
    """Wire dependency edges from the outgoing map."""
    for source, dependents in outgoing.items():
        unconditional = [s for s in dependents if not s.when]
        conditional = [s for s in dependents if s.when]
        if not conditional:
            for step in unconditional:
                graph.add_edge(source, step.name)
            continue
        add_fan_out_edges(graph, source, unconditional, conditional)


def add_terminal_edges(graph: StateGraph, config: WorkflowConfig) -> None:
    """Add END edges for terminal (non-loop) steps."""
    has_dependents: set[str] = set()
    for step in config.steps:
        has_dependents.update(step.depends_on)

    step_by_name = {step.name: step for step in config.steps}
    terminal_steps = [
        step.name for step in config.steps if step.name not in has_dependents
    ]
    for step_name in terminal_steps:
        step_cfg = step_by_name[step_name]
        if not step_cfg.loop_until:
            graph.add_edge(step_name, END)


def add_loop_edge(graph: StateGraph, step: StepConfig) -> None:
    """Add a self-loop: step re-runs until loop_until is True or loop_max."""
    loop_expr = step.loop_until

    def _loop_route(state: WorkflowState) -> str:
        step_data = state.get("steps", {}).get(step.name, {})

        # If the step was self-skipped, don't loop — proceed to END
        if step_data.get("status") == "skipped":
            return END

        # Check iteration count
        iteration = step_data.get("loop_iteration", 0)
        max_iters = resolve_loop_max(step, state)

        if iteration >= max_iters:
            return END

        if evaluate_condition(loop_expr, dict(state)):
            return END  # Condition met, stop looping

        return step.name  # Loop back

    graph.add_conditional_edges(
        step.name,
        _loop_route,
        {step.name: step.name, END: END},
    )


def add_loop_edges(graph: StateGraph, config: WorkflowConfig) -> None:
    """Add self-loop wiring for loop-enabled steps."""
    for step in config.steps:
        if step.loop_until:
            add_loop_edge(graph, step)


def compile_graph(graph: StateGraph, checkpointer: Any = None) -> Any:
    """Compile graph with optional checkpointer.

    Args:
        graph: Fully wired but uncompiled ``StateGraph``.
        checkpointer: Optional LangGraph checkpointer instance.  When
            provided, enables persistence, HITL interrupts, and time-travel
            debugging.  Requires ``langgraph>=1.2``.

    Returns:
        A compiled ``CompiledGraph`` ready to ``.invoke()`` or ``.stream()``.
    """
    if checkpointer is None:
        return graph.compile()
    return graph.compile(checkpointer=checkpointer)


def build_graph(
    config: WorkflowConfig,
    trace_adapter: TraceAdapter | None = None,
    *,
    validate_only: bool = False,
    _create_agent_fn: Any = None,
    _get_candidates_fn: Any = None,
) -> StateGraph:
    """Populate and return a fully wired (uncompiled) ``StateGraph``.

    Parameters
    ----------
    config:
        Parsed workflow config from YAML.
    trace_adapter:
        Optional trace adapter for step-level observability.
    validate_only:
        When True, wire graph topology without constructing live agents.
    _create_agent_fn:
        Override for ``create_agent`` (used by ``graph.py`` for monkeypatch support).
    _get_candidates_fn:
        Override for ``get_model_candidates_for_tier`` (same rationale).

    Returns
    -------
    A ``StateGraph`` with all nodes and edges added, ready for
    ``compile_graph()`` (or ``graph.compile()`` directly).
    """
    graph: StateGraph = StateGraph(WorkflowState)
    step_names = {s.name for s in config.steps}
    root_steps = [s.name for s in config.steps if not s.depends_on]

    add_step_nodes(
        graph,
        config,
        trace_adapter,
        validate_only=validate_only,
        _create_agent_fn=_create_agent_fn,
        _get_candidates_fn=_get_candidates_fn,
    )
    add_start_edges(graph, root_steps)
    validate_dependencies(config, step_names)
    wire_dependency_edges(graph, build_outgoing_map(config))
    add_terminal_edges(graph, config)
    add_loop_edges(graph, config)

    return graph
