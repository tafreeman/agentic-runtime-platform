"""Tests for API request and response models."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from agentic_v2.server.models import (
    AgentInfo,
    DAGEdgeModel,
    DAGNodeModel,
    DAGResponse,
    ListAgentsResponse,
    RunsSummaryResponse,
    RunSummaryModel,
    WorkflowEvaluationRequest,
    WorkflowExecutionProfileRequest,
    WorkflowRunRequest,
)


class TestWorkflowRunRequest:
    """Tests for WorkflowRunRequest model."""

    def test_minimal_request(self) -> None:
        """WorkflowRunRequest requires only workflow field."""
        req = WorkflowRunRequest(workflow="test-workflow")
        assert req.workflow == "test-workflow"

    def test_defaults(self) -> None:
        """input_data defaults to empty dict, run_id defaults to None."""
        req = WorkflowRunRequest(workflow="test")
        assert req.input_data == {}
        assert req.run_id is None
        assert req.evaluation is None
        assert req.execution_profile is None

    def test_with_input_data(self) -> None:
        """Input data is accepted and preserved."""
        req = WorkflowRunRequest(
            workflow="test",
            input_data={"key": "value", "nested": {"a": 1}},
        )
        assert req.input_data["key"] == "value"
        assert req.input_data["nested"]["a"] == 1

    def test_with_evaluation(self) -> None:
        """Evaluation config is correctly nested."""
        req = WorkflowRunRequest(
            workflow="test",
            evaluation=WorkflowEvaluationRequest(enabled=True),
        )
        assert req.evaluation is not None
        assert req.evaluation.enabled is True

    def test_with_execution_profile(self) -> None:
        """Execution profile validates runtime and constraints."""
        req = WorkflowRunRequest(
            workflow="test",
            execution_profile=WorkflowExecutionProfileRequest(
                runtime="docker",
                max_attempts=3,
            ),
        )
        assert req.execution_profile is not None
        assert req.execution_profile.runtime == "docker"
        assert req.execution_profile.max_attempts == 3

    def test_default_execution_profile_string_is_compatible(self) -> None:
        """Legacy clients may send execution_profile='default'."""
        req = WorkflowRunRequest(workflow="test", execution_profile="default")
        assert req.execution_profile is None

    def test_default_adapter_string_is_compatible(self) -> None:
        """Legacy clients may send adapter='default'."""
        req = WorkflowRunRequest(workflow="test", adapter="default")
        assert req.adapter == "langchain"

    def test_missing_workflow_raises(self) -> None:
        """Missing required workflow field raises ValidationError."""
        with pytest.raises(ValidationError):
            WorkflowRunRequest()  # type: ignore[call-arg]


class TestWorkflowEvaluationRequest:
    """Tests for WorkflowEvaluationRequest model."""

    def test_defaults(self) -> None:
        """Default values: enabled=False, enforce_hard_gates=True."""
        req = WorkflowEvaluationRequest()
        assert req.enabled is False
        assert req.enforce_hard_gates is True
        assert req.dataset_source == "none"
        assert req.sample_index == 0

    def test_sample_index_validation(self) -> None:
        """sample_index must be >= 0."""
        with pytest.raises(ValidationError):
            WorkflowEvaluationRequest(sample_index=-1)

    def test_dataset_source_literal(self) -> None:
        """dataset_source accepts valid literals."""
        for source in ("none", "repository", "local"):
            req = WorkflowEvaluationRequest(dataset_source=source)
            assert req.dataset_source == source


class TestWorkflowExecutionProfileRequest:
    """Tests for WorkflowExecutionProfileRequest model."""

    def test_runtime_literal_validation(self) -> None:
        """Runtime must be 'subprocess' or 'docker'."""
        for rt in ("subprocess", "docker"):
            req = WorkflowExecutionProfileRequest(runtime=rt)
            assert req.runtime == rt

    def test_runtime_invalid_raises(self) -> None:
        """Invalid runtime raises ValidationError."""
        with pytest.raises(ValidationError):
            WorkflowExecutionProfileRequest(runtime="kubernetes")  # type: ignore[arg-type]

    def test_max_attempts_validation(self) -> None:
        """max_attempts must be >= 1 when set."""
        req = WorkflowExecutionProfileRequest(max_attempts=5)
        assert req.max_attempts == 5

    def test_max_attempts_zero_raises(self) -> None:
        """max_attempts=0 raises ValidationError."""
        with pytest.raises(ValidationError):
            WorkflowExecutionProfileRequest(max_attempts=0)

    def test_defaults(self) -> None:
        """Default values are correct."""
        req = WorkflowExecutionProfileRequest()
        assert req.runtime == "subprocess"
        assert req.max_attempts is None
        assert req.container_image is None


class TestDAGModels:
    """Tests for DAG visualization models."""

    def test_dag_node_model(self) -> None:
        """DAGNodeModel accepts all optional fields."""
        node = DAGNodeModel(
            id="step-1", agent="coder", description="Code step", depends_on=[]
        )
        assert node.id == "step-1"
        assert node.agent == "coder"
        assert node.depends_on == []

    def test_dag_node_defaults(self) -> None:
        """DAGNodeModel has correct defaults (depends_on is required, must be passed explicitly)."""
        node = DAGNodeModel(id="step-1", depends_on=[])
        assert node.agent is None
        assert node.description == ""
        assert node.tier is None
        assert node.depends_on == []

    def test_dag_response(self) -> None:
        """DAGResponse contains nodes and edges."""
        nodes = [DAGNodeModel(id="a", depends_on=[]), DAGNodeModel(id="b", depends_on=["a"])]
        edges = [DAGEdgeModel(source="a", target="b")]
        dag = DAGResponse(name="test-wf", nodes=nodes, edges=edges)
        assert dag.name == "test-wf"
        assert len(dag.nodes) == 2
        assert len(dag.edges) == 1
        assert dag.edges[0].source == "a"
        assert dag.edges[0].target == "b"


class TestAgentModels:
    """Tests for agent-related models."""

    def test_agent_info(self) -> None:
        """AgentInfo stores all fields."""
        info = AgentInfo(name="Coder", description="Writes code", tier="1")
        assert info.name == "Coder"
        assert info.description == "Writes code"
        assert info.tier == "1"

    def test_list_agents_response(self) -> None:
        """ListAgentsResponse contains agent list."""
        agents = [AgentInfo(name="A", description="", tier="1")]
        resp = ListAgentsResponse(agents=agents)
        assert len(resp.agents) == 1


class TestRunModels:
    """Tests for run summary models."""

    def test_run_summary_defaults(self) -> None:
        """RunSummaryModel has correct optional defaults."""
        summary = RunSummaryModel(filename="run_001.json")
        assert summary.filename == "run_001.json"
        assert summary.run_id is None
        assert summary.status is None

    def test_runs_summary_response_defaults(self) -> None:
        """RunsSummaryResponse has correct defaults."""
        resp = RunsSummaryResponse()
        assert resp.total_runs == 0
        assert resp.success == 0
        assert resp.failed == 0
        assert resp.workflows == []
