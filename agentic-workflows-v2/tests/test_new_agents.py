"""Tests for Architect and Test agents."""

import pytest
from agentic_v2.agents import (
    ArchitectAgent,
    ArchitectureInput,
    TechStackChoice,
    TestAgent,
    TestFile,
    TestGenerationInput,
    TestType,
)
from agentic_v2.agents.base import AgentConfig, AgentState
from agentic_v2.models import ModelTier

# ============================================================================
# Architect Agent Tests
# ============================================================================


class TestArchitectureInput:
    """Tests for ArchitectureInput validation."""

    def test_valid_input(self):
        """Test valid architecture input."""
        inp = ArchitectureInput(
            requirements="Build a REST API for user management",
            arch_constraints="Must use PostgreSQL",
        )
        assert inp.requirements == "Build a REST API for user management"
        assert inp.arch_constraints == "Must use PostgreSQL"

    def test_empty_requirements_raises(self):
        """Test that empty requirements raises validation error."""
        with pytest.raises(Exception):  # Pydantic ValidationError for min_length
            ArchitectureInput(requirements="")

    def test_optional_fields_default(self):
        """Test optional fields have defaults."""
        inp = ArchitectureInput(requirements="Build an API")
        assert inp.arch_constraints is None
        assert inp.user_stories is None
        assert inp.existing_architecture is None
        assert inp.preferences == {}


class TestTechStackChoice:
    """Tests for TechStackChoice dataclass."""

    def test_basic_creation(self):
        """Test creating a tech stack choice."""
        choice = TechStackChoice(
            name="FastAPI",
            justification="High performance async framework",
            alternatives=["Flask", "Django"],
        )
        assert choice.name == "FastAPI"
        assert choice.justification == "High performance async framework"
        assert choice.alternatives == ["Flask", "Django"]

    def test_defaults(self):
        """Test default values."""
        choice = TechStackChoice(name="React", justification="Popular UI library")
        assert choice.alternatives == []


class TestArchitectAgent:
    """Tests for ArchitectAgent."""

    def test_default_config(self):
        """Test agent has correct default config."""
        agent = ArchitectAgent()
        assert agent.config.name == "architect"
        assert agent.config.default_tier == ModelTier.TIER_3
        assert agent.config.max_iterations == 3

    def test_custom_config(self):
        """Test agent with custom config."""
        config = AgentConfig(
            name="custom_architect",
            default_tier=ModelTier.TIER_4,
            max_iterations=5,
        )
        agent = ArchitectAgent(config=config)
        assert agent.config.name == "custom_architect"
        assert agent.config.default_tier == ModelTier.TIER_4

    def test_initial_state(self):
        """Test agent starts in CREATED state."""
        agent = ArchitectAgent()
        assert agent._state == AgentState.CREATED

    def test_format_task_message_basic(self):
        """Test task message formatting with basic input."""
        agent = ArchitectAgent()
        task = ArchitectureInput(requirements="Build a user management API")

        message = agent._format_task_message(task)

        assert "## Requirements" in message
        assert "Build a user management API" in message
        assert "## Task" in message
        assert "valid JSON" in message

    def test_format_task_message_with_constraints(self):
        """Test task message includes constraints."""
        agent = ArchitectAgent()
        task = ArchitectureInput(
            requirements="Build an API",
            arch_constraints="Use PostgreSQL and Redis",
        )

        message = agent._format_task_message(task)

        assert "## Constraints" in message
        assert "PostgreSQL and Redis" in message

    def test_format_task_message_with_user_stories(self):
        """Test task message includes user stories."""
        agent = ArchitectAgent()
        task = ArchitectureInput(
            requirements="Build an API",
            user_stories="As a user, I want to login",
        )

        message = agent._format_task_message(task)

        assert "## User Stories" in message
        assert "As a user" in message

    def test_parse_architecture_json_valid(self):
        """Test parsing valid JSON response."""
        agent = ArchitectAgent()
        response = """Here's the architecture:

```json
{
    "tech_stack": {
        "backend": {"name": "FastAPI", "justification": "Fast"}
    },
    "component_diagram": "graph TD",
    "api_strategy": {"type": "REST"}
}
```"""

        result = agent._parse_architecture_json(response)

        assert "tech_stack" in result
        assert result["tech_stack"]["backend"]["name"] == "FastAPI"

    def test_parse_architecture_json_raw_json(self):
        """Test parsing raw JSON without code block."""
        agent = ArchitectAgent()
        response = """{"tech_stack": {"backend": "FastAPI"}, "api_strategy": {}}"""

        result = agent._parse_architecture_json(response)

        assert result["tech_stack"]["backend"] == "FastAPI"

    def test_parse_architecture_json_invalid(self):
        """Test parsing invalid JSON returns fallback."""
        agent = ArchitectAgent()
        response = "This is not JSON at all"

        result = agent._parse_architecture_json(response)

        assert "raw_response" in result

    def test_extract_mermaid(self):
        """Test extracting Mermaid diagram."""
        agent = ArchitectAgent()
        response = """Some text
```mermaid
graph TD
    A --> B
```
More text"""

        diagram = agent._extract_mermaid(response)

        assert "```mermaid" in diagram
        assert "graph TD" in diagram
        assert "A --> B" in diagram


