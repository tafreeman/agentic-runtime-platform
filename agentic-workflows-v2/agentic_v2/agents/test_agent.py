"""Agent specialized for automated test suite generation.

Provides :class:`TestAgent`, a :class:`~agentic_v2.agents.base.BaseAgent`
subclass that generates runnable test files from source code.  Supports
multiple languages (Python/pytest, TypeScript/Jest, JavaScript/Jest,
Go/testing, Rust/cargo test) and test types (unit, integration, E2E,
performance, security).

The agent produces :class:`TestGenerationOutput` containing parsed
:class:`TestFile` instances, test counts, and a heuristic coverage
estimate.
"""

from __future__ import annotations

import re
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator

from ..contracts import TaskInput, TaskOutput
from ..models import ModelTier
from .base import AgentConfig, BaseAgent


class TestType(str, Enum):
    """Enumeration of test categories that :class:`TestAgent` can generate."""

    __test__ = False  # Not a pytest test class

    UNIT = "unit"
    INTEGRATION = "integration"
    E2E = "e2e"
    PERFORMANCE = "performance"
    SECURITY = "security"


class TestGenerationInput(TaskInput):
    """Input schema for the :class:`TestAgent`.

    Attributes:
        code: Source code to generate tests for (single file).
        files: Multiple source files as ``{filename: content}`` pairs.
            When provided and ``code`` is empty, files are concatenated.
        language: Target programming language (default ``"python"``).
        test_types: Categories of tests to generate (default: unit only).
        coverage_target: Desired code coverage percentage (default 80).
        framework: Explicit test framework override (e.g., ``"pytest"``,
            ``"jest"``).  Defaults to the language's standard framework
            from ``LANGUAGE_CONFIG``.
        mocking_strategy: Optional natural-language description of the
            desired mocking approach.
    """

    __test__ = False  # Not a pytest test class

    code: str = Field(default="", description="Code to generate tests for")
    files: dict[str, str] = Field(
        default_factory=dict, description="Multiple files to test"
    )
    language: str = Field(default="python", description="Programming language")
    test_types: list[TestType] = Field(
        default_factory=lambda: [TestType.UNIT],
        description="Types of tests to generate",
    )
    coverage_target: int = Field(default=80, description="Target coverage percentage")
    framework: str | None = Field(
        default=None, description="Test framework (pytest, jest, etc.)"
    )
    mocking_strategy: str | None = Field(default=None, description="Mocking approach")

    @field_validator("test_types", mode="before")
    @classmethod
    def convert_test_types(cls, v: Any) -> list[TestType]:
        """Convert string test types to enum."""
        if not v:
            return [TestType.UNIT]
        result = []
        for item in v:
            if isinstance(item, str):
                result.append(TestType(item))
            else:
                result.append(item)
        return result


class TestFile(BaseModel):
    """A single test file parsed from the LLM's response.

    Attributes:
        filename: Name of the test file (e.g., ``test_utils.py``).
        content: Full source code of the test file.
        test_type: Inferred :class:`TestType` based on filename and content
            heuristics.
        test_count: Number of individual test functions detected in the
            content via language-specific regex patterns.
    """

    __test__ = False  # Not a pytest test class

    filename: str = Field(default="", description="Test file name")
    content: str = Field(default="", description="Test file content")
    test_type: TestType = Field(
        default=TestType.UNIT, description="Type of tests in file"
    )
    test_count: int = Field(default=0, description="Number of tests in file")


class TestGenerationOutput(TaskOutput):
    """Output schema produced by the :class:`TestAgent`.

    Attributes:
        test_files: Parsed :class:`TestFile` instances extracted from
            the model response.
        total_tests: Sum of ``test_count`` across all files.
        coverage_estimate: Heuristic coverage estimate (0--95) based on
            the number of generated tests.
        test_summary: Human-readable summary of what was generated.
        raw_response: Unprocessed model response for debugging.
    """

    test_files: list[TestFile] = Field(default_factory=list)
    total_tests: int = Field(default=0)
    coverage_estimate: int = Field(default=0)
    test_summary: str = Field(default="")
    raw_response: str = Field(default="")


