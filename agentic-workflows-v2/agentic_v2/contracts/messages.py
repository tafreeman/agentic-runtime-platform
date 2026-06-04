"""Message contracts for agent communication and step/workflow results.

Defines the core data structures that flow through every layer of the
system — from the engine, through the server, to the UI:

- :class:`StepResult` — outcome of a single workflow step (status,
  outputs, model used, duration, retry count, error details).
- :class:`WorkflowResult` — aggregate outcome with per-step results,
  overall status, and computed properties (``success_rate``,
  ``failed_steps``, ``total_duration_ms``).
- :class:`AgentMessage` — inter-agent communication envelope.
- :class:`ReviewStatus` — canonical review outcomes with
  ``normalize()`` for coercing freeform LLM output strings.
- :class:`ReviewReport` / :class:`Finding` — structured code review
  output with severity classification.

All models use Pydantic v2 with computed fields, field validators,
and ``exclude_none`` serialization.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator


class MessageType(str, Enum):
    """Type of message in the agent workflow."""

    TASK = "task"
    RESPONSE = "response"
    ERROR = "error"
    STATUS = "status"
    TOOL_CALL = "tool_call"
    TOOL_RESULT = "tool_result"


class StepStatus(str, Enum):
    """Status of a workflow step execution."""

    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"
    RETRYING = "retrying"


class ReviewStatus(str, Enum):
    """Canonical review outcome values.

    All LLM-returned review statuses are normalized to one of
    these values, eliminating the need for free-form string
    comparisons in YAML when-conditions.

    Used in YAML conditions:
        when: ${steps.review_code.outputs.overall_status} not in ['APPROVED', 'APPROVED_WITH_NOTES']
    """

    APPROVED = "APPROVED"  # Code is acceptable, no changes needed
    APPROVED_WITH_NOTES = (
        "APPROVED_WITH_NOTES"  # Acceptable with minor non-blocking notes
    )
    NEEDS_FIXES = "NEEDS_FIXES"  # Issues found, rework required
    REJECTED = "REJECTED"  # Fundamental problems, major rework required

    @classmethod
    def normalize(cls, raw: str | None) -> "ReviewStatus":
        """Map any LLM-returned status string to a canonical ReviewStatus.

        Handles all known variants: APPROVED, PASS, pass, approved,
        APPROVED_WITH_NOTES, NEEDS_FIXES, NEEDS_REVISION, needs_work, REJECTED, etc.

        Returns NEEDS_FIXES for unknown/None values (conservative default).
        """
        if raw is None:
            return cls.NEEDS_FIXES

        cleaned = raw.strip().upper().replace(" ", "_").replace("-", "_")

        # Approved-with-notes variants (check before plain APPROVED)
        if cleaned in {
            "APPROVED_WITH_NOTES",
            "APPROVED_WITH_COMMENTS",
            "CONDITIONAL_APPROVAL",
            "APPROVED_CONDITIONALLY",
        }:
            return cls.APPROVED_WITH_NOTES

        # Approved variants
        if cleaned in {
            "APPROVED",
            "PASS",
            "PASSED",
            "ACCEPT",
            "ACCEPTED",
            "OK",
            "LGTM",
            "NO_ISSUES",
            "NO_CHANGES_NEEDED",
        }:
            return cls.APPROVED

        # Rejected variants
        if cleaned in {
            "REJECTED",
            "REJECT",
            "FAIL",
            "FAILED",
            "CRITICAL",
            "BLOCKED",
        }:
            return cls.REJECTED

        # Everything else maps to needs_fixes (conservative)
        return cls.NEEDS_FIXES


class TestGateStatus(str, Enum):
    """Pass/fail status returned by test-execution and validator agents.

    Used in YAML conditions:
        when: ${steps.execute_tests.outputs.overall_status} not in ['PASS']
    """

    PASS = "PASS"  # All tests passed
    FAIL = "FAIL"  # One or more tests failed
    ERROR = "ERROR"  # Execution error, tests could not run
    SKIPPED = "SKIPPED"  # Tests were skipped

    @classmethod
    def normalize(cls, raw: str | None) -> "TestGateStatus":
        """Map any LLM-returned test status string to a canonical TestGateStatus."""
        if raw is None:
            return cls.FAIL
        cleaned = raw.strip().upper()
        if cleaned in {"PASS", "PASSED", "SUCCESS", "GREEN", "OK"}:
            return cls.PASS
        if cleaned in {"SKIP", "SKIPPED", "NOT_RUN"}:
            return cls.SKIPPED
        if cleaned in {"ERROR", "EXCEPTION", "CRASH"}:
            return cls.ERROR
        return cls.FAIL


class FindingSeverity(str, Enum):
    """Severity level for a code review finding."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"

    @classmethod
    def normalize(cls, raw: str | None) -> "FindingSeverity":
        """Map any LLM-returned severity string to a canonical FindingSeverity."""
        if raw is None:
            return cls.MEDIUM
        cleaned = raw.strip().upper()
        mapping = {
            "CRITICAL": cls.CRITICAL,
            "HIGH": cls.HIGH,
            "MEDIUM": cls.MEDIUM,
            "MODERATE": cls.MEDIUM,
            "LOW": cls.LOW,
            "INFO": cls.LOW,
            "INFORMATIONAL": cls.LOW,
        }
        return mapping.get(cleaned, cls.MEDIUM)


