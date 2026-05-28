"""Tests for QualityEvaluator and LLMEvaluatorDefinition."""

from __future__ import annotations

from unittest.mock import MagicMock

from agentic_v2_eval.evaluators.quality import (
    COHERENCE,
    STANDARD_CHOICES,
    Choice,
    LLMEvaluatorDefinition,
    QualityEvaluator,
)


class TestChoice:
    """Tests for Choice dataclass."""

    def test_create(self):
        """Test creating a Choice."""
        choice = Choice(choice="1", score=0.0)
        assert choice.choice == "1"
        assert choice.score == 0.0

    def test_standard_choices(self):
        """Test STANDARD_CHOICES has 5 levels."""
        assert len(STANDARD_CHOICES) == 5
        assert STANDARD_CHOICES[0].choice == "1"
        assert STANDARD_CHOICES[0].score == 0.0
        assert STANDARD_CHOICES[4].choice == "5"
        assert STANDARD_CHOICES[4].score == 1.0


class TestLLMEvaluatorDefinition:
    """Tests for LLMEvaluatorDefinition."""

    def test_create_minimal(self):
        """Test creating with minimal fields."""
        defn = LLMEvaluatorDefinition(
            name="test",
            system_prompt="You are a tester.",
            prompt_template="Rate: {{completion}}",
            choices=STANDARD_CHOICES,
        )
        assert defn.name == "test"
        assert defn.model_id == "gh:gpt-4o"  # default

    def test_create_with_model(self):
        """Test creating with custom model."""
        defn = LLMEvaluatorDefinition(
            name="test",
            system_prompt="System",
            prompt_template="Template",
            choices=STANDARD_CHOICES,
            model_id="local:phi4",
        )
        assert defn.model_id == "local:phi4"

    def test_coherence_definition(self):
        """Test COHERENCE built-in is defined."""
        assert COHERENCE.name == "coherence"
        assert "Coherence" in COHERENCE.system_prompt
        assert "{{completion}}" in COHERENCE.prompt_template
        assert len(COHERENCE.choices) == 5


