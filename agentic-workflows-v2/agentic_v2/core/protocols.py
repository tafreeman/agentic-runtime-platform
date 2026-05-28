r"""Core protocols — engine-agnostic interfaces for the workflow system.

Defines the structural subtyping contracts (PEP 544) that all execution
engines, agents, tools, and memory stores must satisfy.  Uses
``typing.Protocol`` so existing classes conform implicitly by shape
without inheriting from these types.

Why Protocol over ABC:
- **Structural subtyping** — conformance checked by shape, not lineage.
- **No runtime cost** — erased at runtime; no ``super().__init__()`` needed.
- **Gradual adoption** — opt-in ``runtime_checkable`` verification.

Type-safety notes (Sprint C1):
- ``ctx`` parameters are typed as ``Optional[ExecutionContext]`` — every
  known implementation accepts this type.
- ``ExecutionEngine.execute()`` returns ``WorkflowResult`` — verified
  across DAGExecutor, PipelineExecutor, WorkflowExecutor, NativeEngine,
  and LangChainEngine.
- ``workflow`` remains ``Any`` because different engines accept different
  representations (``DAG``, ``Pipeline``, ``str``, etc.).
- ``AgentProtocol.run()`` uses ``object`` — enforces explicit casting at call
  sites.  Concrete agents use the bounded ``TypeVar``\s (``TInput``,
  ``TOutput``) defined in ``agents.base``.
- Imports guarded by ``TYPE_CHECKING`` to prevent circular imports
  (``core/`` <- ``engine/`` <- ``core/``).
"""

from __future__ import annotations

from typing import (
    TYPE_CHECKING,
    Any,
    AsyncIterator,
    Awaitable,
    Callable,
    Optional,
    Protocol,
    Sequence,
    runtime_checkable,
)

if TYPE_CHECKING:
    from ..contracts import WorkflowResult as _WorkflowResult
    from ..contracts.sanitization import Finding as _Finding
    from ..contracts.sanitization import SanitizationResult as _SanitizationResult
    from ..contracts.verification import VerificationPolicy as _VerificationPolicy
    from ..contracts.verification import VerificationStatus as _VerificationStatus
    from ..engine.context import ExecutionContext as _ExecutionContext
else:
    _ExecutionContext = Any
    _Finding = Any
    _SanitizationResult = Any
    _VerificationPolicy = Any
    _VerificationStatus = Any
    _WorkflowResult = Any


@runtime_checkable
class ExecutionEngine(Protocol):
    """Common interface for workflow execution engines.

    Any class with a matching ``execute`` signature satisfies this protocol
    via structural subtyping — no explicit inheritance required.

    Implementations:
    - ``DAGExecutor`` — Kahn's algorithm scheduler, maximum parallelism
    - ``PipelineExecutor`` — sequential pipeline execution
    - ``WorkflowExecutor`` — polymorphic executor
    - ``LangChainEngine`` — LangGraph state-machine compiler (via adapter)

    All engines MUST:
    - Accept an execution context for shared state
    - Return a ``WorkflowResult`` with step results, status, and timing
    - Call ``on_update`` (if provided) for real-time progress reporting
    - Propagate exceptions from individual steps
    - Never mutate the workflow definition in-place
    """

    async def execute(
        self,
        workflow: Any,
        ctx: Optional[_ExecutionContext] = None,
        on_update: Optional[Callable[[dict[str, Any]], Awaitable[None]]] = None,
        **kwargs: Any,
    ) -> _WorkflowResult:
        """Execute a workflow and return results.

        Args:
            workflow: Engine-specific workflow definition (``DAG``, ``Pipeline``,
                workflow name string, etc.).  Typed as ``Any`` because each
                engine accepts a different representation.
            ctx: Execution context with shared variables and services.
            on_update: Async callback fired on step start/end/error events.
            **kwargs: Engine-specific options (e.g., ``max_concurrency``).

        Returns:
            ``WorkflowResult`` with ordered step results, aggregate status,
            final outputs, and timing metadata.
        """
        ...


@runtime_checkable
class SupportsStreaming(Protocol):
    """Optional capability: streaming execution events."""

    async def stream(
        self,
        workflow: Any,
        ctx: Optional[_ExecutionContext] = None,
        **kwargs: Any,
    ) -> AsyncIterator[dict[str, Any]]:
        """Stream execution events as an async iterator."""
        ...


@runtime_checkable
class SupportsCheckpointing(Protocol):
    """Optional capability: execution checkpointing."""

    def get_checkpoint_state(
        self,
        workflow: Any,
        *,
        thread_id: str,
        **kwargs: Any,
    ) -> dict[str, Any] | None:
        """Retrieve the latest checkpoint state for a workflow thread."""
        ...

    async def resume(
        self,
        workflow: Any,
        *,
        thread_id: str,
        ctx: Optional[_ExecutionContext] = None,
        **kwargs: Any,
    ) -> _WorkflowResult:
        """Resume execution from the last checkpoint."""
        ...


@runtime_checkable
class AgentProtocol(Protocol):
    r"""Common interface for workflow agents.

    Agents process task inputs and produce task outputs, optionally
    maintaining state across invocations.

    Note: ``input_data`` and the return type use ``object`` (not ``Any``) so
    the type checker enforces explicit casting at call sites.  Concrete agents
    should use the bounded ``TypeVar``\s (``TInput`` / ``TOutput``) from
    :mod:`agentic_v2.agents.base`.
    """

    @property
    def name(self) -> str:
        """Agent's unique name."""
        ...

    async def run(
        self,
        input_data: object,
        ctx: Optional[_ExecutionContext] = None,
    ) -> object:
        """Execute the agent on the given input.

        Args:
            input_data: Task input (varies by agent type).
            ctx: Optional execution context.

        Returns:
            Task output.
        """
        ...


@runtime_checkable
class ToolProtocol(Protocol):
    """Common interface for tools available to agents."""

    @property
    def name(self) -> str:
        """Tool's unique name."""
        ...

    @property
    def description(self) -> str:
        """Human-readable description of what the tool does."""
        ...

    async def execute(self, **kwargs: object) -> object:
        """Execute the tool with the given arguments.

        Returns:
            Tool output (varies by tool type).
        """
        ...


# MemoryStore is deprecated — use MemoryStoreProtocol from core.memory instead.
# Kept as an alias for backward compatibility with existing agent code.
from .memory import MemoryStoreProtocol as MemoryStore  # noqa: F401

# --- Sanitization & Verification Protocols (ADR-002) ---


@runtime_checkable
class DetectorProtocol(Protocol):
    """A pluggable detector that scans text for a specific threat category."""

    @property
    def name(self) -> str:
        """Return the detector's unique name."""
        ...

    @property
    def version(self) -> str:
        """Return the detector's current version string."""
        ...

    async def scan(self, text: str) -> Sequence[_Finding]:
        """Scan *text* and return a sequence of threat findings (empty if clean)."""
        ...


@runtime_checkable
class MiddlewareProtocol(Protocol):
    """A middleware that transforms or gates content flowing through the pipeline."""

    async def process(
        self, content: str, context: dict[str, object]
    ) -> _SanitizationResult:
        """Transform or gate *content* and return the sanitization result."""
        ...


@runtime_checkable
class VerifierProtocol(Protocol):
    """A verification gate that checks step output quality."""

    async def verify(
        self, step_output: Any, policy: _VerificationPolicy
    ) -> _VerificationStatus:
        """Verify *step_output* against *policy* and return the verification status."""
        ...
