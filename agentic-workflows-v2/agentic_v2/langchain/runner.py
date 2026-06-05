"""Top-level workflow runner.

Provides the high-level ``WorkflowRunner`` class that:
1. Loads a YAML workflow config
2. Validates inputs
3. Compiles it into a LangGraph
4. Executes (invoke / stream)
5. Resolves outputs

Result construction helpers are implemented in :mod:`.result_builder` and
imported here.  The private aliases ``_steps_dict_to_list`` and
``_build_workflow_result`` are kept at module level so any existing internal
call sites continue to work without change.
"""

from __future__ import annotations

import logging
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, AsyncIterator, Iterator

from ..contracts import WorkflowResult
from ..integrations.base import TraceAdapter
from ..integrations.tracing import NullTraceAdapter
from ..settings import get_settings
from .config import WorkflowConfig, list_workflows, load_workflow_config
from .expressions import resolve_expression
from .graph import compile_workflow
from .result_builder import (
    build_workflow_result,
    extract_metadata,
    steps_dict_to_list,
)
from .state import WorkflowState, initial_state

logger = logging.getLogger(__name__)

# Private aliases keep call-site names stable throughout this module.
_steps_dict_to_list = steps_dict_to_list
_build_workflow_result = build_workflow_result


def _checkpoint_thread_id(
    checkpointer: Any,
    *,
    thread_id: str | None,
    run_id: str,
) -> str | None:
    """Resolve the checkpoint thread identifier for a workflow execution."""
    if thread_id:
        return thread_id
    if checkpointer is None:
        return None
    return run_id


def _default_checkpointer() -> Any:
    """Return the platform default checkpointer (MemorySaver in-memory).

    Uses ``MemorySaver`` so each runner instance gets a fresh in-memory
    checkpoint store.  Callers wanting a persistent file-backed store should
    construct ``AsyncSqliteSaver`` themselves and inject it via the
    ``checkpointer`` parameter.

    If the import fails (langgraph not installed), emits a warning and
    returns ``None`` — the runner will then compile graphs without
    checkpointing, which defeats the "persistence on by default" contract
    but lets the test harness still construct a runner without the
    [langchain] extra installed.
    """
    try:
        from langgraph.checkpoint.memory import MemorySaver

        return MemorySaver()
    except ImportError:
        logger.warning(
            "_default_checkpointer: langgraph.checkpoint.memory.MemorySaver "
            "not available; WorkflowRunner will run WITHOUT checkpointing. "
            "Install the [langchain] extra (langgraph>=1.2) to enable "
            "persistence, HITL interrupts, and time-travel debugging."
        )
        return None



def _checkpointer_from_url(url: str) -> Any:
    """Build an AsyncPostgresSaver from a connection URL.

    Attempts to import ``langgraph.checkpoint.postgres.aio.AsyncPostgresSaver``.
    Falls back to ``_default_checkpointer()`` (in-memory MemorySaver) when the
    ``[postgres]`` extra is not installed, logging a warning so operators know
    the URL was ignored.

    Note: ``AsyncPostgresSaver.setup()`` (which creates the checkpoint tables)
    is *not* called here — callers that need the schema to exist must call it
    explicitly before the first workflow run.
    """
    try:
        from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

        return AsyncPostgresSaver.from_conn_string(url)
    except ImportError:
        logger.warning(
            "_checkpointer_from_url: langgraph-checkpoint-postgres is not "
            "installed; ignoring AGENTIC_CHECKPOINTER_URL and falling back to "
            "in-memory MemorySaver. Install the [postgres] extra to enable "
            "persistent checkpointing: pip install 'agentic-workflows-v2[postgres]'."
        )
        return _default_checkpointer()


_CONTEXT_SYNC_WORKFLOW_RESERVED_KEYS = frozenset({"inputs", "workflow_run_id"})
_CONTEXT_SYNC_PROTECTED_KEYS = frozenset(
    {
        "workflow_id",
        "run_id",
        "services",
        "start_time",
        "metadata",
        "current_step",
        "completed_steps",
        "failed_steps",
        "checkpoint_dir",
    }
)
_CONTEXT_SYNC_DYNAMIC_KEY_ATTRS = (
    "RESERVED_KEYS",
    "_RESERVED_KEYS",
    "PROTECTED_KEYS",
    "_PROTECTED_KEYS",
    "PROTECTED_FIELDS",
    "_PROTECTED_FIELDS",
    "PROTECTED_VARIABLE_KEYS",
    "_PROTECTED_VARIABLE_KEYS",
    "RESERVED_VARIABLE_KEYS",
    "_RESERVED_VARIABLE_KEYS",
    "reserved_keys",
    "_reserved_keys",
    "protected_keys",
    "_protected_keys",
    "protected_fields",
    "_protected_fields",
)


