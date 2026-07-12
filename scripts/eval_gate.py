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
    0  All cases passed at or above threshold (or ``--live`` was skipped for
       lack of provider credentials -- see below).
    1  One or more cases failed, or a dataset/golden load error occurred.

``--live`` mode
----------------
``--live`` replaces the mocked golden-file comparison with a REAL run of each
case's workflow through ``agentic_v2.workflows.run_workflow`` (the platform's
existing engine, itself backed by ``SmartModelRouter`` / the shared model
client). Each case runs 3x and the MEDIAN of the 3 ``weighted_score`` values is
used, to damp single-call variance from a live model -- a single unlucky or
lucky sample never flips the gate on its own.

``--live`` degrades cleanly rather than crashing: if ``AGENTIC_NO_LLM`` is
truthy, or none of the canonical provider key env vars (``ANTHROPIC_API_KEY``,
``OPENAI_API_KEY``, ``GEMINI_API_KEY``, ``AZURE_OPENAI_API_KEY``,
``AZURE_FOUNDRY_API_KEY``) are CONFIGURED, the gate prints a clear message and
exits 0 (collected-but-skipped) without importing ``agentic_v2`` or attempting
a call -- it never fails a run merely for lacking a key. This is a presence
check, not a validity check (it does not authenticate the key), and it reads
through the platform's own secret resolver, which also honours a ``.env``
file -- a repo with a stale/expired key in ``.env`` will NOT be classified as
"no key" and --live will proceed to call the real provider(s), surfacing
their errors per-run rather than as a skip. Never run --live ad hoc against an
unknown environment's credentials; ARP-4's label/nightly CI gating (not this
presence check) is the actual guard against invoking it unintentionally. The
mocked path above is completely unaffected by ``--live``; it remains the
every-commit, key-free floor.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
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

# Canonical cloud-provider API key env vars this platform recognises (mirrors
# agentic_v2.models.backends._register_cloud_backends). --live is skipped,
# never crashed, when none of these are configured -- see NoProviderConfiguredError
# in agentic_v2.core.errors for the same message shown to interactive users.
_LIVE_PROVIDER_KEY_NAMES = (
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "GEMINI_API_KEY",
    "AZURE_OPENAI_API_KEY",
    "AZURE_FOUNDRY_API_KEY",
)

# Number of independent live runs per case; the gate scores the MEDIAN
# weighted_score across these to damp single-call variance from a real model.
_LIVE_RUNS_PER_CASE = 3


