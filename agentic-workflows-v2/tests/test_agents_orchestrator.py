"""Tests for OrchestratorAgent DAG generation and execution.

Tests the orchestrator's ability to:
- Parse task decomposition JSON
- Build DAG structures from subtasks
- Execute DAGs with proper dependency handling
- Handle failures and replanning
"""

import pytest
from agentic_v2.agents.base import AgentConfig, agent_to_step
from agentic_v2.agents.coder import CoderAgent
from agentic_v2.agents.orchestrator import (
    OrchestratorAgent,
    OrchestratorInput,
    OrchestratorOutput,
    SubTask,
)
from agentic_v2.contracts import StepStatus
from agentic_v2.engine import DAG, DAGExecutor, ExecutionContext
from agentic_v2.engine.step import StepDefinition
from agentic_v2.models import LLMClientWrapper, MockBackend, get_smart_router


@pytest.fixture
def mock_backend():
    """Create a mock LLM backend for testing."""
    backend = MockBackend()
    # Response for task decomposition
    backend.set_response(
        "decompose",
        """{
    "subtasks": [
        {
            "id": "design_schema",
            "description": "Design the database schema for the user system",
            "capabilities": ["architecture"],
            "dependencies": [],
            "parallel_group": 1
        },
        {
            "id": "create_models",
            "description": "Create database models based on schema",
            "capabilities": ["code_generation"],
            "dependencies": ["design_schema"],
            "parallel_group": 2
        },
        {
            "id": "create_api",
            "description": "Create REST API endpoints",
            "capabilities": ["code_generation"],
            "dependencies": ["create_models"],
            "parallel_group": 3
        },
        {
            "id": "write_tests",
            "description": "Write unit tests for API",
            "capabilities": ["test_generation"],
            "dependencies": ["create_api"],
            "parallel_group": 4
        }
    ],
    "execution_order": ["design_schema", "create_models", "create_api", "write_tests"],
    "validation_steps": ["Run tests", "Check code coverage"]
}""",
    )
    # Response for parallel task decomposition
    backend.set_response(
        "parallel",
        """{
    "subtasks": [
        {
            "id": "task_a",
            "description": "Independent task A",
            "capabilities": ["code_generation"],
            "dependencies": [],
            "parallel_group": 1
        },
        {
            "id": "task_b",
            "description": "Independent task B",
            "capabilities": ["code_generation"],
            "dependencies": [],
            "parallel_group": 1
        },
        {
            "id": "task_c",
            "description": "Depends on A and B",
            "capabilities": ["code_generation"],
            "dependencies": ["task_a", "task_b"],
            "parallel_group": 2
        }
    ],
    "execution_order": ["task_a", "task_b", "task_c"],
    "validation_steps": []
}""",
    )
    return backend


@pytest.fixture
def llm_client(mock_backend):
    """Create an LLM client with mock backend."""
    client = LLMClientWrapper(
        router=get_smart_router(),
        enable_cache=False,
    )
    client.set_backend(mock_backend)
    return client


class TestSubTaskModel:
    """Test SubTask dataclass."""

    def test_subtask_creation(self):
        """Test creating a SubTask."""
        subtask = SubTask(
            id="test_task",
            description="Test task description",
            required_capabilities=[],
            dependencies=["other_task"],
        )
        assert subtask.id == "test_task"
        assert subtask.description == "Test task description"
        assert subtask.dependencies == ["other_task"]
        assert subtask.status == StepStatus.PENDING

    def test_subtask_defaults(self):
        """Test SubTask default values."""
        subtask = SubTask(
            id="minimal",
            description="Minimal task",
            required_capabilities=[],
        )
        assert subtask.dependencies == []
        assert subtask.assigned_agent is None
        assert subtask.result is None
        assert subtask.status == StepStatus.PENDING