def _declared_context_sync_skip_keys(ctx: Any) -> set[str]:
    """Return context keys that must never be written back to ``ctx``."""
    skip_keys = set(_CONTEXT_SYNC_WORKFLOW_RESERVED_KEYS)
    skip_keys.update(_CONTEXT_SYNC_PROTECTED_KEYS)

    module = sys.modules.get(type(ctx).__module__)
    owners = (ctx, type(ctx), module) if module is not None else (ctx, type(ctx))

    for owner in owners:
        for attr in _CONTEXT_SYNC_DYNAMIC_KEY_ATTRS:
            value = getattr(owner, attr, None)
            if isinstance(value, (dict, frozenset, list, set, tuple)):
                skip_keys.update(str(key) for key in value)

    return skip_keys


def _merge_execution_context_into_state(
    state: WorkflowState | dict[str, Any],
    ctx: Any,
    workflow_name: str,
    *,
    stream: bool = False,
) -> None:
    """Merge caller-supplied context variables into LangGraph state."""
    all_variables = getattr(ctx, "all_variables", None)
    if not callable(all_variables):
        return

    ctx_vars = all_variables()
    if not isinstance(ctx_vars, dict):
        logger.debug(
            "ExecutionContext all_variables() returned %s for workflow %r; "
            "skipping context merge.",
            type(ctx_vars).__name__,
            workflow_name,
        )
        return

    if not ctx_vars:
        return

    logger.debug(
        "Merging %d ExecutionContext variable(s) into LangGraph state "
        "for workflow %r%s",
        len(ctx_vars),
        workflow_name,
        " (astream)" if stream else "",
    )
    # Workflow-level keys (inputs, workflow_run_id) take precedence.
    merged = {**ctx_vars, **state["context"]}
    state["context"] = merged


def _set_execution_context_variable(ctx: Any, key: str, value: Any) -> bool:
    """Set one variable on an ExecutionContext-like object when supported."""
    set_sync = getattr(ctx, "set_sync", None)
    if callable(set_sync):
        set_sync(key, value)
        return True

    variables = getattr(ctx, "_variables", None)
    if isinstance(variables, dict):
        variables[key] = value
        return True

    return False


def _sync_execution_context_from_state(
    ctx: Any,
    final_state: dict[str, Any],
    workflow_name: str,
) -> None:
    """Write safe final ``state["context"]`` values back into ``ctx``."""
    final_context = final_state.get("context")
    if not isinstance(final_context, dict):
        return

    skip_keys = _declared_context_sync_skip_keys(ctx)
    synced = 0

    for key, value in final_context.items():
        if not isinstance(key, str) or key.startswith("_") or key in skip_keys:
            continue

        try:
            if _set_execution_context_variable(ctx, key, value):
                synced += 1
        except Exception:
            logger.warning(
                "Failed to sync LangGraph context key %r back into "
                "ExecutionContext for workflow %r.",
                key,
                workflow_name,
                exc_info=True,
            )

    if synced:
        logger.debug(
            "Synced %d LangGraph context key(s) back into ExecutionContext "
            "for workflow %r.",
            synced,
            workflow_name,
        )