class Finding(BaseModel):
    """A single code-review finding with structured location and fix info.

    Designed to be stable across LLM outputs: all fields except
    ``finding_id`` and ``description`` are optional so partial responses
    can still be stored and displayed.
    """

    model_config = ConfigDict(extra="allow")

    finding_id: str = Field(description="Unique identifier, e.g. 'F-001'")
    severity: FindingSeverity = Field(description="Severity level")
    category: str = Field(
        default="quality",
        description="Category: security | quality | performance",
    )
    title: str = Field(default="", description="Brief one-line title")
    file: str = Field(default="", description="Affected file path")
    line_range: tuple[int, int] | None = Field(
        default=None, description="(start_line, end_line) in the affected file"
    )
    description: str = Field(description="What is wrong")
    impact: str = Field(default="", description="What could happen if unfixed")
    suggested_fix: str = Field(default="", description="How to fix it")
    code_before: str = Field(default="", description="Vulnerable/problematic snippet")
    code_after: str = Field(default="", description="Fixed snippet")
    references: list[str] = Field(
        default_factory=list, description="CWE / OWASP references"
    )

    @field_validator("severity", mode="before")
    @classmethod
    def _normalize_severity(cls, v: Any) -> FindingSeverity:
        if isinstance(v, FindingSeverity):
            return v
        return FindingSeverity.normalize(str(v) if v is not None else None)


class ReviewReport(BaseModel):
    """Structured output from a code-review step.

    The ``overall_status`` field drives ``when:`` conditions in YAML;
    ``findings`` carry the machine-readable detail.
    """

    model_config = ConfigDict(extra="allow")

    overall_status: ReviewStatus = Field(
        default=ReviewStatus.NEEDS_FIXES,
        description="Canonical review outcome",
    )
    quality_score: float | None = Field(
        default=None,
        description="0-10 quality score (10 = perfect)",
        ge=0,
        le=10,
    )
    findings: list[Finding] = Field(
        default_factory=list,
        description="Ordered list of findings (critical first)",
    )
    summary: dict[str, Any] = Field(
        default_factory=dict,
        description="Counts by severity: {critical, high, medium, low, passed_checks}",
    )
    positive_observations: list[str] = Field(
        default_factory=list,
        description="Things done well",
    )

    @field_validator("overall_status", mode="before")
    @classmethod
    def _normalize_status(cls, v: Any) -> ReviewStatus:
        if isinstance(v, ReviewStatus):
            return v
        return ReviewStatus.normalize(str(v) if v is not None else None)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def needs_fixes(self) -> bool:
        """True when at least one finding requires rework."""
        return self.overall_status != ReviewStatus.APPROVED

    @computed_field  # type: ignore[prop-decorator]
    @property
    def critical_count(self) -> int:
        """Number of critical findings."""
        return sum(1 for f in self.findings if f.severity == FindingSeverity.CRITICAL)


