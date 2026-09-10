"""LangChain execution engine — wraps the existing WorkflowRunner.

:class:`LangChainEngine` satisfies both the :class:`ExecutionEngine` and
:class:`SupportsStreaming` protocols by delegating to the
:class:`~agentic_v2.langchain.runner.WorkflowRunner` methods.

This adapter is a thin wrapper — it does **not** re-implement any
LangGraph compilation or state management logic.  All heavy lifting
is handled by the existing ``agentic_v2.langchain`` package.

LangChain/LangGraph imports are guarded with ``try/except ImportError``
so the module can be safely imported even when those packages are not
installed (registration simply won't occur).
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, AsyncIterator, Awaitable, Callable, Mapping

from ...contracts import WorkflowResult
from ...core.errors import ConfigurationError
from ...langchain.config import WorkflowConfig
from ...langchain.dependencies import (
    is_missing_langchain_dependency_error,
    to_missing_langchain_dependency_error,
)

logger = logging.getLogger(__name__)

try:
    from ...langchain.runner import WorkflowRunner as _WorkflowRunner

    _HAS_LANGCHAIN = True
    _LANGCHAIN_IMPORT_ERROR: ImportError | None = None
except ImportError as exc:  # pragma: no cover
    if not is_missing_langchain_dependency_error(exc):
        raise
    _HAS_LANGCHAIN = False
    _LANGCHAIN_IMPORT_ERROR = to_missing_langchain_dependency_error(
        exc,
        install_hint="pip install langchain langgraph",
    )
    _WorkflowRunner = None  # type: ignore[assignment,misc]


class LangChainEngine:
    """Adapter that delegates to the LangChain ``WorkflowRunner``.

    Satisfies :class:`~agentic_v2.core.protocols.ExecutionEngine` and
    :class:`~agentic_v2.core.protocols.SupportsStreaming` via structural
    subtyping — no explicit inheritance required.

    ``execute`` and ``stream`` accept a YAML name/path or a LangChain
    ``WorkflowConfig`` (the parsed inputs, outputs, and StepConfig list).
    Loaded configs execute their supplied contents, bypassing the name cache.
    Native ``WorkflowDefinition``/DAG objects are not supported.

    Args:
        runner: An existing :class:`WorkflowRunner` instance.  If ``None``
            (the default), a fresh runner is created on first use.
    """

    def __init__(self, runner: Any = None) -> None:
        self._runner = runner

    @classmethod
    def validate_configuration(cls) -> None:
        """Raise if the LangChain/LangGraph extras are not importable.

        Called by :meth:`~agentic_v2.adapters.registry.AdapterRegistry.validate_selected`.
        Performs a live import attempt rather than trusting the
        module-load-time ``_HAS_LANGCHAIN`` flag above, since a caller may
        want to detect an environment change (e.g. tests simulate a
        missing extra via ``sys.modules`` after this module already
        imported successfully).

        Raises:
            ConfigurationError: If ``langchain`` or ``langgraph`` cannot be
                imported, with an actionable install hint.
        """
        try:
            import langchain  # noqa: F401
            import langgraph  # noqa: F401
        except ImportError as exc:
            raise ConfigurationError(
                "LangChain engine selected but extras not installed. "
                "Install with: pip install -e '.[langchain]'"
            ) from exc
        logger.debug("LangChain adapter validation passed")

    @property
    def runner(self) -> Any:
        """Lazily create the underlying ``WorkflowRunner`` if needed."""
        if self._runner is None:
            if not _HAS_LANGCHAIN:
                assert _LANGCHAIN_IMPORT_ERROR is not None
                raise _LANGCHAIN_IMPORT_ERROR
            self._runner = _WorkflowRunner()
        return self._runner

    @staticmethod
    def _validate_workflow(workflow: Any) -> str | Path | WorkflowConfig:
        """Reject incompatible definitions instead of reloading their name."""
        if isinstance(workflow, (str, Path, WorkflowConfig)):
            return workflow
        raise TypeError(
            "LangChainEngine workflow name must be a string or Path, or supply "
            "a LangChain WorkflowConfig; native WorkflowDefinition/DAG objects "
            f"are unsupported (got {type(workflow).__name__})"
        )

    def load_workflow(
        self, workflow_name: str, *, definitions_dir: Path | None = None
    ) -> WorkflowConfig:
        """Load a YAML name/path using this engine's runner and directory default.

        The returned config is an independent copy, safe for caller
        edits. A per-call directory affects loading only; tracing and
        checkpoints remain attached to the injected runner.
        """
        return self.runner.load_workflow(workflow_name, definitions_dir=definitions_dir)

    def _execution_workflow(
        self, workflow: Any, definitions_dir: Path | None
    ) -> str | Path | WorkflowConfig:
        workflow = self._validate_workflow(workflow)
        if definitions_dir is not None and not isinstance(workflow, WorkflowConfig):
            return self.load_workflow(str(workflow), definitions_dir=definitions_dir)
        return workflow

    async def execute(
        self,
        workflow: Any,
        ctx: Any = None,
        on_update: Callable[[dict[str, Any]], Awaitable[None]] | None = None,
        *,
        definitions_dir: Path | None = None,
        workflow_inputs: Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> WorkflowResult:
        """Execute a YAML name/path or the contents of a loaded WorkflowConfig.

        Args:
            workflow: YAML name/path or LangChain ``WorkflowConfig``.
            ctx: Execution context forwarded to
                :meth:`WorkflowRunner.run`.  When the context has an
                ``all_variables()`` method (i.e. is an
                :class:`~agentic_v2.engine.context.ExecutionContext`),
                its variables are merged into the LangGraph state before
                execution begins.
            definitions_dir: Optional directory to resolve *workflow*
                from, for a workflow loaded from an arbitrary YAML file
                path rather than the default definitions directory.
            on_update: Awaited callback receiving real ``step_start``,
                ``step_end``, and ``step_error`` events. Callback exceptions
                propagate without replaying execution.
            workflow_inputs: Structured workflow data; keys cannot collide
                with execution controls. These values override legacy keyword
                inputs with the same name.
            **kwargs: Forwarded as keyword inputs to
                :meth:`WorkflowRunner.run`.

        Returns:
            :class:`~agentic_v2.contracts.WorkflowResult` produced by
            the runner.

        Raises:
            TypeError: If *workflow* is not a YAML name/path or WorkflowConfig.
        """
        workflow = self._execution_workflow(workflow, definitions_dir)
        if on_update is not None:
            kwargs["on_update"] = on_update
        if workflow_inputs is not None:
            kwargs["workflow_inputs"] = workflow_inputs
        return await self.runner.run(workflow, ctx=ctx, **kwargs)

    async def stream(
        self,
        workflow: Any,
        ctx: Any = None,
        *,
        definitions_dir: Path | None = None,
        workflow_inputs: Mapping[str, Any] | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[dict[str, Any]]:
        """Stream execution events for a workflow.

        Args:
            workflow: YAML name/path or LangChain ``WorkflowConfig``.
            ctx: Execution context forwarded to
                :meth:`WorkflowRunner.astream` so that caller-supplied
                variables are merged into LangGraph state before streaming.
            definitions_dir: Optional directory to resolve *workflow*
                from; see :meth:`execute`.
            workflow_inputs: Structured workflow data, overriding legacy
                keyword inputs. See :meth:`execute`.
            **kwargs: Forwarded as keyword inputs to
                :meth:`WorkflowRunner.astream`.

        Yields:
            Event dictionaries from the LangGraph execution.

        Raises:
            TypeError: If *workflow* is not a YAML name/path or WorkflowConfig.
        """
        workflow = self._execution_workflow(workflow, definitions_dir)
        if workflow_inputs is not None:
            kwargs["workflow_inputs"] = workflow_inputs
        async for event in self.runner.astream(workflow, ctx=ctx, **kwargs):
            yield event
