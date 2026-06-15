#!/usr/bin/env python3
"""Deterministic, key-free scored-eval CI gate over a committed golden dataset.

Audit FIX #3. Reads a committed dataset manifest (e.g.
``datasets/default/golden_cases.json``), and for each case:

1. loads the referenced golden workflow-result JSON,
2. deterministically derives the rubric's criterion floats from stable
   structural fields (no LLM, no network, no wall-clock, no ids),
3. scores them with the real ``agentic_v2_eval`` ``Scorer`` + ``load_rubric``,
4. asserts every rubric criterion was supplied (``missing_criteria == []`` is a
   hard fail -- a missing/typo'd criterion silently shrinks the denominator in
   ``Scorer.score`` rather than lowering the score, so we guard it explicitly),
5. compares ``weighted_score`` to the per-case / global threshold.

Exits non-zero when any case scores below threshold, leaks a rubric criterion,
or cannot be loaded. Safe to run with ``AGENTIC_NO_LLM=1`` and zero credentials;
the scoring path never constructs a model.

Usage::

    AGENTIC_NO_LLM=1 python scripts/eval_gate.py \\
        --cases datasets/default/golden_cases.json --threshold 0.80

Exit codes:
    0  All cases passed at or above threshold.
    1  One or more cases failed, or a dataset/golden load error occurred.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from agentic_v2_eval.rubrics import load_rubric
from agentic_v2_eval.scorer import Scorer, ScoringResult

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_CASES = _REPO_ROOT / "datasets" / "default" / "golden_cases.json"
_DEFAULT_THRESHOLD = 0.80

# Required code_metrics keys that the parse_code step must expose. Code Quality
# scores on key PRESENCE (schema), not value magnitude -- the golden's metrics
# are legitimately 0 for empty input code.
_REQUIRED_METRIC_KEYS = frozenset(
    {"chars", "lines", "function_count", "class_count", "import_count"}
)

# Default expected step names for the code_review workflow, overridable per case
# via expected_criteria.expected_step_names.
_DEFAULT_EXPECTED_STEPS = (
    "parse_code",
    "style_check",
    "complexity_analysis",
    "review_code",
    "generate_summary",
)


def _load_json(path: Path) -> Any:
    """Load and return parsed JSON from ``path``."""
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def derive_criteria(golden: dict[str, Any], case: dict[str, Any]) -> dict[str, float]:
    """Derive ``code`` rubric criterion floats from a golden workflow result.

    Pure, deterministic, key-free. Criterion names match ``rubrics/code.yaml``:
    Correctness, Completeness, Code Quality, Efficiency, Security. All values
    are normalized to ``[0.0, 1.0]``.
    """
    expected_criteria = case.get("expected_criteria", {})
    steps: list[dict[str, Any]] = [
        s for s in golden.get("steps", []) if isinstance(s, dict)
    ]

    # Correctness -- normalized step success rate.
    correctness = float(golden.get("success_rate", 0.0)) / 100.0

    # Completeness -- fraction of expected steps that completed as "success".
    expected_names = tuple(
        expected_criteria.get("expected_step_names", _DEFAULT_EXPECTED_STEPS)
    )
    succeeded = {s.get("step_name") for s in steps if s.get("status") == "success"}
    completeness = (
        sum(1 for name in expected_names if name in succeeded) / len(expected_names)
        if expected_names
        else 0.0
    )

    # Code Quality -- fraction of required code_metrics keys present on parse_code.
    parse_step = next((s for s in steps if s.get("step_name") == "parse_code"), None)
    code_quality = 0.0
    if parse_step is not None:
        metrics = parse_step.get("output_data", {}).get("code_metrics", {})
        if isinstance(metrics, dict):
            present = _REQUIRED_METRIC_KEYS & metrics.keys()
            code_quality = len(present) / len(_REQUIRED_METRIC_KEYS)

    # Efficiency -- retry penalty. 0 retries -> 1.0; degrade linearly toward
    # max_retries + 1 (so consuming the full retry budget scores 0.0).
    total_retries = int(golden.get("total_retries", 0))
    retry_budget = int(expected_criteria.get("max_retries", 0)) + 1
    efficiency = max(0.0, 1.0 - (total_retries / retry_budget))

    # Security -- 1.0 unless any step leaks a non-empty error_type. Tolerate the
    # key being absent or explicitly null (both mean "no error surfaced").
    has_error_leak = any(s.get("error_type") not in (None, "") for s in steps)
    security = 0.0 if has_error_leak else 1.0

    return {
        "Correctness": correctness,
        "Completeness": completeness,
        "Code Quality": code_quality,
        "Efficiency": efficiency,
        "Security": security,
    }


def score_case(
    case: dict[str, Any], cases_dir: Path, global_threshold: float
) -> dict[str, Any]:
    """Score a single dataset case and return a structured result dict."""
    case_id = str(case.get("case_id", "<unnamed>"))
    rubric_name = str(case.get("rubric", "code"))
    # Both bars must clear: the global (--threshold) and the case's own bar. The
    # global can tighten a case but never loosen it below its committed value.
    case_threshold = case.get("threshold")
    threshold = (
        global_threshold
        if case_threshold is None
        else max(global_threshold, float(case_threshold))
    )

    golden_path = Path(case.get("golden_output_path", ""))
    if not golden_path.is_absolute():
        golden_path = (cases_dir / golden_path).resolve()

    if not golden_path.exists():
        return {
            "case_id": case_id,
            "passed": False,
            "error": f"golden file not found: {golden_path}",
            "weighted_score": 0.0,
            "threshold": threshold,
            "missing_criteria": [],
            "criterion_scores": {},
        }

    golden = _load_json(golden_path)
    if not isinstance(golden, dict):
        return {
            "case_id": case_id,
            "passed": False,
            "error": f"golden file is not a JSON object: {golden_path}",
            "weighted_score": 0.0,
            "threshold": threshold,
            "missing_criteria": [],
            "criterion_scores": {},
        }

    scorer = Scorer(load_rubric(rubric_name))
    criteria = derive_criteria(golden, case)
    result: ScoringResult = scorer.score(criteria)

    # Guard the silent-skip footgun: every rubric criterion must be supplied.
    missing = list(result.missing_criteria)
    passed = not missing and result.weighted_score >= threshold

    return {
        "case_id": case_id,
        "rubric": rubric_name,
        "weighted_score": result.weighted_score,
        "total_score": result.total_score,
        "criterion_scores": result.criterion_scores,
        "missing_criteria": missing,
        "threshold": threshold,
        "passed": passed,
        "error": None,
    }


def main(argv: list[str] | None = None) -> int:
    """Entry point. Returns 0 (all cases pass) or 1 (any fail / load error)."""
    parser = argparse.ArgumentParser(
        prog="eval_gate",
        description=(
            "Deterministic, key-free scored-eval gate over a committed golden dataset."
        ),
    )
    parser.add_argument(
        "--cases",
        type=Path,
        default=_DEFAULT_CASES,
        help=(
            "Path to the dataset manifest JSON "
            "(default: datasets/default/golden_cases.json)."
        ),
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=_DEFAULT_THRESHOLD,
        dest="threshold",
        help=(
            "Global weighted_score pass threshold in [0, 1]; a case may override "
            f"it with its own 'threshold' field (default {_DEFAULT_THRESHOLD})."
        ),
    )
    args = parser.parse_args(argv)

    cases_path: Path = args.cases.resolve()
    if not cases_path.exists():
        print(f"ERROR: cases file not found: {cases_path}", file=sys.stderr)
        return 1

    loaded = _load_json(cases_path)
    if not isinstance(loaded, list) or not loaded:
        print(
            f"ERROR: dataset must be a non-empty JSON list: {cases_path}",
            file=sys.stderr,
        )
        return 1

    cases_dir = cases_path.parent
    scored = [score_case(case, cases_dir, args.threshold) for case in loaded]

    any_failed = False
    for result in scored:
        status = "PASS" if result["passed"] else "FAIL"
        print(
            f"[{status}] {result['case_id']}  "
            f"score={result['weighted_score']:.4f}  "
            f"threshold={result['threshold']:.4f}"
        )
        if result.get("error"):
            print(f"       error: {result['error']}", file=sys.stderr)
        if not result["passed"]:
            any_failed = True
            print(f"       criterion_scores: {result.get('criterion_scores', {})}")
            if result.get("missing_criteria"):
                print(
                    f"       missing criteria: {result['missing_criteria']}",
                    file=sys.stderr,
                )

    scores = [r["weighted_score"] for r in scored]
    aggregate = sum(scores) / len(scores) if scores else 0.0
    print(
        f"\nAggregate weighted_score: {aggregate:.4f}  "
        f"(global threshold: {args.threshold:.4f})"
    )

    if any_failed:
        print(
            "\nEVAL GATE FAILED -- one or more cases below threshold or missing "
            "criteria.",
            file=sys.stderr,
        )
        return 1

    print("\nEVAL GATE PASSED.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