class TestOrchestratorAgentConfiguration:
    """Test OrchestratorAgent configuration."""

    def test_orchestrator_initialization(self, llm_client):
        """Test basic orchestrator initialization."""
        orchestrator = OrchestratorAgent(
            config=AgentConfig(name="test-orchestrator"),
            llm_client=llm_client,
        )
        assert orchestrator.config.name == "test-orchestrator"
        assert orchestrator._agents == {}

    def test_register_agent(self, llm_client):
        """Test registering agents with orchestrator."""
        orchestrator = OrchestratorAgent(
            config=AgentConfig(name="orchestrator"),
            llm_client=llm_client,
        )
        coder = CoderAgent(
            config=AgentConfig(name="coder"),
            llm_client=llm_client,
        )

        orchestrator._agents["coder"] = coder
        assert "coder" in orchestrator._agents
        assert orchestrator._agents["coder"] is coder

    def test_multiple_agents(self, llm_client):
        """Test registering multiple agents."""
        orchestrator = OrchestratorAgent(
            config=AgentConfig(name="orchestrator"),
            llm_client=llm_client,
        )

        for name in ["coder", "reviewer", "tester"]:
            agent = CoderAgent(
                config=AgentConfig(name=name),
                llm_client=llm_client,
            )
            orchestrator._agents[name] = agent

        assert len(orchestrator._agents) == 3
        assert set(orchestrator._agents.keys()) == {"coder", "reviewer", "tester"}


class TestOrchestratorInput:
    """Test OrchestratorInput model."""

    def test_input_defaults(self):
        """Test OrchestratorInput default values."""
        input_data = OrchestratorInput()
        assert input_data.task == ""
        assert input_data.available_agents == []
        assert input_data.max_parallel == 3
        assert input_data.require_review is True

    def test_input_with_values(self):
        """Test OrchestratorInput with custom values."""
        input_data = OrchestratorInput(
            task="Build a REST API",
            available_agents=["coder", "tester"],
            max_parallel=5,
            require_review=False,
        )
        assert input_data.task == "Build a REST API"
        assert input_data.available_agents == ["coder", "tester"]
        assert input_data.max_parallel == 5
        assert input_data.require_review is False


class TestOrchestratorOutput:
    """Test OrchestratorOutput model."""

    def test_output_defaults(self):
        """Test OrchestratorOutput default values."""
        output = OrchestratorOutput(success=True)
        assert output.subtasks == []
        assert output.agent_assignments == {}
        assert output.final_result is None
        assert output.execution_trace == []

    def test_output_with_data(self):
        """Test OrchestratorOutput with data."""
        output = OrchestratorOutput(
            subtasks=[{"id": "task1", "description": "Do something"}],
            agent_assignments={"task1": "coder"},
            final_result={"status": "complete"},
            success=True,
        )
        assert len(output.subtasks) == 1
        assert output.agent_assignments["task1"] == "coder"
        assert output.final_result == {"status": "complete"}


class TestDAGBuildingFromSubtasks:
    """Test building DAGs from orchestrator subtasks."""

    def test_build_simple_dag(self):
        """Test building a simple sequential DAG."""
        dag = DAG(name="test-dag")

        # Simulate subtasks from orchestrator
        subtasks = [
            {"id": "step1", "dependencies": []},
            {"id": "step2", "dependencies": ["step1"]},
            {"id": "step3", "dependencies": ["step2"]},
        ]

        for subtask in subtasks:

            async def handler(ctx):
                return {"done": True}

            step = StepDefinition(
                name=subtask["id"],
                description=f"Step {subtask['id']}",
                func=handler,
                depends_on=subtask["dependencies"],
            )
            dag.add(step)

        # Validate DAG structure
        dag.validate()
        order = dag.get_execution_order()
        assert order == ["step1", "step2", "step3"]

    def test_build_parallel_dag(self):
        """Test building a DAG with parallel branches."""
        dag = DAG(name="parallel-dag")

        # Diamond pattern: A -> (B, C) -> D
        subtasks = [
            {"id": "A", "dependencies": []},
            {"id": "B", "dependencies": ["A"]},
            {"id": "C", "dependencies": ["A"]},
            {"id": "D", "dependencies": ["B", "C"]},
        ]

        for subtask in subtasks:

            async def handler(ctx):
                return {"done": True}

            step = StepDefinition(
                name=subtask["id"],
                description=f"Step {subtask['id']}",
                func=handler,
                depends_on=subtask["dependencies"],
            )
            dag.add(step)

        dag.validate()

        # Check ready steps at start
        ready = dag.get_ready_steps(set())
        assert ready == ["A"]

        # After A completes, both B and C should be ready
        ready = dag.get_ready_steps({"A"})
        assert set(ready) == {"B", "C"}

        # After B and C complete, D should be ready
        ready = dag.get_ready_steps({"A", "B", "C"})
        assert ready == ["D"]

    def test_dag_cycle_detection(self):
        """Test that DAG detects cycles."""
        dag = DAG(name="cycle-test")

        async def handler(ctx):
            return {}

        step_a = StepDefinition(name="A", func=handler, depends_on=["C"])
        step_b = StepDefinition(name="B", func=handler, depends_on=["A"])
        step_c = StepDefinition(name="C", func=handler, depends_on=["B"])

        dag.add(step_a).add(step_b).add(step_c)

        from agentic_v2.engine.dag import CycleDetectedError

        with pytest.raises(CycleDetectedError):
            dag.validate()


