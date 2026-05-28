"""Task schemas for structured agent inputs/outputs.

Provides Pydantic v2 models for the three primary task domains:

1. **Code Generation** — :class:`CodeGenerationInput` /
   :class:`CodeGenerationOutput` with automatic diff generation and
   file-level output tracking.
2. **Code Review** — :class:`CodeReviewInput` / :class:`CodeReviewOutput`
   with :class:`CodeIssue` findings categorized by :class:`Severity` and
   :class:`IssueCategory`.
3. **Test Generation** — :class:`TestGenerationInput` /
   :class:`TestGenerationOutput` with :class:`TestCase` items and
   framework inference.

Base classes :class:`TaskInput` / :class:`TaskOutput` provide a fluent
builder pattern (``with_context()``, ``with_constraint()``) for
programmatic task construction.
"""

from enum import Enum
from typing import Any, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

T = TypeVar("T")


class Severity(str, Enum):
    """Severity level for code issues."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class IssueCategory(str, Enum):
    """Category of code issue."""

    SECURITY = "security"
    PERFORMANCE = "performance"
    MAINTAINABILITY = "maintainability"
    CORRECTNESS = "correctness"
    STYLE = "style"
    DOCUMENTATION = "documentation"
    TESTING = "testing"


class TestType(str, Enum):
    """Type of test to generate."""

    __test__ = False  # Not a pytest test class

    UNIT = "unit"
    INTEGRATION = "integration"
    E2E = "e2e"
    PROPERTY = "property"
    SNAPSHOT = "snapshot"


# ============================================================================
# Base Classes with Generic Support
# ============================================================================


class TaskInput(BaseModel):
    """Base class for all task inputs.

    Design: Generic base with common fields and validation hooks.
    Subclasses add task-specific fields and validators.
    """

    model_config = ConfigDict(validate_assignment=True, extra="ignore", frozen=False)

    task_id: str | None = Field(
        default=None, description="Unique task identifier for tracking"
    )
    context: dict[str, Any] = Field(
        default_factory=dict, description="Additional context for task execution"
    )
    constraints: dict[str, Any] = Field(
        default_factory=dict,
        description="Execution constraints (max_tokens, timeout, etc.)",
    )

    def with_context(self, **kwargs: Any) -> "TaskInput":
        """Fluent builder: Add context values.

        Returns:
            Self for chaining
        """
        self.context.update(kwargs)
        return self

    def with_constraint(self, key: str, value: Any) -> "TaskInput":
        """Fluent builder: Add constraint.

        Returns:
            Self for chaining
        """
        self.constraints[key] = value
        return self


class TaskOutput(BaseModel):
    """Base class for all task outputs.

    Design: Common success/error handling with rich metadata.
    """

    model_config = ConfigDict(
        validate_assignment=True, extra="allow"  # Allow task-specific extra fields
    )

    success: bool = Field(description="Whether task completed successfully")
    error: str | None = Field(default=None, description="Error message if failed")
    confidence: float = Field(
        default=1.0, description="Model's confidence in output (0-1)", ge=0.0, le=1.0
    )
    tokens_used: int = Field(default=0, description="Total tokens consumed", ge=0)
    model_used: str | None = Field(
        default=None, description="Model that produced this output"
    )

    @classmethod
    def failure(cls, error: str, **kwargs: Any) -> "TaskOutput":
        """Factory: Create a failed output.

        Args:
            error: Error message
            **kwargs: Additional fields

        Returns:
            Failed TaskOutput instance
        """
        return cls(success=False, error=error, **kwargs)


# ============================================================================
# Code Generation Schemas
# ============================================================================


class CodeGenerationInput(TaskInput):
    """Input for code generation tasks.

    Aggressive improvements:
    - Language-specific validation
    - Template/pattern suggestions
    - Dependency awareness
    """

    description: str = Field(
        description="Natural language description of code to generate", min_length=10
    )
    language: str = Field(description="Target programming language", min_length=1)
    file_path: str | None = Field(
        default=None, description="Target file path for generated code"
    )
    existing_code: str | None = Field(
        default=None, description="Existing code to modify/extend"
    )
    dependencies: list[str] = Field(
        default_factory=list, description="Required dependencies/imports"
    )
    style_guide: str | None = Field(
        default=None, description="Coding style guide to follow"
    )
    examples: list[str] = Field(
        default_factory=list, description="Example code snippets for reference"
    )

    @field_validator("language")
    @classmethod
    def normalize_language(cls, v: str) -> str:
        """Normalize language name to lowercase."""
        return v.lower().strip()

    @classmethod
    def for_function(
        cls,
        description: str,
        language: str,
        function_name: str,
        parameters: list[tuple[str, str]],
        return_type: str,
    ) -> "CodeGenerationInput":
        """Factory: Create input for function generation.

        Args:
            description: What the function should do
            language: Target language
            function_name: Name of function
            parameters: List of (name, type) tuples
            return_type: Return type

        Returns:
            Configured CodeGenerationInput
        """
        params_str = ", ".join(f"{name}: {typ}" for name, typ in parameters)
        full_desc = f"{description}\n\nSignature: {function_name}({params_str}) -> {return_type}"
        return cls(description=full_desc, language=language)


class CodeGenerationOutput(TaskOutput):
    """Output from code generation tasks.

    Aggressive improvements:
    - Automatic diff generation
    - Syntax validation hooks
    - Import extraction
    """

    code: str = Field(default="", description="Generated code")
    language: str = Field(default="", description="Language of generated code")
    imports: list[str] = Field(
        default_factory=list, description="Required imports extracted from code"
    )
    explanation: str | None = Field(
        default=None, description="Explanation of generated code"
    )

    @property
    def line_count(self) -> int:
        """Count non-empty lines in generated code."""
        return sum(1 for line in self.code.splitlines() if line.strip())

    def get_diff(self, original: str) -> str:
        """Generate unified diff against original code.

        Args:
            original: Original code to diff against

        Returns:
            Unified diff string
        """
        import difflib

        original_lines = original.splitlines(keepends=True)
        new_lines = self.code.splitlines(keepends=True)
        diff = difflib.unified_diff(
            original_lines, new_lines, fromfile="original", tofile="generated"
        )
        return "".join(diff)


# ============================================================================
# Code Review Schemas
# ============================================================================


class CodeIssue(BaseModel):
    """A single issue found during code review."""

    severity: Severity = Field(description="Issue severity")
    category: IssueCategory = Field(description="Issue category")
    message: str = Field(description="Issue description", min_length=1)
    line_number: int | None = Field(default=None, ge=1)
    column: int | None = Field(default=None, ge=1)
    suggestion: str | None = Field(default=None, description="Suggested fix")
    code_snippet: str | None = Field(default=None, description="Relevant code")

    @property
    def location(self) -> str:
        """Get formatted location string."""
        if self.line_number is None:
            return "unknown"
        if self.column is None:
            return f"line {self.line_number}"
        return f"line {self.line_number}, col {self.column}"


class CodeReviewInput(TaskInput):
    """Input for code review tasks.

    Aggressive improvements:
    - Severity filtering
    - Focus areas
    - Previous review context
    """

    code: str = Field(description="Code to review", min_length=1)
    language: str = Field(description="Programming language")
    file_path: str | None = Field(default=None, description="File path for context")
    focus_areas: list[IssueCategory] = Field(
        default_factory=list, description="Categories to focus on (empty = all)"
    )
    min_severity: Severity = Field(
        default=Severity.LOW, description="Minimum severity to report"
    )
    previous_issues: list[CodeIssue] = Field(
        default_factory=list, description="Issues from previous reviews to check"
    )

    @field_validator("language")
    @classmethod
    def normalize_language(cls, v: str) -> str:
        """Normalize language name."""
        return v.lower().strip()


class CodeReviewOutput(TaskOutput):
    """Output from code review tasks.

    Aggressive improvements:
    - Issue aggregation by severity/category
    - Quality score calculation
    - Actionable summary
    """

    issues: list[CodeIssue] = Field(
        default_factory=list, description="Issues found in code"
    )
    summary: str = Field(default="", description="Overall review summary")
    quality_score: float = Field(
        default=0.0, description="Overall quality score (0-100)", ge=0.0, le=100.0
    )

    @property
    def critical_count(self) -> int:
        """Count critical issues."""
        return sum(1 for i in self.issues if i.severity == Severity.CRITICAL)

    @property
    def high_count(self) -> int:
        """Count high severity issues."""
        return sum(1 for i in self.issues if i.severity == Severity.HIGH)

    @property
    def issues_by_category(self) -> dict[IssueCategory, list[CodeIssue]]:
        """Group issues by category."""
        result: dict[IssueCategory, list[CodeIssue]] = {}
        for issue in self.issues:
            if issue.category not in result:
                result[issue.category] = []
            result[issue.category].append(issue)
        return result

    @property
    def issues_by_severity(self) -> dict[Severity, list[CodeIssue]]:
        """Group issues by severity."""
        result: dict[Severity, list[CodeIssue]] = {}
        for issue in self.issues:
            if issue.severity not in result:
                result[issue.severity] = []
            result[issue.severity].append(issue)
        return result

    @property
    def needs_attention(self) -> bool:
        """Check if review found significant issues."""
        return self.critical_count > 0 or self.high_count > 2


# ============================================================================
# Test Generation Schemas
# ============================================================================


class TestCase(BaseModel):
    """A single generated test case."""

    __test__ = False  # Not a pytest test class

    name: str = Field(description="Test function name")
    description: str = Field(description="What the test verifies")
    test_type: TestType = Field(description="Type of test")
    code: str = Field(description="Test code")
    expected_to_pass: bool = Field(default=True)

    @property
    def is_unit_test(self) -> bool:
        """Check if this is a unit test."""
        return self.test_type == TestType.UNIT


class TestGenerationInput(TaskInput):
    """Input for test generation tasks.

    Aggressive improvements:
    - Coverage target specification
    - Edge case generation hints
    - Mocking strategy
    """

    __test__ = False  # Not a pytest test class

    code: str = Field(description="Code to generate tests for", min_length=1)
    language: str = Field(description="Programming language")
    test_types: list[TestType] = Field(
        default_factory=lambda: [TestType.UNIT],
        description="Types of tests to generate",
    )
    framework: str | None = Field(
        default=None, description="Testing framework to use (pytest, jest, etc.)"
    )
    coverage_target: float = Field(
        default=80.0, description="Target code coverage percentage", ge=0.0, le=100.0
    )
    edge_cases: list[str] = Field(
        default_factory=list, description="Specific edge cases to test"
    )
    mock_dependencies: bool = Field(
        default=True, description="Whether to mock external dependencies"
    )

    @field_validator("language")
    @classmethod
    def normalize_language(cls, v: str) -> str:
        """Normalize language name."""
        return v.lower().strip()

    @model_validator(mode="after")
    def infer_framework(self) -> "TestGenerationInput":
        """Auto-infer test framework if not specified."""
        if self.framework is None:
            frameworks = {
                "python": "pytest",
                "javascript": "jest",
                "typescript": "jest",
                "java": "junit",
                "go": "testing",
                "rust": "cargo test",
                "c#": "xunit",
                "csharp": "xunit",
            }
            self.framework = frameworks.get(self.language, "unittest")
        return self


class TestGenerationOutput(TaskOutput):
    """Output from test generation tasks.

    Aggressive improvements:
    - Coverage estimation
    - Test organization
    - Setup/teardown extraction
    """

    __test__ = False  # Not a pytest test class

    tests: list[TestCase] = Field(
        default_factory=list, description="Generated test cases"
    )
    setup_code: str | None = Field(
        default=None, description="Shared setup/fixtures code"
    )
    teardown_code: str | None = Field(default=None, description="Shared teardown code")
    estimated_coverage: float = Field(
        default=0.0, description="Estimated code coverage percentage", ge=0.0, le=100.0
    )

    @property
    def test_count(self) -> int:
        """Count generated tests."""
        return len(self.tests)

    @property
    def by_type(self) -> dict[TestType, list[TestCase]]:
        """Group tests by type."""
        result: dict[TestType, list[TestCase]] = {}
        for test in self.tests:
            if test.test_type not in result:
                result[test.test_type] = []
            result[test.test_type].append(test)
        return result

    def get_combined_code(self) -> str:
        """Get all test code combined.

        Returns:
            Combined test file content
        """
        parts = []
        if self.setup_code:
            parts.append(f"# Setup\n{self.setup_code}\n")
        for test in self.tests:
            parts.append(f"# {test.description}\n{test.code}\n")
        if self.teardown_code:
            parts.append(f"# Teardown\n{self.teardown_code}\n")
        return "\n".join(parts)
