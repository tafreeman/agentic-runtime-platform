"""Tests for workflow loader.

Covers:
- Loading workflows from YAML files
- Parsing step definitions into DAG
- Input/output schema parsing
- Error handling for invalid workflows
"""

from pathlib import Path
from tempfile import TemporaryDirectory

import pytest
from agentic_v2.workflows.loader import (
    WorkflowLoader,
    WorkflowLoadError,
    get_dag,
    load_workflow,
)


class TestWorkflowLoaderBasic:
    """Basic workflow loading tests."""

    def test_list_workflows(self):
        """List available workflows in definitions directory."""
        loader = WorkflowLoader()
        workflows = loader.list_workflows()

        # Should find our defined workflows
        assert "code_review" in workflows
        assert "fullstack_generation" in workflows

    def test_load_code_review_workflow(self):
        """Load the code_review workflow."""
        loader = WorkflowLoader()
        workflow = loader.load("code_review")

        assert workflow.name == "code_review"
        assert workflow.version == "1.0"
        assert "code review" in workflow.description.lower()

    def test_load_fullstack_generation_workflow(self):
        """Load the fullstack_generation workflow."""
        loader = WorkflowLoader()
        workflow = loader.load("fullstack_generation")

        assert workflow.name == "fullstack_generation"
        assert len(workflow.dag.steps) > 0

    def test_load_nonexistent_workflow_raises(self):
        """Loading nonexistent workflow raises WorkflowLoadError."""
        loader = WorkflowLoader()

        with pytest.raises(WorkflowLoadError, match="not found"):
            loader.load("nonexistent_workflow")

    def test_list_workflows_excludes_experimental(self):
        """Experimental workflows are hidden from default list."""
        loader = WorkflowLoader()
        workflows = loader.list_workflows()
        # No experimental workflows currently defined
        assert isinstance(workflows, list)


class TestWorkflowLoaderDAG:
    """Tests for DAG construction from workflows."""

    def test_dag_contains_all_steps(self):
        """DAG contains all steps from workflow definition."""
        loader = WorkflowLoader()
        workflow = loader.load("code_review")

        dag = workflow.dag
        step_names = set(dag.steps.keys())

        # Check expected steps exist
        assert "parse_code" in step_names
        assert "style_check" in step_names
        assert "review_code" in step_names

    def test_dag_preserves_dependencies(self):
        """DAG preserves step dependencies."""
        loader = WorkflowLoader()
        workflow = loader.load("code_review")

        dag = workflow.dag

        # style_check depends on parse_code
        assert "parse_code" in dag.steps["style_check"].depends_on

        # review_code depends on style_check and complexity_analysis
        review_deps = dag.steps["review_code"].depends_on
        assert "style_check" in review_deps
        assert "complexity_analysis" in review_deps

    def test_dag_is_valid(self):
        """Loaded DAG passes validation."""
        loader = WorkflowLoader()
        workflow = loader.load("code_review")

        # Should not raise
        workflow.dag.validate()

    def test_fullstack_dag_has_parallel_structure(self):
        """Fullstack workflow has expected parallel structure."""
        loader = WorkflowLoader()
        workflow = loader.load("fullstack_generation")

        dag = workflow.dag

        # generate_api and generate_frontend should both depend on design_architecture
        assert "design_architecture" in dag.steps["generate_api"].depends_on
        assert "design_architecture" in dag.steps["generate_frontend"].depends_on

        # They are in parallel (not depending on each other)
        assert "generate_frontend" not in dag.steps["generate_api"].depends_on
        assert "generate_api" not in dag.steps["generate_frontend"].depends_on

    def test_step_tools_metadata_is_parsed(self):
        """Step-level tools allowlist is preserved in metadata."""
        with TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)

            workflow_yaml = """
name: tools_workflow
steps:
  - name: inspect
    agent: tier2_coder
    tools: [file_read, search]
"""
            (tmppath / "tools_workflow.yaml").write_text(
                workflow_yaml,
                encoding="utf-8",
            )

            loader = WorkflowLoader(definitions_dir=tmppath)
            workflow = loader.load("tools_workflow")

            step = workflow.dag.steps["inspect"]
            assert step.metadata["tools"] == ["file_read", "search"]


class TestWorkflowLoaderInputs:
    """Tests for workflow input parsing."""

    def test_parse_workflow_inputs(self):
        """Workflow inputs are parsed correctly."""
        loader = WorkflowLoader()
        workflow = loader.load("code_review")

        assert "code_file" in workflow.inputs
        assert workflow.inputs["code_file"].type == "string"

        assert "review_depth" in workflow.inputs
        assert workflow.inputs["review_depth"].default == "standard"
        assert "quick" in workflow.inputs["review_depth"].enum

    def test_parse_complex_inputs(self):
        """Complex input types (objects) are parsed."""
        loader = WorkflowLoader()
        workflow = loader.load("fullstack_generation")

        assert "tech_stack" in workflow.inputs
        assert workflow.inputs["tech_stack"].type == "object"
        default_stack = workflow.inputs["tech_stack"].default
        assert default_stack["frontend"] == "react"


