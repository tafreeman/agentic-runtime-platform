"""LLM-as-Judge evaluation engine for hybrid workflow scoring.

Provides :class:`LLMJudge`, which scores candidate outputs against
anchored 1--5 rubric criteria using an LLM backend.  Key design features:

* **Anchored rubric prompts** -- each criterion includes a definition and
  scale anchors (1=worst, 5=best) so the judge produces calibrated scores.
* **Positional bias mitigation** -- criteria are shuffled using a
  deterministic seed derived from the candidate and expected outputs.
* **Pairwise consistency check** -- optionally scores a reference output
  with swapped presentation order and flags criteria whose scores diverge
  by more than ``max_delta`` (default 1.0).
* **Strict output validation** -- the judge must return valid JSON matching
  ``{\"criteria\": [{\"name\", \"score\", \"evidence\"}]}``.  Schema
  violations raise ``ValueError``.
* **Calibration drift detection** -- :func:`evaluate_calibration_set` runs
  the judge against human-labeled fixtures and reports mean absolute error.

The judge is invoked synchronously via :func:`_run_coro_sync`, which
handles both active-event-loop and bare contexts.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import re
import threading
from dataclasses import dataclass, field
from hashlib import sha256
from typing import Any, Protocol

from ..models.client import LLMClientWrapper, get_client
from .normalization import normalize_score

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class JudgeCriterionDefinition:
    """Immutable definition of a single rubric criterion for judge prompts.

    Attributes:
        name: Criterion identifier (e.g., ``"correctness"``).
        definition: Human-readable description of what this criterion measures.
        scale: Mapping of score values (as strings) to anchor descriptions
            (e.g., ``{"1": "Major failures", "5": "Excellent"}``).
    """

    name: str
    definition: str = ""
    scale: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class JudgeCriterionScore:
    """Immutable score for a single criterion as returned by the judge.

    Attributes:
        name: Criterion name matching :attr:`JudgeCriterionDefinition.name`.
        raw_score: Judge-assigned score on the 1--5 Likert scale.
        normalized_score: Score mapped to the [0, 1] range via
            ``normalize_score(raw, "likert_1_5")``.
        evidence: Free-text justification provided by the judge.
    """

    name: str
    raw_score: float
    normalized_score: float
    evidence: str


@dataclass(frozen=True)
class JudgeEvaluationResult:
    """Immutable bundle of all judge outputs for one evaluation invocation.

    Attributes:
        criteria: Per-criterion scores and evidence.
        normalized_score: Average of all criterion normalized scores (0--1).
        model: LLM model identifier used for judging.
        model_version: Specific model version or revision string.
        prompt_version: Version tag of the judge prompt template.
        temperature: Sampling temperature used (clamped to [0.0, 0.1]).
        pairwise_consistent: True if the swapped-order consistency check
            passed, False if it failed, or None if not performed.
        inconsistency_reasons: List of criterion names that showed
            positional bias in the pairwise check.
    """

    criteria: list[JudgeCriterionScore]
    normalized_score: float
    model: str
    model_version: str
    prompt_version: str
    temperature: float
    pairwise_consistent: bool | None = None
    inconsistency_reasons: list[str] = field(default_factory=list)

    def to_payload(self) -> dict[str, Any]:
        return {
            "criteria": [
                {
                    "name": item.name,
                    "raw_score": round(item.raw_score, 4),
                    "normalized_score": round(item.normalized_score, 4),
                    "evidence": item.evidence,
                }
                for item in self.criteria
            ],
            "normalized_score": round(self.normalized_score, 4),
            "score": round(self.normalized_score * 100.0, 2),
            "model": self.model,
            "model_version": self.model_version,
            "prompt_version": self.prompt_version,
            "temperature": self.temperature,
            "pairwise_consistent": self.pairwise_consistent,
            "inconsistency_reasons": list(self.inconsistency_reasons),
        }


class JudgeResponseProvider(Protocol):
    """Protocol for pluggable judge backends, enabling test mocking.

    Implementations must accept ``prompt``, ``model``, and ``temperature``
    keyword arguments and return either a parsed dict or a raw JSON string.
    """

    def __call__(
        self, *, prompt: str, model: str, temperature: float
    ) -> dict[str, Any] | str: ...


def _stable_seed(*parts: str) -> int:
    """Derive a deterministic integer seed from string parts via SHA-256.

    Args:
        *parts: Strings concatenated with ``||`` before hashing.

    Returns:
        32-bit unsigned integer derived from the first 8 hex digits.
    """
    value = "||".join(parts)
    digest = sha256(value.encode("utf-8")).hexdigest()
    return int(digest[:8], 16)


def _extract_first_json_object(raw: str) -> dict[str, Any]:
    """Extract and parse the first JSON object from a raw LLM response string.

    Handles responses that may include markdown fences or preamble text
    before the JSON payload.

    Args:
        raw: Raw string output from the LLM.

    Returns:
        Parsed JSON dict.

    Raises:
        ValueError: If the string is empty or contains no JSON object.
    """
    raw = raw.strip()
    if not raw:
        raise ValueError("Judge returned empty output")

    if raw.startswith("{"):
        return json.loads(raw)

    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        raise ValueError("Judge output did not contain a JSON object")
    return json.loads(match.group(0))


def validate_judge_structured_output(
    payload: dict[str, Any],
    *,
    expected_criteria: set[str] | None = None,
) -> tuple[bool, list[str]]:
    """Validate that a judge response conforms to the expected schema.

    Checks that ``criteria`` is a non-empty list of dicts, each containing
    ``name`` (non-empty string), ``score`` (numeric, 1--5), and ``evidence``
    (string).  Optionally verifies that all ``expected_criteria`` names
    are present.

    Args:
        payload: Parsed JSON dict from the judge.
        expected_criteria: If provided, the set of criterion names that
            must appear in the response.

    Returns:
        A 2-tuple of ``(is_valid, error_messages)``.
    """
    if not isinstance(payload, dict):
        return False, ["payload must be a mapping"]

    errors: list[str] = []
    criteria = payload.get("criteria")
    if not isinstance(criteria, list) or not criteria:
        errors.append("criteria must be a non-empty list")
    else:
        seen: set[str] = set()
        for idx, item in enumerate(criteria):
            errors.extend(_validate_judge_criterion_item(idx, item, seen))

        if expected_criteria:
            missing = sorted(expected_criteria - seen)
            if missing:
                errors.append(f"missing criteria: {', '.join(missing)}")

    return len(errors) == 0, errors


def _validate_judge_criterion_item(
    idx: int,
    item: Any,
    seen: set[str],
) -> list[str]:
    """Validate one judge criterion entry, recording its name in ``seen``.

    Args:
        idx: Index of the entry within the ``criteria`` list (for messages).
        item: The raw criterion entry to validate.
        seen: Mutable set of valid criterion names collected so far.

    Returns:
        A list of validation error messages (empty when the entry is valid).
    """
    if not isinstance(item, dict):
        return [f"criteria[{idx}] must be an object"]

    errors: list[str] = []
    for required in ("name", "score", "evidence"):
        if required not in item:
            errors.append(f"criteria[{idx}] missing key: {required}")

    name = item.get("name")
    if not isinstance(name, str) or not name.strip():
        errors.append(f"criteria[{idx}].name must be non-empty string")
    else:
        seen.add(name.strip())

    score = item.get("score")
    if not isinstance(score, (int, float)):
        errors.append(f"criteria[{idx}].score must be numeric")
    elif float(score) < 1.0 or float(score) > 5.0:
        errors.append(f"criteria[{idx}].score must be in [1, 5]")

    evidence = item.get("evidence")
    if not isinstance(evidence, str):
        errors.append(f"criteria[{idx}].evidence must be string")

    return errors


def check_swapped_order_consistency(
    forward_payload: dict[str, Any],
    swapped_payload: dict[str, Any],
    *,
    max_delta: float = 1.0,
) -> tuple[bool, list[str]]:
    """Detect positional bias by comparing forward and swapped-order judge scores.

    For each criterion present in both payloads, checks whether the
    absolute score difference exceeds ``max_delta``.

    Args:
        forward_payload: Judge output from the original presentation order.
        swapped_payload: Judge output with candidate and reference swapped.
        max_delta: Maximum tolerated score difference per criterion.

    Returns:
        A 2-tuple of ``(is_consistent, list_of_inconsistent_criterion_names)``.
    """
    forward = {
        str(item.get("name")): float(item.get("score"))
        for item in forward_payload.get("criteria", [])
        if isinstance(item, dict) and item.get("name") is not None
    }
    swapped = {
        str(item.get("name")): float(item.get("score"))
        for item in swapped_payload.get("criteria", [])
        if isinstance(item, dict) and item.get("name") is not None
    }

    inconsistent: list[str] = []
    for name in sorted(set(forward.keys()) & set(swapped.keys())):
        if abs(forward[name] - swapped[name]) > max_delta:
            inconsistent.append(name)
    return len(inconsistent) == 0, inconsistent


def evaluate_calibration_set(
    *,
    judge: "LLMJudge",
    fixtures: list[dict[str, Any]],
    tolerance: float = 0.5,
) -> dict[str, Any]:
    """Evaluate judge calibration drift against human-labeled fixtures.

    Runs the judge on each fixture and computes the mean absolute error
    (MAE) between judge-assigned and human-assigned raw scores across
    all criteria.

    Args:
        judge: The :class:`LLMJudge` instance to evaluate.
        fixtures: List of calibration fixture dicts, each containing
            ``candidate_output``, ``expected_output``, ``criteria``,
            and ``human_scores`` (mapping criterion name to float).
        tolerance: Maximum acceptable MAE.

    Returns:
        Dict with ``samples``, ``mae``, ``within_tolerance``, and
        ``tolerance`` keys.
    """
    deltas: list[float] = []

    for fixture in fixtures:
        criteria = fixture.get("criteria", [])
        human_scores = fixture.get("human_scores", {})
        result = judge.evaluate(
            candidate_output=str(fixture.get("candidate_output", "")),
            expected_output=str(fixture.get("expected_output", "")),
            criteria=criteria,
        )
        for criterion in result.criteria:
            if criterion.name in human_scores:
                deltas.append(
                    abs(criterion.raw_score - float(human_scores[criterion.name]))
                )

    mae = (sum(deltas) / len(deltas)) if deltas else 0.0
    return {
        "samples": len(fixtures),
        "mae": round(mae, 4),
        "within_tolerance": mae <= tolerance,
        "tolerance": tolerance,
    }


def _run_coro_sync(coro: Any) -> Any:
    """Run an async coroutine from a synchronous context.

    If no event loop is running, uses ``asyncio.run()``.  If an event
    loop is already active (e.g., inside a FastAPI request handler),
    spawns a daemon thread with its own ``asyncio.run()`` to avoid
    nested-loop errors.

    Args:
        coro: The awaitable coroutine to execute.

    Returns:
        The coroutine's return value.

    Raises:
        Exception: Re-raises any exception from the coroutine.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    result_event = threading.Event()
    box: dict[str, Any] = {}

    def _runner() -> None:
        try:
            box["value"] = asyncio.run(coro)
        except Exception as exc:  # pragma: no cover - thread error path
            box["error"] = exc
        finally:
            result_event.set()

    thread = threading.Thread(target=_runner, daemon=True)
    thread.start()
    result_event.wait()
    if "error" in box:
        raise box["error"]
    return box.get("value")


