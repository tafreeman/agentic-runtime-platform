"""Tests for PatternEvaluator and PatternScore."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from agentic_v2_eval.evaluators.pattern import (
    PATTERN_PHASES,
    PATTERN_SCORE_FIELDS,
    PATTERN_SPECIFIC_INSTRUCTIONS,
    PATTERN_STATE_MACHINES,
    PatternEvaluator,
    PatternScore,
)


class TestPatternScore:
    """Tests for PatternScore dataclass."""

    def test_create_minimal(self):
        """Test creating PatternScore with minimal data."""
        score = PatternScore(
            prompt_file="test.md",
            pattern="react",
            universal_scores={"PIF": 5, "POI": 5},
            pattern_scores={"R1": 4, "R2": 4, "R3": 4},
            overall_universal=30.0,
            overall_pattern=12.0,
            combined_score=42.0,
            hard_gates_passed=True,
        )
        assert score.prompt_file == "test.md"
        assert score.pattern == "react"
        assert score.hard_gates_passed is True

    def test_to_dict(self):
        """Test serialization to dict."""
        score = PatternScore(
            prompt_file="cove.md",
            pattern="cove",
            universal_scores={"PIF": 4, "POI": 5, "PC": 4},
            pattern_scores={"C1": 5, "C2": 4, "C3": 5},
            overall_universal=25.0,
            overall_pattern=14.0,
            combined_score=39.0,
            hard_gates_passed=True,
            model="gh:gpt-4o",
            runs=10,
            successful_runs=9,
        )
        d = score.to_dict()

        assert d["eval_type"] == "pattern"
        assert d["prompt_file"] == "cove.md"
        assert d["pattern"] == "cove"
        assert d["model"] == "gh:gpt-4o"
        assert d["runs"] == 10
        assert d["successful_runs"] == 9
        assert "universal_scores" in d
        assert "pattern_scores" in d

    def test_defaults(self):
        """Test default values."""
        score = PatternScore(
            prompt_file="test.md",
            pattern="react",
            universal_scores={},
            pattern_scores={},
            overall_universal=0.0,
            overall_pattern=0.0,
            combined_score=0.0,
            hard_gates_passed=False,
        )
        assert score.hard_gate_failures == []
        assert score.failures == []
        assert score.pass_rate == 1.0
        assert score.confidence == 1.0
        assert score.model == ""
        assert score.eval_type == "pattern"
        assert score.runs == 20
        assert score.temperature == 0.1


class TestPatternConstants:
    """Tests for pattern constants."""

    def test_pattern_phases_defined(self):
        """Test all patterns have phases defined."""
        assert "react" in PATTERN_PHASES
        assert "cove" in PATTERN_PHASES
        assert "reflexion" in PATTERN_PHASES
        assert "rag" in PATTERN_PHASES

    def test_react_phases(self):
        """Test ReAct has correct phases."""
        phases = PATTERN_PHASES["react"]
        assert "Thought" in phases
        assert "Action" in phases
        assert "Observation" in phases
        assert "Final Answer" in phases

    def test_cove_phases(self):
        """Test CoVe has correct phases."""
        phases = PATTERN_PHASES["cove"]
        assert "Draft Answer" in phases
        assert "Verification Questions" in phases
        assert "Revised Answer" in phases

    def test_state_machines_defined(self):
        """Test all patterns have state machines."""
        for pattern in PATTERN_PHASES:
            assert pattern in PATTERN_STATE_MACHINES
            assert "→" in PATTERN_STATE_MACHINES[pattern]

    def test_specific_instructions_defined(self):
        """Test all patterns have specific instructions."""
        for pattern in PATTERN_PHASES:
            assert pattern in PATTERN_SPECIFIC_INSTRUCTIONS
            assert len(PATTERN_SPECIFIC_INSTRUCTIONS[pattern]) > 0

    def test_score_fields_defined(self):
        """Test all patterns have score fields."""
        for pattern in PATTERN_PHASES:
            assert pattern in PATTERN_SCORE_FIELDS


class TestPatternEvaluator:
    """Tests for PatternEvaluator."""

    def test_init(self):
        """Test evaluator initialization."""
        mock_client = MagicMock()
        evaluator = PatternEvaluator(llm_client=mock_client)
        assert evaluator.llm_client is mock_client

    def test_invalid_pattern_raises(self):
        """Test that invalid pattern raises ValueError."""
        mock_client = MagicMock()
        evaluator = PatternEvaluator(llm_client=mock_client)

        with pytest.raises(ValueError, match="Unknown pattern"):
            evaluator.score_pattern(
                prompt_name="test.md",
                prompt_content="Test prompt",
                model_output="Test output",
                pattern="invalid_pattern",
            )

    def test_score_pattern_calls_llm(self):
        """Test that score_pattern calls LLM client."""
        mock_client = MagicMock()
        mock_client.generate_text.return_value = """
        ```json
        {
            "universal_scores": {"PIF": 5, "POI": 5, "PC": 5, "CA": 5, "SRC": 5, "PR": 0.9, "IR": 5},
            "pattern_scores": {"R1": 5, "R2": 5, "R3": 5},
            "failures": [],
            "confidence": 0.95
        }
        ```
        """

        evaluator = PatternEvaluator(llm_client=mock_client)

        result = evaluator.score_pattern(
            prompt_name="react-prompt.md",
            prompt_content="Think step by step...",
            model_output="Thought: I need to analyze...",
            pattern="react",
            model="gh:gpt-4o",
            runs=1,
        )

        mock_client.generate_text.assert_called_once()
        assert isinstance(result, PatternScore)
        assert result.pattern == "react"
        assert result.hard_gates_passed is True

    def test_score_pattern_with_failed_hard_gates(self):
        """Test scoring with hard gate failures."""
        mock_client = MagicMock()
        mock_client.generate_text.return_value = """
        {
            "universal_scores": {"PIF": 5, "POI": 2, "PC": 3, "CA": 2, "SRC": 5, "PR": 0.5, "IR": 5},
            "pattern_scores": {"R1": 5, "R2": 5, "R3": 5},
            "failures": ["POI too low"],
            "confidence": 0.8
        }
        """

        evaluator = PatternEvaluator(llm_client=mock_client)

        result = evaluator.score_pattern(
            prompt_name="bad-react.md",
            prompt_content="Just answer...",
            model_output="The answer is 42",
            pattern="react",
            runs=1,
        )

        assert result.hard_gates_passed is False
        assert len(result.hard_gate_failures) > 0
        # POI < 4, PC < 4, CA < 4, PR < 0.75 - all should fail
        assert (
            "Phase Ordering Integrity" in result.hard_gate_failures[0]
            or "Phase Completeness" in result.hard_gate_failures[0]
        )

    def test_score_pattern_handles_llm_error(self):
        """Test that LLM errors result in empty score."""
        mock_client = MagicMock()
        mock_client.generate_text.side_effect = Exception("API Error")

        evaluator = PatternEvaluator(llm_client=mock_client)

        result = evaluator.score_pattern(
            prompt_name="test.md",
            prompt_content="Test",
            model_output="Output",
            pattern="cove",
            runs=1,
        )

        assert result.hard_gates_passed is False
        assert "Execution failed" in result.hard_gate_failures

    def test_score_pattern_handles_invalid_json(self):
        """Test that invalid JSON results in empty score."""
        mock_client = MagicMock()
        mock_client.generate_text.return_value = "This is not JSON"

        evaluator = PatternEvaluator(llm_client=mock_client)

        result = evaluator.score_pattern(
            prompt_name="test.md",
            prompt_content="Test",
            model_output="Output",
            pattern="reflexion",
            runs=1,
        )

        assert result.hard_gates_passed is False

    def test_parse_json_from_markdown(self):
        """Test JSON extraction from markdown code blocks."""
        mock_client = MagicMock()
        evaluator = PatternEvaluator(llm_client=mock_client)

        text_with_markdown = """
