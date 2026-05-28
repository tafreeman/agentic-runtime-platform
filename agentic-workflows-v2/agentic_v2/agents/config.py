"""Agent configuration, state, and event type definitions.

Provides the configuration dataclass and enumeration types that describe
a :class:`~agentic_v2.agents.base.BaseAgent` instance's identity, runtime
limits, and observable lifecycle.

Key abstractions:
    AgentState:
        Finite-state enum covering the full agent lifecycle from ``CREATED``
        through terminal states ``COMPLETED``, ``FAILED``, and ``CANCELLED``.

    AgentEvent:
        Observable event kinds emitted during agent execution, used by the
        event-handler mechanism on :class:`~agentic_v2.agents.base.BaseAgent`.

    AgentConfig:
        Mutable dataclass holding all tunable parameters for an agent: name,
        system prompt, model tier selection, iteration limits, memory sizing,
        streaming flag, and verbosity.

Type aliases:
    AgentEventHandler:
        Callable signature for event listener callbacks registered via
        :meth:`~agentic_v2.agents.base.BaseAgent.on_event`.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING, Any, Callable

from ..models import ModelTier

if TYPE_CHECKING:
    from .base import BaseAgent


class AgentState(str, Enum):
    """Finite-state enum representing the lifecycle of a
    :class:`~agentic_v2.agents.base.BaseAgent`.

    The valid state transitions are::

        CREATED -> INITIALIZING -> READY -> RUNNING -> COMPLETED
                                                    -> FAILED
                                                    -> CANCELLED
                                         -> PAUSED  -> RUNNING (resumed)
    """

    CREATED = "created"
    INITIALIZING = "initializing"
    READY = "ready"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class AgentEvent(str, Enum):
    """Observable events emitted by :class:`~agentic_v2.agents.base.BaseAgent` during
    execution.

    Register handlers via :meth:`~agentic_v2.agents.base.BaseAgent.on_event`
    to receive these events for logging, metrics, or UI updates.
    """

    STATE_CHANGE = "state_change"
    MESSAGE_RECEIVED = "message_received"
    MESSAGE_SENT = "message_sent"
    TOOL_CALLED = "tool_called"
    TOOL_RESULT = "tool_result"
    THINKING = "thinking"
    STREAMING = "streaming"
    ERROR = "error"


AgentEventHandler = Callable[["BaseAgent", AgentEvent, dict[str, Any]], None]
"""Type alias for agent event listener callbacks.

Signature::

    handler(agent: BaseAgent, event: AgentEvent, data: dict[str, Any]) -> None
"""


@dataclass
class AgentConfig:
    """Configuration parameters for a :class:`~agentic_v2.agents.base.BaseAgent`
    instance.

    Attributes:
        name: Human-readable agent identifier used in logging and
            :func:`~agentic_v2.agents.base.agent_to_step` conversion.
        description: Brief description of the agent's purpose.
        system_prompt: System-level instruction prepended to conversation
            memory on initialization.
        default_tier: Default :class:`~agentic_v2.models.ModelTier` used
            for LLM routing and tool binding.
        max_tier: Maximum model tier the agent is allowed to escalate to.
        max_iterations: Upper bound on the execution loop iterations before
            the agent raises ``RuntimeError``.
        max_tool_calls_per_turn: Maximum number of tool calls processed
            per single model response.
        timeout_seconds: Per-run wall-clock timeout.
        max_memory_messages: Passed to :class:`~agentic_v2.agents.memory.ConversationMemory`
            as ``max_messages``.
        max_memory_tokens: Passed to :class:`~agentic_v2.agents.memory.ConversationMemory`
            as ``max_tokens``.
        enable_streaming: When ``True``, the :meth:`~agentic_v2.agents.base.BaseAgent.stream`
            method uses the model's streaming endpoint instead of falling back to
            a single ``run()`` call.
        verbose: Enable debug-level logging output.
    """

    # Identity
    name: str = "agent"
    description: str = ""
    system_prompt: str = ""

    # Model selection
    default_tier: ModelTier = ModelTier.TIER_2
    max_tier: ModelTier = ModelTier.TIER_4

    # Behavior
    max_iterations: int = 10
    max_tool_calls_per_turn: int = 5
    timeout_seconds: float = 300.0

    # Memory
    max_memory_messages: int = 50
    max_memory_tokens: int = 8000

    # Streaming
    enable_streaming: bool = False

    # Debug
    verbose: bool = False
