"""Core module — engine-agnostic protocols, contracts, and context.

This module provides the foundational abstractions that all execution
engines, adapters, agents, and tools build upon.  Import from here
rather than from ``engine/`` or ``contracts/`` for engine-agnostic code.

Exports:
- **Protocols**: :class:`ExecutionEngine`, :class:`SupportsStreaming`,
  :class:`SupportsCheckpointing`, :class:`AgentProtocol`,
  :class:`ToolProtocol`, :class:`MemoryStore`, :class:`MemoryStoreProtocol`.
- **Memory**: :class:`MemoryStoreProtocol`, :class:`InMemoryStore`.
- **Contracts**: Re-exports from ``contracts/`` — :class:`StepResult`,
  :class:`WorkflowResult`, :class:`StepStatus`, :class:`TaskInput`,
  :class:`TaskOutput`.
- **Context**: Re-exports from ``engine/context`` — :class:`ExecutionContext`,
  :class:`ServiceContainer`.
- **DAG**: Re-exports from ``engine/dag`` — :class:`DAG`.
- **Errors**: Core exception hierarchy.
"""

# Re-export contracts (canonical types used across all engines)
from ..contracts import (
    StepResult,
    StepStatus,
    TaskInput,
    TaskOutput,
    WorkflowResult,
)

# Re-export context (shared across all engines)
from ..engine.context import (
    EventType,
    ExecutionContext,
    ServiceContainer,
    get_context,
    reset_context,
    set_context,
)

# Re-export DAG (used by native engine and orchestrator)
from ..engine.dag import DAG, CycleDetectedError, MissingDependencyError
from .errors import (
    AdapterError,
    AdapterNotFoundError,
    AgenticError,
    ConfigurationError,
    MemoryStoreError,
    SchemaValidationError,
    StepError,
    ToolError,
    WorkflowError,
)
from .memory import InMemoryStore, MemoryStoreProtocol
from .protocols import (
    AgentProtocol,
    ExecutionEngine,
    MemoryStore,
    SupportsCheckpointing,
    SupportsStreaming,
    ToolProtocol,
)
from .tenant import DEFAULT_TENANT_ID, TENANT_HEADER, TenantContext, get_tenant_context

__all__ = [
    # Protocols
    "ExecutionEngine",
    "SupportsStreaming",
    "SupportsCheckpointing",
    "AgentProtocol",
    "ToolProtocol",
    "MemoryStore",
    # Memory
    "MemoryStoreProtocol",
    "InMemoryStore",
    # Contracts
    "StepResult",
    "StepStatus",
    "WorkflowResult",
    "TaskInput",
    "TaskOutput",
    # Context
    "EventType",
    "ExecutionContext",
    "ServiceContainer",
    "get_context",
    "set_context",
    "reset_context",
    # DAG
    "DAG",
    "CycleDetectedError",
    "MissingDependencyError",
    # Errors
    "AgenticError",
    "WorkflowError",
    "StepError",
    "SchemaValidationError",
    "AdapterError",
    "AdapterNotFoundError",
    "ToolError",
    "MemoryStoreError",
    "ConfigurationError",
    # Tenant
    "DEFAULT_TENANT_ID",
    "TENANT_HEADER",
    "TenantContext",
    "get_tenant_context",
]
