"""Decide which arm scored higher, honestly.

Three things happen here, in this order:

1. ``compare_runs`` is called on the two reports and is *expected to refuse*.
   ``target_name`` and ``target_fingerprint`` are non-waivable provenance
   fields (ADR-0015), and two different workflows are two different systems,
   so EvalKit raises ``IncompatibleRuns`` rather than reporting a delta. That
   refusal is printed rather than hidden: it is the library working. Giving
   both arms the same target name would slip a real difference past the gate,
   which is the one thing this whole harness exists to prevent.

2. A paired analysis over the sample ids both runs share -- the same
   arithmetic ``compare_runs`` performs internally, minus the same-system
   assumption it is entitled to make and we are not. McNemar's exact test on
   the discordant pairs, plus a paired bootstrap interval on the difference.

3. The cost side: wall-clock and step count per arm. An arm that wins by two
   points while spending four times the tokens has not won.

Usage:
    uv run python analyze.py
"""

from __future__ import annotations

import argparse
import json
import math
import random
import statistics
from datetime import datetime
from pathlib import Path
from typing import Any

KIT_ROOT = Path(__file__).resolve().parent
REPORTS_DIR = KIT_ROOT / "reports"

PASS_STATUSES = {"pass"}
#: Statuses that mean "the harness never delivered a verdict". Under ADR-0008
#: these are operational, and folding them into failures would understate an
#: arm whose infrastructure flaked.
NON_VERDICT = {"error", "unavailable", "abstain"}


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


class IncompatibleUnion(ValueError):
    """Reports asked to union describe different systems, not one system."""


#: Manifest fields that must agree across every report in one arm's union.
#: Each was verified constant within an arm across all seven campaign waves,
#: so a mismatch is a mistake rather than normal variation. ``target_name``
#: is the arm itself; ``timeout_seconds`` differs *between* arms (900 vs
#: 1200) but never within one.
UNION_IDENTITY_FIELDS = (
    "target_name",
    "grader",
    "adapter",
    "target_fingerprint",
    "sampling",
    "concurrency",
    "timeout_seconds",
)


def union_identity(report: dict[str, Any]) -> dict[str, Any]:
    """The manifest fields that decide whether two reports describe one system."""
    manifest = report.get("manifest") or {}
    return {field: manifest.get(field) for field in UNION_IDENTITY_FIELDS}


def merge_outcomes(paths: list[Path]) -> dict[str, dict[str, Any]]:
    """Union several reports for one arm, later paths winning on collision.

    A subset re-run supplements a full run rather than replacing it: when a
    broken oracle is fixed, only the cases it spoiled need re-executing, and
    those results supersede the earlier ones for the same sample ids. This is
    only sound because every run in the union shares an arm, a model, and a
    configuration -- it unions disjoint evidence about one system, it does not
    average two systems together.

    That precondition is now enforced rather than merely stated: a report
    whose identity fields disagree with the first raises
    :class:`IncompatibleUnion` instead of silently overwriting colliding
    sample ids and producing pass rates and significance statistics for a
    system that never ran.

    One half of the invariant is *not* checkable here: nothing in the report
    records the model. ``target_fingerprint`` and every sample's
    ``model_name`` are null across the whole campaign, so swapping the model
    between waves would pass this gate. The pinned ``CAMPAIGN`` block in
    ``tools/run_wave.py`` remains the only thing holding the model steady.
    """
    merged: dict[str, dict[str, Any]] = {}
    baseline: dict[str, Any] | None = None
    baseline_path: Path | None = None
    for path in paths:
        report = load(path)
        identity = union_identity(report)
        if baseline is None:
            baseline, baseline_path = identity, path
        elif identity != baseline:
            differing = sorted(
                field
                for field in UNION_IDENTITY_FIELDS
                if identity[field] != baseline[field]
            )
            details = "\n".join(
                f"    {field}: {baseline[field]!r} != {identity[field]!r}"
                for field in differing
            )
            raise IncompatibleUnion(
                f"refusing to union reports that describe different systems:\n"
                f"  {baseline_path}\n  {path}\n"
                f"  disagree on {', '.join(differing)}:\n{details}\n"
                f"  A union is only sound across runs of one arm at one "
                f"configuration; unioning these would overwrite colliding "
                f"sample ids and report statistics for a system that never ran."
            )
        merged.update(outcomes(report))
    return merged