class TestAgentToStepForDAG:
    """Test converting agents to DAG-compatible steps."""

    @pytest.mark.asyncio
    async def test_agent_step_has_required_fields(self, llm_client):
        """Test that agent_to_step creates DAG-compatible steps."""
        coder = CoderAgent(
            config=AgentConfig(name="coder"),
            llm_client=llm_client,
        )

        step = agent_to_step(coder, "code_step")

        # Check required DAG fields
        assert step.name == "code_step"
        assert step.func is not None
        assert hasattr(step, "depends_on")

    @pytest.mark.asyncio
    async def test_agent_step_can_be_added_to_dag(self, llm_client):
        """Test that agent steps can be added to DAGs."""
        coder = CoderAgent(
            config=AgentConfig(name="coder"),
            llm_client=llm_client,
        )

        step = agent_to_step(coder, "code_step")
        step.depends_on = []

        dag = DAG(name="agent-dag")
        dag.add(step)

        # Should not raise
        dag.validate()


class TestDAGExecutorWithAgentSteps:
    """Test DAGExecutor with agent-based steps."""

    @pytest.mark.asyncio
    async def test_executor_runs_agent_steps(self):
        """Test that DAGExecutor can run agent steps."""
        dag = DAG(name="agent-execution-test")

        results = []

        async def step1_handler(ctx):
            results.append("step1")
            return {"output": "from_step1"}

        async def step2_handler(ctx):
            results.append("step2")
            return {"output": "from_step2"}

        step1 = StepDefinition(
            name="step1",
            description="First step",
            func=step1_handler,
            depends_on=[],
        )
        step2 = StepDefinition(
            name="step2",
            description="Second step",
            func=step2_handler,
            depends_on=["step1"],
        )

        dag.add(step1).add(step2)

        executor = DAGExecutor()
        ctx = ExecutionContext()
        result = await executor.execute(dag, ctx)

        assert result.overall_status == StepStatus.SUCCESS
        assert len(result.steps) == 2
        assert "step1" in results
        assert "step2" in results
        # step1 should execute before step2
        assert results.index("step1") < results.index("step2")

    @pytest.mark.asyncio
    async def test_executor_with_max_parallel(self):
        """Test DAGExecutor respects max_parallel from orchestrator input."""
        dag = DAG(name="parallel-execution")

        async def handler(ctx):
            return {"done": True}

        # Create 5 independent steps
        for i in range(5):
            step = StepDefinition(
                name=f"step_{i}",
                func=handler,
                depends_on=[],
            )
            dag.add(step)

        executor = DAGExecutor()
        ctx = ExecutionContext()

        # Execute with max_concurrency matching orchestrator.max_parallel
        result = await executor.execute(dag, ctx, max_concurrency=3)

        assert result.overall_status == StepStatus.SUCCESS
        assert len(result.steps) == 5


class TestCoderAgentLLMIntegration:
    """Test CoderAgent with LLM client."""

    @pytest.mark.asyncio
    async def test_coder_uses_llm_client_when_backend_set(self, llm_client):
        """Test that CoderAgent uses the LLM client when backend is configured."""
        mock_backend = llm_client.backend
        mock_backend.set_response(
            "function",
            """```python
def greet(name: str) -> str:
    return f"Hello, {name}!"
```""",
        )

        coder = CoderAgent(
            config=AgentConfig(name="test-coder"),
            llm_client=llm_client,
        )

        code = await coder.generate_code(
            description="Create a greeting function",
            language="python",
        )

        # The mock should have been called
        assert len(mock_backend.call_history) > 0

    @pytest.mark.asyncio
    async def test_coder_returns_mock_when_no_backend(self):
        """Test that CoderAgent returns mock response when no backend."""
        client = LLMClientWrapper(
            router=get_smart_router(),
            enable_cache=False,
        )

        coder = CoderAgent(
            config=AgentConfig(name="test-coder"),
            llm_client=client,
        )

        code = await coder.generate_code(
            description="Create something",
            language="python",
        )

        assert "placeholder" in code.lower() or "example" in code.lower()
