"""Contracts module — Pydantic v2 message and schema definitions.

This is the single source of truth for all typed data structures flowing
through the workflow engine, evaluation framework, and server API.

**Rule: Additive-only changes** — never remove or rename existing fields.
Add new optional fields with defaults to maintain backward compatibility.

Exports by category:

- **Lifecycle enums**: :class:`MessageType`, :class:`StepStatus`,
  :class:`ReviewStatus`, :class:`TestGateStatus`.
- **Message contracts**: :class:`AgentMessage` (inter-agent),
  :class:`StepResult` (per-step outcome), :class:`WorkflowResult`
  (aggregate run outcome).
- **Review contracts**: :class:`FindingSeverity`, :class:`Finding`,
  :class:`ReviewReport` — structured code review output with
  ``ReviewStatus.normalize()`` for LLM output coercion.
- **Task schemas**: :class:`TaskInput` / :class:`TaskOutput` (base),
  code generation, code review, and test generation I/O shapes.
- **Issue types**: :class:`CodeIssue`, :class:`Severity`,
  :class:`IssueCategory`, :class:`TestType`, :class:`TestCase`.
- **Chat playground**: :class:`ChatMessage`, :class:`ChatRequest`,
  :data:`ChatStreamEvent` (route/token/media/done/error SSE union for
  ``POST /api/chat``).
"""

from .chat import (
    ChatDoneEvent,
    ChatErrorEvent,
    ChatImagePart,
    ChatMediaEvent,
    ChatMessage,
    ChatRequest,
    ChatRole,
    ChatRouteEvent,
    ChatStreamEvent,
    ChatTextPart,
    ChatTokenEvent,
    ModelChatRequest,
    TierChatRequest,
    validate_chat_stream_event,
)
from .events import (
    ApprovalDecisionEvent,
    ApprovalRequiredEvent,
    ErrorEvent,
    EvaluationCompleteEvent,
    EvaluationStartEvent,
    ExecutionEvent,
    StepCompleteEvent,
    StepEndEvent,
    StepErrorEvent,
    StepStartEvent,
    WorkflowEndEvent,
    WorkflowStartEvent,
    validate_event,
)
from .messages import (
    AgentMessage,
    Finding,
    FindingSeverity,
    MessageType,
    ReviewReport,
    ReviewStatus,
    StepResult,
    StepStatus,
    TestGateStatus,
    WorkflowResult,
)
from .schemas import (  # Enums; Base classes; Code generation; Code review; Test generation
    CodeGenerationInput,
    CodeGenerationOutput,
    CodeIssue,
    CodeReviewInput,
    CodeReviewOutput,
    IssueCategory,
    Severity,
    TaskInput,
    TaskOutput,
    TestCase,
    TestGenerationInput,
    TestGenerationOutput,
    TestType,
)

__all__ = [
    # Messages
    "MessageType",
    "StepStatus",
    "ReviewStatus",
    "TestGateStatus",
    "AgentMessage",
    "StepResult",
    "WorkflowResult",
    # Review
    "FindingSeverity",
    "Finding",
    "ReviewReport",
    # Schemas - enums
    "Severity",
    "IssueCategory",
    "TestType",
    # Schemas - base
    "TaskInput",
    "TaskOutput",
    # Schemas - code generation
    "CodeGenerationInput",
    "CodeGenerationOutput",
    # Schemas - code review
    "CodeIssue",
    "CodeReviewInput",
    "CodeReviewOutput",
    # Schemas - test generation
    "TestCase",
    "TestGenerationInput",
    "TestGenerationOutput",
    # Events
    "ExecutionEvent",
    "WorkflowStartEvent",
    "StepStartEvent",
    "StepEndEvent",
    "StepCompleteEvent",
    "StepErrorEvent",
    "WorkflowEndEvent",
    "ErrorEvent",
    "EvaluationStartEvent",
    "EvaluationCompleteEvent",
    "ApprovalRequiredEvent",
    "ApprovalDecisionEvent",
    "validate_event",
    # Chat playground (POST /api/chat wire format)
    "ChatRole",
    "ChatTextPart",
    "ChatImagePart",
    "ChatMessage",
    "ChatRequest",
    "ModelChatRequest",
    "TierChatRequest",
    "ChatStreamEvent",
    "ChatRouteEvent",
    "ChatTokenEvent",
    "ChatMediaEvent",
    "ChatDoneEvent",
    "ChatErrorEvent",
    "validate_chat_stream_event",
]