# ============================================================================
# Test Agent Tests
# ============================================================================


class TestTestGenerationInput:
    """Tests for TestGenerationInput validation."""

    def test_valid_with_code(self):
        """Test valid input with code."""
        inp = TestGenerationInput(
            code="def add(a, b): return a + b",
            language="python",
        )
        assert inp.code == "def add(a, b): return a + b"
        assert inp.language == "python"

    def test_valid_with_files(self):
        """Test valid input with files dict."""
        inp = TestGenerationInput(
            files={"main.py": "def main(): pass"},
            language="python",
        )
        assert "main.py" in inp.files

    def test_empty_code_and_files_allowed(self):
        """Test that empty code and files is allowed (agent handles validation)."""
        # Pydantic allows this - agent logic handles the validation during execution
        inp = TestGenerationInput(code="", files={}, language="python")
        assert inp.code == ""
        assert inp.files == {}

    def test_test_types_conversion(self):
        """Test string test types are converted to enum."""
        inp = TestGenerationInput(
            code="def test(): pass",
            test_types=["unit", "integration"],
        )
        assert inp.test_types[0] == TestType.UNIT
        assert inp.test_types[1] == TestType.INTEGRATION

    def test_default_values(self):
        """Test default values."""
        inp = TestGenerationInput(code="def x(): pass")
        assert inp.language == "python"
        assert inp.coverage_target == 80
        assert inp.test_types == [TestType.UNIT]


class TestTestFile:
    """Tests for TestFile dataclass."""

    def test_creation(self):
        """Test creating a test file."""
        tf = TestFile(
            filename="test_module.py",
            content="def test_example(): pass",
            test_type=TestType.UNIT,
            test_count=1,
        )
        assert tf.filename == "test_module.py"
        assert tf.test_type == TestType.UNIT
        assert tf.test_count == 1


class TestTestType:
    """Tests for TestType enum."""

    def test_values(self):
        """Test enum values."""
        assert TestType.UNIT.value == "unit"
        assert TestType.INTEGRATION.value == "integration"
        assert TestType.E2E.value == "e2e"
        assert TestType.PERFORMANCE.value == "performance"
        assert TestType.SECURITY.value == "security"


