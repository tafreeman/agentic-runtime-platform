#!/usr/bin/env python3
"""LLM-as-judge evaluator for benchmark outputs.

Scores generated text against a gold standard using a five-dimension
rubric (Completeness, Correctness, Quality, Specificity, Alignment)
on a 0.0--10.0 scale.  The LLM judge prompt is constructed by
:func:`build_evaluation_prompt`, and the structured JSON response is
parsed by :func:`parse_evaluation_response`.

This evaluator is benchmark-agnostic: it works for SWE-bench patches,
HumanEval functions, or any task with a gold-standard dictionary.

Data models and rubric constants live in :mod:`evaluator_models`.
Output formatting and batch summarisation live in :mod:`evaluator_reporting`.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

# ---------------------------------------------------------------------------
# Re-exports for backward compatibility
# ---------------------------------------------------------------------------
from tools.agents.benchmarks.evaluator_models import (
    EVALUATION_DIMENSIONS,
    SCORE_RUBRIC,
    BatchEvaluationSummary,
    DimensionScore,
    EvaluationResult,
)
from tools.agents.benchmarks.evaluator_reporting import (
    print_evaluation_report,
    save_evaluation_report,
    summarize_batch_results,
)

# =============================================================================
# LLM EVALUATOR — core prompt construction and evaluation logic
# =============================================================================


def build_evaluation_prompt(
    task_prompt: str,
    generated_output: str,
    gold_standard: dict[str, Any],
    dimensions: dict[str, dict[str, Any]] | None = None,
) -> str:
    """Build the evaluation prompt for the LLM judge."""

    if dimensions is None:
        dimensions = EVALUATION_DIMENSIONS

    # Build gold standard summary (generic)
    gold_summary_parts = []

    # Handle common gold standard fields
    if "required_components" in gold_standard:
        gold_summary_parts.append(
            f"Required Components: {gold_standard['required_components']}"
        )

    if "required_patterns" in gold_standard:
        gold_summary_parts.append(
            f"Required Patterns: {gold_standard['required_patterns']}"
        )

    if "key_decisions" in gold_standard:
        gold_summary_parts.append(
            f"Key Decisions/Concepts: {gold_standard['key_decisions']}"
        )

    if "expected_output" in gold_standard:
        gold_summary_parts.append(
            f"Expected Output: {gold_standard['expected_output']}"
        )

    if "api_endpoints" in gold_standard:
        endpoints = [
            f"{e.get('method', 'ANY')} {e.get('path', 'N/A')}"
            for e in gold_standard["api_endpoints"]
        ]
        gold_summary_parts.append(f"Expected Endpoints: {endpoints}")

    if "database_tables" in gold_standard:
        gold_summary_parts.append(
            f"Expected Tables/Schemas: {gold_standard['database_tables']}"
        )

    if "test_cases" in gold_standard:
        gold_summary_parts.append(
            f"Test Cases: {len(gold_standard['test_cases'])} defined"
        )

    # Add any other keys generically
    skip_keys = {
        "required_components",
        "required_patterns",
        "key_decisions",
        "expected_output",
        "api_endpoints",
        "database_tables",
        "test_cases",
        "task_id",
        "name",
        "version",
        "last_updated",
        "source_references",
        "prompt",
        "instruction",
    }
    for key, value in gold_standard.items():
        if key not in skip_keys and value:
            gold_summary_parts.append(f"{key.replace('_', ' ').title()}: {value}")

    gold_summary = (
        "\n".join(gold_summary_parts)
        if gold_summary_parts
        else "No specific gold standard defined."
    )

    # Build dimensions section
    dimensions_text = "\n".join(
        [
            f"- **{name}** (weight: {info['weight']}): {info['description']}"
            for name, info in dimensions.items()
        ]
    )

    # Build score rubric text
    rubric_text = "\n".join(
        [
            f"  {score}: {desc}"
            for score, desc in sorted(SCORE_RUBRIC.items(), reverse=True)
        ]
    )

    prompt = f"""You are an expert code/design evaluator. Evaluate the following generated output against the task requirements and gold standard.

## TASK PROMPT
{task_prompt}

## GOLD STANDARD EXPECTATIONS
{gold_summary}

## GENERATED OUTPUT
{generated_output}

## EVALUATION DIMENSIONS
Evaluate each dimension on a 0.0-10.0 scale:
{dimensions_text}

## SCORING RUBRIC
{rubric_text}

## INSTRUCTIONS
1. Analyze the generated output against the task requirements
2. Compare with gold standard expectations
3. Score each dimension with detailed reasoning
4. Provide specific evidence (quotes, examples) for each score
5. List strengths, weaknesses, and improvement suggestions