class AgentMessage(BaseModel):
    """Message exchanged between agents and orchestrator.

    Design improvements:
    - Discriminated union via message_type for polymorphic serialization
    - Auto-timestamps with timezone awareness
    - Computed properties for common checks
    - Content truncation helper for logging
    """

    model_config = ConfigDict(
        use_enum_values=False,
        validate_assignment=True,
        arbitrary_types_allowed=True,
        extra="forbid",
    )

    message_type: MessageType = Field(
        description="Type of message for discriminated union"
    )
    role: str = Field(
        description="Agent role (e.g., 'coder', 'reviewer', 'orchestrator')",
        min_length=1,
        max_length=100,
    )
    content: str = Field(
        description="Message content (prompt, response, error details)", min_length=1
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional context (model, tier, tokens, etc.)",
    )
    timestamp: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp of message creation",
    )
    correlation_id: str | None = Field(
        default=None, description="ID to correlate related messages across workflow"
    )

    @field_validator("role")
    @classmethod
    def validate_role(cls, v: str) -> str:
        """Ensure role is lowercase and alphanumeric."""
        cleaned = v.lower().strip()
        if not cleaned.replace("_", "").replace("-", "").isalnum():
            raise ValueError(f"Role must be alphanumeric (with _ or -), got: {v}")
        return cleaned

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_error(self) -> bool:
        """Check if this message represents an error."""
        return self.message_type == MessageType.ERROR

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_tool_call(self) -> bool:
        """Check if this message is a tool invocation."""
        return self.message_type == MessageType.TOOL_CALL

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_tool_result(self) -> bool:
        """Check if this message is a tool result."""
        return self.message_type == MessageType.TOOL_RESULT

    def truncated_content(self, max_length: int = 200) -> str:
        """Get truncated content for logging.

        Args:
            max_length: Maximum characters to return

        Returns:
            Truncated content with ellipsis if needed
        """
        if len(self.content) <= max_length:
            return self.content
        return self.content[: max_length - 3] + "..."

    def __repr__(self) -> str:
        """Rich representation for debugging."""
        content_preview = self.truncated_content(50)
        return (
            f"AgentMessage(type={self.message_type.value}, "
            f"role={self.role}, "
            f"content='{content_preview}', "
            f"timestamp={self.timestamp.isoformat()})"
        )