def _load_json(path: Path) -> Any:
    """Load and return parsed JSON from ``path``."""
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _safe_float(value: Any, default: float = 0.0) -> float:
    """Coerce a possibly-null / non-numeric JSON value to float; ``default`` on
    failure."""
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def derive_criteria(golden: dict[str, Any], case: dict[str, Any]) -> dict[str, float]:
    """Derive ``code`` rubric criterion floats from a golden workflow result.

    Pure, deterministic, key-free. Criterion names match ``rubrics/code.yaml``:
    Correctness, Completeness, Code Quality, Efficiency, Security. All values
    are normalized to ``[0.0, 1.0]``.
    """
    # Defensive throughout: a golden may be malformed (null/wrong-typed fields).
    # The gate must fail with a clear score, never a traceback.
    expected_criteria = case.get("expected_criteria")
    if not isinstance(expected_criteria, dict):
        expected_criteria = {}

    raw_steps = golden.get("steps")
    steps: list[dict[str, Any]] = [
        s
        for s in (raw_steps if isinstance(raw_steps, list) else [])
        if isinstance(s, dict)
    ]

    # Correctness -- normalized step success rate.
    correctness = _safe_float(golden.get("success_rate")) / 100.0

    # Completeness -- fraction of expected steps that completed as "success".
    raw_names = expected_criteria.get("expected_step_names")
    expected_names = (
        tuple(raw_names)
        if isinstance(raw_names, (list, tuple))
        else _DEFAULT_EXPECTED_STEPS
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
        output_data = parse_step.get("output_data")
        metrics = (
            output_data.get("code_metrics") if isinstance(output_data, dict) else None
        )
        if isinstance(metrics, dict):
            present = _REQUIRED_METRIC_KEYS & metrics.keys()
            code_quality = len(present) / len(_REQUIRED_METRIC_KEYS)

    # Efficiency -- retry penalty. 0 retries -> 1.0; degrade linearly toward
    # max_retries + 1. Both clamped to >= 0 so a malformed negative value can't
    # make retry_budget 0 and divide by zero.
    total_retries = max(0, int(_safe_float(golden.get("total_retries"))))
    retry_budget = max(0, int(_safe_float(expected_criteria.get("max_retries")))) + 1
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


def _error_result(case_id: str, threshold: float, message: str) -> dict[str, Any]:
    """Build the common failure-shaped result dict for a case that can't be scored."""
    return {
        "case_id": case_id,
        "passed": False,
        "error": message,
        "weighted_score": 0.0,
        "threshold": threshold,
        "missing_criteria": [],
        "criterion_scores": {},
    }


def _resolve_case_threshold(case: dict[str, Any], global_threshold: float) -> float:
    """Resolve the effective pass threshold for a case.

    Both bars must clear: the global (``--threshold``) and the case's own bar.
    The global can tighten a case but never loosen it below its committed
    value -- so a case's own ``threshold`` field can only ever raise the bar
    relative to what ``--threshold`` passes on the command line.
    """
    case_threshold = case.get("threshold")
    try:
        return (
            global_threshold
            if case_threshold is None
            else max(global_threshold, float(case_threshold))
        )
    except (TypeError, ValueError):
        return global_threshold


def _score_criteria(
    case_id: str,
    rubric_name: str,
    criteria: dict[str, float],
    threshold: float,
) -> dict[str, Any]:
    """Score already-derived criteria against ``rubric_name`` and assemble a result.

    Shared tail for both the mocked (golden-file) and ``--live`` (real-model)
    paths -- both produce a ``criteria`` dict via :func:`derive_criteria` and
    hand it here so the ``Scorer`` invocation and pass/fail assembly are never
    duplicated.
    """
    scorer = Scorer(load_rubric(rubric_name))
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


def score_case(
    case: dict[str, Any], cases_dir: Path, global_threshold: float
) -> dict[str, Any]:
    """Score a single dataset case against its committed golden file.

    Mocked path: no LLM, no network. Behavior is unchanged by ``--live``.
    """
    if not isinstance(case, dict):
        return _error_result(
            "<invalid>",
            global_threshold,
            f"case is not a JSON object: {type(case).__name__}",
        )

    case_id = str(case.get("case_id", "<unnamed>"))
    rubric_name = str(case.get("rubric", "code"))
    threshold = _resolve_case_threshold(case, global_threshold)

    golden_path = Path(case.get("golden_output_path", ""))
    if not golden_path.is_absolute():
        golden_path = (cases_dir / golden_path).resolve()

    if not golden_path.exists():
        return _error_result(
            case_id, threshold, f"golden file not found: {golden_path}"
        )

    try:
        golden = _load_json(golden_path)
    except (json.JSONDecodeError, OSError) as err:
        return _error_result(
            case_id, threshold, f"failed to load or parse golden file: {err}"
        )
    if not isinstance(golden, dict):
        return _error_result(
            case_id, threshold, f"golden file is not a JSON object: {golden_path}"
        )

    criteria = derive_criteria(golden, case)
    return _score_criteria(case_id, rubric_name, criteria, threshold)


def _has_live_provider_credentials() -> bool:
    """Return True when a real cloud-provider API key is CONFIGURED (present).

    This is a presence check, not a validity check -- it does not verify the
    key actually authenticates. Deliberately checks the environment directly
    (via the platform's own ``get_secret`` resolver, so any configured
    ``SecretProvider`` chain -- including a ``.env`` file -- not just raw
    process env vars, is honoured) rather than attempting a live model call
    and catching the failure: --live must never depend on network behavior to
    decide whether to run at all. If a configured key is stale/invalid,
    per-run failures inside :func:`score_case_live`'s try/except still report
    cleanly rather than crash; they just won't be classified as
    "skipped for lack of a key" -- see ARP-4's label/nightly CI gating for the
    actual guard against running --live unintentionally.
    """
    from agentic_v2.models.secrets import get_secret

    return any(get_secret(name) for name in _LIVE_PROVIDER_KEY_NAMES)


async def score_case_live(
    case: dict[str, Any], global_threshold: float
) -> dict[str, Any]:
    """Score a single dataset case by running its workflow against a REAL model.

    Runs ``case['workflow_name']`` with ``case['live_inputs']`` through the
    platform's existing engine (``agentic_v2.workflows.run_workflow``, backed by
    ``SmartModelRouter`` / the shared model client) ``_LIVE_RUNS_PER_CASE`` times
    and scores the MEDIAN ``weighted_score`` across the runs, to damp
    single-call variance from a live model. Uses the exact same
    :func:`derive_criteria` + :func:`_score_criteria` path as the mocked gate,
    so the two are directly comparable.

    Never calls a real provider itself -- that happens inside
    ``run_workflow``/the model client, gated by :func:`_has_live_provider_credentials`
    at the call site in :func:`main`.
    """
    from agentic_v2.workflows import run_workflow

    if not isinstance(case, dict):
        return _error_result(
            "<invalid>",
            global_threshold,
            f"case is not a JSON object: {type(case).__name__}",
        )

    case_id = str(case.get("case_id", "<unnamed>"))
    rubric_name = str(case.get("rubric", "code"))
    threshold = _resolve_case_threshold(case, global_threshold)

    workflow_name = case.get("workflow_name")
    if not isinstance(workflow_name, str) or not workflow_name:
        return _error_result(
            case_id, threshold, "case is missing a string 'workflow_name'"
        )

    live_inputs = case.get("live_inputs")
    if live_inputs is None:
        live_inputs = {}
    if not isinstance(live_inputs, dict):
        return _error_result(
            case_id, threshold, "case 'live_inputs' must be a JSON object"
        )

    scorer = Scorer(load_rubric(rubric_name))
    per_run: list[ScoringResult] = []
    for run_index in range(_LIVE_RUNS_PER_CASE):
        try:
            live_result = await run_workflow(workflow_name, **live_inputs)
        except Exception as err:
            # Deliberately broad: a live model call can fail in arbitrarily
            # many provider-specific ways (timeouts, rate limits, malformed
            # responses); the gate must report which run failed rather than
            # crash the whole dataset scoring loop.
            return _error_result(
                case_id,
                threshold,
                f"live run {run_index + 1}/{_LIVE_RUNS_PER_CASE} of "
                f"'{workflow_name}' failed: {err}",
            )
        golden = live_result.model_dump(mode="json")
        criteria = derive_criteria(golden, case)
        per_run.append(scorer.score(criteria))

    # The MEDIAN weighted_score across the _LIVE_RUNS_PER_CASE runs, to damp
    # single-call variance from a live model.
    run_scores = [r.weighted_score for r in per_run]
    median_score = statistics.median(run_scores)

    # Report the criterion breakdown from the run that produced the median
    # score, so criterion_scores/missing_criteria trace back to an actual
    # observed run rather than an interpolated, never-observed blend. For the
    # odd run count this module always uses, statistics.median() returns one
    # of the sampled values exactly, so this lookup always finds a match.
    median_result = next(
        (r for r in per_run if r.weighted_score == median_score), per_run[0]
    )

    missing = list(median_result.missing_criteria)
    return {
        "case_id": case_id,
        "rubric": rubric_name,
        "weighted_score": median_score,
        "total_score": median_result.total_score,
        "criterion_scores": median_result.criterion_scores,
        "missing_criteria": missing,
        "threshold": threshold,
        "passed": not missing and median_score >= threshold,
        "error": None,
        "live_run_scores": run_scores,
    }


async def _score_all_live(
    cases: list[dict[str, Any]], threshold: float
) -> list[dict[str, Any]]:
    """Score every case in ``cases`` via :func:`score_case_live`, sequentially.

    Sequential (not ``asyncio.gather``) is deliberate: live runs consume real
    provider rate limits / spend, and a clear per-case progress log is more
    useful than concurrent, interleaved output for a gate a human will read
    when it fails.
    """
    results = []
    for case in cases:
        results.append(await score_case_live(case, threshold))
    return results


def _report_and_exit(scored: list[dict[str, Any]], global_threshold: float) -> int:
    """Print the per-case + aggregate report shared by the mocked and --live paths, and
    return the process exit code (0 pass, 1 fail)."""
    any_failed = False
    for result in scored:
        status = "PASS" if result["passed"] else "FAIL"
        print(
            f"[{status}] {result['case_id']}  "
            f"score={result['weighted_score']:.4f}  "
            f"threshold={result['threshold']:.4f}"
        )
        if result.get("live_run_scores"):
            formatted = ", ".join(f"{s:.4f}" for s in result["live_run_scores"])
            print(f"       live run scores (median reported above): [{formatted}]")
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
        f"(global threshold: {global_threshold:.4f})"
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


def main(argv: list[str] | None = None) -> int:
    """Entry point.

    Returns 0 (all cases pass, or --live was skipped for lack of
    provider credentials) or 1 (any fail / load error).
    """
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
    parser.add_argument(
        "--live",
        action="store_true",
        help=(
            "Run each case's workflow against a REAL model "
            f"({_LIVE_RUNS_PER_CASE}x per case, scored by median weighted_score) "
            "instead of comparing to the committed golden file. Requires a "
            "configured provider API key and AGENTIC_NO_LLM unset/false; "
            "otherwise this gate is collected-but-skipped (exit 0) rather than "
            "failing for lack of a key. The mocked path (no --live) is "
            "completely unaffected and remains the every-commit, key-free floor."
        ),
    )
    args = parser.parse_args(argv)

    cases_path: Path = args.cases.resolve()
    if not cases_path.exists():
        print(f"ERROR: cases file not found: {cases_path}", file=sys.stderr)
        return 1

    try:
        loaded = _load_json(cases_path)
    except (json.JSONDecodeError, OSError) as err:
        print(f"ERROR: failed to load or parse cases file: {err}", file=sys.stderr)
        return 1
    if not isinstance(loaded, list) or not loaded:
        print(
            f"ERROR: dataset must be a non-empty JSON list: {cases_path}",
            file=sys.stderr,
        )
        return 1

    if args.live:
        from agentic_v2.settings import is_agentic_no_llm_enabled

        if is_agentic_no_llm_enabled():
            print(
                "SKIPPED: --live requested but AGENTIC_NO_LLM is set -- refusing "
                "to run a 'live' gate against the placeholder backend. Unset "
                "AGENTIC_NO_LLM (and configure a provider key) to run this gate "
                "for real.",
            )
            return 0
        if not _has_live_provider_credentials():
            key_list = ", ".join(_LIVE_PROVIDER_KEY_NAMES)
            print(
                "SKIPPED: --live requested but no provider API key is configured "
                f"(checked: {key_list}). This is expected in environments with no "
                "credentials -- the mocked eval-golden-gate remains the "
                "every-commit floor; this --live gate is collected-but-skipped, "
                "not failed.",
            )
            return 0

        print(
            f"--live: running {len(loaded)} case(s) x {_LIVE_RUNS_PER_CASE} "
            "against a real model (this calls a real provider and consumes "
            "real spend)."
        )
        scored = asyncio.run(_score_all_live(loaded, args.threshold))
        return _report_and_exit(scored, args.threshold)

    cases_dir = cases_path.parent
    scored = [score_case(case, cases_dir, args.threshold) for case in loaded]
    return _report_and_exit(scored, args.threshold)


if __name__ == "__main__":
    sys.exit(main())