class WorkflowRunner:
    """Load, validate, compile, and execute YAML workflows.

    Usage::

        runner = WorkflowRunner()
        result = await runner.run("code_review", code_file="main.py")

    Or synchronously::

        result = runner.invoke("code_review", code_file="main.py")
    """

    def __init__(
        self,
        definitions_dir: Path | None = None,
        checkpointer: Any = None,
        checkpointer_url: str | None = None,
        trace_adapter: TraceAdapter | None = None,
    ):
        """
        Parameters
        ----------
        definitions_dir:
            Directory containing YAML workflow files.
        checkpointer:
            Optional LangGraph checkpointer instance (e.g. ``MemorySaver()``).
            Takes precedence over ``checkpointer_url`` and
            ``AGENTIC_CHECKPOINTER_URL``.
        checkpointer_url:
            Optional PostgreSQL connection URL for persistent checkpointing
            (e.g. ``'postgresql://user:pass@host:5432/db'``).  Requires the
            ``[postgres]`` extra.  When omitted, falls back to the
            ``AGENTIC_CHECKPOINTER_URL`` environment variable, then to the
            default in-memory ``MemorySaver``.
        trace_adapter:
            Optional trace adapter for workflow-level observability.
        """
        self._definitions_dir = definitions_dir
        if checkpointer is not None:
            self._checkpointer = checkpointer
        else:
            url = checkpointer_url or get_settings().agentic_checkpointer_url
            self._checkpointer = (
                _checkpointer_from_url(url) if url else _default_checkpointer()
            )
        self._trace_adapter = (
            trace_adapter if trace_adapter is not None else NullTraceAdapter()
        )
        self._graph_cache: dict[tuple[str, int | None, int], Any] = {}

    # -----------------------------------------------------------------
    # Public API
    # -----------------------------------------------------------------

    def invoke(
        self,
        workflow_name: str,
        *,
        use_cache: bool = True,
        thread_id: str | None = None,
        run_config: dict[str, Any] | None = None,
        **inputs: Any,
    ) -> WorkflowResult:
        """Run a workflow synchronously.

        Parameters
        ----------
        workflow_name:
            Name of the YAML workflow (without extension).
        inputs:
            Keyword arguments matching the workflow's declared inputs.
        """
        config = load_workflow_config(workflow_name, self._definitions_dir)
        validated = self._validate_inputs(config, inputs)
        graph = self._get_or_compile(config, use_cache)
        run_id = thread_id or str(uuid.uuid4())
        langgraph_config = self._build_langgraph_config(
            _checkpoint_thread_id(
                self._checkpointer,
                thread_id=thread_id,
                run_id=run_id,
            ),
            run_config,
        )

        self._trace_adapter.emit_workflow_start(workflow_name, run_id, validated)

        state = initial_state(workflow_inputs=validated)
        # Seed context with inputs so ${inputs.X} resolves
        state["context"]["inputs"] = validated
        # Seed workflow_run_id for step tracing
        state["context"]["workflow_run_id"] = run_id

        started_at = datetime.now(UTC)
        start = time.perf_counter()
        try:
            final = graph.invoke(state, config=langgraph_config)
        except Exception as e:
            elapsed = time.perf_counter() - start
            self._trace_adapter.emit_workflow_end(
                workflow_name,
                run_id,
                "failed",
                {"errors": [str(e)]},
            )
            return _build_workflow_result(
                workflow_name=workflow_name,
                run_id=run_id,
                started_at=started_at,
                elapsed_seconds=elapsed,
                errors=[str(e)],
                failed=True,
            )

        elapsed = time.perf_counter() - start

        # Resolve declared outputs
        outputs = self.resolve_outputs(config, final)

        token_counts, models_used = self.extract_metadata(final)
        errors = [str(e) for e in final.get("errors", []) if e]
        step_results = _steps_dict_to_list(
            final.get("steps", {}), token_counts, models_used
        )
        result = _build_workflow_result(
            workflow_name=workflow_name,
            run_id=run_id,
            started_at=started_at,
            elapsed_seconds=elapsed,
            final_state=dict(final),
            outputs=outputs,
            steps=step_results,
            errors=errors,
            token_counts=token_counts,
            models_used=models_used,
        )
        self._trace_adapter.emit_workflow_end(
            workflow_name,
            run_id,
            result.overall_status.value,
            result.final_output,
        )
        return result

    async def run(
        self,
        workflow_name: str,
        *,
        ctx: Any = None,
        use_cache: bool = True,
        thread_id: str | None = None,
        run_config: dict[str, Any] | None = None,
        **inputs: Any,
    ) -> WorkflowResult:
        """Run a workflow asynchronously.

        Parameters
        ----------
        workflow_name:
            Name of the YAML workflow.
        ctx:
            Optional execution context.  When supplied, its variables are
            merged into the LangGraph ``state["context"]`` so that workflow
            steps can access caller-supplied state (e.g. ``workflow_id``,
            ``run_id``, and any variables set on the context before the run).
        inputs:
            Keyword arguments matching the workflow's declared inputs.
        """
        config = load_workflow_config(workflow_name, self._definitions_dir)
        validated = self._validate_inputs(config, inputs)
        graph = self._get_or_compile(config, use_cache)
        run_id = thread_id or str(uuid.uuid4())
        langgraph_config = self._build_langgraph_config(
            _checkpoint_thread_id(
                self._checkpointer,
                thread_id=thread_id,
                run_id=run_id,
            ),
            run_config,
        )

        self._trace_adapter.emit_workflow_start(workflow_name, run_id, validated)

        state = initial_state(workflow_inputs=validated)
        state["context"]["inputs"] = validated
        # Ensure step-level trace events can be correlated to this run.
        state["context"]["workflow_run_id"] = run_id

        # Merge caller-supplied execution context variables into LangGraph state
        # so that downstream step nodes can access them via state["context"].
        if ctx is not None:
            _merge_execution_context_into_state(state, ctx, workflow_name)

        started_at = datetime.now(UTC)
        start = time.perf_counter()
        try:
            final = await graph.ainvoke(state, config=langgraph_config)
        except Exception as e:
            elapsed = time.perf_counter() - start
            self._trace_adapter.emit_workflow_end(
                workflow_name,
                run_id,
                "failed",
                {"errors": [str(e)]},
            )
            return _build_workflow_result(
                workflow_name=workflow_name,
                run_id=run_id,
                started_at=started_at,
                elapsed_seconds=elapsed,
                errors=[str(e)],
                failed=True,
            )

        elapsed = time.perf_counter() - start
        if ctx is not None:
            _sync_execution_context_from_state(ctx, final, workflow_name)
        outputs = self.resolve_outputs(config, final)

        token_counts, models_used = self.extract_metadata(final)
        errors = [str(e) for e in final.get("errors", []) if e]
        step_results = _steps_dict_to_list(
            final.get("steps", {}), token_counts, models_used
        )
        result = _build_workflow_result(
            workflow_name=workflow_name,
            run_id=run_id,
            started_at=started_at,
            elapsed_seconds=elapsed,
            final_state=dict(final),
            outputs=outputs,
            steps=step_results,
            errors=errors,
            token_counts=token_counts,
            models_used=models_used,
        )
        self._trace_adapter.emit_workflow_end(
            workflow_name,
            run_id,
            result.overall_status.value,
            result.final_output,
        )
        return result

    def stream(
        self,
        workflow_name: str,
        *,
        use_cache: bool = True,
        thread_id: str | None = None,
        run_config: dict[str, Any] | None = None,
        **inputs: Any,
    ) -> Iterator[dict[str, Any]]:
        """Stream workflow execution events synchronously."""
        config = load_workflow_config(workflow_name, self._definitions_dir)
        validated = self._validate_inputs(config, inputs)
        graph = self._get_or_compile(config, use_cache)
        run_id = thread_id or str(uuid.uuid4())
        langgraph_config = self._build_langgraph_config(
            _checkpoint_thread_id(
                self._checkpointer,
                thread_id=thread_id,
                run_id=run_id,
            ),
            run_config,
        )

        state = initial_state(workflow_inputs=validated)
        state["context"]["inputs"] = validated
        # Ensure step-level trace events can be correlated to this run.
        state["context"]["workflow_run_id"] = run_id

        self._trace_adapter.emit_workflow_start(workflow_name, run_id, validated)

        stream_failed = False
        stream_error = ""

        try:
            yield from graph.stream(state, config=langgraph_config)
        except Exception as e:
            stream_failed = True
            stream_error = str(e)
            raise
        finally:
            self._trace_adapter.emit_workflow_end(
                workflow_name,
                run_id,
                "failed" if stream_failed else "success",
                {"errors": [stream_error]} if stream_failed else {},
            )

    async def astream(
        self,
        workflow_name: str,
        *,
        ctx: Any = None,
        use_cache: bool = True,
        thread_id: str | None = None,
        run_config: dict[str, Any] | None = None,
        **inputs: Any,
    ) -> AsyncIterator[dict[str, Any]]:
        """Stream workflow execution events asynchronously.

        Parameters
        ----------
        workflow_name:
            Name of the YAML workflow.
        ctx:
            Optional execution context.  When supplied, its variables are
            merged into the LangGraph ``state["context"]`` before streaming
            begins.  Final context values are not synced back into ``ctx``:
            supported LangGraph ``astream`` implementations yield event
            deltas, not one reliable aggregate final state.
        inputs:
            Keyword arguments matching the workflow's declared inputs.
        """
        config = load_workflow_config(workflow_name, self._definitions_dir)
        validated = self._validate_inputs(config, inputs)
        graph = self._get_or_compile(config, use_cache)
        run_id = thread_id or str(uuid.uuid4())
        langgraph_config = self._build_langgraph_config(
            _checkpoint_thread_id(
                self._checkpointer,
                thread_id=thread_id,
                run_id=run_id,
            ),
            run_config,
        )

        state = initial_state(workflow_inputs=validated)
        state["context"]["inputs"] = validated
        # Ensure step-level trace events can be correlated to this run.
        state["context"]["workflow_run_id"] = run_id

        # Merge caller-supplied execution context variables into LangGraph state.
        if ctx is not None:
            _merge_execution_context_into_state(
                state,
                ctx,
                workflow_name,
                stream=True,
            )

        self._trace_adapter.emit_workflow_start(workflow_name, run_id, validated)

        stream_failed = False
        stream_error = ""

        try:
            async for event in graph.astream(state, config=langgraph_config):
                yield event
        except Exception as e:
            stream_failed = True
            stream_error = str(e)
            raise
        finally:
            # LangGraph's async streaming API does not consistently expose a
            # final aggregate WorkflowState; callers that need ExecutionContext
            # sync should use run(), which receives the final state from ainvoke().
            self._trace_adapter.emit_workflow_end(
                workflow_name,
                run_id,
                "failed" if stream_failed else "success",
                {"errors": [stream_error]} if stream_failed else {},
            )

    def get_checkpoint_state(
        self,
        workflow_name: str,
        *,
        thread_id: str,
        use_cache: bool = True,
        run_config: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Return latest checkpoint state snapshot for a thread, if available."""
        config = load_workflow_config(workflow_name, self._definitions_dir)
        graph = self._get_or_compile(config, use_cache)
        langgraph_config = self._build_langgraph_config(thread_id, run_config)

        try:
            snapshot = graph.get_state(config=langgraph_config)
        except (AttributeError, TypeError):
            return None

        if snapshot is None:
            return None

        return {
            "values": getattr(snapshot, "values", None),
            "next": list(getattr(snapshot, "next", ()) or ()),
            "metadata": getattr(snapshot, "metadata", None),
            "created_at": getattr(snapshot, "created_at", None),
        }

    def get_checkpoint_history(
        self,
        workflow_name: str,
        *,
        thread_id: str,
        use_cache: bool = True,
        run_config: dict[str, Any] | None = None,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """Return checkpoint history snapshots for a thread when supported."""
        config = load_workflow_config(workflow_name, self._definitions_dir)
        graph = self._get_or_compile(config, use_cache)
        langgraph_config = self._build_langgraph_config(thread_id, run_config)

        try:
            history_iter = graph.get_state_history(config=langgraph_config)
        except (AttributeError, TypeError):
            return []

        snapshots: list[dict[str, Any]] = []
        for idx, snapshot in enumerate(history_iter):
            if idx >= limit:
                break
            snapshots.append(
                {
                    "values": getattr(snapshot, "values", None),
                    "next": list(getattr(snapshot, "next", ()) or ()),
                    "metadata": getattr(snapshot, "metadata", None),
                    "created_at": getattr(snapshot, "created_at", None),
                }
            )
        return snapshots

    def resume(
        self,
        workflow_name: str,
        *,
        thread_id: str,
        use_cache: bool = True,
        run_config: dict[str, Any] | None = None,
    ) -> WorkflowResult:
        """Resume an interrupted workflow from the latest checkpoint thread state."""
        config = load_workflow_config(workflow_name, self._definitions_dir)
        graph = self._get_or_compile(config, use_cache)
        langgraph_config = self._build_langgraph_config(thread_id, run_config)

        started_at = datetime.now(UTC)
        start = time.perf_counter()
        self._trace_adapter.emit_workflow_start(
            workflow_name,
            thread_id,
            {"resume": True},
        )

        try:
            final = graph.invoke(None, config=langgraph_config)
        except Exception as e:
            elapsed = time.perf_counter() - start
            self._trace_adapter.emit_workflow_end(
                workflow_name,
                thread_id,
                "failed",
                {"errors": [str(e)]},
            )
            return _build_workflow_result(
                workflow_name=workflow_name,
                run_id=thread_id,
                started_at=started_at,
                elapsed_seconds=elapsed,
                errors=[str(e)],
                failed=True,
            )

        elapsed = time.perf_counter() - start
        outputs = self.resolve_outputs(config, final)
        token_counts, models_used = self.extract_metadata(final)
        errors = [str(e) for e in final.get("errors", []) if e]
        step_results = _steps_dict_to_list(
            final.get("steps", {}), token_counts, models_used
        )
        result = _build_workflow_result(
            workflow_name=workflow_name,
            run_id=thread_id,
            started_at=started_at,
            elapsed_seconds=elapsed,
            final_state=dict(final),
            outputs=outputs,
            steps=step_results,
            errors=errors,
            token_counts=token_counts,
            models_used=models_used,
        )
        self._trace_adapter.emit_workflow_end(
            workflow_name,
            thread_id,
            result.overall_status.value,
            result.final_output,
        )
        return result

    def list_workflows(self) -> list[str]:
        """List available workflow names."""
        return list_workflows(self._definitions_dir)

    @staticmethod
    def extract_metadata(
        final_state: dict[str, Any],
    ) -> tuple[dict[str, dict], dict[str, str]]:
        """Extract token counts and models used from final workflow state.

        Delegates to :func:`.result_builder.extract_metadata`.
        """
        return extract_metadata(final_state)

    # -----------------------------------------------------------------
    # Internal
    # -----------------------------------------------------------------

    def _get_or_compile(self, config: WorkflowConfig, use_cache: bool) -> Any:
        """Compile a WorkflowConfig to a graph, with optional caching."""
        cache_key = (
            config.name,
            id(self._checkpointer) if self._checkpointer is not None else None,
            id(self._trace_adapter),
        )

        if use_cache and cache_key in self._graph_cache:
            return self._graph_cache[cache_key]

        compiled = compile_workflow(
            config,
            checkpointer=self._checkpointer,
            trace_adapter=self._trace_adapter,
        )
        if use_cache:
            self._graph_cache[cache_key] = compiled
        return compiled

    @staticmethod
    def _build_langgraph_config(
        thread_id: str | None,
        run_config: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Build LangGraph runtime config with optional thread checkpoint key."""
        config: dict[str, Any] = dict(run_config or {})

        if thread_id:
            configurable = dict(config.get("configurable", {}))
            configurable["thread_id"] = thread_id
            config["configurable"] = configurable

        return config

    def _validate_inputs(
        self,
        config: WorkflowConfig,
        supplied: dict[str, Any],
    ) -> dict[str, Any]:
        """Validate and apply defaults for workflow inputs."""
        result: dict[str, Any] = {}
        errors: list[str] = []

        for name, input_cfg in config.inputs.items():
            if name in supplied:
                value = supplied[name]
                # Treat empty string as missing for required string inputs
                if input_cfg.required and isinstance(value, str) and not value.strip():
                    errors.append(f"Required input '{name}' must not be empty")
                    continue
                # Enum validation
                if input_cfg.enum and value not in input_cfg.enum:
                    errors.append(
                        f"Input '{name}' must be one of {input_cfg.enum}, "
                        f"got '{value}'"
                    )
                result[name] = value
            elif input_cfg.default is not None:
                result[name] = input_cfg.default
            elif input_cfg.required:
                errors.append(f"Missing required input: '{name}'")

        if errors:
            raise ValueError(
                f"Input validation failed for '{config.name}': " + "; ".join(errors)
            )

        return result

    @staticmethod
    def resolve_outputs(
        config: WorkflowConfig,
        final_state: dict[str, Any],
    ) -> dict[str, Any]:
        """Resolve declared outputs from final state."""
        outputs: dict[str, Any] = {}

        for name, output_cfg in config.outputs.items():
            value = resolve_expression(output_cfg.from_expr, final_state)
            if value is not None:
                outputs[name] = value
            elif not output_cfg.optional:
                logger.warning("Output '%s' could not be resolved", name)

        return outputs