## REQUIRED OUTPUT FORMAT
Respond with a valid JSON object (no markdown code blocks):
{{
  "dimension_scores": {{
    "completeness": {{
      "score": <0.0-10.0>,
      "reasoning": "<detailed explanation>",
      "evidence": ["<specific quote or example>", ...]
    }},
    "correctness": {{
      "score": <0.0-10.0>,
      "reasoning": "<detailed explanation>",
      "evidence": ["<specific quote or example>", ...]
    }},
    "quality": {{
      "score": <0.0-10.0>,
      "reasoning": "<detailed explanation>",
      "evidence": ["<specific quote or example>", ...]
    }},
    "specificity": {{
      "score": <0.0-10.0>,
      "reasoning": "<detailed explanation>",
      "evidence": ["<specific quote or example>", ...]
    }},
    "alignment": {{
      "score": <0.0-10.0>,
      "reasoning": "<detailed explanation>",
      "evidence": ["<specific quote or example>", ...]
    }}
  }},
  "strengths": ["<strength 1>", "<strength 2>", ...],
  "weaknesses": ["<weakness 1>", "<weakness 2>", ...],
  "improvement_suggestions": ["<suggestion 1>", "<suggestion 2>", ...],
  "key_findings": ["<finding 1>", "<finding 2>", ...]
}}"""

    return prompt


def parse_evaluation_response(response: str) -> dict[str, Any]:
    """Parse the LLM evaluation response."""
    # Try to extract JSON from the response
    response = response.strip()

    # Remove markdown code blocks if present
    if response.startswith("```"):
        # Find the end of the opening code fence
        first_newline = response.find("\n")
        if first_newline != -1:
            response = response[first_newline + 1 :]
        # Remove closing fence
        if response.endswith("```"):
            response = response[:-3].strip()

    # Try direct JSON parse
    try:
        return json.loads(response)
    except json.JSONDecodeError:
        pass

    # Try to find JSON object in response
    json_match = re.search(r"\{[\s\S]*\}", response)
    if json_match:
        try:
            return json.loads(json_match.group())
        except json.JSONDecodeError:
            pass

    # Return empty structure on parse failure
    return {
        "dimension_scores": {},
        "strengths": [],
        "weaknesses": ["Failed to parse evaluation response"],
        "improvement_suggestions": [],
        "key_findings": ["Evaluation parsing error"],
        "parse_error": True,
        "raw_response": response[:500],
    }


def evaluate_with_llm(
    task_id: str,
    task_prompt: str,
    generated_output: str,
    gold_standard: dict[str, Any],
    model: str,
    benchmark_id: str,
    evaluator_model: str | None = None,
    verbose: bool = False,
) -> EvaluationResult:
    """Evaluate generated output using an LLM judge.

    Args:
        task_id: Unique task identifier
        task_prompt: Original task prompt
        generated_output: The generated output to evaluate
        gold_standard: Gold standard data for comparison
        model: Model that generated the output
        benchmark_id: Benchmark identifier
        evaluator_model: Model to use for evaluation (defaults to same as generation)
        verbose: Print detailed output

    Returns:
        EvaluationResult with scores and analysis
    """
    from tools.llm.llm_client import LLMClient

    if evaluator_model is None:
        evaluator_model = model

    # Build evaluation prompt
    eval_prompt = build_evaluation_prompt(
        task_prompt=task_prompt,
        generated_output=generated_output,
        gold_standard=gold_standard,
    )

    if verbose:
        print(f"  [Evaluator] Using {evaluator_model} for evaluation...")

    # Call LLM (generate_text is a static method with model_name as first arg)
    start_time = datetime.now()

    try:
        response = LLMClient.generate_text(
            evaluator_model,  # model_name is first positional arg
            eval_prompt,  # prompt is second positional arg
            max_tokens=2000,
        )

        duration = (datetime.now() - start_time).total_seconds()

        if verbose:
            print(f"  [Evaluator] Completed in {duration:.1f}s")

    except Exception as e:
        if verbose:
            print(f"  [Evaluator] Error: {e}")

        # Return error result
        return EvaluationResult(
            task_id=task_id,
            model=model,
            benchmark_id=benchmark_id,
            timestamp=datetime.now().isoformat(),
            overall_score=0.0,
            grade="F",
            task_prompt=task_prompt[:500],
            generated_output=generated_output[:500],
            evaluator_model=evaluator_model,
            weaknesses=[f"Evaluation failed: {e!s}"],
        )

    # Parse response
    parsed = parse_evaluation_response(response)

    # Build dimension scores
    dimension_scores = {}
    total_weighted = 0.0

    for dim_name, dim_info in EVALUATION_DIMENSIONS.items():
        dim_data = parsed.get("dimension_scores", {}).get(dim_name, {})
        score = float(dim_data.get("score", 0.0))

        # Clamp score to valid range
        score = max(0.0, min(10.0, score))

        dim_score = DimensionScore(
            dimension=dim_name,
            score=score,
            reasoning=dim_data.get("reasoning", "No reasoning provided"),
            evidence=dim_data.get("evidence", []),
            weight=dim_info["weight"],
        )
        dimension_scores[dim_name] = dim_score
        total_weighted += dim_score.weighted_score

    # Calculate overall score
    overall_score = total_weighted
    grade = EvaluationResult.grade_from_score(overall_score)

    # Build gold standard summary for storage
    gold_summary = json.dumps(
        {k: v for k, v in gold_standard.items() if k not in ["prompt", "instruction"]},
        indent=2,
    )[:1000]

    return EvaluationResult(
        task_id=task_id,
        model=model,
        benchmark_id=benchmark_id,
        timestamp=datetime.now().isoformat(),
        dimension_scores=dimension_scores,
        overall_score=overall_score,
        grade=grade,
        task_prompt=task_prompt,
        generated_output=generated_output,
        gold_standard_summary=gold_summary,
        duration_seconds=duration,
        evaluator_model=evaluator_model,
        strengths=parsed.get("strengths", []),
        weaknesses=parsed.get("weaknesses", []),
        improvement_suggestions=parsed.get("improvement_suggestions", []),
        key_findings=parsed.get("key_findings", []),
    )
