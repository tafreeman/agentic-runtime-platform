"""Tests for agent components."""

# ADR-008 cleanup: removed 3 duplicate tests (see docs/adr/ADR-008-testing-approach-overhaul.md)

import pytest
from agentic_v2.agents import AgentConfig  # Base; Capabilities; Agents
from agentic_v2.agents import (
    AgentEvent,
    AgentState,
    Capability,
    CapabilitySet,
    CapabilityType,
    CoderAgent,
    ConversationMemory,
    OrchestratorAgent,
    OrchestratorInput,
    ReviewerAgent,
    get_agent_capabilities,
)
from agentic_v2.contracts import (
    CodeGenerationInput,
    CodeGenerationOutput,
    CodeReviewInput,
    CodeReviewOutput,
)
from agentic_v2.models import ModelTier

# ============================================================================
# ConversationMemory Tests
# ============================================================================


class TestConversationMemory:
    """Tests for ConversationMemory."""

    def test_add_messages(self):
        """Test adding different message types."""
        memory = ConversationMemory()

        memory.add_user("Hello")
        memory.add_assistant("Hi there")
        memory.add_system("You are helpful")

        assert len(memory.messages) == 3
        assert memory.messages[0].role == "user"
        assert memory.messages[1].role == "assistant"
        assert memory.messages[2].role == "system"

    def test_add_tool_result(self):
        """Test adding tool result."""
        memory = ConversationMemory()

        memory.add_tool_result("read_file", "content here", "call_123")

        assert len(memory.messages) == 1
        msg = memory.messages[0]
        assert msg.role == "tool"
        assert msg.tool_name == "read_file"
        assert msg.tool_call_id == "call_123"

    def test_get_messages_for_api(self):
        """Test converting to API format."""
        memory = ConversationMemory()

        memory.add_system("System prompt")
        memory.add_user("User message")
        memory.add_assistant("Response")

        messages = memory.get_messages()

        assert len(messages) == 3
        assert all("role" in m and "content" in m for m in messages)

    def test_auto_summarization(self):
        """Test automatic summarization when limit exceeded."""
        memory = ConversationMemory(max_messages=10)

        # Add more than max messages
        for i in range(15):
            memory.add_user(f"Message {i}")

        # Should have trimmed
        assert len(memory.messages) <= 10
        # Should have created summary
        assert len(memory.summaries) > 0

    def test_last_message(self):
        """Test getting last message."""
        memory = ConversationMemory()

        assert memory.last_message is None

        memory.add_user("First")
        memory.add_user("Last")

        assert memory.last_message.content == "Last"

    def test_clear(self):
        """Test clearing memory."""
        memory = ConversationMemory()

        memory.add_user("Test")
        memory.summaries.append("Summary")

        memory.clear()

        assert len(memory.messages) == 0
        assert len(memory.summaries) == 0


# ============================================================================
# Capability Tests
# ============================================================================


class TestCapability:
    """Tests for Capability and CapabilitySet."""

    def test_capability_proficiency_bounds(self):
        """Test proficiency is bounded."""
        cap = Capability(type=CapabilityType.CODE_GENERATION, proficiency=1.5)
        assert cap.proficiency == 1.0

        cap = Capability(type=CapabilityType.CODE_GENERATION, proficiency=-0.5)
        assert cap.proficiency == 0.0

    def test_capability_set_has(self):
        """Test capability set has check."""
        cap_set = CapabilitySet()
        cap_set.add(Capability(type=CapabilityType.CODE_GENERATION, proficiency=0.8))

        assert cap_set.has(CapabilityType.CODE_GENERATION)
        assert cap_set.has(CapabilityType.CODE_GENERATION, min_proficiency=0.5)
        assert not cap_set.has(CapabilityType.CODE_GENERATION, min_proficiency=0.9)
        assert not cap_set.has(CapabilityType.CODE_REVIEW)

    def test_capability_set_from_types(self):
        """Test creating from types."""
        cap_set = CapabilitySet.from_types(
            CapabilityType.CODE_GENERATION, CapabilityType.CODE_REVIEW
        )

        assert cap_set.has(CapabilityType.CODE_GENERATION)
        assert cap_set.has(CapabilityType.CODE_REVIEW)

    def test_meets_requirements(self):
        """Test requirement checking."""
        have = CapabilitySet.from_types(
            CapabilityType.CODE_GENERATION, CapabilityType.CODE_REVIEW
        )

        required = CapabilitySet.from_types(CapabilityType.CODE_GENERATION)

        assert have.meets_requirements(required)

        required.add(Capability(type=CapabilityType.TEST_GENERATION))
        assert not have.meets_requirements(required)

    def test_score_match(self):
        """Test capability matching score."""
        have = CapabilitySet()
        have.add(Capability(type=CapabilityType.CODE_GENERATION, proficiency=1.0))

        required = CapabilitySet()
        required.add(Capability(type=CapabilityType.CODE_GENERATION, proficiency=0.5))

        score = have.score_match(required)
        assert score == 1.0  # Have more than required

        # Test partial match
        required.add(Capability(type=CapabilityType.CODE_REVIEW))
        score = have.score_match(required)
        assert 0 < score < 1.0  # Missing one capability


