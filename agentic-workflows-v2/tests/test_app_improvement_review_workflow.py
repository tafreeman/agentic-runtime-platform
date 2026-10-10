"""Contract tests for the built-in application improvement review workflow."""

from agentic_v2.langchain import compile_workflow, load_workflow_config
from agentic_v2.workflows.loader import WorkflowLoader

LENS_STEPS = {
    "architecture_lens",
    "product_ux_lens",
    "reliability_security_lens",
    "delivery_maintainability_lens",
    "performance_cost_lens",
    "reinvention_lens",
}

READ_ONLY_TOOLS = {"file_read", "file_list", "search_files", "code_analyze"}
MUTATING_TOOLS = {"file_write", "shell_run"}


def test_app_improvement_review_has_parallel_read_only_lenses() -> None:
    """All review lenses fan out from one inventory and cannot mutate the app."""
    workflow = WorkflowLoader().load("app_improvement_review")

    assert workflow.inputs["app_path"].required is True
    assert workflow.inputs["change_appetite"].enum == [
        "incremental",
        "balanced",
        "reimagine",
    ]

    for name in LENS_STEPS:
        step = workflow.dag.steps[name]
        assert step.depends_on == ["inventory_app"]
        assert set(step.metadata["tools"]) == READ_ONLY_TOOLS

    for step in workflow.dag.steps.values():
        tools = set(step.metadata["tools"] or [])
        assert tools.isdisjoint(MUTATING_TOOLS)

    challenge = workflow.dag.steps["challenge_analysis"]
    assert set(challenge.depends_on) == LENS_STEPS
    assert challenge.metadata["tools"] == []


def test_app_improvement_review_scoring_and_roadmap_contract() -> None:
    """The fan-in produces scored decisions and an actionable final report."""
    workflow = WorkflowLoader().load("app_improvement_review")

    assert workflow.evaluation is not None
    assert workflow.evaluation.rubric_id == "app_improvement_review_v1"
    assert workflow.evaluation.scoring_profile == "B"

    score_step = workflow.dag.steps["score_and_prioritize"]
    assert score_step.depends_on == ["challenge_analysis"]
    assert set(score_step.output_mapping) == {
        "scorecard",
        "ranked_changes",
        "recommended_direction",
        "decision_rationale",
    }

    assert set(workflow.outputs) == {
        "executive_summary",
        "current_state",
        "scorecard",
        "recommended_direction",
        "ranked_changes",
        "roadmap",
        "rethink_options",
        "evidence_gaps",
        "full_report",
    }


def test_app_improvement_review_compiles_for_langchain_adapter() -> None:
    """The second supported adapter accepts the same workflow definition."""
    config = load_workflow_config("app_improvement_review")

    assert len(config.steps) == 11
    assert compile_workflow(config, validate_only=True) is not None