# Language-specific test frameworks and patterns
LANGUAGE_CONFIG = {
    "python": {
        "framework": "pytest",
        "file_extension": "py",
        "test_prefix": "test_",
        "import_statement": "import pytest\n",
        "patterns": [
            "Use pytest fixtures for common setup",
            "Use @pytest.mark.parametrize for data-driven tests",
            "Use pytest.raises for exception testing",
            "Use unittest.mock for mocking",
        ],
    },
    "typescript": {
        "framework": "jest",
        "file_extension": "test.ts",
        "test_prefix": "",
        "import_statement": "import { describe, it, expect, jest } from '@jest/globals';\n",
        "patterns": [
            "Use describe blocks for grouping",
            "Use beforeEach/afterEach for setup/teardown",
            "Use jest.mock for module mocking",
            "Use expect().toThrow for exception testing",
        ],
    },
    "javascript": {
        "framework": "jest",
        "file_extension": "test.js",
        "test_prefix": "",
        "import_statement": "const { describe, it, expect, jest } = require('@jest/globals');\n",
        "patterns": [
            "Use describe blocks for grouping",
            "Use beforeEach/afterEach for setup/teardown",
            "Use jest.mock for module mocking",
        ],
    },
    "go": {
        "framework": "testing",
        "file_extension": "_test.go",
        "test_prefix": "Test",
        "import_statement": 'import "testing"\n',
        "patterns": [
            "Use table-driven tests",
            "Use t.Run for subtests",
            "Use testify for assertions",
        ],
    },
    "rust": {
        "framework": "cargo test",
        "file_extension": "rs",
        "test_prefix": "test_",
        "import_statement": "#[cfg(test)]\nmod tests {\n    use super::*;\n",
        "patterns": [
            "Use #[test] attribute",
            "Use assert! and assert_eq! macros",
            "Use #[should_panic] for panic tests",
        ],
    },
}

SYSTEM_PROMPT = """You are a test automation expert specializing in comprehensive test coverage.

Generate high-quality tests including:
1. Unit tests targeting >80% code coverage
2. Integration tests for component interactions
3. End-to-end tests for critical user flows
4. Edge case and error scenario tests
5. Boundary condition tests

Best Practices:
- Use descriptive test names that explain what is being tested
- Follow the Arrange-Act-Assert (AAA) pattern
- Use proper mocking and fixtures for external dependencies
- Include both positive (happy path) and negative (error) cases
- Use parameterized/table-driven tests for multiple inputs
- Test boundary conditions (empty, null, max values)
- Include setup and teardown where needed

Generate complete, runnable test files with all necessary imports and fixtures.
Each test file should be in a markdown code block with the filename.
"""


