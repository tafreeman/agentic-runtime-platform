"""Agentic Workflows V2 - Tier-based multi-model orchestration."""

from __future__ import annotations

__version__ = "0.1.0"

# Phase 3: Agents
from .agents import AgentEvent  # Base; Capabilities; Agents
from .agents import (
    AgentConfig,
    AgentState,
    BaseAgent,
    Capability,
    CapabilityMixin,
    CapabilitySet,
    CapabilityType,
    CodeGenerationMixin,
    CoderAgent,
    CodeReviewMixin,
    ConversationMemory,
    ConversationMessage,
    OrchestrationMixin,
    OrchestratorAgent,
    OrchestratorInput,
    OrchestratorOutput,
    ReviewerAgent,
    SubTask,
    TestGenerationMixin,
    agent_to_step,
    get_agent_capabilities,
    requires_capabilities,
)

# Phase 1: Contracts
from .contracts import CodeGenerationInput  # Messages; Schemas
from .contracts import (
    AgentMessage,
    CodeGenerationOutput,
    CodeIssue,
    CodeReviewInput,
    CodeReviewOutput,
    IssueCategory,
    MessageType,
    Severity,
    StepResult,
    StepStatus,
    TaskInput,
    TaskOutput,
    TestCase,
    TestGenerationInput,
    TestGenerationOutput,
    TestType,
    WorkflowResult,
)

# Phase 2: Engine
from .engine import DAG  # Context; Steps; Pipeline; DAG; Executor
from .engine import (
    ConditionalBranch,
    CycleDetectedError,
    DAGExecutor,
    EventType,
    ExecutionConfig,
    ExecutionContext,
    ExecutionHistory,
    ExecutorEvent,
    ExpressionEvaluator,
    MissingDependencyError,
    ParallelGroup,
    Pipeline,
    PipelineBuilder,
    PipelineExecutor,
    PipelineStatus,
    RetryConfig,
    RetryStrategy,
    ServiceContainer,
    StepDefinition,
    StepExecutor,
    StepState,
    StepStateManager,
    WorkflowExecutor,
    execute,
    get_context,
    get_executor,
    reset_context,
    reset_executor,
    run,
    run_pipeline,
    run_step,
    step,
)

# Phase 1: Models
from .models import FallbackChain  # Stats; Router; Client
from .models import (
    CircuitState,
    LLMClientWrapper,
    ModelRouter,
    ModelStats,
    ModelTier,
    SmartModelRouter,
    TokenBudget,
    get_client,
    get_router,
    get_smart_router,
)

# Phase 0: Tools
from .tools.base import BaseTool, ToolResult, ToolSchema
from .tools.registry import ToolRegistry, get_registry

__all__ = [
    "__version__",
    # Tools (Phase 0)
    "BaseTool",
    "ToolResult",
    "ToolSchema",
    "ToolRegistry",
    "get_registry",
    # Messages (Phase 1)
    "MessageType",
    "StepStatus",
    "AgentMessage",
    "StepResult",
    "WorkflowResult",
    # Schemas (Phase 1)
    "Severity",
    "IssueCategory",
    "TestType",
    "TaskInput",
    "TaskOutput",
    "CodeGenerationInput",
    "CodeGenerationOutput",
    "CodeIssue",
    "CodeReviewInput",
    "CodeReviewOutput",
    "TestCase",
    "TestGenerationInput",
    "TestGenerationOutput",
    # Model Stats (Phase 1)
    "CircuitState",
    "ModelStats",
    # Router (Phase 1)
    "ModelTier",
    "FallbackChain",
    "ModelRouter",
    "SmartModelRouter",
    "get_router",
    "get_smart_router",
    # Client (Phase 1)
    "LLMClientWrapper",
    "TokenBudget",
    "get_client",
    # Context (Phase 2)
    "EventType",
    "ServiceContainer",
    "ExecutionContext",
    "get_context",
    "reset_context",
    # Steps (Phase 2)
    "RetryStrategy",
    "RetryConfig",
    "StepDefinition",
    "StepExecutor",
    "step",
    "run_step",
    # Pipeline (Phase 2)
    "PipelineStatus",
    "ParallelGroup",
    "ConditionalBranch",
    "Pipeline",
    "PipelineBuilder",
    "PipelineExecutor",
    "run_pipeline",
    # DAG (Phase 4)
    "DAG",
    "DAGExecutor",
    "MissingDependencyError",
    "CycleDetectedError",
    "ExpressionEvaluator",
    "StepState",
    "StepStateManager",
    # Executor (Phase 2)
    "ExecutorEvent",
    "ExecutionConfig",
    "ExecutionHistory",
    "WorkflowExecutor",
    "get_executor",
    "reset_executor",
    "execute",
    "run",
    # Agent Base (Phase 3)
    "AgentConfig",
    "AgentEvent",
    "AgentState",
    "BaseAgent",
    "ConversationMemory",
    "ConversationMessage",
    "agent_to_step",
    # Capabilities (Phase 3)
    "Capability",
    "CapabilityMixin",
    "CapabilitySet",
    "CapabilityType",
    "CodeGenerationMixin",
    "CodeReviewMixin",
    "OrchestrationMixin",
    "TestGenerationMixin",
    "get_agent_capabilities",
    "requires_capabilities",
    # Agents (Phase 3)
    "CoderAgent",
    "ReviewerAgent",
    "OrchestratorAgent",
    "OrchestratorInput",
    "OrchestratorOutput",
    "SubTask",
]