class StepResult(BaseModel):
    """Result of a single workflow step execution.

    Design improvements:
    - Computed duration property
    - Success rate tracking
    - Detailed error context
    - Retry tracking
    """

    model_config = ConfigDict(
        use_enum_values=False,
        validate_assignment=True,
        extra="allow",  # Allow extra fields for extensibility
    )

    step_name: str = Field(
        description="Unique identifier for this workflow step", min_length=1
    )
    status: StepStatus = Field(description="Execution status of the step")
    agent_role: str | None = Field(
        default=None, description="Role of agent that executed this step"
    )
    tier: int | None = Field(
        default=None,
        description="Model tier used (0=no LLM, 1=1-3B, 2=7-14B, 3=32B+)",
        ge=0,
        le=5,
    )
    model_used: str | None = Field(
        default=None,
        description="Specific model identifier (e.g., 'ollama:phi4', 'gh:gpt-4o')",
    )
    input_data: dict[str, Any] = Field(
        default_factory=dict, description="Input parameters for this step"
    )
    output_data: dict[str, Any] = Field(
        default_factory=dict, description="Output/results from this step"
    )
    error: str | None = Field(default=None, description="Error message if step failed")
    error_type: str | None = Field(
        default=None, description="Error class name for structured handling"
    )
    start_time: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp when step started",
    )
    end_time: datetime | None = Field(
        default=None, description="UTC timestamp when step completed"
    )
    retry_count: int = Field(default=0, description="Number of retries attempted", ge=0)
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Additional metrics (tokens, latency, cache hits, etc.)",
    )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_success(self) -> bool:
        """Check if step succeeded."""
        return self.status == StepStatus.SUCCESS

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_failed(self) -> bool:
        """Check if step failed."""
        return self.status == StepStatus.FAILED

    @computed_field  # type: ignore[prop-decorator]
    @property
    def is_complete(self) -> bool:
        """Check if step finished (success or failure)."""
        return self.status in (
            StepStatus.SUCCESS,
            StepStatus.FAILED,
            StepStatus.SKIPPED,
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def duration_ms(self) -> float | None:
        """Calculate execution duration in milliseconds."""
        if self.end_time is None:
            return None
        delta = self.end_time - self.start_time
        return delta.total_seconds() * 1000

    def mark_complete(self, success: bool = True, error: str | None = None) -> None:
        """Mark step as complete.

        Args:
            success: Whether step succeeded
            error: Optional error message if failed
        """
        self.end_time = datetime.now(timezone.utc)
        self.status = StepStatus.SUCCESS if success else StepStatus.FAILED
        if error:
            self.error = error

    def __repr__(self) -> str:
        """Rich representation for debugging."""
        duration_str = f"{self.duration_ms:.1f}ms" if self.duration_ms else "running"
        return (
            f"StepResult(name={self.step_name}, "
            f"status={self.status.value}, "
            f"duration={duration_str}, "
            f"retries={self.retry_count})"
        )


class WorkflowResult(BaseModel):
    """Complete result of a workflow execution.

    Design improvements:
    - Aggregate success rate
    - Total execution time
    - Step dependency tracking
    - Failure analysis
    """

    model_config = ConfigDict(
        use_enum_values=False, validate_assignment=True, extra="allow"
    )

    workflow_id: str = Field(
        description="Unique identifier for this workflow run", min_length=1
    )
    workflow_name: str = Field(description="Human-readable workflow name", min_length=1)
    steps: list[StepResult] = Field(
        default_factory=list, description="Ordered list of step results"
    )
    overall_status: StepStatus = Field(
        description="Aggregate status of entire workflow"
    )
    start_time: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        description="UTC timestamp when workflow started",
    )
    end_time: datetime | None = Field(
        default=None, description="UTC timestamp when workflow completed"
    )
    final_output: dict[str, Any] = Field(
        default_factory=dict, description="Final workflow output/artifacts"
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Workflow-level metadata (costs, resource usage, etc.)",
    )

    @property
    def run_id(self) -> str:
        """Backward-compatible alias for ``workflow_id``."""
        return self.workflow_id

    @computed_field  # type: ignore[prop-decorator]
    @property
    def total_duration_ms(self) -> float | None:
        """Calculate total workflow duration in milliseconds."""
        if self.end_time is None:
            return None
        delta = self.end_time - self.start_time
        return delta.total_seconds() * 1000

    @computed_field  # type: ignore[prop-decorator]
    @property
    def success_rate(self) -> float:
        """Calculate percentage of successful steps."""
        if not self.steps:
            return 0.0
        successful = sum(1 for step in self.steps if step.is_success)
        return (successful / len(self.steps)) * 100

    @computed_field  # type: ignore[prop-decorator]
    @property
    def failed_steps(self) -> list[StepResult]:
        """Get list of failed steps."""
        return [step for step in self.steps if step.is_failed]

    @computed_field  # type: ignore[prop-decorator]
    @property
    def total_retries(self) -> int:
        """Count total retry attempts across all steps."""
        return sum(step.retry_count for step in self.steps)

    def add_step(self, step: StepResult) -> None:
        """Add a step result to the workflow.

        Args:
            step: Step result to add
        """
        self.steps.append(step)
        # Update overall status based on step status
        if step.is_failed and self.overall_status != StepStatus.FAILED:
            self.overall_status = StepStatus.FAILED

    def mark_complete(self, success: bool = True) -> None:
        """Mark workflow as complete.

        Args:
            success: Whether workflow succeeded overall
        """
        self.end_time = datetime.now(timezone.utc)
        self.overall_status = StepStatus.SUCCESS if success else StepStatus.FAILED

    def __repr__(self) -> str:
        """Rich representation for debugging."""
        duration_str = (
            f"{self.total_duration_ms:.1f}ms" if self.total_duration_ms else "running"
        )
        return (
            f"WorkflowResult(name={self.workflow_name}, "
            f"status={self.overall_status.value}, "
            f"steps={len(self.steps)}, "
            f"success_rate={self.success_rate:.1f}%, "
            f"duration={duration_str})"
        )
