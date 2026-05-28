"""Tests for rubrics module."""

from __future__ import annotations

from pathlib import Path

import pytest
from agentic_v2_eval.rubrics import (
    AGENT,
    CODE,
    DEFAULT,
    PATTERN,
    RUBRICS_DIR,
    get_rubric_path,
    list_rubrics,
    load_rubric,
)


class TestRubricConstants:
    """Tests for rubric constants."""

    def test_rubric_dir_exists(self):
        """Test RUBRICS_DIR points to existing directory."""
        assert RUBRICS_DIR.exists()
        assert RUBRICS_DIR.is_dir()

    def test_constants_defined(self):
        """Test rubric name constants are defined."""
        assert DEFAULT == "default"
        assert AGENT == "agent"
        assert CODE == "code"
        assert PATTERN == "pattern"


class TestListRubrics:
    """Tests for list_rubrics function."""

    def test_returns_list(self):
        """Test list_rubrics returns a list."""
        rubrics = list_rubrics()
        assert isinstance(rubrics, list)

    def test_contains_expected_rubrics(self):
        """Test all expected rubrics are listed."""
        rubrics = list_rubrics()
        assert "default" in rubrics
        assert "agent" in rubrics
        assert "code" in rubrics
        assert "pattern" in rubrics

    def test_sorted(self):
        """Test rubrics are returned sorted."""
        rubrics = list_rubrics()
        assert rubrics == sorted(rubrics)


class TestLoadRubric:
    """Tests for load_rubric function."""

    def test_load_default(self):
        """Test loading default rubric."""
        rubric = load_rubric("default")
        assert "criteria" in rubric
        assert isinstance(rubric["criteria"], list)

    def test_load_default_no_arg(self):
        """Test loading default rubric without argument."""
        rubric = load_rubric()
        assert "criteria" in rubric

    def test_load_agent_rubric(self):
        """Test loading agent rubric."""
        rubric = load_rubric("agent")
        assert "criteria" in rubric
        assert "thresholds" in rubric
        assert "metadata" in rubric

        # Check criteria
        criteria_names = [c["name"] for c in rubric["criteria"]]
        assert "Correctness" in criteria_names
        assert "Completeness" in criteria_names
        assert "Safety" in criteria_names

    def test_load_code_rubric(self):
        """Test loading code rubric."""
        rubric = load_rubric("code")
        assert "criteria" in rubric

        criteria_names = [c["name"] for c in rubric["criteria"]]
        assert "Correctness" in criteria_names
        assert "Code Quality" in criteria_names
        assert "Security" in criteria_names

    def test_load_pattern_rubric(self):
        """Test loading pattern rubric."""
        rubric = load_rubric("pattern")
        assert "criteria" in rubric
        assert "hard_gates" in rubric

        criteria_names = [c["name"] for c in rubric["criteria"]]
        assert "Pattern Invocation" in criteria_names
        assert "Phase Ordering" in criteria_names
        assert "Phase Completeness" in criteria_names

    def test_rubric_not_found(self):
        """Test FileNotFoundError for missing rubric."""
        with pytest.raises(FileNotFoundError, match="Rubric not found"):
            load_rubric("nonexistent-rubric-xyz")

    def test_error_message_includes_available(self):
        """Test error message includes available rubrics."""
        with pytest.raises(FileNotFoundError) as exc_info:
            load_rubric("nonexistent")
        assert "Available:" in str(exc_info.value)
        assert "default" in str(exc_info.value)


class TestGetRubricPath:
    """Tests for get_rubric_path function."""

    def test_returns_path(self):
        """Test get_rubric_path returns a Path."""
        path = get_rubric_path("default")
        assert isinstance(path, Path)

    def test_path_exists(self):
        """Test returned path exists."""
        path = get_rubric_path("default")
        assert path.exists()

    def test_path_is_yaml(self):
        """Test returned path is a YAML file."""
        path = get_rubric_path("agent")
        assert path.suffix == ".yaml"

    def test_not_found_raises(self):
        """Test FileNotFoundError for missing rubric."""
        with pytest.raises(FileNotFoundError):
            get_rubric_path("nonexistent-xyz")


class TestRubricStructure:
    """Tests for rubric YAML structure."""

    @pytest.mark.parametrize("rubric_name", ["default", "agent", "code", "pattern"])
    def test_criteria_have_required_fields(self, rubric_name):
        """Test all criteria have name, weight, description."""
        rubric = load_rubric(rubric_name)

        for criterion in rubric["criteria"]:
            assert "name" in criterion, f"Missing name in {rubric_name}"
            assert "weight" in criterion, f"Missing weight in {rubric_name}"
            assert "description" in criterion, f"Missing description in {rubric_name}"

    @pytest.mark.parametrize("rubric_name", ["default", "agent", "code", "pattern"])
    def test_weights_sum_to_one(self, rubric_name):
        """Test criteria weights sum to approximately 1.0."""
        rubric = load_rubric(rubric_name)

        total_weight = sum(c["weight"] for c in rubric["criteria"])
        assert (
            0.99 <= total_weight <= 1.01
        ), f"Weights sum to {total_weight} in {rubric_name}"

    @pytest.mark.parametrize("rubric_name", ["agent", "code", "pattern"])
    def test_thresholds_defined(self, rubric_name):
        """Test thresholds are defined for comprehensive rubrics."""
        rubric = load_rubric(rubric_name)

        assert "thresholds" in rubric
        assert "pass" in rubric["thresholds"]
        assert "excellent" in rubric["thresholds"]

    def test_agent_has_levels(self):
        """Test agent rubric criteria have scoring levels."""
        rubric = load_rubric("agent")

        for criterion in rubric["criteria"]:
            assert "levels" in criterion, f"Missing levels for {criterion['name']}"
            levels = criterion["levels"]
            assert 5 in levels
            assert 0 in levels

    def test_pattern_has_hard_gates(self):
        """Test pattern rubric has hard gates defined."""
        rubric = load_rubric("pattern")

        assert "hard_gates" in rubric
        assert len(rubric["hard_gates"]) > 0

        for gate in rubric["hard_gates"]:
            assert "criterion" in gate
            assert "minimum" in gate


class TestRubricUsability:
    """Tests for rubric usability with Scorer."""

    def test_default_rubric_works_with_scorer(self):
        """Test default rubric can be used with Scorer."""
        from agentic_v2_eval.scorer import Scorer

        rubric = load_rubric("default")
        scorer = Scorer(rubric)

        # Should not raise
        assert scorer is not None

    def test_agent_rubric_works_with_scorer(self):
        """Test agent rubric can be used with Scorer."""
        from agentic_v2_eval.scorer import Scorer

        rubric = load_rubric("agent")
        scorer = Scorer(rubric)

        assert scorer is not None

    def test_all_rubrics_loadable(self):
        """Test all listed rubrics can be loaded."""
        for rubric_name in list_rubrics():
            rubric = load_rubric(rubric_name)
            assert rubric is not None
            # Rubrics can define criteria (output scoring), definitions (judge prompts), or judge_prompt (meta-eval)
            assert any(k in rubric for k in ["criteria", "definitions", "judge_prompt"])
