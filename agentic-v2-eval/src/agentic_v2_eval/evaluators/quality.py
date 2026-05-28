"""Quality evaluators for model outputs using LLM judges.

Provides five built-in quality dimensions -- Coherence, Fluency,
Relevance, Groundedness, and Similarity -- each defined in
``rubrics/quality.yaml`` and scored on a 5-point scale via an LLM
judge.  Registered as ``"quality"`` in the :class:`EvaluatorRegistry`.
"""

from dataclasses import dataclass
from typing import Any

from agentic_v2_eval.interfaces import LLMClientProtocol
from agentic_v2_eval.rubrics import load_rubric

from .base import EvaluatorRegistry
from .llm import STANDARD_CHOICES, Choice


@dataclass
class LLMEvaluatorDefinition:
    """Declarative definition of an LLM-based quality evaluator.

    Loaded from ``rubrics/quality.yaml`` at module import time.
    Each definition specifies the system prompt, user prompt template,
    scoring choices, and the default judge model.

    Attributes:
        name: Short identifier (e.g. ``"coherence"``).
        system_prompt: System-level instruction for the judge.
        prompt_template: User prompt with ``{{variable}}`` placeholders.
        choices: Ordered list of :class:`Choice` labels and scores.
        model_id: Default LLM model for judging.
    """

    name: str
    system_prompt: str
    prompt_template: str
    choices: list[Choice]
    model_id: str = "gh:gpt-4o"


@EvaluatorRegistry.register("quality")
class QualityEvaluator:
    """Evaluator that scores output quality via LLM judges.

    Accepts an :class:`LLMEvaluatorDefinition` per call, templates the
    prompt with input variables, sends it to the judge LLM, and extracts
    a ``[0.0, 1.0]`` score from the response using choice matching.

    Attributes:
        llm_client: Client satisfying :class:`LLMClientProtocol`.
    """

    def __init__(self, llm_client: LLMClientProtocol):
        self.llm_client = llm_client

    def evaluate(
        self,
        definition: LLMEvaluatorDefinition,
        inputs: dict[str, Any],
        output: str,
        model_override: str | None = None,
    ) -> float:
        """Evaluate an output against a definition."""

        # Prepare variables
        variables = dict(inputs)
        variables["completion"] = output

        # Template prompt
        prompt = definition.prompt_template
        for k, v in variables.items():
            prompt = prompt.replace(f"{{{{{k}}}}}", str(v))

        # Build prompt
        full_prompt = ""
        if definition.system_prompt:
            full_prompt += f"System: {definition.system_prompt}\n\n"
        full_prompt += prompt

        model = model_override or definition.model_id

        try:
            response = self.llm_client.generate_text(
                model_name=model, prompt=full_prompt, temperature=0.0
            )

            return self._extract_score(response, definition.choices)
        except Exception as e:
            print(f"Evaluation failed: {e}")
            return 0.0

    def _extract_score(self, response: str, choices: list[Choice]) -> float:
        """Extract score using choice matching."""
        response_lower = response.strip().lower()
        lines = response_lower.split("\n")
        last_line = lines[-1].strip() if lines else ""

        # Exact match on last line
        for choice in choices:
            if last_line == choice.choice.lower():
                return choice.score

        # Containment in last few lines
        search_text = "\n".join(lines[-3:]) if len(lines) >= 3 else response_lower
        for choice in choices:
            if choice.choice.lower() in search_text:
                return choice.score

        return 0.0


# =============================================================================
# BUILT-IN DEFINITIONS (Loaded from YAML)
# =============================================================================


def _load_definitions() -> dict[str, LLMEvaluatorDefinition]:
    """Load definitions from rubrics/quality.yaml."""
    definitions = {}

    try:
        yaml_data = load_rubric("quality")
        raw_defs = yaml_data.get("definitions", {})

        for key, data in raw_defs.items():
            # Map choice types
            choices = STANDARD_CHOICES
            if data.get("choices_type") == "standard_5_point":
                choices = STANDARD_CHOICES

            definitions[key] = LLMEvaluatorDefinition(
                name=key,
                system_prompt=data.get("system_prompt", ""),
                prompt_template=data.get("prompt_template", ""),
                choices=choices,
                model_id=data.get("model_id", "gh:gpt-4o"),
            )

    except Exception as e:
        print(f"Failed to load quality definitions: {e}")
        # Fallback to empty or raise depending on strictness

    return definitions


_DEFINITIONS = _load_definitions()

# Expose as constants for backward compatibility
COHERENCE = _DEFINITIONS.get("coherence")
FLUENCY = _DEFINITIONS.get("fluency")
RELEVANCE = _DEFINITIONS.get("relevance")
GROUNDEDNESS = _DEFINITIONS.get("groundedness")
SIMILARITY = _DEFINITIONS.get("similarity")

# Create a default empty definition if missing to avoid import errors
if not COHERENCE:
    # Fallback/Placeholder
    COHERENCE = LLMEvaluatorDefinition("coherence", "", "", [])
    FLUENCY = LLMEvaluatorDefinition("fluency", "", "", [])
    RELEVANCE = LLMEvaluatorDefinition("relevance", "", "", [])
    GROUNDEDNESS = LLMEvaluatorDefinition("groundedness", "", "", [])
    SIMILARITY = LLMEvaluatorDefinition("similarity", "", "", [])