def outcomes(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Map sample_id -> {passed, status, exec_status, metadata}."""
    result: dict[str, dict[str, Any]] = {}
    for sample in report.get("samples", []):
        sample_id = sample["sample"]["sample_id"]
        grade = sample.get("grade") or {}
        execution = sample.get("execution") or {}
        status = str(grade.get("status", "")).lower()
        result[sample_id] = {
            "passed": status in PASS_STATUSES,
            "verdict": status not in NON_VERDICT and bool(status),
            "status": status,
            "exec_status": str(execution.get("status", "")).lower(),
            "score": grade.get("score"),
            "metadata": sample["sample"].get("metadata") or {},
        }
    return result


def wilson(successes: int, total: int) -> tuple[float, float]:
    """95% Wilson interval -- the honest interval at small n."""
    if total == 0:
        return (0.0, 0.0)
    z = 1.959963984540054
    phat = successes / total
    denominator = 1 + z * z / total
    centre = (phat + z * z / (2 * total)) / denominator
    margin = (
        z
        * math.sqrt(phat * (1 - phat) / total + z * z / (4 * total * total))
        / denominator
    )
    return (max(0.0, centre - margin), min(1.0, centre + margin))


def mcnemar_exact(b: int, c: int) -> float:
    """Two-sided exact McNemar p-value on the discordant pairs.

    *b* = cases only arm A solved, *c* = cases only arm B solved. Concordant
    pairs carry no information about which arm is better and are excluded --
    that exclusion is the whole point of a paired test.
    """
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    tail = sum(math.comb(n, i) for i in range(0, k + 1)) / (2**n)
    return min(1.0, 2 * tail)


def paired_bootstrap(
    deltas: list[int], samples: int = 10000, seed: int = 20260827
) -> tuple[float, float]:
    if not deltas:
        return (0.0, 0.0)
    rng = random.Random(seed)
    size = len(deltas)
    means = []
    for _ in range(samples):
        means.append(
            statistics.fmean(deltas[rng.randrange(size)] for _ in range(size))
        )
    means.sort()
    return (means[int(0.025 * samples)], means[int(0.975 * samples)])


def provenance_check(left_path: Path, right_path: Path) -> None:
    """Ask EvalKit to compare the runs and report what it says."""
    try:
        from agentic_evalkit.errors import IncompatibleRuns
        from agentic_evalkit.models import EvalRunResult
        from agentic_evalkit.stats.compare import compare_runs
    except ImportError as error:  # pragma: no cover - diagnostic path
        print(f"  (agentic_evalkit not importable here: {error})")
        return

    # JsonReporter adds presentation-only keys (generated_at, provenance) that
    # EvalRunResult forbids under extra="forbid". Drop them before validating;
    # they are derived from fields the model already carries.
    reporter_only = ("generated_at", "provenance")
    left = EvalRunResult.model_validate(
        {k: v for k, v in load(left_path).items() if k not in reporter_only}
    )
    right = EvalRunResult.model_validate(
        {k: v for k, v in load(right_path).items() if k not in reporter_only}
    )
    try:
        comparison = compare_runs(left, right, seed=20260827)
    except IncompatibleRuns as error:
        print("  compare_runs REFUSED, as designed:")
        print(f"    {error}")
        print(
            "  Two workflows are two systems. The paired analysis below is the\n"
            "  honest read; renaming a target to satisfy this gate would not be."
        )
        return
    print(f"  compare_runs accepted: difference={comparison.difference:+.3f}")


def summarise(name: str, data: dict[str, dict[str, Any]]) -> None:
    total = len(data)
    passed = sum(1 for row in data.values() if row["passed"])
    non_verdict = sum(1 for row in data.values() if not row["verdict"])
    low, high = wilson(passed, total)
    print(
        f"  {name:<22} {passed}/{total} = {passed / total:6.1%}  "
        f"[95% CI {low:.1%} - {high:.1%}]   non-verdict: {non_verdict}"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--left",
        action="append",
        default=None,
        help="arm A report; repeat to union a subset re-run over the full run",
    )
    parser.add_argument(
        "--right", action="append", default=None, help="arm B report; repeatable"
    )
    args = parser.parse_args()

    left_paths = [Path(p) for p in (args.left or [str(REPORTS_DIR / "arm-a-direct.json")])]
    right_paths = [
        Path(p) for p in (args.right or [str(REPORTS_DIR / "arm-b-review-loop.json")])
    ]
    for path in (*left_paths, *right_paths):
        if not path.is_file():
            print(f"missing report: {path}")
            return 1

    left_path, right_path = left_paths[0], right_paths[0]
    left_report, right_report = load(left_path), load(right_path)
    try:
        left, right = merge_outcomes(left_paths), merge_outcomes(right_paths)
    except IncompatibleUnion as error:
        print(f"\n{error}")
        return 1
    if len(left_paths) > 1 or len(right_paths) > 1:
        print(
            f"\n(unioned {len(left_paths)} report(s) for A, "
            f"{len(right_paths)} for B -- later runs supersede earlier ones "
            f"for the same sample id)"
        )

    print("=" * 74)
    print("SWE-fix A/B: Arm A (direct) vs Arm B (review loop)")
    print("=" * 74)

    print("\nPass rate")
    summarise("A: swe_fix_direct", left)
    summarise("B: swe_fix_review_loop", right)

    print("\nEvalKit's own comparability gate")
    provenance_check(left_path, right_path)

    shared = sorted(set(left) & set(right))
    both = sum(1 for s in shared if left[s]["passed"] and right[s]["passed"])
    only_a = sum(1 for s in shared if left[s]["passed"] and not right[s]["passed"])
    only_b = sum(1 for s in shared if right[s]["passed"] and not left[s]["passed"])
    neither = len(shared) - both - only_a - only_b

    print(f"\nPaired outcomes over {len(shared)} shared cases")
    print(f"  both solved .......... {both}")
    print(f"  only A solved ........ {only_a}")
    print(f"  only B solved ........ {only_b}")
    print(f"  neither solved ....... {neither}")

    deltas = [
        int(right[s]["passed"]) - int(left[s]["passed"]) for s in shared
    ]
    observed = statistics.fmean(deltas) if deltas else 0.0
    low, high = paired_bootstrap(deltas)
    p_value = mcnemar_exact(only_a, only_b)

    # Operational context only. `passed` is False for error/unavailable/
    # abstain, so an arm whose infrastructure flaked more often looks worse
    # here for reasons that have nothing to do with repair quality. The
    # experiment's verdict is decided on the verdict-only set below; this
    # read stays visible so nothing is hidden, but it does not conclude.
    print("\nDifference (B - A), all shared cases -- operational context, not the verdict")
    print(f"  observed ............. {observed:+.1%}")
    print(f"  95% bootstrap CI ..... [{low:+.1%}, {high:+.1%}]")
    print(f"  McNemar exact p ...... {p_value:.4f}  (discordant pairs: {only_a + only_b})")
    if p_value < 0.05 and observed != 0:
        leader = "B (review loop)" if observed > 0 else "A (direct)"
        print(
            f"  note ................. {leader} leads on this read, but it counts\n"
            f"                         non-verdicts as unsolved. See the verdict-only\n"
            f"                         section below for the experiment's conclusion."
        )

    # --- verdict-only read (ADR-0008) --------------------------------
    # A timeout is an operational failure, not a wrong answer. Folding it into
    # the task-failure count charges an arm for infrastructure. The primary
    # accuracy read therefore restricts to cases where BOTH arms returned an
    # actual verdict; the raw read above stays visible so nothing is hidden.
    verdicted = [s for s in shared if left[s]["verdict"] and right[s]["verdict"]]
    if verdicted:
        v_only_a = sum(1 for s in verdicted if left[s]["passed"] and not right[s]["passed"])
        v_only_b = sum(1 for s in verdicted if right[s]["passed"] and not left[s]["passed"])
        va = sum(1 for s in verdicted if left[s]["passed"])
        vb = sum(1 for s in verdicted if right[s]["passed"])
        v_deltas = [
            int(right[s]["passed"]) - int(left[s]["passed"]) for s in verdicted
        ]
        v_observed = statistics.fmean(v_deltas)
        v_p = mcnemar_exact(v_only_a, v_only_b)
        print(f"\nAccuracy on the {len(verdicted)} cases where both arms gave a verdict")
        print(f"  A solved ............. {va}/{len(verdicted)} = {va / len(verdicted):.1%}")
        print(f"  B solved ............. {vb}/{len(verdicted)} = {vb / len(verdicted):.1%}")
        print(f"  discordant ........... A-only {v_only_a}, B-only {v_only_b}")
        print(f"  McNemar exact p ...... {v_p:.4f}")
        dropped = len(shared) - len(verdicted)
        if dropped:
            print(
                f"  excluded ............. {dropped} case(s) where at least one arm\n"
                f"                         returned no verdict (error/unavailable/abstain)"
            )
        if v_p < 0.05 and v_observed != 0:
            winner = "B (review loop)" if v_observed > 0 else "A (direct)"
            print(f"  VERDICT .............. {winner} scores higher, p < 0.05")
        else:
            print(
                "  VERDICT .............. no significant difference at this sample size.\n"
                "                         The interval, not the point estimate, is the result."
            )
    else:
        print(
            "\nVERDICT ................ none. No case had a verdict from both arms,\n"
            "                         so this run measured infrastructure, not repair."
        )

    print("\nCost")
    for label, report in (("A", left_report), ("B", right_report)):
        durations = [
            ((sample.get("execution") or {}).get("output") or {}).get("elapsed_seconds")
            for sample in report.get("samples", [])
        ]
        durations = [value for value in durations if isinstance(value, (int, float))]
        window = ""
        if report.get("started_at") and report.get("finished_at"):
            start = datetime.fromisoformat(report["started_at"])
            end = datetime.fromisoformat(report["finished_at"])
            window = f"wall clock {(end - start).total_seconds() / 60:5.1f} min"
        median = (
            f"median {sorted(durations)[len(durations) // 2]:5.1f} s/case "
            f"(n={len(durations)} kept inline)"
            if durations
            else "no inline timing (outputs spilled to artifacts)"
        )
        print(f"  arm {label}: {window}; {median}")

    print("\nBy case kind")
    kinds = sorted({str(row["metadata"].get("kind", "?")) for row in left.values()})
    for kind in kinds:
        ids = [s for s in shared if str(left[s]["metadata"].get("kind", "?")) == kind]
        if not ids:
            continue
        a_pass = sum(1 for s in ids if left[s]["passed"])
        b_pass = sum(1 for s in ids if right[s]["passed"])
        print(f"  {kind:<6} n={len(ids):<3} A={a_pass:<3} B={b_pass:<3}")

    print("\nOperational health (never folded into task failures, ADR-0008)")
    for label, data in (("A", left), ("B", right)):
        statuses: dict[str, int] = {}
        for row in data.values():
            statuses[row["exec_status"]] = statuses.get(row["exec_status"], 0) + 1
        print(f"  arm {label}: {statuses}")

    print("\nReports")
    print(f"  A: {left_path}")
    print(f"  B: {right_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