class TestTestAgent:
    """Tests for TestAgent."""

    def test_default_config(self):
        """Test agent has correct default config."""
        agent = TestAgent()
        assert agent.config.name == "test_agent"
        assert agent.config.default_tier == ModelTier.TIER_2
        assert agent.config.max_iterations == 5

    def test_custom_config(self):
        """Test agent with custom config."""
        config = AgentConfig(
            name="custom_tester",
            default_tier=ModelTier.TIER_3,
        )
        agent = TestAgent(config=config)
        assert agent.config.name == "custom_tester"

    def test_format_task_message_python(self):
        """Test task message formatting for Python."""
        agent = TestAgent()
        task = TestGenerationInput(
            code="def add(a, b): return a + b",
            language="python",
            test_types=[TestType.UNIT],
        )

        message = agent._format_task_message(task)

        assert "pytest" in message
        assert "def add(a, b)" in message
        assert "Unit tests" in message

    def test_format_task_message_typescript(self):
        """Test task message formatting for TypeScript."""
        agent = TestAgent()
        task = TestGenerationInput(
            code="function add(a: number, b: number): number { return a + b; }",
            language="typescript",
            test_types=[TestType.UNIT, TestType.INTEGRATION],
        )

        message = agent._format_task_message(task)

        assert "jest" in message.lower() or "Jest" in message
        assert "typescript" in message.lower()
        assert "Integration tests" in message

    def test_combine_files(self):
        """Test combining multiple files."""
        agent = TestAgent()
        files = {
            "module_a.py": "def func_a(): pass",
            "module_b.py": "def func_b(): pass",
        }

        combined = agent._combine_files(files)

        assert "module_a.py" in combined
        assert "module_b.py" in combined
        assert "func_a" in combined
        assert "func_b" in combined

    def test_count_tests_python(self):
        """Test counting Python tests."""
        agent = TestAgent()
        content = """
def test_one():
    pass

def test_two():
    pass

def helper():  # Not a test
    pass
"""
        count = agent._count_tests(content, "python")
        assert count == 2

    def test_count_tests_typescript(self):
        """Test counting TypeScript tests."""
        agent = TestAgent()
        content = """
it('should do something', () => {});
test('another test', () => {});
"""
        count = agent._count_tests(content, "typescript")
        assert count == 2

    def test_infer_test_type_unit(self):
        """Test inferring unit test type."""
        agent = TestAgent()
        assert (
            agent._infer_test_type("test_module.py", "def test_unit(): pass")
            == TestType.UNIT
        )

    def test_infer_test_type_integration(self):
        """Test inferring integration test type."""
        agent = TestAgent()
        assert agent._infer_test_type("test_integration.py", "") == TestType.INTEGRATION
        assert (
            agent._infer_test_type("test_api.py", "integration test")
            == TestType.INTEGRATION
        )

    def test_infer_test_type_e2e(self):
        """Test inferring E2E test type."""
        agent = TestAgent()
        assert agent._infer_test_type("test_e2e.py", "") == TestType.E2E
        assert agent._infer_test_type("test_flow.py", "end-to-end test") == TestType.E2E

    def test_parse_test_files_python(self):
        """Test parsing Python test files from response."""
        agent = TestAgent()
        from agentic_v2.agents.test_agent import LANGUAGE_CONFIG

        response = """Here are the tests:

```test_module.py
import pytest

def test_add():
    assert add(1, 2) == 3

def test_subtract():
    assert subtract(5, 3) == 2
```

```test_integration.py
def test_api_flow():
    pass
```
"""
        lang_config = LANGUAGE_CONFIG["python"]
        files = agent._parse_test_files(response, "python", lang_config)

        assert len(files) == 2
        assert files[0].filename == "test_module.py"
        assert files[0].test_count == 2
        assert files[1].filename == "test_integration.py"

    def test_generate_summary(self):
        """Test generating test summary."""
        agent = TestAgent()
        task = TestGenerationInput(code="def x(): pass", language="python")
        test_files = [
            TestFile(
                filename="test_unit.py",
                content="...",
                test_type=TestType.UNIT,
                test_count=5,
            ),
            TestFile(
                filename="test_int.py",
                content="...",
                test_type=TestType.INTEGRATION,
                test_count=3,
            ),
        ]

        summary = agent._generate_summary(test_files, task)

        assert "2 test file(s)" in summary
        assert "Unit tests: 5" in summary
        assert "Integration tests: 3" in summary


# ============================================================================
# Factory Function Tests
# ============================================================================


class TestFactoryFunctions:
    """Tests for agent factory functions."""

    def test_create_architect_agent(self):
        """Test architect agent factory."""
        from agentic_v2.agents.architect import create_architect_agent

        agent = create_architect_agent()
        assert isinstance(agent, ArchitectAgent)

    def test_create_test_agent(self):
        """Test test agent factory."""
        from agentic_v2.agents.test_agent import create_test_agent

        agent = create_test_agent()
        assert isinstance(agent, TestAgent)
