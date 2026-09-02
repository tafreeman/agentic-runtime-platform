"""Diff the ledger's paired verdict against analyze.py's, wave by wave.

`migrate_reports.py` transcribes 37 report files into 1,703 ledger trials
and 1,130 grades. Transcription is not verification: this script checks
that the numbers the ledger now computes from those rows -- McNemar's exact
p-value, the paired bootstrap interval, the raw discordant-pair counts --
match what `analyze.py` computes directly from the same two report files,
for every two-arm wave `migrate_reports.CAMPAIGNS` defines. A mismatch means
either the migration lost or altered evidence, or the two statistics
implementations (`analyze.py` and `ledger/stats.py`, ported "verbatim" per
the ledger's own audit trail) have actually diverged on real data rather
than only in the validation code the earlier review found.

Two known, non-bug sources of difference, called out rather than debugged:

* **Bootstrap CI bounds will not match bit-for-bit.** Both sides call
  `paired_bootstrap` with the same seed (20260827) and the same delta
  *values*, but in different *order* -- `analyze.py` iterates
  `sorted(shared)` over SWE-bench instance ids, `ledger.queries.
  paired_outcomes` iterates `sorted(instances)` over content-hashed
  `(task_id, run_idx)` pairs. `paired_bootstrap`'s resampling is
  index-based (`rng.randrange(size)`), so a same-seed, same-multiset,
  different-order input walks the PRNG stream differently and lands on a
  different (but statistically equivalent) interval. McNemar's p-value has
  no such dependency -- it is pure combinatorics over two scalar counts --
  so it is compared for exact equality; the bootstrap interval is reported
  side by side with a tolerance instead.
* **Per-arm pass rate is not directly comparable.** `ledger.queries.
  arm_pass_rates` counts an arm's verdicts over every trial in its wave;
  `analyze.py`'s verdict-only accuracy read restricts to instances where
  *both* arms produced a verdict. This script compares the restricted
  (`paired_outcomes`) counts on both sides, not `arm_pass_rates`.

Usage:
    uv run python diff_verdicts.py [--db PATH]
"""

from __future__ import annotations

import argparse
import math
import sqlite3
from dataclasses import dataclass
from pathlib import Path

import analyze
import migrate_reports as mr
from ledger import queries
from ledger.store import open_ledger

BOOTSTRAP_TOLERANCE = 0.05  # bootstrap CIs are order-sensitive; see module docstring


@dataclass(frozen=True, slots=True)
class WaveDiff:
    campaign: str
    wave_no: int
    n_compared_ledger: int
    n_compared_analyze: int
    only_a_ledger: int
    only_a_analyze: int
    only_b_ledger: int
    only_b_analyze: int
    mcnemar_p_ledger: float
    mcnemar_p_analyze: float
    bootstrap_ledger: tuple[float, float]
    bootstrap_analyze: tuple[float, float]

    @property
    def counts_match(self) -> bool:
        return (
            self.n_compared_ledger == self.n_compared_analyze
            and self.only_a_ledger == self.only_a_analyze
            and self.only_b_ledger == self.only_b_analyze
        )

    @property
    def mcnemar_matches(self) -> bool:
        return math.isclose(self.mcnemar_p_ledger, self.mcnemar_p_analyze, abs_tol=1e-9)

    @property
    def bootstrap_close(self) -> bool:
        low_l, high_l = self.bootstrap_ledger
        low_a, high_a = self.bootstrap_analyze
        return (
            math.isclose(low_l, low_a, abs_tol=BOOTSTRAP_TOLERANCE)
            and math.isclose(high_l, high_a, abs_tol=BOOTSTRAP_TOLERANCE)
        )

    @property
    def ok(self) -> bool:
        return self.counts_match and self.mcnemar_matches and self.bootstrap_close


def _analyze_side(report_a_path: Path, report_b_path: Path) -> WaveDiff | None:
    """analyze.py's own verdict-only computation for one report pair."""
    left = analyze.outcomes(analyze.load(report_a_path))
    right = analyze.outcomes(analyze.load(report_b_path))
    shared = sorted(set(left) & set(right))
    verdicted = [s for s in shared if left[s]["verdict"] and right[s]["verdict"]]
    if not verdicted:
        return None

    only_a = sum(1 for s in verdicted if left[s]["passed"] and not right[s]["passed"])
    only_b = sum(1 for s in verdicted if right[s]["passed"] and not left[s]["passed"])
    deltas = [int(right[s]["passed"]) - int(left[s]["passed"]) for s in verdicted]
    p_value = analyze.mcnemar_exact(only_a, only_b)
    bootstrap = analyze.paired_bootstrap(deltas)

    return WaveDiff(
        campaign="",
        wave_no=0,
        n_compared_ledger=0,
        n_compared_analyze=len(verdicted),
        only_a_ledger=0,
        only_a_analyze=only_a,
        only_b_ledger=0,
        only_b_analyze=only_b,
        mcnemar_p_ledger=0.0,
        mcnemar_p_analyze=p_value,
        bootstrap_ledger=(0.0, 0.0),
        bootstrap_analyze=bootstrap,
    )