class TestAgent(BaseAgent[TestGenerationInput, TestGenerationOutput]):
    """Agent that generates comprehensive test suites from source code.

    Extends :class:`~agentic_v2.agents.base.BaseAgent` parameterized with
    :class:`TestGenerationInput` / :class:`TestGenerationOutput`.

    The agent:

    1. Selects language-specific test patterns and framework from
       ``LANGUAGE_CONFIG``.
    2. Formats a detailed prompt including coverage targets, test types,
       and mocking strategy.
    3. Parses the model response into :class:`TestFile` instances by
       extracting fenced code blocks, counting test functions, and
       inferring :class:`TestType` from filenames and content.

    Args:
        config: Agent configuration. Defaults to a Tier-2 config named
            ``"test_agent"`` with 5 max iterations.
        **kwargs: Passed through to :class:`BaseAgent.__init__`.
    """

    __test__ = False  # Not a pytest test class

    def __init__(self, config: AgentConfig | None = None, **kwargs):
        if config is None:
            config = AgentConfig(
                name="test_agent",
                description="Test generation agent",
                system_prompt=SYSTEM_PROMPT,
                default_tier=ModelTier.TIER_2,
                max_iterations=5,
            )

        super().__init__(config=config, **kwargs)

    async def _call_model(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        """Call the underlying LLM to generate tests.

        Args:
            messages: Chat messages to send
            tools: Optional tools (not typically used for test generation)

        Returns:
            Model response dict with "content" key
        """

        # If no backend is configured, return a mock response for testing
        if self.llm_client.backend is None:
            return {"content": """
```python
# test_example.py
import pytest

def test_example_function():
    '''Test example function.'''
    assert True

def test_example_edge_case():
    '''Test edge case.'''
    assert 1 + 1 == 2

@pytest.fixture
def sample_data():
    return {"key": "value"}

def test_with_fixture(sample_data):
    '''Test using fixture.'''
    assert sample_data["key"] == "value"
```

Generated 3 tests with ~80% estimated coverage.
"""}

        # Use real LLM client
        result_dict, model_used, tokens = await self.llm_client.complete_chat(
            messages=messages,
            tier=self.config.default_tier,
            temperature=0.2,  # Lower temp for test generation
        )

        return {"content": result_dict.get("content", result_dict.get("message", ""))}

    def _format_task_message(self, task: TestGenerationInput) -> str:
        """Format test generation task."""
        lang_config = LANGUAGE_CONFIG.get(
            task.language.lower(), LANGUAGE_CONFIG["python"]
        )
        framework = task.framework or lang_config["framework"]

        # Combine code from files if needed
        if task.files and not task.code:
            code = self._combine_files(task.files)
        else:
            code = task.code

        # Build test type descriptions
        type_descriptions = []
        for tt in task.test_types:
            if tt == TestType.UNIT:
                type_descriptions.append(
                    "- Unit tests for individual functions/methods"
                )
            elif tt == TestType.INTEGRATION:
                type_descriptions.append(
                    "- Integration tests for component interactions"
                )
            elif tt == TestType.E2E:
                type_descriptions.append("- End-to-end tests for complete user flows")
            elif tt == TestType.PERFORMANCE:
                type_descriptions.append("- Performance tests for critical paths")
            elif tt == TestType.SECURITY:
                type_descriptions.append("- Security tests for vulnerabilities")

        # Build prompt
        parts = [
            "## Test Generation Request",
            "",
            f"Generate comprehensive tests using **{framework}** for the following {task.language} code.",
            "",
            "## Code to Test",
            "",
            f"```{task.language}",
            code,
            "```",
            "",
            "## Test Types Required",
            "",
            "\n".join(type_descriptions),
            "",
            "## Requirements",
            "",
            f"1. Target >{task.coverage_target}% code coverage",
            "2. Test happy paths and error cases",
            "3. Include edge cases and boundary conditions",
            "4. Use descriptive test names",
            "5. Include proper mocking for external dependencies",
            "6. Add fixtures for common test data",
            "7. Use parameterized tests where appropriate",
            "",
            f"## {task.language.title()} Testing Patterns",
            "",
            "\n".join(f"- {p}" for p in lang_config["patterns"]),
            "",
            "## Output Format",
            "",
            "Format each test file as a code block with filename:",
            f"```{lang_config['test_prefix']}module_name.{lang_config['file_extension']}",
            "// test contents",
            "```",
        ]

        if task.mocking_strategy:
            parts.extend(
                [
                    "",
                    "## Mocking Strategy",
                    "",
                    task.mocking_strategy,
                ]
            )

        return "\n".join(parts)

    def _combine_files(self, files: dict[str, str]) -> str:
        """Combine multiple files for test generation."""
        parts = []
        for filename, content in files.items():
            parts.append(f"// File: {filename}")
            parts.append(content)
            parts.append("")
        return "\n".join(parts)

    async def _is_task_complete(self, task: TestGenerationInput, response: str) -> bool:
        """Check if response contains valid tests."""
        # Must have at least one code block
        return "```" in response and (
            "def test_" in response
            or "it(" in response
            or "func Test" in response
            or "#[test]" in response
        )

    async def _parse_output(
        self, task: TestGenerationInput, response: str
    ) -> TestGenerationOutput:
        """Parse response into TestGenerationOutput."""
        lang_config = LANGUAGE_CONFIG.get(
            task.language.lower(), LANGUAGE_CONFIG["python"]
        )
        test_files = self._parse_test_files(response, task.language, lang_config)

        # Count total tests
        total_tests = sum(tf.test_count for tf in test_files)

        # Estimate coverage (rough heuristic)
        coverage_estimate = min(95, 40 + total_tests * 3)

        # Generate summary
        test_summary = self._generate_summary(test_files, task)

        return TestGenerationOutput(
            test_files=test_files,
            total_tests=total_tests,
            coverage_estimate=coverage_estimate,
            test_summary=test_summary,
            raw_response=response,
        )

    def _parse_test_files(
        self, response: str, language: str, lang_config: dict
    ) -> list[TestFile]:
        """Parse test files from model response."""
        files: list[TestFile] = []

        # Split by code blocks
        parts = response.split("```")

        for i in range(1, len(parts), 2):
            if i >= len(parts):
                break

            block = parts[i]
            lines = block.split("\n", 1)

            if len(lines) < 2:
                continue

            first_line = lines[0].strip()
            content = lines[1] if len(lines) > 1 else ""

            # Determine filename
            ext = lang_config["file_extension"]
            prefix = lang_config["test_prefix"]

            if first_line.startswith(prefix) or first_line.endswith(f".{ext}"):
                filename = first_line
            elif first_line in (
                language,
                "python",
                "typescript",
                "javascript",
                "go",
                "rust",
            ):
                filename = f"{prefix}generated.{ext}"
            else:
                filename = f"{prefix}generated.{ext}"

            # Count tests in content
            test_count = self._count_tests(content, language)

            # Determine test type (heuristic)
            test_type = self._infer_test_type(filename, content)

            files.append(
                TestFile(
                    filename=filename,
                    content=content.strip(),
                    test_type=test_type,
                    test_count=test_count,
                )
            )

        return files

    def _count_tests(self, content: str, language: str) -> int:
        """Count number of tests in content."""
        patterns = {
            "python": r"def test_\w+",
            "typescript": r"(it|test)\s*\(",
            "javascript": r"(it|test)\s*\(",
            "go": r"func Test\w+",
            "rust": r"#\[test\]",
        }

        pattern = patterns.get(language.lower(), patterns["python"])
        matches = re.findall(pattern, content)
        return len(matches)

    def _infer_test_type(self, filename: str, content: str) -> TestType:
        """Infer test type from filename and content."""
        lower_name = filename.lower()
        lower_content = content.lower()

        if "integration" in lower_name or "integration" in lower_content:
            return TestType.INTEGRATION
        if "e2e" in lower_name or "end-to-end" in lower_content:
            return TestType.E2E
        if "perf" in lower_name or "performance" in lower_content:
            return TestType.PERFORMANCE
        if "security" in lower_name or "vulnerability" in lower_content:
            return TestType.SECURITY

        return TestType.UNIT

    def _generate_summary(
        self, test_files: list[TestFile], task: TestGenerationInput
    ) -> str:
        """Generate a summary of generated tests."""
        if not test_files:
            return "No test files generated."

        parts = [
            f"Generated {len(test_files)} test file(s) for {task.language}:",
            "",
        ]

        type_counts: dict[TestType, int] = {}
        for tf in test_files:
            type_counts[tf.test_type] = type_counts.get(tf.test_type, 0) + tf.test_count

        for tt, count in type_counts.items():
            parts.append(f"- {tt.value.title()} tests: {count}")

        parts.append("")
        parts.append("Files:")
        for tf in test_files:
            parts.append(f"- {tf.filename} ({tf.test_count} tests)")

        return "\n".join(parts)


# Convenience factory
def create_test_agent(**kwargs) -> TestAgent:
    """Create a test agent with optional overrides."""
    return TestAgent(**kwargs)