class TestQualityEvaluator:
    """Tests for QualityEvaluator."""

    def test_init(self):
        """Test evaluator initialization."""
        mock_client = MagicMock()
        evaluator = QualityEvaluator(llm_client=mock_client)
        assert evaluator.llm_client is mock_client

    def test_evaluate_calls_llm(self):
        """Test that evaluate calls the LLM client."""
        mock_client = MagicMock()
        mock_client.generate_text.return_value = "5"

        evaluator = QualityEvaluator(llm_client=mock_client)

        definition = LLMEvaluatorDefinition(
            name="test_eval",
            system_prompt="Rate quality.",
            prompt_template="Input: {{input}}\nOutput: {{completion}}\n\nScore:",
            choices=STANDARD_CHOICES,
        )

        score = evaluator.evaluate(
            definition=definition,
            inputs={"input": "What is 2+2?"},
            output="4",
        )

        mock_client.generate_text.assert_called_once()
        assert score == 1.0  # "5" maps to 1.0

    def test_evaluate_with_model_override(self):
        """Test model override in evaluate."""
        mock_client = MagicMock()
        mock_client.generate_text.return_value = "3"

        evaluator = QualityEvaluator(llm_client=mock_client)

        definition = LLMEvaluatorDefinition(
            name="test",
            system_prompt="",
            prompt_template="{{completion}}",
            choices=STANDARD_CHOICES,
            model_id="gh:gpt-4o",
        )

        evaluator.evaluate(
            definition=definition,
            inputs={},
            output="test output",
            model_override="local:phi4",
        )

        call_args = mock_client.generate_text.call_args
        assert call_args.kwargs["model_name"] == "local:phi4"

    def test_extract_score_exact_match(self):
        """Test score extraction with exact match."""
        mock_client = MagicMock()
        evaluator = QualityEvaluator(llm_client=mock_client)

        score = evaluator._extract_score("4", STANDARD_CHOICES)
        assert score == 0.75

    def test_extract_score_in_text(self):
        """Test score extraction from text."""
        mock_client = MagicMock()
        evaluator = QualityEvaluator(llm_client=mock_client)

        response = """The response is well-written and coherent.
        
        Based on my analysis, I give it a score of 5."""

        score = evaluator._extract_score(response, STANDARD_CHOICES)
        assert score == 1.0

    def test_extract_score_not_found(self):
        """Test score extraction when not found."""
        mock_client = MagicMock()
        evaluator = QualityEvaluator(llm_client=mock_client)

        score = evaluator._extract_score("This text has no score.", STANDARD_CHOICES)
        assert score == 0.0

    def test_extract_score_case_insensitive(self):
        """Test score extraction is case insensitive."""
        mock_client = MagicMock()
        evaluator = QualityEvaluator(llm_client=mock_client)

        choices = [Choice("EXCELLENT", 1.0), Choice("GOOD", 0.75), Choice("POOR", 0.0)]

        score = evaluator._extract_score("excellent", choices)
        assert score == 1.0

    def test_evaluate_handles_error(self):
        """Test that errors return 0.0 score."""
        mock_client = MagicMock()
        mock_client.generate_text.side_effect = Exception("API Error")

        evaluator = QualityEvaluator(llm_client=mock_client)

        definition = LLMEvaluatorDefinition(
            name="test",
            system_prompt="",
            prompt_template="{{completion}}",
            choices=STANDARD_CHOICES,
        )

        score = evaluator.evaluate(
            definition=definition,
            inputs={},
            output="test",
        )

        assert score == 0.0

    def test_template_substitution(self):
        """Test that template variables are substituted."""
        mock_client = MagicMock()
        mock_client.generate_text.return_value = "5"

        evaluator = QualityEvaluator(llm_client=mock_client)

        definition = LLMEvaluatorDefinition(
            name="test",
            system_prompt="Evaluate.",
            prompt_template="Query: {{query}}\nResponse: {{completion}}",
            choices=STANDARD_CHOICES,
        )

        evaluator.evaluate(
            definition=definition,
            inputs={"query": "What is AI?"},
            output="AI is artificial intelligence.",
        )

        call_args = mock_client.generate_text.call_args
        prompt = call_args.kwargs["prompt"]

        assert "What is AI?" in prompt
        assert "AI is artificial intelligence." in prompt

    def test_temperature_zero(self):
        """Test that temperature is 0.0 for deterministic scoring."""
        mock_client = MagicMock()
        mock_client.generate_text.return_value = "5"

        evaluator = QualityEvaluator(llm_client=mock_client)

        definition = LLMEvaluatorDefinition(
            name="test",
            system_prompt="",
            prompt_template="{{completion}}",
            choices=STANDARD_CHOICES,
        )

        evaluator.evaluate(
            definition=definition,
            inputs={},
            output="test",
        )

        call_args = mock_client.generate_text.call_args
        assert call_args.kwargs["temperature"] == 0.0


class TestQualityEvaluatorIntegration:
    """Integration-style tests for QualityEvaluator."""

    def test_coherence_evaluation(self):
        """Test using COHERENCE built-in definition."""
        mock_client = MagicMock()
        mock_client.generate_text.return_value = "4"

        evaluator = QualityEvaluator(llm_client=mock_client)

        score = evaluator.evaluate(
            definition=COHERENCE,
            inputs={"input": "Explain quantum computing"},
            output="Quantum computing uses qubits instead of classical bits...",
        )

        assert score == 0.75  # "4" maps to 0.75
        mock_client.generate_text.assert_called_once()

    def test_custom_choices(self):
        """Test with custom choice labels."""
        mock_client = MagicMock()
        mock_client.generate_text.return_value = "strongly agree"

        evaluator = QualityEvaluator(llm_client=mock_client)

        custom_choices = [
            Choice("strongly disagree", 0.0),
            Choice("disagree", 0.25),
            Choice("neutral", 0.5),
            Choice("agree", 0.75),
            Choice("strongly agree", 1.0),
        ]

        definition = LLMEvaluatorDefinition(
            name="agreement",
            system_prompt="Rate agreement.",
            prompt_template="Statement: {{completion}}",
            choices=custom_choices,
        )

        score = evaluator.evaluate(
            definition=definition,
            inputs={},
            output="The sky is blue.",
        )

        assert score == 1.0
