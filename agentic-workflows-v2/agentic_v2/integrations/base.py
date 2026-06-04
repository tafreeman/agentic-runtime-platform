"""Base adapter interfaces for framework-neutral integration."""

import json
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any


@dataclass
class CanonicalEvent:
    """Unified event model for workflow execution tracing.

    All framework adapters emit events in this canonical format to
    enable consistent observability and debugging across LangChain,
    Microsoft Agent Framework, and other integrations.
    """

    type: str  # e.g., "workflow_start", "step_start", "step_complete", "workflow_end"
    timestamp: datetime
    step_name: str | None = None
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert event to dictionary for JSON serialization."""
        return {
            "type": self.type,
            "timestamp": self.timestamp.isoformat(),
            "step_name": self.step_name,
            "data": self.data,
        }

    def to_json(self) -> str:
        """Convert event to JSON string."""
        return json.dumps(self.to_dict(), default=str)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CanonicalEvent":
        """Create event from dictionary."""
        return cls(
            type=data["type"],
            timestamp=datetime.fromisoformat(data["timestamp"]),
            step_name=data.get("step_name"),
            data=data.get("data", {}),
        )


class AgentAdapter(ABC):
    """Abstract base class for agent framework adapters."""

    @abstractmethod
    async def invoke(self, prompt: str, context: dict[str, Any]) -> dict[str, Any]:
        """Invoke the agent with a prompt and context.

        Args:
            prompt: The prompt/instruction for the agent
            context: Contextual information and parameters

        Returns:
            Agent response as a dictionary with at minimum:
            - "output": The agent's response text
            - "metadata": Optional metadata about the invocation
        """
        pass


class ToolAdapter(ABC):
    """Abstract base class for tool execution adapters."""

    @abstractmethod
    async def execute(self, tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
        """Execute a tool with the given arguments.

        Args:
            tool_name: Name of the tool to execute
            args: Tool arguments

        Returns:
            Tool result as a dictionary with at minimum:
            - "output": The tool's output
            - "success": Boolean indicating success/failure
            - "error": Optional error message if success=False
        """
        pass


class WorkflowAdapter(ABC):
    """Abstract base class for workflow execution adapters."""

    @abstractmethod
    async def run(
        self, workflow_def: dict[str, Any], inputs: dict[str, Any]
    ) -> dict[str, Any]:
        """Run a workflow with the given inputs.

        Args:
            workflow_def: Workflow definition
            inputs: Workflow input parameters

        Returns:
            Workflow result as a dictionary with at minimum:
            - "status": Execution status
            - "outputs": Workflow outputs
            - "metadata": Execution metadata
        """
        pass


class TraceAdapter(ABC):
    """Abstract base class for execution tracing adapters.

    TraceAdapter implementations receive CanonicalEvent instances during
    workflow execution and can emit them to various backends (console,
    file, OpenTelemetry, etc.).
    """

    @abstractmethod
    def emit(self, event: CanonicalEvent) -> None:
        """Emit a canonical event to the tracing backend.

        Args:
            event: The event to emit
        """
        pass

    def emit_workflow_start(
        self, workflow_name: str, run_id: str, inputs: dict[str, Any]
    ) -> None:
        """Helper to emit a workflow start event."""
        self.emit(
            CanonicalEvent(
                type="workflow_start",
                timestamp=datetime.now(UTC),
                data={
                    "workflow_name": workflow_name,
                    "run_id": run_id,
                    "inputs": inputs,
                },
            )
        )

    def emit_workflow_end(
        self, workflow_name: str, run_id: str, status: str, outputs: dict[str, Any]
    ) -> None:
        """Helper to emit a workflow end event."""
        self.emit(
            CanonicalEvent(
                type="workflow_end",
                timestamp=datetime.now(UTC),
                data={
                    "workflow_name": workflow_name,
                    "run_id": run_id,
                    "status": status,
                    "outputs": outputs,
                },
            )
        )

    def emit_step_start(
        self, step_name: str, run_id: str, inputs: dict[str, Any]
    ) -> None:
        """Helper to emit a step start event."""
        self.emit(
            CanonicalEvent(
                type="step_start",
                timestamp=datetime.now(UTC),
                step_name=step_name,
                data={"run_id": run_id, "inputs": inputs},
            )
        )

    def emit_step_complete(
        self, step_name: str, run_id: str, status: str, outputs: dict[str, Any]
    ) -> None:
        """Helper to emit a step complete event."""
        self.emit(
            CanonicalEvent(
                type="step_complete",
                timestamp=datetime.now(UTC),
                step_name=step_name,
                data={"run_id": run_id, "status": status, "outputs": outputs},
            )
        )
