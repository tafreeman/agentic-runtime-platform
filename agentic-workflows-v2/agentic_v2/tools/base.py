"""Base classes for the tool system."""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


@dataclass
class ToolSchema:
    """Schema describing a tool for agent consumption."""

    name: str
    description: str
    parameters: dict[str, Any]
    returns: str
    tier: int = 0  # 0 = no LLM needed, 1-3 = model tiers
    examples: list[str] = field(default_factory=list)


@dataclass
class ToolResult:
    """Standardized result from tool execution."""

    success: bool
    data: Any = None
    error: str | None = None
    execution_time_ms: float = 0.0
    tool_name: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        """Validate that error is set if success is False."""
        if not self.success and self.error is None:
            self.error = "Tool execution failed (no error message provided)"


class BaseTool(ABC):
    """Base class for all tools in the system.

    Tools are atomic operations that can be called by agents.
    They should be:
    - Deterministic when possible
    - Idempotent when reasonable
    - Fast (< 1s for tier 0, < 5s for tier 1-2)
    - Well-documented with clear input/output contracts
    """

    def __init__(self):
        """Initialize the tool."""
        self._schema: ToolSchema | None = None

    @property
    @abstractmethod
    def name(self) -> str:
        """Return the tool name (used for registration)."""
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        """Return a human-readable description of what the tool does."""
        ...

    @property
    @abstractmethod
    def parameters(self) -> dict[str, Any]:
        """Return the parameter schema for this tool.

        Format:
        {
            "param_name": {
                "type": "string|number|boolean|array|object",
                "description": "What this parameter does",
                "required": True|False,
                "default": value (optional)
            }
        }
        """
        ...

    @property
    def returns(self) -> str:
        """Return a description of what the tool returns."""
        return "ToolResult with success status and data"

    @property
    def tier(self) -> int:
        """Return the tier of this tool (0-3).

        Tier 0: No LLM needed (file ops, transforms)
        Tier 1: Small model (1-3B) - formatting, simple generation
        Tier 2: Medium model (7-14B) - code generation, review
        Tier 3: Large model (32B+/cloud) - architecture, reasoning
        """
        return 0

    @property
    def examples(self) -> list[str]:
        """Return usage examples (optional)."""
        return []

    def get_schema(self) -> ToolSchema:
        """Get the tool schema for agent consumption."""
        if self._schema is None:
            self._schema = ToolSchema(
                name=self.name,
                description=self.description,
                parameters=self.parameters,
                returns=self.returns,
                tier=self.tier,
                examples=self.examples,
            )
        return self._schema

    @abstractmethod
    async def execute(self, **kwargs) -> ToolResult:
        """Execute the tool with the given parameters.

        Args:
            **kwargs: Parameters matching the tool's parameter schema

        Returns:
            ToolResult with success status, data, and optional error
        """
        ...

    async def __call__(self, **kwargs) -> ToolResult:
        """Allow the tool to be called directly."""
        start_time = time.perf_counter()
        try:
            result = await self.execute(**kwargs)
            result.execution_time_ms = (time.perf_counter() - start_time) * 1000
            result.tool_name = self.name
            return result
        except Exception as e:
            execution_time = (time.perf_counter() - start_time) * 1000
            return ToolResult(
                success=False,
                error=f"{type(e).__name__}: {e!s}",
                execution_time_ms=execution_time,
                tool_name=self.name,
            )

    def validate_parameters(self, **kwargs) -> tuple[bool, str | None]:
        """Validate parameters against the schema.

        Returns:
            (is_valid, error_message)
        """
        params = self.parameters

        for param_name, param_spec in params.items():
            required = param_spec.get("required", False)
            if required and param_name not in kwargs:
                return False, f"Required parameter '{param_name}' is missing"

        # Check for unexpected parameters
        unexpected = set(kwargs.keys()) - set(params.keys())
        if unexpected:
            return False, f"Unexpected parameters: {', '.join(unexpected)}"

        return True, None