# ============================================================================
# AgentConfig Tests
# ============================================================================


class TestAgentConfig:
    """Tests for AgentConfig."""

    def test_default_config(self):
        """Test default configuration."""
        config = AgentConfig()

        assert config.name == "agent"
        assert config.default_tier == ModelTier.TIER_2
        assert config.max_iterations == 10

    def test_custom_config(self):
        """Test custom configuration."""
        config = AgentConfig(
            name="custom",
            default_tier=ModelTier.TIER_3,
            max_iterations=5,
            timeout_seconds=60.0,
        )

        assert config.name == "custom"
        assert config.default_tier == ModelTier.TIER_3
        assert config.max_iterations == 5
        assert config.timeout_seconds == 60.0


# ============================================================================
# CoderAgent Tests
# ============================================================================


class TestCoderAgent:
    """Tests for CoderAgent."""

    @pytest.mark.asyncio
    async def test_initialization(self):
        """Test agent initialization."""
        agent = CoderAgent()

        assert agent.state == AgentState.CREATED

        await agent.initialize()

        assert agent.state == AgentState.READY

    @pytest.mark.asyncio
    async def test_run_code_generation(self):
        """Test running code generation."""
        agent = CoderAgent()

        task = CodeGenerationInput(
            description="Create a hello world function that prints a greeting",
            language="python",
        )

        result = await agent.run(task)

        assert isinstance(result, CodeGenerationOutput)
        assert agent.state == AgentState.COMPLETED

    @pytest.mark.asyncio
    async def test_extract_code_blocks(self):
        """Test code block extraction."""
        agent = CoderAgent()

        text = """Here's the code:

```python
def hello():
    print("Hello")
```

That's it!"""

        blocks = agent._extract_code_blocks(text, "python")

        assert len(blocks) == 1
        assert "def hello" in blocks[0]

    @pytest.mark.asyncio
    async def test_generate_code_mixin(self):
        """Test generate_code mixin method."""
        agent = CoderAgent()

        code = await agent.generate_code(
            description="A function that adds two numbers together", language="python"
        )

        assert isinstance(code, str)

    @pytest.mark.asyncio
    async def test_event_emission(self):
        """Test event emission during execution."""
        agent = CoderAgent()
        events = []

        def handler(agent, event, data):
            events.append(event)

        agent.on_event(handler)

        task = CodeGenerationInput(
            description="Generate a simple test function that passes", language="python"
        )

        await agent.run(task)

        assert AgentEvent.STATE_CHANGE in events
        assert AgentEvent.THINKING in events


# ============================================================================
# ReviewerAgent Tests
# ============================================================================