Here is my evaluation:

```json
{"universal_scores": {"PIF": 4}, "pattern_scores": {}, "failures": [], "confidence": 0.9}
```
"""
        result = evaluator._parse_json_response(text_with_markdown)
        assert result is not None
        assert result["universal_scores"]["PIF"] == 4

    def test_parse_json_fallback(self):
        """Test JSON extraction fallback (no markdown)."""
        mock_client = MagicMock()
        evaluator = PatternEvaluator(llm_client=mock_client)

        text = 'Some text {"key": "value"} more text'
        result = evaluator._parse_json_response(text)
        assert result is not None
        assert result["key"] == "value"

    def test_all_patterns_can_be_scored(self):
        """Test that all defined patterns can be scored."""
        mock_client = MagicMock()
        mock_client.generate_text.return_value = """
        {"universal_scores": {"PIF": 5, "POI": 5, "PC": 5, "CA": 5, "SRC": 5, "PR": 0.9, "IR": 5},
         "pattern_scores": {},
         "failures": [],
         "confidence": 0.9}
        """

        evaluator = PatternEvaluator(llm_client=mock_client)

        for pattern in PATTERN_PHASES:
            result = evaluator.score_pattern(
                prompt_name=f"{pattern}-test.md",
                prompt_content="Test prompt",
                model_output="Test output",
                pattern=pattern,
                runs=1,
            )
            assert result.pattern == pattern
            assert isinstance(result, PatternScore)

    def test_escapes_special_characters_in_prompt(self):
        """Test that { and } in prompt/output are escaped."""
        mock_client = MagicMock()
        mock_client.generate_text.return_value = '{"universal_scores": {}, "pattern_scores": {}, "failures": [], "confidence": 1.0}'

        evaluator = PatternEvaluator(llm_client=mock_client)

        # This should not raise due to format string issues
        evaluator.score_pattern(
            prompt_name="test.md",
            prompt_content="Use {input} and {output} variables",
            model_output="Result: {value}",
            pattern="react",
            runs=1,
        )

        # Check that the call was made (no KeyError from format())
        mock_client.generate_text.assert_called_once()
