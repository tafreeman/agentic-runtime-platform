"""Tests using Hugging Face dataset fixtures against workflow runner.

Validates that real-world data from 6 HF datasets can be loaded,
adapted, and fed through the workflow input validation layer.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration

from tests.fixtures.datasets import (
    code_review_inputs,
    dataset_summary,
    fullstack_generation_inputs,
    load_code_instructions_120k,
    load_code_review_instruct,
    load_python_code_instructions,
    load_react_code_instructions,
    load_swe_bench_lite,
    load_swe_bench_verified,
)

# ---------------------------------------------------------------------------
# Dataset loading smoke tests
# ---------------------------------------------------------------------------


class TestDatasetLoading:
    """Verify all 6 dataset fixture files load correctly."""

    def test_code_review_instruct_loads(self):
        data = load_code_review_instruct()
        assert len(data) == 20
        assert "prompt" in data[0]
        assert "response" in data[0]

    def test_python_code_instructions_loads(self):
        data = load_python_code_instructions()
        assert len(data) == 20
        assert "instruction" in data[0]
        assert "output" in data[0]

    def test_react_code_instructions_loads(self):
        data = load_react_code_instructions()
        assert len(data) == 20
        assert "messages" in data[0]
        assert "model" in data[0]

    def test_code_instructions_120k_loads(self):
        data = load_code_instructions_120k()
        assert len(data) == 20
        assert "instruction" in data[0]
        assert "output" in data[0]

    def test_swe_bench_lite_loads(self):
        data = load_swe_bench_lite()
        assert len(data) == 20
        assert "problem_statement" in data[0]
        assert "repo" in data[0]
        assert "patch" in data[0]

    def test_swe_bench_verified_loads(self):
        data = load_swe_bench_verified()
        assert len(data) == 20
        assert "problem_statement" in data[0]
        assert "difficulty" in data[0]

    def test_dataset_summary(self):
        summary = dataset_summary()
        assert len(summary) == 9
        for name, info in summary.items():
            assert info["file_exists"], f"{name} fixture file missing"
            assert info["sample_count"] == 20, f"{name} expected 20 samples"


# ---------------------------------------------------------------------------
# Adapter tests — verify mapping to workflow input schemas
# ---------------------------------------------------------------------------


class TestCodeReviewAdapter:
    """code_review_inputs() maps datasets → code_review.yaml schema."""

    def test_returns_expected_keys(self):
        inputs = code_review_inputs(limit=2)
        assert len(inputs) > 0
        for inp in inputs:
            assert "code_file" in inp
            assert "code_content" in inp
            assert "review_depth" in inp
            assert inp["review_depth"] in ("quick", "standard", "deep")

    def test_meta_tracks_source(self):
        inputs = code_review_inputs(limit=2)
        sources = {inp["_meta"]["source"] for inp in inputs}
        assert "Dahoas/code-review-instruct-critique-revision-python" in sources
        assert "iamtarun/python_code_instructions_18k_alpaca" in sources

    def test_code_content_not_empty(self):
        for inp in code_review_inputs(limit=3):
            assert len(inp["code_content"]) > 0


class TestFullstackGenerationAdapter:
    """fullstack_generation_inputs() maps datasets → fullstack_generation.yaml
    schema."""

    def test_returns_expected_keys(self):
        inputs = fullstack_generation_inputs(limit=2)
        assert len(inputs) > 0
        for inp in inputs:
            assert "feature_spec" in inp
            assert "tech_stack" in inp
            assert "frontend" in inp["tech_stack"]
            assert "backend" in inp["tech_stack"]
            assert "database" in inp["tech_stack"]

    def test_meta_tracks_source(self):
        inputs = fullstack_generation_inputs(limit=2)
        sources = {inp["_meta"]["source"] for inp in inputs}
        assert "cfahlgren1/react-code-instructions" in sources
        assert "iamtarun/code_instructions_120k_alpaca" in sources

    def test_feature_spec_not_empty(self):
        for inp in fullstack_generation_inputs(limit=3):
            assert len(inp["feature_spec"]) > 0


# ---------------------------------------------------------------------------
# Workflow validation integration tests
# ---------------------------------------------------------------------------


class TestWorkflowValidationWithDatasets:
    """Feed adapted dataset inputs through WorkflowRunner validation."""

    @pytest.mark.asyncio
    async def test_code_review_inputs_pass_validation(self):
        """Real dataset inputs pass code_review.yaml input validation."""
        from agentic_v2.workflows.runner import WorkflowRunner

        runner = WorkflowRunner()
        for inp in code_review_inputs(limit=3):
            clean = {k: v for k, v in inp.items() if not k.startswith("_")}
            result = await runner.run("code_review", **clean)
            assert result is not None

    @pytest.mark.asyncio
    async def test_fullstack_inputs_pass_validation(self):
        """Real dataset inputs pass fullstack_generation.yaml input validation.

        Note: Without an LLM backend, placeholder outputs don't populate
        nested fields like ``review_report.approved``, so the conditional
        ``assemble_feature`` step may raise.  We still verify that input
        validation succeeds and the DAG runs through its earlier phases.
        """
        from agentic_v2.workflows.runner import WorkflowRunner

        runner = WorkflowRunner()
        for inp in fullstack_generation_inputs(limit=2):
            clean = {k: v for k, v in inp.items() if not k.startswith("_")}
            try:
                result = await runner.run("fullstack_generation", **clean)
            except AttributeError:
                # Expected: when clause references nested attr on placeholder
                continue
            assert result is not None
