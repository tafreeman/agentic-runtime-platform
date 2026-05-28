"""Base agent implementation with full lifecycle management.

Defines the abstract :class:`BaseAgent` class that all concrete agents must
subclass, along with supporting infrastructure for agent state tracking,
conversation memory, configuration, and pipeline integration.

Key abstractions:
    BaseAgent:
        Generic, lifecycle-managed agent with typed I/O
        (``TInput`` / ``TOutput``), an iterative execution loop, dynamic tool
        binding filtered by :class:`~agentic_v2.models.ModelTier`, conversation
        memory with automatic summarization, and an event system for
        observability hooks.

    ConversationMemory:
        Sliding-window message buffer with configurable token budget and
        automatic summarization of evicted messages.  Defined in
        :mod:`agentic_v2.agents.memory` and re-exported here for backward
        compatibility.

    AgentConfig:
        Frozen configuration controlling identity, model tier selection,
        iteration limits, memory sizing, and streaming behavior.  Defined in
        :mod:`agentic_v2.agents.config` and re-exported here for backward
        compatibility.

    agent_to_step:
        Adapter that wraps any :class:`BaseAgent` instance into a
        :class:`~agentic_v2.engine.StepDefinition` for use in DAG or
        pipeline execution.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import uuid
from abc import ABC, abstractmethod
from typing import Any, AsyncIterator, Generic, TypeVar

from ..contracts import TaskInput, TaskOutput
from ..integrations.otel import get_tracer as _get_tracer
from ..engine import ExecutionContext, StepDefinition
from ..models import (
    LLMClientWrapper,
    SmartModelRouter,
    get_client,
    get_smart_router,
)
from ..tools import BaseTool, ToolRegistry, get_registry
from .config import AgentConfig, AgentEvent, AgentEventHandler, AgentState
from .memory import ConversationMemory, ConversationMessage

__all__ = [
    "AgentConfig",
    "AgentEvent",
    "AgentEventHandler",
    "AgentState",
    "BaseAgent",
    "ConversationMemory",
    "ConversationMessage",
    "agent_to_step",
]

logger = logging.getLogger(__name__)

TInput = TypeVar("TInput", bound=TaskInput)
TOutput = TypeVar("TOutput", bound=TaskOutput)


class BaseAgent(ABC, Generic[TInput, TOutput]):
    """Abstract base class for all agents in the workflow engine.

    ``BaseAgent`` is generic over ``TInput`` (a :class:`~agentic_v2.contracts.TaskInput`
    subclass) and ``TOutput`` (a :class:`~agentic_v2.contracts.TaskOutput` subclass),
    providing compile-time type safety for agent I/O.

    Lifecycle:
        Every agent transitions through :class:`AgentState` values:
        ``CREATED -> INITIALIZING -> READY -> RUNNING -> COMPLETED | FAILED | CANCELLED``.
        The :meth:`run` method auto-initializes on first call.

    Subclass contract:
        Concrete agents **must** implement:

        - :meth:`_call_model` -- invoke the LLM and return a dict with
          ``"content"`` and optionally ``"tool_calls"``.
        - :meth:`_format_task_message` -- serialize ``TInput`` to a user
          message string.
        - :meth:`_is_task_complete` -- decide whether the model response
          constitutes a final answer.
        - :meth:`_parse_output` -- deserialize the model response string
          into ``TOutput``.

    Integration with the workflow engine:
        Use :func:`agent_to_step` to wrap any ``BaseAgent`` into a
        :class:`~agentic_v2.engine.StepDefinition` for DAG or pipeline
        execution.

    Capability composition:
        Agents gain declared capabilities by mixing in subclasses of
        :class:`~agentic_v2.agents.capabilities.CapabilityMixin` (e.g.,
        :class:`CodeGenerationMixin`, :class:`CodeReviewMixin`).  The
        :class:`OrchestratorAgent` uses these capabilities for automatic
        agent-to-task matching.

    Args:
        config: Agent configuration. Defaults to a generic
            :class:`AgentConfig` if ``None``.
        router: Model router for tier-based LLM selection. Defaults to
            the global :func:`~agentic_v2.models.get_smart_router`.
        tools: Tool registry for dynamic tool binding. Defaults to the
            global :func:`~agentic_v2.tools.get_registry`.
        llm_client: LLM client wrapper. Defaults to the global
            :func:`~agentic_v2.models.get_client`.
    """

    def __init__(
        self,
        config: AgentConfig | None = None,
        router: SmartModelRouter | None = None,
        tools: ToolRegistry | None = None,
        llm_client: LLMClientWrapper | None = None,
    ):
        self.id = str(uuid.uuid4())
        self.config = config or AgentConfig()
        self.router = router or get_smart_router()
        self.tools = tools or get_registry()
        self.llm_client = llm_client or get_client()

        # State
        self._state = AgentState.CREATED
        self._memory = ConversationMemory(
            max_messages=self.config.max_memory_messages,
            max_tokens=self.config.max_memory_tokens,
        )
        self._bound_tools: dict[str, BaseTool] = {}
        self._event_handlers: list[AgentEventHandler] = []

        # Execution tracking
        self._current_ctx: ExecutionContext | None = None
        self._iteration_count = 0
        self._tool_call_count = 0

        # Results
        self._last_result: TOutput | None = None
        self._error: str | None = None

    # -------------------------------------------------------------------------
    # Lifecycle
    # -------------------------------------------------------------------------

    async def initialize(self, ctx: ExecutionContext | None = None) -> None:
        """Initialize the agent."""
        self._set_state(AgentState.INITIALIZING)
        self._current_ctx = ctx or ExecutionContext()

        # Set up system prompt
        if self.config.system_prompt:
            self._memory.add_system(self.config.system_prompt)

        # Discover and bind tools
        await self._bind_tools()

        # Subclass initialization
        await self._on_initialize()

        self._set_state(AgentState.READY)

    async def _on_initialize(self) -> None:
        """Override for custom initialization."""
        pass

    async def cleanup(self) -> None:
        """Clean up agent resources."""
        await self._on_cleanup()
        self._memory.clear()
        self._bound_tools.clear()
        self._current_ctx = None

    async def _on_cleanup(self) -> None:
        """Override for custom cleanup."""
        pass

    # -------------------------------------------------------------------------
    # Execution
    # -------------------------------------------------------------------------

    async def run(self, task: TInput, ctx: ExecutionContext | None = None) -> TOutput:
        """Run the agent on a task.

        Args:
            task: The input task
            ctx: Optional execution context

        Returns:
            The task output
        """
        # Initialize if needed
        if self._state == AgentState.CREATED:
            await self.initialize(ctx)
        elif ctx:
            self._current_ctx = ctx

        self._set_state(AgentState.RUNNING)
        self._iteration_count = 0
        self._tool_call_count = 0

        _tracer = _get_tracer()
        _span_cm = (
            _tracer.start_as_current_span(f"agent.{self.name}")
            if _tracer
            else contextlib.nullcontext()
        )
        with _span_cm:
            try:
                # Add task to memory
                task_message = self._format_task_message(task)
                self._memory.add_user(task_message)

                # Main execution loop
                result = await self._execute_loop(task)

                self._last_result = result
                self._set_state(AgentState.COMPLETED)
                return result

            except asyncio.CancelledError:
                self._set_state(AgentState.CANCELLED)
                raise

            except Exception as e:
                self._error = str(e)
                self._set_state(AgentState.FAILED)
                raise

    async def _execute_loop(self, task: TInput) -> TOutput:
        """Main execution loop with iteration limit."""
        while self._iteration_count < self.config.max_iterations:
            self._iteration_count += 1

            # Get model response
            self._emit(AgentEvent.THINKING, {"iteration": self._iteration_count})

            response = await self._get_model_response()

            # Check for tool calls
            if response.get("tool_calls"):
                await self._handle_tool_calls(response["tool_calls"])
                continue

            # Check if done
            content = response.get("content", "")
            self._memory.add_assistant(content)

            if await self._is_task_complete(task, content):
                return await self._parse_output(task, content)

        # Max iterations reached
        raise RuntimeError(
            f"Agent reached max iterations ({self.config.max_iterations}) without completing task"
        )

    async def stream(
        self, task: TInput, ctx: ExecutionContext | None = None
    ) -> AsyncIterator[str]:
        """Stream agent output.

        Yields content chunks as they're generated.
        """
        if not self.config.enable_streaming:
            # Fall back to non-streaming
            result = await self.run(task, ctx)
            yield str(result)
            return

        # Initialize if needed
        if self._state == AgentState.CREATED:
            await self.initialize(ctx)

        self._set_state(AgentState.RUNNING)

        try:
            task_message = self._format_task_message(task)
            self._memory.add_user(task_message)

            async for chunk in self._stream_response():
                self._emit(AgentEvent.STREAMING, {"chunk": chunk})
                yield chunk

            self._set_state(AgentState.COMPLETED)

        except Exception as e:
            self._error = str(e)
            self._set_state(AgentState.FAILED)
            raise

    # -------------------------------------------------------------------------
    # Model Interaction (override for real LLM calls)
    # -------------------------------------------------------------------------

    async def _get_model_response(self) -> dict[str, Any]:
        """Get response from the model.

        Override this to implement actual LLM calls. Default
        implementation returns a simple response for testing.
        """
        messages = self._memory.get_messages()
        tools = self._get_tool_schemas()

        # Default: subclass should override with actual LLM call
        return await self._call_model(messages, tools)

    @abstractmethod
    async def _call_model(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Call the LLM.

        Must be implemented by subclasses.

        Returns:
            Dict with 'content' and optionally 'tool_calls'
        """
        pass

    async def _stream_response(self) -> AsyncIterator[str]:
        """Stream response from model.

        Override for real streaming.
        """
        response = await self._get_model_response()
        yield response.get("content", "")

    # -------------------------------------------------------------------------
    # Tool Handling
    # -------------------------------------------------------------------------

    async def _bind_tools(self) -> None:
        """Bind tools based on agent's tier."""
        max_tier = self.config.default_tier.value

        for tool in self.tools.list_tools():
            if tool.tier <= max_tier:
                self._bound_tools[tool.name] = tool

    def bind_tool(self, tool: BaseTool) -> None:
        """Manually bind a tool."""
        self._bound_tools[tool.name] = tool

    def unbind_tool(self, name: str) -> bool:
        """Unbind a tool."""
        if name in self._bound_tools:
            del self._bound_tools[name]
            return True
        return False

    def _get_tool_schemas(self) -> list[dict[str, Any]]:
        """Get OpenAI-compatible tool schemas."""
        schemas = []
        for tool in self._bound_tools.values():
            tool_schema = tool.get_schema()
            schemas.append(
                {
                    "type": "function",
                    "function": {
                        "name": tool.name,
                        "description": tool.description,
                        "parameters": tool_schema.parameters if tool_schema else {},
                    },
                }
            )
        return schemas

    async def _handle_tool_calls(self, tool_calls: list[dict[str, Any]]) -> None:
        """Handle tool calls from model response."""
        for call in tool_calls[: self.config.max_tool_calls_per_turn]:
            self._tool_call_count += 1

            tool_name = call.get("function", {}).get("name", "")
            tool_args = call.get("function", {}).get("arguments", {})
            call_id = call.get("id", str(uuid.uuid4()))

            self._emit(
                AgentEvent.TOOL_CALLED,
                {"tool": tool_name, "args": tool_args, "call_id": call_id},
            )

            # Execute tool
            tool = self._bound_tools.get(tool_name)
            if tool:
                try:
                    result = await tool.execute(**tool_args)
                    result_str = (
                        str(result.data) if result.success else f"Error: {result.error}"
                    )
                except Exception as e:
                    result_str = f"Error executing tool: {e}"
            else:
                result_str = f"Unknown tool: {tool_name}"

            self._emit(
                AgentEvent.TOOL_RESULT,
                {"tool": tool_name, "result": result_str, "call_id": call_id},
            )

            # Add to memory
            self._memory.add_tool_result(tool_name, result_str, call_id)

    # -------------------------------------------------------------------------
    # Abstract Methods
    # -------------------------------------------------------------------------

    @abstractmethod
    def _format_task_message(self, task: TInput) -> str:
        """Format the task as a user message."""
        pass

    @abstractmethod
    async def _is_task_complete(self, task: TInput, response: str) -> bool:
        """Check if the task is complete based on response."""
        pass

    @abstractmethod
    async def _parse_output(self, task: TInput, response: str) -> TOutput:
        """Parse the model response into output type."""
        pass

    # -------------------------------------------------------------------------
    # Events
    # -------------------------------------------------------------------------

    def on_event(self, handler: AgentEventHandler) -> None:
        """Register an event handler."""
        self._event_handlers.append(handler)

    def off_event(self, handler: AgentEventHandler) -> bool:
        """Unregister an event handler."""
        if handler in self._event_handlers:
            self._event_handlers.remove(handler)
            return True
        return False

    def _emit(self, event: AgentEvent, data: dict[str, Any]) -> None:
        """Emit an event."""
        for handler in self._event_handlers:
            try:
                handler(self, event, data)
            except Exception:
                logger.warning(
                    "Event handler %r failed for event %s",
                    handler,
                    event.value,
                    exc_info=True,
                )

    def _set_state(self, state: AgentState) -> None:
        """Set agent state and emit event."""
        old_state = self._state
        self._state = state
        self._emit(
            AgentEvent.STATE_CHANGE,
            {"old_state": old_state.value, "new_state": state.value},
        )

    # -------------------------------------------------------------------------
    # Properties
    # -------------------------------------------------------------------------

    @property
    def state(self) -> AgentState:
        """Get current state."""
        return self._state

    @property
    def memory(self) -> ConversationMemory:
        """Get conversation memory."""
        return self._memory

    @property
    def context(self) -> ExecutionContext | None:
        """Get current execution context."""
        return self._current_ctx

    @property
    def last_result(self) -> TOutput | None:
        """Get last execution result."""
        return self._last_result

    @property
    def error(self) -> str | None:
        """Get error if failed."""
        return self._error

    @property
    def iteration_count(self) -> int:
        """Get current iteration count."""
        return self._iteration_count

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(id={self.id[:8]}, state={self._state.value})"


