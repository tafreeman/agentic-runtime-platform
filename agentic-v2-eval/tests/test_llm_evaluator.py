"""Focused tests for the choice-anchored LLM evaluator."""

from __future__ import annotations

from typing import Any

from agentic_v2_eval.evaluators.llm import Choice, LLMEvaluator


class FakeLLMClient:
    """Deterministic LLM client for evaluator tests."""

    def __init__(self, response: str | Exception):
        self.response = response
        self.calls: list[dict[str, Any]] = []

    def generate_text(
        self,
        model_name: str,
        prompt: str,
        temperature: float = 0.1,
        max_tokens: int = 1000,
        **kwargs: Any,
    ) -> str:
        self.calls.append(
            {
                "model_name": model_name,
                "prompt": prompt,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "kwargs": kwargs,
            }
        )
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


def make_evaluator(client: FakeLLMClient | None) -> LLMEvaluator:
    return LLMEvaluator(
        model_id="judge-model",
        system_prompt="Choose the best label.",
        prompt_template="Input: {{input}}\nCompletion: {{completion}}",
        choices=[
            Choice("poor", 0.0),
            Choice("ok", 0.5),
            Choice("excellent", 1.0),
        ],
        llm_client=client,  # type: ignore[arg-type]
    )


def test_choice_matching_prefers_exact_last_line() -> None:
    evaluator = make_evaluator(FakeLLMClient("unused"))

    result = evaluator.get_score_from_response(
        "The answer looks ok in places.\nexcellent"
    )

    assert result == ("excellent", 1.0)


def test_choice_matching_searches_last_few_lines() -> None:
    evaluator = make_evaluator(FakeLLMClient("unused"))

    result = evaluator.get_score_from_response(
        "Long rationale\nSecond line\nFinal label: ok"
    )

    assert result == ("ok", 0.5)


def test_evaluate_returns_error_when_no_client_configured() -> None:
    evaluator = make_evaluator(None)

    result = evaluator.evaluate("completion", input="question")

    assert result == {
        "score": 0.0,
        "passed": False,
        "error": "No LLM client configured",
    }


def test_evaluate_returns_invalid_response_details() -> None:
    client = FakeLLMClient("I cannot choose from this rubric.")
    evaluator = make_evaluator(client)

    result = evaluator.evaluate("completion", input="question")

    assert result["score"] == 0.0
    assert result["passed"] is False
    assert result["details"] == "No valid choice found in response"
    assert result["raw_response"] == "I cannot choose from this rubric."
    assert client.calls[0]["temperature"] == 0.0
    assert "System: Choose the best label." in client.calls[0]["prompt"]
    assert "Completion: completion" in client.calls[0]["prompt"]
    # Judge fingerprint must be present
    assert result["judge_model_id"] == "judge-model"
    assert result["judge_seed"] == 0


def test_evaluate_returns_exception_details() -> None:
    evaluator = make_evaluator(FakeLLMClient(RuntimeError("provider unavailable")))

    result = evaluator.evaluate("completion", input="question")

    assert result["score"] == 0.0
    assert result["passed"] is False
    assert result["error"] == "provider unavailable"
    assert result["details"] == "Exception during execution"
    # Judge fingerprint still present on exception path
    assert result["judge_model_id"] == "judge-model"
    assert result["judge_seed"] == 0


def test_evaluate_includes_judge_fingerprint_on_success() -> None:
    """Successful evaluation result carries judge_model_id and judge_seed."""
    client = FakeLLMClient("excellent")
    evaluator = make_evaluator(client)

    result = evaluator.evaluate("great answer", input="question")

    assert result["score"] == 1.0
    assert result["passed"] is True
    assert result["judge_model_id"] == "judge-model"
    assert result["judge_seed"] == 0


def test_evaluate_passes_seed_to_client() -> None:
    """seed= kwarg is forwarded to the LLM client's generate_text call."""
    client = FakeLLMClient("ok")
    evaluator = LLMEvaluator(
        model_id="judge-model",
        system_prompt="Pick a label.",
        prompt_template="{{completion}}",
        choices=[Choice("ok", 0.5)],
        llm_client=client,
        seed=42,
    )

    result = evaluator.evaluate("answer")

    assert result["judge_seed"] == 42
    assert client.calls[0]["kwargs"].get("seed") == 42


def test_evaluate_custom_seed_in_fingerprint() -> None:
    """A non-default seed is reflected in judge_seed in the result."""
    client = FakeLLMClient("poor")
    evaluator = LLMEvaluator(
        model_id="gpt-4o-mini",
        system_prompt="Rate this.",
        prompt_template="{{completion}}",
        choices=[Choice("poor", 0.0), Choice("good", 1.0)],
        llm_client=client,
        seed=99,
    )

    result = evaluator.evaluate("answer")

    assert result["judge_model_id"] == "gpt-4o-mini"
    assert result["judge_seed"] == 99