def diff_one_wave(
    conn: sqlite3.Connection,
    *,
    campaign_name: str,
    wave_plan: "mr.WavePlan",
) -> WaveDiff | str:
    """Return a `WaveDiff`, or a `str` explaining why this wave was skipped
    (not a two-arm wave, or no report gave both arms a verdict on anything).
    """
    if set(wave_plan.arms) != {"arm-a-direct", "arm-b-review-loop"}:
        return "not a two-arm (arm-a-direct, arm-b-review-loop) wave"

    campaign_id = mr._campaign_row_id(campaign_name)
    wave_id = mr._wave_row_id(campaign_id, wave_plan.wave_no)
    arm_a_id = mr._arm_row_id(campaign_id, "arm-a-direct")
    arm_b_id = mr._arm_row_id(campaign_id, "arm-b-review-loop")

    paired = queries.paired_outcomes(conn, wave_id, arm_a_id, arm_b_id)

    report_a = mr.REPORTS_DIR / wave_plan.arms["arm-a-direct"]
    report_b = mr.REPORTS_DIR / wave_plan.arms["arm-b-review-loop"]
    analyze_side = _analyze_side(report_a, report_b)
    if analyze_side is None:
        return "no instance where both arms gave a verdict (analyze.py side)"

    return WaveDiff(
        campaign=campaign_name,
        wave_no=wave_plan.wave_no,
        n_compared_ledger=paired.n_compared,
        n_compared_analyze=analyze_side.n_compared_analyze,
        only_a_ledger=paired.only_a,
        only_a_analyze=analyze_side.only_a_analyze,
        only_b_ledger=paired.only_b,
        only_b_analyze=analyze_side.only_b_analyze,
        mcnemar_p_ledger=paired.mcnemar_p,
        mcnemar_p_analyze=analyze_side.mcnemar_p_analyze,
        bootstrap_ledger=(paired.bootstrap_diff.low, paired.bootstrap_diff.high),
        bootstrap_analyze=analyze_side.bootstrap_analyze,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=mr.DEFAULT_DB_PATH)
    args = parser.parse_args()

    if not args.db.exists():
        print(
            f"no ledger database at {args.db} -- run migrate_reports.py first",
        )
        return 1

    conn = open_ledger(args.db, create=False)

    diffs: list[WaveDiff] = []
    skipped: list[tuple[str, int, str]] = []
    for campaign_plan in mr.CAMPAIGNS:
        for wave_plan in campaign_plan.waves:
            result = diff_one_wave(
                conn, campaign_name=campaign_plan.name, wave_plan=wave_plan
            )
            if isinstance(result, str):
                skipped.append((campaign_plan.name, wave_plan.wave_no, result))
            else:
                diffs.append(result)

    header = (
        f"{'campaign':<38} {'wave':>4} {'n':>4} {'only_a':>13} {'only_b':>13} "
        f"{'mcnemar p':>21} {'bootstrap (ledger vs analyze)':>38} {'ok':>4}"
    )
    print(header)
    print("-" * len(header))
    for diff in diffs:
        n_col = (
            f"{diff.n_compared_ledger}"
            if diff.n_compared_ledger == diff.n_compared_analyze
            else f"{diff.n_compared_ledger}!={diff.n_compared_analyze}"
        )
        only_a_col = (
            f"{diff.only_a_ledger}"
            if diff.only_a_ledger == diff.only_a_analyze
            else f"{diff.only_a_ledger}!={diff.only_a_analyze}"
        )
        only_b_col = (
            f"{diff.only_b_ledger}"
            if diff.only_b_ledger == diff.only_b_analyze
            else f"{diff.only_b_ledger}!={diff.only_b_analyze}"
        )
        mcnemar_col = f"{diff.mcnemar_p_ledger:.4f} vs {diff.mcnemar_p_analyze:.4f}"
        low_l, high_l = diff.bootstrap_ledger
        low_a, high_a = diff.bootstrap_analyze
        bootstrap_col = f"[{low_l:+.3f},{high_l:+.3f}] vs [{low_a:+.3f},{high_a:+.3f}]"
        print(
            f"{diff.campaign:<38} {diff.wave_no:>4} {n_col:>4} {only_a_col:>13} "
            f"{only_b_col:>13} {mcnemar_col:>21} {bootstrap_col:>38} "
            f"{'yes' if diff.ok else 'NO':>4}"
        )

    failures = [d for d in diffs if not d.ok]
    print(
        f"\n{len(diffs)} two-arm wave(s) compared, {len(failures)} mismatch(es), "
        f"{len(skipped)} skipped"
    )
    for campaign_name, wave_no, reason in skipped:
        print(f"  skipped {campaign_name} wave {wave_no}: {reason}")
    for diff in failures:
        print(f"\nMISMATCH: {diff.campaign} wave {diff.wave_no}")
        if not diff.counts_match:
            print(
                f"  counts differ: n_compared ledger={diff.n_compared_ledger} "
                f"analyze={diff.n_compared_analyze}; only_a ledger={diff.only_a_ledger} "
                f"analyze={diff.only_a_analyze}; only_b ledger={diff.only_b_ledger} "
                f"analyze={diff.only_b_analyze}"
            )
        if not diff.mcnemar_matches:
            print(
                f"  McNemar p differs: ledger={diff.mcnemar_p_ledger!r} "
                f"analyze={diff.mcnemar_p_analyze!r} (should be exact -- pure "
                "combinatorics over the same two counts)"
            )
        if not diff.bootstrap_close:
            print(
                f"  bootstrap CI differs by more than {BOOTSTRAP_TOLERANCE}: "
                f"ledger={diff.bootstrap_ledger} analyze={diff.bootstrap_analyze}"
            )

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