def agent_to_step(
    agent: BaseAgent[TInput, TOutput], name: str | None = None
) -> StepDefinition:
    """Wrap a :class:`BaseAgent` as a :class:`~agentic_v2.engine.StepDefinition`.

    Creates a step function that extracts a ``"task"`` key from the
    :class:`~agentic_v2.engine.ExecutionContext`, passes it to
    :meth:`BaseAgent.run`, and returns the result under a ``"result"`` key.

    Args:
        agent: The agent instance to wrap.
        name: Optional step name override.  Defaults to
            ``agent.config.name``.

    Returns:
        A :class:`~agentic_v2.engine.StepDefinition` ready for insertion
        into a DAG or pipeline.

    Raises:
        ValueError: If the execution context does not contain a ``"task"``
            key at runtime.

    Example::

        coder = CoderAgent()
        pipeline.add_step(agent_to_step(coder, "generate_code"))
    """

    async def run_agent(ctx: ExecutionContext) -> dict[str, Any]:
        task_data = ctx.get_sync("task")
        if task_data is None:
            raise ValueError("No task in context")

        result = await agent.run(task_data, ctx)
        return {"result": result}

    return StepDefinition(
        name=name or agent.config.name,
        description=agent.config.description,
        func=run_agent,
        tier=agent.config.default_tier,
        timeout_seconds=agent.config.timeout_seconds,
    )