class LLMJudge:
    """Bias-aware LLM-as-Judge evaluator with strict output validation.

    Wraps an LLM backend to score candidate outputs against anchored
    rubric criteria on a 1--5 Likert scale.  Includes positional-bias
    mitigation via deterministic criterion shuffling and optional
    pairwise consistency checking.

    Attributes:
        model: LLM model identifier (e.g., ``"gh:openai/gpt-4o"``).
        model_version: Specific model version string.
        prompt_version: Version tag of the judge prompt template.
        temperature: Sampling temperature, clamped to [0.0, 0.1].
        max_tokens: Maximum tokens for the judge response.
    """

    def __init__(
        self,
        *,
        model: str = "gh:openai/gpt-4o",
        model_version: str | None = None,
        prompt_version: str = "judge-v1",
        temperature: float = 0.1,
        max_tokens: int = 1200,
        client: LLMClientWrapper | None = None,
        response_provider: JudgeResponseProvider | None = None,
    ) -> None:
        self.model = model
        self.model_version = model_version or model
        self.prompt_version = prompt_version
        self.temperature = min(max(float(temperature), 0.0), 0.1)
        self.max_tokens = max_tokens
        self._client = client
        self._response_provider = response_provider

    def evaluate(
        self,
        *,
        candidate_output: str,
        criteria: list[JudgeCriterionDefinition] | list[dict[str, Any]],
        expected_output: str = "",
        pairwise_reference_output: str | None = None,
        seed: int | None = None,
    ) -> JudgeEvaluationResult:
        """Score candidate output using anchored 1..5 criteria."""
        normalized_criteria = [
            (
                item
                if isinstance(item, JudgeCriterionDefinition)
                else JudgeCriterionDefinition(
                    name=str(item.get("name")),
                    definition=str(item.get("definition", "")),
                    scale={
                        str(key): str(value)
                        for key, value in (item.get("scale") or {}).items()
                    },
                )
            )
            for item in criteria
        ]
        if not normalized_criteria:
            raise ValueError("Judge criteria cannot be empty")

        eval_seed = (
            seed
            if seed is not None
            else _stable_seed(candidate_output, expected_output, self.prompt_version)
        )
        rng = random.Random(eval_seed)
        shuffled_criteria = list(normalized_criteria)
        rng.shuffle(shuffled_criteria)

        prompt = self._build_prompt(
            candidate_output=candidate_output,
            expected_output=expected_output,
            criteria=shuffled_criteria,
            pairwise_reference_output=pairwise_reference_output,
        )
        forward_payload = self._invoke_prompt(prompt)

        expected_names = {item.name for item in normalized_criteria}
        ok, errors = validate_judge_structured_output(
            forward_payload, expected_criteria=expected_names
        )
        if not ok:
            raise ValueError(f"Judge output schema invalid: {', '.join(errors)}")

        pairwise_consistent: bool | None = None
        inconsistency_reasons: list[str] = []
        if pairwise_reference_output is not None:
            swapped_prompt = self._build_prompt(
                candidate_output=pairwise_reference_output,
                expected_output=expected_output,
                criteria=shuffled_criteria,
                pairwise_reference_output=candidate_output,
                swapped=True,
            )
            swapped_payload = self._invoke_prompt(swapped_prompt)
            pairwise_consistent, inconsistent = check_swapped_order_consistency(
                forward_payload,
                swapped_payload,
                max_delta=1.0,
            )
            inconsistency_reasons = [
                f"inconsistent_swapped_order:{criterion}" for criterion in inconsistent
            ]

        scores_by_name: dict[str, tuple[float, str]] = {}
        for item in forward_payload.get("criteria", []):
            name = str(item["name"])
            raw_score = float(item["score"])
            evidence = str(item.get("evidence", ""))
            scores_by_name[name] = (raw_score, evidence)

        criterion_scores: list[JudgeCriterionScore] = []
        for criterion in normalized_criteria:
            raw_score, evidence = scores_by_name.get(
                criterion.name, (3.0, "missing_from_response")
            )
            normalized_score = normalize_score(raw_score, "likert_1_5")
            criterion_scores.append(
                JudgeCriterionScore(
                    name=criterion.name,
                    raw_score=raw_score,
                    normalized_score=normalized_score,
                    evidence=evidence,
                )
            )

        overall = sum(item.normalized_score for item in criterion_scores) / len(
            criterion_scores
        )
        return JudgeEvaluationResult(
            criteria=criterion_scores,
            normalized_score=overall,
            model=self.model,
            model_version=self.model_version,
            prompt_version=self.prompt_version,
            temperature=self.temperature,
            pairwise_consistent=pairwise_consistent,
            inconsistency_reasons=inconsistency_reasons,
        )

    def _build_prompt(
        self,
        *,
        candidate_output: str,
        expected_output: str,
        criteria: list[JudgeCriterionDefinition],
        pairwise_reference_output: str | None = None,
        swapped: bool = False,
    ) -> str:
        rubric_lines: list[str] = []
        for criterion in criteria:
            anchors = ", ".join(f"{k}:{v}" for k, v in sorted(criterion.scale.items()))
            rubric_lines.append(
                f"- {criterion.name}\n"
                f"  definition: {criterion.definition or 'N/A'}\n"
                f"  anchors: {anchors or '1..5'}"
            )

        mode = "pairwise" if pairwise_reference_output is not None else "single"
        swapped_note = " (SWAPPED_ORDER)" if swapped else ""
        reference_block = (
            f"\nREFERENCE CANDIDATE{swapped_note}:\n{pairwise_reference_output}\n"
            if pairwise_reference_output is not None
            else ""
        )
        return (
            "You are a strict rubric judge. Return ONLY valid JSON.\n"
            'Schema: {"criteria":[{"name":"...","score":1-5,"evidence":"..."}]}\n'
            f"mode: {mode}\n"
            f"rubric:\n{chr(10).join(rubric_lines)}\n"
            f"\nEXPECTED OUTPUT:\n{expected_output}\n"
            f"\nCANDIDATE OUTPUT{swapped_note}:\n{candidate_output}\n"
            f"{reference_block}\n"
            "Score each criterion on anchored 1..5 scale."
        )

    def _invoke_prompt(self, prompt: str) -> dict[str, Any]:
        raw: dict[str, Any] | str
        if self._response_provider is not None:
            raw = self._response_provider(
                prompt=prompt,
                model=self.model,
                temperature=self.temperature,
            )
        else:
            client = self._client or get_client(auto_configure=False)
            if client.backend is None:
                raise RuntimeError("No LLM backend configured for judge")
            response, _, _ = _run_coro_sync(
                client.complete_chat(
                    model=self.model,
                    messages=[
                        {
                            "role": "system",
                            "content": "Return strict JSON only for rubric scoring.",
                        },
                        {"role": "user", "content": prompt},
                    ],
                    max_tokens=self.max_tokens,
                    temperature=self.temperature,
                )
            )
            raw = response.get("content", "")
            if isinstance(response, dict):
                model_version = response.get("model")
                if isinstance(model_version, str) and model_version.strip():
                    self.model_version = model_version

        payload: dict[str, Any]
        if isinstance(raw, dict):
            payload = raw
        else:
            payload = _extract_first_json_object(raw)
        logger.debug("Judge payload keys: %s", sorted(payload.keys()))
        return payload
