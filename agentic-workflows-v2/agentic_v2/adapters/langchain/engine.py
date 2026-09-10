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
from typing import Any, AsyncIterator

from ...core.errors import ConfigurationError
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

    The ``workflow`` argument to :meth:`execute` and :meth:`stream` must
    be a **string** naming a YAML workflow definition (e.g. ``"code_review"``).

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
    def _resolve_workflow_name(workflow: Any) -> str:
        """Accept either a workflow name or an already-loaded definition.

        Native's ``NativeEngine.execute()`` accepts an already-loaded
        ``WorkflowDefinition`` alongside its compiled ``DAG``/``Pipeline``
        forms; this mirrors that so callers can load a workflow once (by
        name or by file path) and pass the same object to whichever
        adapter they selected, instead of special-casing "langchain wants
        a bare name" at every call site.
        """
        if isinstance(workflow, str):
            return workflow
        name = getattr(workflow, "name", None)
        if isinstance(name, str) and name:
            return name
        raise TypeError(
            f"LangChainEngine workflow name must be a string (or an "
            f"object with a 'name' attribute), got {type(workflow).__name__}"
        )

    def _runner_for(self, definitions_dir: Path | None) -> Any:
        """Return the runner to use, honoring a per-call *definitions_dir*.

        The cached :attr:`runner` singleton is built once with no
        directory override, for the common case of running a registered
        workflow by name.  A caller resolving a workflow from an
        arbitrary YAML file path (e.g. ``agentic run ./my_workflow.yaml``)
        needs a runner scoped to that file's directory instead, so this
        builds a one-off runner rather than mutating the shared instance.
        """
        if definitions_dir is None:
            return self.runner
        if not _HAS_LANGCHAIN:
            assert _LANGCHAIN_IMPORT_ERROR is not None
            raise _LANGCHAIN_IMPORT_ERROR
        return _WorkflowRunner(definitions_dir=definitions_dir)

    async def execute(
        self,
        workflow: Any,
        ctx: Any = None,
        *,
        definitions_dir: Path | None = None,
        **kwargs: Any,
    ) -> Any:
        """Execute a workflow by name via the LangChain runner.

        Args:
            workflow: Workflow name string (e.g. ``"code_review"``), or an
                already-loaded object exposing a ``.name`` attribute (e.g.
                a :class:`~agentic_v2.langchain.config.WorkflowConfig` or
                :class:`~agentic_v2.workflows.loader.WorkflowDefinition`).
            ctx: Execution context forwarded to
                :meth:`WorkflowRunner.run`.  When the context has an
                ``all_variables()`` method (i.e. is an
                :class:`~agentic_v2.engine.context.ExecutionContext`),
                its variables are merged into the LangGraph state before
                execution begins.
            definitions_dir: Optional directory to resolve *workflow*
                from, for a workflow loaded from an arbitrary YAML file
                path rather than the default definitions directory.
            **kwargs: Forwarded as keyword inputs to
                :meth:`WorkflowRunner.run`.

        Returns:
            :class:`~agentic_v2.contracts.WorkflowResult` produced by
            the runner.

        Raises:
            TypeError: If *workflow* is not a string or name-bearing object.
        """
        workflow_name = self._resolve_workflow_name(workflow)

        logger.debug(
            "LangChainEngine.execute: forwarding ctx=%r to runner.run for workflow %r",
            ctx,
            workflow_name,
        )
        runner = self._runner_for(definitions_dir)
        return await runner.run(workflow_name, ctx=ctx, **kwargs)

    async def stream(
        self,
        workflow: Any,
        ctx: Any = None,
        *,
        definitions_dir: Path | None = None,
        **kwargs: Any,
    ) -> AsyncIterator[dict[str, Any]]:
        """Stream execution events for a workflow.

        Args:
            workflow: Workflow name string, or an already-loaded object
                exposing a ``.name`` attribute (see :meth:`execute`).
            ctx: Execution context forwarded to
                :meth:`WorkflowRunner.astream` so that caller-supplied
                variables are merged into LangGraph state before streaming.
            definitions_dir: Optional directory to resolve *workflow*
                from; see :meth:`execute`.
            **kwargs: Forwarded as keyword inputs to
                :meth:`WorkflowRunner.astream`.

        Yields:
            Event dictionaries from the LangGraph execution.

        Raises:
            TypeError: If *workflow* is not a string or name-bearing object.
        """
        workflow_name = self._resolve_workflow_name(workflow)

        logger.debug(
            "LangChainEngine.stream: forwarding ctx=%r to runner.astream for workflow %r",
            ctx,
            workflow_name,
        )
        runner = self._runner_for(definitions_dir)
        async for event in runner.astream(workflow_name, ctx=ctx, **kwargs):
            yield event
