"""Standard five-dimension prompt quality scoring.

Evaluates prompts on Clarity, Effectiveness, Structure, Specificity,
and Completeness using an LLM judge whose rubric is loaded from
``rubrics/prompt_standard.yaml``.  Multiple runs are aggregated via
median to reduce variance.  Registered as ``"standard"`` in the
:class:`EvaluatorRegistry`.
"""

from __future__ import annotations

import json
import re
import statistics
from dataclasses import dataclass, field
from typing import Any

from agentic_v2_eval.interfaces import LLMClientProtocol
from agentic_v2_eval.rubrics import load_rubric

from .base import EvaluatorRegistry


@dataclass
class StandardScore:
    """Aggregate result from standard five-dimension prompt scoring.

    Attributes:
        prompt_file: Name or path of the evaluated prompt.
        scores: Per-dimension scores (clarity, effectiveness, structure,
            specificity, completeness), each 0--10.
        overall_score: Simple mean of the five dimension scores (0--10).
        grade: Letter grade (A/B/C/D/F) derived from ``overall_score``.
        passed: ``True`` if ``overall_score >= 7.0``.
        improvements: Deduplicated improvement suggestions from the judge.
        confidence: Median confidence value across runs.
        model: LLM model used as judge.
        eval_type: Always ``"standard"``.
        runs: Total number of judge invocations attempted.
        temperature: Sampling temperature for the judge.
        successful_runs: Number of runs that returned parseable JSON.
    """

    prompt_file: str
    scores: dict[
        str, float
    ]  # clarity, effectiveness, structure, specificity, completeness
    overall_score: float  # 0-10
    grade: str  # A, B, C, D, F
    passed: bool
    improvements: list[str] = field(default_factory=list)
    confidence: float = 1.0
    model: str = ""
    # Metadata
    eval_type: str = "standard"
    runs: int = 1
    temperature: float = 0.1
    successful_runs: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "eval_type": self.eval_type,
            "prompt_file": self.prompt_file,
            "model": self.model,
            "runs": self.runs,
            "successful_runs": self.successful_runs,
            "temperature": self.temperature,
            "scores": self.scores,
            "overall_score": self.overall_score,
            "grade": self.grade,
            "passed": self.passed,
            "improvements": self.improvements,
            "confidence": self.confidence,
        }


def _load_standard_prompt() -> str:
    """Load standard judge prompt from YAML."""
    try:
        data = load_rubric("prompt_standard")
        prompt: str = data.get("judge_prompt", "")
        return prompt
    except Exception as e:
        print(f"Warning: Failed to load prompt_standard.yaml: {e}")
        return ""


STANDARD_JUDGE_PROMPT = _load_standard_prompt()


@EvaluatorRegistry.register("standard")
class StandardEvaluator:
    """LLM-judge evaluator for standard prompt quality.

    Sends the prompt content to a judge LLM using a rubric loaded from
    ``rubrics/prompt_standard.yaml``, parses the JSON response, and
    aggregates scores across multiple runs using median.

    Attributes:
        llm_client: Client satisfying :class:`LLMClientProtocol`.
    """

    def __init__(self, llm_client: LLMClientProtocol):
        self.llm_client = llm_client

    def score_prompt(
        self,
        prompt_name: str,
        prompt_content: str,
        model: str = "gh:gpt-4o",
        runs: int = 1,
        temperature: float = 0.1,
    ) -> StandardScore:
        """Score a prompt using standard (simple) 5-dimension rubric."""

        # Max chars check
        max_chars = 18_000
        content_for_judge = prompt_content
        if len(content_for_judge) > max_chars:
            head = content_for_judge[:16_000]
            tail = content_for_judge[-1_000:]
            content_for_judge = (
                head + "\n\n[...TRUNCATED... tail of prompt follows]\n\n" + tail
            )

        safe_prompt_content = content_for_judge.replace("{", "{{").replace("}", "}}")
        judge_prompt = STANDARD_JUDGE_PROMPT.format(prompt_content=safe_prompt_content)

        all_scores = []
        for i in range(runs):
            try:
                response = self.llm_client.generate_text(
                    model_name=model,
                    prompt=judge_prompt,
                    temperature=temperature,
                    max_tokens=900,
                )

                scores = self._parse_response(response)
                if scores:
                    all_scores.append(scores)
            except Exception as e:
                print(f"Standard eval run {i + 1} failed: {e}")

        if not all_scores:
            return self._create_empty_score(prompt_name, model, runs)

        # Aggregate
        final_scores = {}
        for dim in [
            "clarity",
            "effectiveness",
            "structure",
            "specificity",
            "completeness",
        ]:
            values = [s["scores"].get(dim, 0) for s in all_scores if "scores" in s]
            final_scores[dim] = statistics.median(values) if values else 0

        # Uniform weights for now (or load from rubric in future)
        overall = sum(final_scores.values()) / 5.0  # Simple average, max 10

        all_improvement: list[str] = []
        for s in all_scores:
            all_improvement.extend(s.get("improvements", []))
        improvements = list(dict.fromkeys(all_improvement))[:5]

        confidences = [s.get("confidence", 1.0) for s in all_scores]
        confidence = statistics.median(confidences) if confidences else 1.0

        return StandardScore(
            prompt_file=prompt_name,
            scores=final_scores,
            overall_score=round(overall, 2),
            grade=self._get_grade(overall, 10.0),
            passed=overall >= 7.0,
            improvements=improvements,
            confidence=confidence,
            model=model,
            runs=runs,
            successful_runs=len(all_scores),
        )

    def _get_grade(self, score: float, max_score: float) -> str:
        percent = (score / max_score) * 100
        if percent >= 90:
            return "A"
        if percent >= 80:
            return "B"
        if percent >= 70:
            return "C"
        if percent >= 60:
            return "D"
        return "F"

    def _create_empty_score(
        self, prompt_name: str, model: str, runs: int
    ) -> StandardScore:
        return StandardScore(
            prompt_file=prompt_name,
            scores={},
            overall_score=0,
            grade="F",
            passed=False,
            improvements=["Evaluation failed"],
            model=model,
            runs=runs,
        )

    def _parse_response(self, text: str) -> dict[str, Any] | None:
        match = re.search(r"```(?:json)?\s*(.*?)\s*```", text, re.DOTALL)
        if match:
            text = match.group(1)

        try:
            parsed: dict[str, Any] = json.loads(text)
            return parsed
        except json.JSONDecodeError:
            # Try finding object
            s = text.find("{")
            e = text.rfind("}")
            if s != -1 and e != -1:
                try:
                    fallback: dict[str, Any] = json.loads(text[s : e + 1])
                    return fallback
                except json.JSONDecodeError:
                    pass
        return None
