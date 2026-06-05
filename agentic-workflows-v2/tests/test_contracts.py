"""Tests for contract messages and schemas."""

from datetime import timedelta

import pytest

from agentic_v2.contracts import (
    AgentMessage,  # Messages; Schemas
    CodeGenerationInput,
    CodeGenerationOutput,
    CodeIssue,
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

# ============================================================================
# AgentMessage Tests
# ============================================================================


class TestAgentMessage:
    """Tests for AgentMessage contract."""

    def test_create_basic_message(self):
        """Test creating a basic message."""
        msg = AgentMessage(
            message_type=MessageType.TASK, role="coder", content="Generate a function"
        )

        assert msg.message_type == MessageType.TASK
        assert msg.role == "coder"
        assert msg.content == "Generate a function"
        assert msg.timestamp is not None
        assert not msg.is_error

    def test_role_normalization(self):
        """Test that role is normalized to lowercase."""
        msg = AgentMessage(
            message_type=MessageType.RESPONSE, role="  CODER  ", content="Done"
        )

        assert msg.role == "coder"

    def test_invalid_role_rejected(self):
        """Test that invalid role characters are rejected."""
        with pytest.raises(ValueError, match="alphanumeric"):
            AgentMessage(
                message_type=MessageType.TASK, role="coder@special", content="Test"
            )

    def test_error_detection(self):
        """Test is_error computed property."""
        error_msg = AgentMessage(
            message_type=MessageType.ERROR, role="system", content="Something failed"
        )

        assert error_msg.is_error

        normal_msg = AgentMessage(
            message_type=MessageType.RESPONSE, role="coder", content="Success"
        )

        assert not normal_msg.is_error

    def test_tool_call_detection(self):
        """Test tool call computed properties."""
        tool_call = AgentMessage(
            message_type=MessageType.TOOL_CALL,
            role="agent",
            content='{"tool": "file_read"}',
        )

        assert tool_call.is_tool_call
        assert not tool_call.is_tool_result

    def test_content_truncation(self):
        """Test content truncation for logging."""
        msg = AgentMessage(
            message_type=MessageType.RESPONSE, role="coder", content="A" * 500
        )

        truncated = msg.truncated_content(100)
        assert len(truncated) == 100
        assert truncated.endswith("...")

        # Short content not truncated
        short_msg = AgentMessage(
            message_type=MessageType.RESPONSE, role="coder", content="Short"
        )
        assert short_msg.truncated_content(100) == "Short"

    def test_correlation_id(self):
        """Test correlation ID for message tracking."""
        msg = AgentMessage(
            message_type=MessageType.TASK,
            role="orchestrator",
            content="Start workflow",
            correlation_id="workflow-123",
        )

        assert msg.correlation_id == "workflow-123"

    def test_repr(self):
        """Test string representation."""
        msg = AgentMessage(
            message_type=MessageType.TASK, role="coder", content="Generate code"
        )

        repr_str = repr(msg)
        assert "AgentMessage" in repr_str
        assert "task" in repr_str
        assert "coder" in repr_str


# ============================================================================
# StepResult Tests
# ============================================================================


class TestStepResult:
    """Tests for StepResult contract."""

    def test_create_pending_step(self):
        """Test creating a pending step."""
        step = StepResult(step_name="code_generation", status=StepStatus.PENDING)

        assert step.step_name == "code_generation"
        assert step.status == StepStatus.PENDING
        assert not step.is_success
        assert not step.is_failed
        assert not step.is_complete

    def test_mark_complete_success(self):
        """Test marking step as successfully completed."""
        step = StepResult(step_name="test", status=StepStatus.RUNNING)

        step.mark_complete(success=True)

        assert step.status == StepStatus.SUCCESS
        assert step.is_success
        assert step.is_complete
        assert step.end_time is not None

    def test_mark_complete_failure(self):
        """Test marking step as failed."""
        step = StepResult(step_name="test", status=StepStatus.RUNNING)

        step.mark_complete(success=False, error="Network timeout")

        assert step.status == StepStatus.FAILED
        assert step.is_failed
        assert step.error == "Network timeout"

    def test_duration_calculation(self):
        """Test duration calculation."""
        step = StepResult(step_name="test", status=StepStatus.RUNNING)

        # Duration is None while running
        assert step.duration_ms is None

        # Set end time
        step.end_time = step.start_time + timedelta(milliseconds=150)

        assert step.duration_ms is not None
        assert abs(step.duration_ms - 150) < 1  # Allow small rounding

    def test_model_tracking(self):
        """Test model and tier tracking."""
        step = StepResult(
            step_name="generate",
            status=StepStatus.SUCCESS,
            tier=2,
            model_used="ollama:phi4",
        )

        assert step.tier == 2
        assert step.model_used == "ollama:phi4"

    def test_retry_tracking(self):
        """Test retry count tracking."""
        step = StepResult(
            step_name="api_call", status=StepStatus.SUCCESS, retry_count=2
        )

        assert step.retry_count == 2

    def test_repr(self):
        """Test string representation."""
        step = StepResult(
            step_name="test_step", status=StepStatus.SUCCESS, retry_count=1
        )
        step.end_time = step.start_time + timedelta(milliseconds=100)

        repr_str = repr(step)
        assert "StepResult" in repr_str
        assert "test_step" in repr_str
        assert "success" in repr_str


# ============================================================================
# WorkflowResult Tests
# ============================================================================


class TestWorkflowResult:
    """Tests for WorkflowResult contract."""

    def test_create_workflow(self):
        """Test creating a workflow result."""
        workflow = WorkflowResult(
            workflow_id="wf-123",
            workflow_name="code-review",
            overall_status=StepStatus.RUNNING,
        )

        assert workflow.workflow_id == "wf-123"
        assert workflow.workflow_name == "code-review"
        assert workflow.steps == []

    def test_add_steps(self):
        """Test adding steps to workflow."""
        workflow = WorkflowResult(
            workflow_id="wf-123",
            workflow_name="pipeline",
            overall_status=StepStatus.RUNNING,
        )

        step1 = StepResult(step_name="step1", status=StepStatus.SUCCESS)
        step2 = StepResult(step_name="step2", status=StepStatus.SUCCESS)

        workflow.add_step(step1)
        workflow.add_step(step2)

        assert len(workflow.steps) == 2

    def test_success_rate(self):
        """Test success rate calculation."""
        workflow = WorkflowResult(
            workflow_id="wf-123",
            workflow_name="test",
            overall_status=StepStatus.SUCCESS,
        )

        workflow.add_step(StepResult(step_name="s1", status=StepStatus.SUCCESS))
        workflow.add_step(StepResult(step_name="s2", status=StepStatus.SUCCESS))
        workflow.add_step(StepResult(step_name="s3", status=StepStatus.FAILED))

        assert workflow.success_rate == pytest.approx(66.67, rel=0.1)

    def test_failed_steps(self):
        """Test failed steps tracking."""
        workflow = WorkflowResult(
            workflow_id="wf-123", workflow_name="test", overall_status=StepStatus.FAILED
        )

        workflow.add_step(StepResult(step_name="s1", status=StepStatus.SUCCESS))
        workflow.add_step(
            StepResult(step_name="s2", status=StepStatus.FAILED, error="Timeout")
        )
        workflow.add_step(
            StepResult(step_name="s3", status=StepStatus.FAILED, error="Rate limit")
        )

        failed = workflow.failed_steps
        assert len(failed) == 2
        assert failed[0].step_name == "s2"

    def test_total_retries(self):
        """Test total retry count across steps."""
        workflow = WorkflowResult(
            workflow_id="wf-123",
            workflow_name="test",
            overall_status=StepStatus.SUCCESS,
        )

        workflow.add_step(
            StepResult(step_name="s1", status=StepStatus.SUCCESS, retry_count=2)
        )
        workflow.add_step(
            StepResult(step_name="s2", status=StepStatus.SUCCESS, retry_count=1)
        )

        assert workflow.total_retries == 3

    def test_mark_complete(self):
        """Test marking workflow as complete."""
        workflow = WorkflowResult(
            workflow_id="wf-123",
            workflow_name="test",
            overall_status=StepStatus.RUNNING,
        )

        workflow.mark_complete(success=True)

        assert workflow.overall_status == StepStatus.SUCCESS
        assert workflow.end_time is not None
        assert workflow.total_duration_ms is not None


# ============================================================================
# TaskInput/TaskOutput Tests
# ============================================================================


class TestTaskInputOutput:
    """Tests for base task input/output."""

    def test_task_input_fluent_builder(self):
        """Test fluent builder pattern for task input."""
        task = TaskInput()
        task.with_context(file_path="/src/main.py", language="python")
        task.with_constraint("max_tokens", 1000)

        assert task.context["file_path"] == "/src/main.py"
        assert task.constraints["max_tokens"] == 1000

    def test_task_input_ignores_unknown_fields(self):
        """Unknown TaskInput fields are ignored for additive compatibility."""
        task = TaskInput(future_field="ignored")

        assert task.model_dump() == {"task_id": None, "context": {}, "constraints": {}}

    def test_task_input_known_field_types_still_validate(self):
        """Known TaskInput fields still enforce their declared types."""
        with pytest.raises(ValueError):
            TaskInput(context="not-a-dict")

    def test_task_output_failure_factory(self):
        """Test failure factory method."""
        output = TaskOutput.failure("Connection timeout")

        assert not output.success
        assert output.error == "Connection timeout"

    def test_task_output_confidence(self):
        """Test confidence bounds."""
        output = TaskOutput(success=True, confidence=0.85)
        assert output.confidence == 0.85

        # Invalid confidence
        with pytest.raises(ValueError):
            TaskOutput(success=True, confidence=1.5)


# ============================================================================
# CodeGeneration Tests
# ============================================================================


class TestCodeGeneration:
    """Tests for code generation schemas."""

    def test_code_gen_input_basic(self):
        """Test basic code generation input."""
        input = CodeGenerationInput(
            description="Create a function to add two numbers", language="Python"
        )

        assert input.description == "Create a function to add two numbers"
        assert input.language == "python"  # Normalized

    def test_code_gen_input_factory(self):
        """Test function generation factory."""
        input = CodeGenerationInput.for_function(
            description="Add two numbers",
            language="python",
            function_name="add",
            parameters=[("a", "int"), ("b", "int")],
            return_type="int",
        )

        assert "add" in input.description
        assert "a: int" in input.description
        assert "-> int" in input.description

    def test_code_gen_output_line_count(self):
        """Test line counting in output."""
        output = CodeGenerationOutput(
            success=True, code="def add(a, b):\n    return a + b\n", language="python"
        )

        assert output.line_count == 2  # Non-empty lines

    def test_code_gen_output_diff(self):
        """Test diff generation."""
        original = "def foo():\n    pass\n"
        output = CodeGenerationOutput(
            success=True, code="def foo():\n    return 42\n", language="python"
        )

        diff = output.get_diff(original)
        assert "-    pass" in diff
        assert "+    return 42" in diff


# ============================================================================
# CodeReview Tests
# ============================================================================


class TestCodeReview:
    """Tests for code review schemas."""

    def test_code_issue(self):
        """Test code issue creation."""
        issue = CodeIssue(
            severity=Severity.HIGH,
            category=IssueCategory.SECURITY,
            message="SQL injection vulnerability",
            line_number=42,
            suggestion="Use parameterized queries",
        )

        assert issue.severity == Severity.HIGH
        assert issue.location == "line 42"

    def test_code_review_output_grouping(self):
        """Test issue grouping by severity and category."""
        output = CodeReviewOutput(
            success=True,
            issues=[
                CodeIssue(
                    severity=Severity.CRITICAL,
                    category=IssueCategory.SECURITY,
                    message="SQL injection",
                ),
                CodeIssue(
                    severity=Severity.HIGH,
                    category=IssueCategory.SECURITY,
                    message="XSS possible",
                ),
                CodeIssue(
                    severity=Severity.LOW,
                    category=IssueCategory.STYLE,
                    message="Line too long",
                ),
            ],
            quality_score=60.0,
        )

        by_severity = output.issues_by_severity
        assert len(by_severity[Severity.CRITICAL]) == 1
        assert len(by_severity[Severity.HIGH]) == 1

        by_category = output.issues_by_category
        assert len(by_category[IssueCategory.SECURITY]) == 2

    def test_needs_attention(self):
        """Test needs_attention flag."""
        # With critical issue
        output = CodeReviewOutput(
            success=True,
            issues=[
                CodeIssue(
                    severity=Severity.CRITICAL,
                    category=IssueCategory.SECURITY,
                    message="Critical!",
                )
            ],
            quality_score=50.0,
        )
        assert output.needs_attention

        # Without critical issues
        clean_output = CodeReviewOutput(
            success=True,
            issues=[
                CodeIssue(
                    severity=Severity.LOW, category=IssueCategory.STYLE, message="Minor"
                )
            ],
            quality_score=90.0,
        )
        assert not clean_output.needs_attention


# ============================================================================
# TestGeneration Tests
# ============================================================================


class TestTestGeneration:
    """Tests for test generation schemas."""

    def test_auto_framework_inference(self):
        """Test automatic framework inference."""
        input = TestGenerationInput(
            code="def add(a, b): return a + b", language="python"
        )

        assert input.framework == "pytest"

        js_input = TestGenerationInput(
            code="function add(a, b) { return a + b; }", language="javascript"
        )

        assert js_input.framework == "jest"

    def test_test_case(self):
        """Test TestCase model."""
        test = TestCase(
            name="test_add_positive",
            description="Test adding positive numbers",
            test_type=TestType.UNIT,
            code="def test_add_positive():\n    assert add(1, 2) == 3",
        )

        assert test.is_unit_test
        assert test.expected_to_pass

    def test_output_combined_code(self):
        """Test combining all test code."""
        output = TestGenerationOutput(
            success=True,
            setup_code="@pytest.fixture\ndef calculator():\n    return Calculator()",
            tests=[
                TestCase(
                    name="test1",
                    description="Test 1",
                    test_type=TestType.UNIT,
                    code="def test1(): pass",
                ),
                TestCase(
                    name="test2",
                    description="Test 2",
                    test_type=TestType.UNIT,
                    code="def test2(): pass",
                ),
            ],
            estimated_coverage=85.0,
        )

        combined = output.get_combined_code()
        assert "Setup" in combined
        assert "test1" in combined
        assert "test2" in combined

    def test_by_type_grouping(self):
        """Test grouping tests by type."""
        output = TestGenerationOutput(
            success=True,
            tests=[
                TestCase(
                    name="unit1",
                    description="Unit",
                    test_type=TestType.UNIT,
                    code="...",
                ),
                TestCase(
                    name="unit2",
                    description="Unit",
                    test_type=TestType.UNIT,
                    code="...",
                ),
                TestCase(
                    name="int1",
                    description="Integration",
                    test_type=TestType.INTEGRATION,
                    code="...",
                ),
            ],
        )

        by_type = output.by_type
        assert len(by_type[TestType.UNIT]) == 2
        assert len(by_type[TestType.INTEGRATION]) == 1