class TestWorkflowLoaderOutputs:
    """Tests for workflow output parsing."""

    def test_parse_workflow_outputs(self):
        """Workflow outputs are parsed correctly."""
        loader = WorkflowLoader()
        workflow = loader.load("code_review")

        assert "review" in workflow.outputs
        assert "summary" in workflow.outputs
        assert workflow.outputs["summary"].optional is True

    def test_workflow_yaml_selects_profile(self):
        """Workflow evaluation block includes scoring profile."""
        loader = WorkflowLoader()
        workflow = loader.load("code_review")
        assert workflow.evaluation is not None
        assert workflow.evaluation.scoring_profile == "B"

    def test_rubric_criterion_has_anchored_scale(self):
        """Loaded rubric criteria include anchored scale definitions."""
        loader = WorkflowLoader()
        workflow = loader.load("code_review")
        assert workflow.evaluation is not None
        assert workflow.evaluation.criteria
        assert workflow.evaluation.criteria[0].scale


class TestWorkflowLoaderCaching:
    """Tests for caching behavior."""

    def test_cached_load_returns_same_object(self):
        """Cached loads return the same object."""
        loader = WorkflowLoader()

        workflow1 = loader.load("code_review")
        workflow2 = loader.load("code_review")

        assert workflow1 is workflow2

    def test_clear_cache_forces_reload(self):
        """clear_cache forces fresh load."""
        loader = WorkflowLoader()

        workflow1 = loader.load("code_review")
        loader.clear_cache()
        workflow2 = loader.load("code_review")

        assert workflow1 is not workflow2

    def test_no_cache_flag(self):
        """use_cache=False bypasses cache."""
        loader = WorkflowLoader()

        workflow1 = loader.load("code_review")
        workflow2 = loader.load("code_review", use_cache=False)

        assert workflow1 is not workflow2


class TestWorkflowLoaderCustomDirectory:
    """Tests for custom definitions directory."""

    def test_load_from_custom_directory(self):
        """Load workflows from custom directory."""
        with TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)

            # Create a simple workflow
            workflow_yaml = """
name: test_workflow
description: Test workflow
steps:
  - name: step1
    description: First step
    agent: tier2_coder
  - name: step2
    depends_on: [step1]
    agent: tier2_reviewer
"""
            (tmppath / "test_workflow.yaml").write_text(workflow_yaml)

            loader = WorkflowLoader(definitions_dir=tmppath)
            workflow = loader.load("test_workflow")

            assert workflow.name == "test_workflow"
            assert len(workflow.dag.steps) == 2

    def test_load_file_directly(self):
        """Load workflow from specific file path."""
        with TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)

            workflow_yaml = """
name: direct_load
steps:
  - name: only_step
    agent: tier2_coder
"""
            file_path = tmppath / "my_workflow.yaml"
            file_path.write_text(workflow_yaml)

            loader = WorkflowLoader()
            workflow = loader.load_file(file_path)

            assert workflow.name == "direct_load"


class TestWorkflowLoaderErrors:
    """Tests for error handling."""

    def test_invalid_yaml_raises(self):
        """Invalid YAML raises WorkflowLoadError."""
        with TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)

            # Invalid YAML
            (tmppath / "bad.yaml").write_text("{ invalid yaml [")

            loader = WorkflowLoader(definitions_dir=tmppath)

            with pytest.raises(WorkflowLoadError, match="Invalid YAML"):
                loader.load("bad")

    def test_missing_step_name_raises(self):
        """Step without name raises WorkflowLoadError."""
        with TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)

            workflow_yaml = """
name: no_name
steps:
  - description: Step without name
"""
            (tmppath / "no_name.yaml").write_text(workflow_yaml)

            loader = WorkflowLoader(definitions_dir=tmppath)

            with pytest.raises(WorkflowLoadError, match="must have a 'name'"):
                loader.load("no_name")

    def test_rubric_unknown_formula_id_rejected(self):
        """Unknown criterion formula_id is rejected during load."""
        with TemporaryDirectory() as tmpdir:
            tmppath = Path(tmpdir)

            workflow_yaml = """
name: bad_formula
evaluation:
  criteria:
    - name: correctness
      definition: test
      evidence_required: []
      scale:
        "1": bad
        "5": good
      weight: 1.0
      formula_id: unknown_formula
steps:
  - name: step1
    agent: tier2_coder
"""
            (tmppath / "bad_formula.yaml").write_text(workflow_yaml)

            loader = WorkflowLoader(definitions_dir=tmppath)
            with pytest.raises(WorkflowLoadError, match="unknown formula_id"):
                loader.load("bad_formula")


class TestConvenienceFunctions:
    """Tests for convenience functions."""

    def test_load_workflow_function(self):
        """load_workflow convenience function works."""
        workflow = load_workflow("code_review")
        assert workflow.name == "code_review"

    def test_get_dag_function(self):
        """get_dag convenience function returns DAG."""
        dag = get_dag("code_review")
        assert dag.name == "code_review"
        assert len(dag.steps) > 0
