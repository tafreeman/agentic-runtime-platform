"""
Engine module - Workflow execution infrastructure.

Exports:
- Context: ExecutionContext, ServiceContainer
- Steps: StepDefinition, StepExecutor, step decorator
- Pipeline: Pipeline, PipelineBuilder, PipelineExecutor
- Executor: WorkflowExecutor, ExecutionConfig
- Utilities: execute, run, get_executor
"""

from .context import (
    EventType,
    ExecutionContext,
    ServiceContainer,
    get_context,
    reset_context,
    set_context,
)
from .dag import DAG, CycleDetectedError, MissingDependencyError
from .dag_executor import DAGExecutor
from .executor import (
    ExecutionConfig,
    ExecutionHistory,
    ExecutorEvent,
    WorkflowExecutor,
    execute,
    get_executor,
    reset_executor,
    run,
)
from .expressions import ExpressionEvaluator
from .pipeline import (
    ConditionalBranch,
    ParallelGroup,
    Pipeline,
    PipelineBuilder,
    PipelineExecutor,
    PipelineStatus,
    run_pipeline,
)
from .protocol import ExecutionEngine, SupportsCheckpointing, SupportsStreaming
from .runtime import (
    DockerRuntime,
    IsolatedTaskRuntime,
    RuntimeExecutionError,
    RuntimeExecutionResult,
    SubprocessRuntime,
    create_runtime,
)
from .step import (
    RetryConfig,
    RetryStrategy,
    StepDefinition,
    StepExecutor,
    run_step,
    step,
)
from .step_state import StepState, StepStateManager

__all__ = [
    # Context
    "EventType",
    "ServiceContainer",
    "ExecutionContext",
    "get_context",
    "set_context",
    "reset_context",
    # Steps
    "RetryStrategy",
    "RetryConfig",
    "StepDefinition",
    "StepExecutor",
    "step",
    "run_step",
    # Pipeline
    "PipelineStatus",
    "ParallelGroup",
    "ConditionalBranch",
    "Pipeline",
    "PipelineBuilder",
    "PipelineExecutor",
    "run_pipeline",
    # Protocol (ADR-001)
    "ExecutionEngine",
    "SupportsStreaming",
    "SupportsCheckpointing",
    # DAG
    "DAG",
    "MissingDependencyError",
    "CycleDetectedError",
    "DAGExecutor",
    # Expressions
    "ExpressionEvaluator",
    # Step State
    "StepState",
    "StepStateManager",
    # Runtime
    "IsolatedTaskRuntime",
    "RuntimeExecutionResult",
    "RuntimeExecutionError",
    "SubprocessRuntime",
    "DockerRuntime",
    "create_runtime",
    # Executor
    "ExecutorEvent",
    "ExecutionConfig",
    "ExecutionHistory",
    "WorkflowExecutor",
    "get_executor",
    "reset_executor",
    "execute",
    "run",
]