class TestReviewerAgent:
    """Tests for ReviewerAgent."""

    @pytest.mark.asyncio
    async def test_run_code_review(self):
        """Test running code review."""
        agent = ReviewerAgent()

        task = CodeReviewInput(code="def foo():\n    pass", language="python")

        result = await agent.run(task)

        assert isinstance(result, CodeReviewOutput)
        assert result.success

    @pytest.mark.asyncio
    async def test_review_code_mixin(self):
        """Test review_code mixin method."""
        agent = ReviewerAgent()

        result = await agent.review_code(code="x = 1", language="python")

        assert "summary" in result
        assert "issues" in result

    @pytest.mark.asyncio
    async def test_severity_parsing(self):
        """Test severity string parsing."""
        agent = ReviewerAgent()

        from agentic_v2.contracts import Severity

        assert agent._parse_severity("critical") == Severity.CRITICAL
        assert agent._parse_severity("HIGH") == Severity.HIGH
        assert agent._parse_severity("unknown") == Severity.INFO

    @pytest.mark.asyncio
    async def test_json_extraction(self):
        """Test JSON extraction from response."""
        agent = ReviewerAgent()

        # Test with code block
        text = '```json\n{"key": "value"}\n```'
        data = agent._extract_json(text)
        assert data["key"] == "value"

        # Test raw JSON
        text = '{"key": "value2"}'
        data = agent._extract_json(text)
        assert data["key"] == "value2"


# ============================================================================
# OrchestratorAgent Tests
# ============================================================================


class TestOrchestratorAgent:
    """Tests for OrchestratorAgent."""

    @pytest.mark.asyncio
    async def test_run_orchestration(self):
        """Test running orchestration."""
        orchestrator = OrchestratorAgent()

        task = OrchestratorInput(task="Build a calculator module", require_review=False)

        result = await orchestrator.run(task)

        assert result.success
        assert len(result.subtasks) > 0

    @pytest.mark.asyncio
    async def test_agent_assignment(self):
        """Test capability-based agent assignment."""
        orchestrator = OrchestratorAgent()
        coder = CoderAgent()
        reviewer = ReviewerAgent()

        orchestrator.register_agent("coder", coder)
        orchestrator.register_agent("reviewer", reviewer)

        task = OrchestratorInput(task="Generate and review code")

        result = await orchestrator.run(task)

        # Should have assignments
        assert result.agent_assignments

    @pytest.mark.asyncio
    async def test_decompose_task(self):
        """Test task decomposition."""
        orchestrator = OrchestratorAgent()

        subtasks = await orchestrator.decompose_task("Create a REST API with tests")

        assert isinstance(subtasks, list)


# ============================================================================
# Agent Integration Tests
# ============================================================================


class TestAgentIntegration:
    """Integration tests for agents."""

    @pytest.mark.asyncio
    async def test_agent_cleanup(self):
        """Test agent cleanup."""
        agent = CoderAgent()

        await agent.initialize()
        agent._memory.add_user("Test")

        await agent.cleanup()

        assert len(agent._memory.messages) == 0

    @pytest.mark.asyncio
    async def test_get_agent_capabilities(self):
        """Test getting all capabilities from agent."""
        coder = CoderAgent()

        caps = get_agent_capabilities(coder)

        assert caps.has(CapabilityType.CODE_GENERATION)


# ============================================================================
# Agent State Machine Tests
# ============================================================================


class TestAgentStateMachine:
    """Tests for agent state transitions."""

    @pytest.mark.asyncio
    async def test_normal_lifecycle(self):
        """Test normal state transitions."""
        agent = CoderAgent()

        assert agent.state == AgentState.CREATED

        await agent.initialize()
        assert agent.state == AgentState.READY

        task = CodeGenerationInput(
            description="Generate test code for lifecycle testing", language="python"
        )
        await agent.run(task)

        assert agent.state == AgentState.COMPLETED

    @pytest.mark.asyncio
    async def test_error_state(self):
        """Test transition to error state."""
        agent = CoderAgent()
        agent.config.max_iterations = 0  # Force error

        await agent.initialize()

        task = CodeGenerationInput(
            description="Generate code that will trigger max iterations",
            language="python",
        )

        with pytest.raises(RuntimeError):
            await agent.run(task)

        assert agent.state == AgentState.FAILED
        assert agent.error is not None
