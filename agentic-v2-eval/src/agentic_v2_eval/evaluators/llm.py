"""LLM-as-judge evaluator using choice-anchored rubrics.

Sends a templated prompt to an LLM, then extracts a discrete score by
matching the response against a set of predefined :class:`Choice` labels.
Registered as ``"llm"`` in the :class:`EvaluatorRegistry`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from ..interfaces import LLMClientProtocol
from .base import Evaluator, EvaluatorRegistry

__all__ = [
    "Choice",
    "STANDARD_CHOICES",
    "LLMClientProtocol",
    "LLMEvaluator",
]

logger = logging.getLogger(__name__)


@dataclass
class Choice:
    """A discrete scoring option mapping a label to a normalized score.

    Attributes:
        choice: Display label emitted by the LLM (e.g. ``"3"``).
        score: Normalized float in ``[0.0, 1.0]``.
    """

    choice: str  # e.g., "1", "2", "poor", "excellent"
    score: float  # Normalized 0.0-1.0


STANDARD_CHOICES = [
    Choice("1", 0.0),
    Choice("2", 0.25),
    Choice("3", 0.5),
    Choice("4", 0.75),
    Choice("5", 1.0),
]


@EvaluatorRegistry.register("llm")
@dataclass
class LLMEvaluator(Evaluator):
    """LLM-based evaluator that scores outputs via choice-anchored prompts.

    Constructs a judge prompt from ``prompt_template`` and
    ``system_prompt``, sends it to the configured LLM, and maps the
    response to a normalized ``[0.0, 1.0]`` score using the ``choices``
    list.

    Attributes:
        model_id: LLM model identifier for the judge.
        system_prompt: System-level instruction for the judge.
        prompt_template: User prompt with ``{{variable}}`` placeholders.
        choices: Ordered list of :class:`Choice` labels and scores.
        llm_client: Client satisfying :class:`LLMClientProtocol`.
    """

    model_id: str
    system_prompt: str
    prompt_template: str
    choices: list[Choice]
    llm_client: LLMClientProtocol

    def get_score_from_response(self, response: str) -> tuple[str, float] | None:
        """Extract score from LLM response using choice matching."""
        response_lower = response.strip().lower()

        # Try to find the score in the last line (most reliable)
        lines = response_lower.strip().split("\n")
        last_line = lines[-1].strip() if lines else ""

        # Check for exact matches first
        for choice in self.choices:
            if last_line == choice.choice.lower():
                return (choice.choice, choice.score)

        # Then check for containment in last few lines
        search_text = "\n".join(lines[-3:]) if len(lines) >= 3 else response_lower
        for choice in self.choices:
            if choice.choice.lower() in search_text:
                return (choice.choice, choice.score)

        return None

    def evaluate(self, output: str, **kwargs: Any) -> dict[str, Any]:
        """Evaluate output using the LLM judge.

        Args:
            output: The completion/response to evaluate.
            **kwargs: Template variables (e.g., input, expected).
        """
        if not self.llm_client:
            return {
                "score": 0.0,
                "passed": False,
                "error": "No LLM client configured",
            }

        # Prepare variables
        variables = dict(kwargs)
        variables["completion"] = output

        # Template the prompt
        prompt = self.prompt_template
        for k, v in variables.items():
            prompt = prompt.replace(f"{{{{{k}}}}}", str(v))

        # Build full prompt
        full_prompt = ""
        if self.system_prompt:
            full_prompt += f"System: {self.system_prompt}\n\n"
        full_prompt += f"{prompt}"

        try:
            response = self.llm_client.generate_text(
                model_name=self.model_id,
                prompt=full_prompt,
                temperature=0.0,
            )

            result = self.get_score_from_response(response)
            if result:
                choice_label, score = result
                return {
                    "score": score,
                    "passed": score > 0,
                    "label": choice_label,
                    "details": f"Matched choice: {choice_label}",
                    "raw_response": response,
                }
            else:
                return {
                    "score": 0.0,
                    "passed": False,
                    "details": "No valid choice found in response",
                    "raw_response": response,
                }

        except Exception as e:
            logger.error(f"LLM Evaluation failed: {e}")
            return {
                "score": 0.0,
                "passed": False,
                "error": str(e),
                "details": "Exception during execution",
            }
