"""SQL queries over the SWE-AB ledger: dataset -> statistics glue.

Every function takes `conn: sqlite3.Connection` first and returns frozen
dataclasses -- never a bare tuple, dict, or `sqlite3.Row` -- so a caller
never has to remember what column 3 means.

The one rule every function here keeps visible, because the schema makes
it easy to lose: a trial with `op_status != 'ok'` has NO `grade` row at
all (enforced by `trg_grade_requires_ok_trial` in schema.sql) and must
never be folded into a failure count. "No verdict" and "failed" are
different facts. Every pass-rate style aggregate below therefore reports
two numbers side by side -- a verdicts-only read (the accuracy question)
and an all-trials read (the operational question) -- rather than picking
one and hiding the other.

The second rule: arms within one wave share a `substrate_id` by
construction (`trg_trial_substrate_match`), but two waves may not. No
function here accepts more than one `wave_id` at a time; the one function
that spans multiple waves, `substrate_groups`, groups them by
`substrate_id` explicitly instead of pooling their trials.

Standard library only. Does not import `store.py` -- callers hand in an
already-open `sqlite3.Connection`.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Final

from .stats import (
    ConfidenceInterval,
    QResult,
    cochrans_q,
    holm_correction,
    mcnemar_exact,
    paired_bootstrap,
    wilson,
)

__all__ = [
    "DEFAULT_ALPHA",
    "OpFailureCount",
    "ArmPassRate",
    "ExclusionReason",
    "PairedResult",
    "PairwiseComparison",
    "OmnibusResult",
    "InstanceProportion",
    "CostSum",
    "ArmCost",
    "StepCost",
    "MissingCell",
    "ArmCompleteness",
    "Completeness",
    "WaveSummary",
    "ArmSummary",
    "SubstrateGroup",
    "Verdict",
    "arm_pass_rates",
    "paired_outcomes",
    "omnibus",
    "repeat_aggregate",
    "cost_by_arm",
    "step_cost_by_arm",
    "completeness",
    "substrate_groups",
    "verdict",
]

#: Two-sided significance threshold `verdict` uses unless overridden.
DEFAULT_ALPHA: Final[float] = 0.05


# ---------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------


def _arms_in_wave(
    conn: sqlite3.Connection, wave_id: str
) -> tuple[tuple[str, str], ...]:
    """Distinct `(arm_id, arm_key)` planned into this wave, by `arm_key`.

    Sourced from `plan_cell` (the design table) rather than `trial` (the
    observation table) deliberately: an arm with zero trials so far must
    still appear -- with `n_trials=0` downstream -- so a wave that has
    not finished running is reported as incomplete, not silently omitted
    from the comparison.
    """
    rows = conn.execute(
        """
        SELECT DISTINCT a.arm_id, a.arm_key
        FROM plan_cell pc
        JOIN arm a ON a.arm_id = pc.arm_id
        WHERE pc.wave_id = ?
        ORDER BY a.arm_key
        """,
        (wave_id,),
    ).fetchall()
    return tuple((r["arm_id"], r["arm_key"]) for r in rows)


def _instance_statuses(
    conn: sqlite3.Connection, wave_id: str, arm_id: str
) -> dict[tuple[str, int], tuple[str, str | None]]:
    """Map `(task_id, run_idx) -> (op_status, outcome)` for one arm.

    `outcome` is `None` unless `op_status == 'ok'` (the schema guarantees
    a grade row, and therefore an outcome, exists exactly then).
    """
    rows = conn.execute(
        """
        SELECT t.task_id, t.run_idx, t.op_status, g.outcome
        FROM trial t
        LEFT JOIN grade g ON g.trial_id = t.trial_id
        WHERE t.wave_id = ? AND t.arm_id = ?
        """,
        (wave_id, arm_id),
    ).fetchall()
    result: dict[tuple[str, int], tuple[str, str | None]] = {}
    for r in rows:
        task_id: str = r["task_id"]
        run_idx: int = r["run_idx"]
        op_status: str = r["op_status"]
        outcome: str | None = r["outcome"]
        result[(task_id, run_idx)] = (op_status, outcome)
    return result


# ---------------------------------------------------------------------
# arm_pass_rates
# ---------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class OpFailureCount:
    op_status: str
    count: int


@dataclass(frozen=True, slots=True)
class ArmPassRate:
    arm_id: str
    arm_key: str
    n_trials: int
    n_verdicts: int
    n_pass: int
    #: The accuracy read: pass rate over verdict-producing trials only.
    pass_rate_verdicts: ConfidenceInterval
    #: The operational read: pass rate over ALL trials, so an arm that
    #: fails operationally as often as it fails the task looks the same
    #: as an arm that never crashes but never passes -- both are 0% here
    #: -- rather than looking better because its failures didn't count.
    pass_rate_all_trials: ConfidenceInterval
    n_operational_failures: int
    operational_failures: tuple[OpFailureCount, ...]


def arm_pass_rates(conn: sqlite3.Connection, wave_id: str) -> tuple[ArmPassRate, ...]:
    """Per-arm pass rate, reported both ways at once (see module
    docstring): over verdicts only, and over every trial including
    operational failures. Never just one -- that is the whole point of
    this ledger.
    """
    results: list[ArmPassRate] = []
    for arm_id, arm_key in _arms_in_wave(conn, wave_id):
        trial_row = conn.execute(
            "SELECT COUNT(*) AS n FROM trial WHERE wave_id = ? AND arm_id = ?",
            (wave_id, arm_id),
        ).fetchone()
        n_trials: int = trial_row["n"]

        verdict_row = conn.execute(
            """
            SELECT COUNT(*) AS n_verdicts,
                   SUM(CASE WHEN g.outcome = 'pass' THEN 1 ELSE 0 END) AS n_pass
            FROM trial t
            JOIN grade g ON g.trial_id = t.trial_id
            WHERE t.wave_id = ? AND t.arm_id = ?
            """,
            (wave_id, arm_id),
        ).fetchone()
        n_verdicts: int = verdict_row["n_verdicts"]
        n_pass: int = verdict_row["n_pass"] or 0

        failure_rows = conn.execute(
            """
            SELECT op_status, COUNT(*) AS n
            FROM trial
            WHERE wave_id = ? AND arm_id = ? AND op_status <> 'ok'
            GROUP BY op_status
            ORDER BY op_status
            """,
            (wave_id, arm_id),
        ).fetchall()
        failures = tuple(
            OpFailureCount(op_status=r["op_status"], count=r["n"]) for r in failure_rows
        )
        n_operational_failures = sum(f.count for f in failures)

        results.append(
            ArmPassRate(
                arm_id=arm_id,
                arm_key=arm_key,
                n_trials=n_trials,
                n_verdicts=n_verdicts,
                n_pass=n_pass,
                pass_rate_verdicts=wilson(n_pass, n_verdicts),
                pass_rate_all_trials=wilson(n_pass, n_trials),
                n_operational_failures=n_operational_failures,
                operational_failures=failures,
            )
        )
    return tuple(results)


# ---------------------------------------------------------------------
# paired_outcomes
# ---------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ExclusionReason:
    """Why one `(task_id, run_idx)` instance was dropped from the 2x2.

    `arm_a_status`/`arm_b_status` are `"verdict"` for the side that DID
    produce one, and either the other side's `op_status` or `"no_trial"`
    (no trial row exists at all for that arm at that instance) for the
    side that did not. An instance excluded because BOTH sides lack a
    verdict gets its own bucket -- e.g. `("timeout", "error")` -- rather
    than being folded into either side's count.
    """

    arm_a_status: str
    arm_b_status: str
    count: int


@dataclass(frozen=True, slots=True)
class PairedResult:
    wave_id: str
    arm_a: str
    arm_b: str
    n_compared: int
    both_pass: int
    only_a: int
    only_b: int
    neither: int
    mcnemar_p: float
    #: Bootstrap CI on the mean of (arm_b outcome - arm_a outcome) over
    #: the compared instances; positive favors arm_b.
    bootstrap_diff: ConfidenceInterval
    n_excluded: int
    excluded_reasons: tuple[ExclusionReason, ...]


def paired_outcomes(
    conn: sqlite3.Connection, wave_id: str, arm_a: str, arm_b: str
) -> PairedResult:
    """McNemar + bootstrap over instances where BOTH `arm_a` and `arm_b`
    produced a verdict at the same `(task_id, run_idx)`.

    An instance where either side has no trial at all, or has a trial
    whose `op_status != 'ok'`, is excluded from the 2x2 table and counted
    in `excluded_reasons` instead of being scored as a loss for that arm
    -- an operational failure is never a wrong answer (ADR-0008's rule,
    enforced here at the query layer).
    """
    a_status = _instance_statuses(conn, wave_id, arm_a)
    b_status = _instance_statuses(conn, wave_id, arm_b)
    instances = sorted(set(a_status) | set(b_status))

    both_pass = only_a = only_b = neither = 0
    deltas: list[float] = []
    exclusions: dict[tuple[str, str], int] = {}

    for key in instances:
        a_op, a_outcome = a_status.get(key, ("no_trial", None))
        b_op, b_outcome = b_status.get(key, ("no_trial", None))
        a_verdict = a_op == "ok"
        b_verdict = b_op == "ok"
        if a_verdict and b_verdict:
            a_pass = a_outcome == "pass"
            b_pass = b_outcome == "pass"
            if a_pass and b_pass:
                both_pass += 1
            elif a_pass:
                only_a += 1
            elif b_pass:
                only_b += 1
            else:
                neither += 1
            deltas.append(float(b_pass) - float(a_pass))
        else:
            reason_key = (
                "verdict" if a_verdict else a_op,
                "verdict" if b_verdict else b_op,
            )
            exclusions[reason_key] = exclusions.get(reason_key, 0) + 1

    n_compared = both_pass + only_a + only_b + neither
    excluded_reasons = tuple(
        ExclusionReason(arm_a_status=k[0], arm_b_status=k[1], count=v)
        for k, v in sorted(exclusions.items())
    )
    n_excluded = sum(r.count for r in excluded_reasons)

    return PairedResult(
        wave_id=wave_id,
        arm_a=arm_a,
        arm_b=arm_b,
        n_compared=n_compared,
        both_pass=both_pass,
        only_a=only_a,
        only_b=only_b,
        neither=neither,
        mcnemar_p=mcnemar_exact(only_a, only_b),
        bootstrap_diff=paired_bootstrap(deltas),
        n_excluded=n_excluded,
        excluded_reasons=excluded_reasons,
    )


# ---------------------------------------------------------------------
# omnibus
# ---------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PairwiseComparison:
    arm_a: str
    arm_b: str
    n_compared: int
    only_a: int
    only_b: int
    mcnemar_p: float
    holm_p: float


@dataclass(frozen=True, slots=True)
class OmnibusResult:
    wave_id: str
    arm_keys: tuple[str, ...]
    n_instances: int
    q: QResult
    pairwise: tuple[PairwiseComparison, ...]


def omnibus(conn: sqlite3.Connection, wave_id: str) -> OmnibusResult:
    """Cochran's Q across every arm in the wave, then pairwise McNemar
    with Holm correction as a post-hoc follow-up.

    Both the omnibus Q and every pairwise test below it are computed on
    the SAME subset: instances where every arm in the wave produced a
    verdict. That is a deliberate choice, not an oversight -- letting
    each pairwise comparison use its own (larger) two-arm-complete subset
    would give every pairwise test a different N, making them
    incomparable with each other and with the omnibus result they are
    meant to follow up on.

    Raises `ValueError` if the wave has fewer than 2 arms.
    """
    arms = _arms_in_wave(conn, wave_id)
    if len(arms) < 2:
        raise ValueError(
            f"omnibus requires at least 2 arms in the wave, got {len(arms)}"
        )
    arm_keys = tuple(key for _, key in arms)
    statuses = {arm_id: _instance_statuses(conn, wave_id, arm_id) for arm_id, _ in arms}

    common_keys = set.intersection(*(set(s) for s in statuses.values()))
    complete_instances = sorted(
        key
        for key in common_keys
        if all(statuses[arm_id][key][0] == "ok" for arm_id, _ in arms)
    )

    table = [
        [1 if statuses[arm_id][key][1] == "pass" else 0 for arm_id, _ in arms]
        for key in complete_instances
    ]
    q_result = (
        cochrans_q(table) if table else QResult(q=0.0, df=len(arms) - 1, p_value=1.0)
    )

    pair_data: list[tuple[str, str, int, int, float]] = []
    for i in range(len(arms)):
        for j in range(i + 1, len(arms)):
            arm_a_id, arm_a_key = arms[i]
            arm_b_id, arm_b_key = arms[j]
            only_a = sum(
                1
                for key in complete_instances
                if statuses[arm_a_id][key][1] == "pass"
                and statuses[arm_b_id][key][1] != "pass"
            )
            only_b = sum(
                1
                for key in complete_instances
                if statuses[arm_b_id][key][1] == "pass"
                and statuses[arm_a_id][key][1] != "pass"
            )
            p = mcnemar_exact(only_a, only_b)
            pair_data.append((arm_a_key, arm_b_key, only_a, only_b, p))

    holm_ps = holm_correction([d[4] for d in pair_data])
    pairwise = tuple(
        PairwiseComparison(
            arm_a=arm_a_key,
            arm_b=arm_b_key,
            n_compared=len(complete_instances),
            only_a=only_a,
            only_b=only_b,
            mcnemar_p=p,
            holm_p=holm_p,
        )
        for (arm_a_key, arm_b_key, only_a, only_b, p), holm_p in zip(
            pair_data, holm_ps, strict=True
        )
    )

    return OmnibusResult(
        wave_id=wave_id,
        arm_keys=arm_keys,
        n_instances=len(complete_instances),
        q=q_result,
        pairwise=pairwise,
    )


# ---------------------------------------------------------------------
# repeat_aggregate
# ---------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class InstanceProportion:
    arm_id: str
    arm_key: str
    task_id: str
    n_runs_verdict: int
    proportion: float


def repeat_aggregate(
    conn: sqlite3.Connection, wave_id: str
) -> tuple[InstanceProportion, ...]:
    """Per-(arm, task) success proportion across `run_idx`, for
    `stats.permutation_test_paired`'s non-deterministic-arm comparison.

    `proportion = n_pass / n_runs_verdict`. A `(arm, task)` with zero
    verdict-producing runs is omitted rather than reported as a
    proportion over zero -- there is no rate to report, and a caller
    pairing two arms' proportions must not silently see a manufactured
    0.0 for missing data. With `planned_runs == 1`, every included row is
    exactly one run, so `proportion` degenerates cleanly to 0.0 or 1.0
    with no special case: one run is just the `n=1` instance of the same
    aggregate.
    """
    rows = conn.execute(
        """
        SELECT a.arm_id, a.arm_key, t.task_id,
               COUNT(*) FILTER (WHERE t.op_status = 'ok') AS n_verdict,
               SUM(CASE WHEN g.outcome = 'pass' THEN 1 ELSE 0 END) AS n_pass
        FROM trial t
        JOIN arm a ON a.arm_id = t.arm_id
        LEFT JOIN grade g ON g.trial_id = t.trial_id
        WHERE t.wave_id = ?
        GROUP BY a.arm_id, t.task_id
        ORDER BY a.arm_key, t.task_id
        """,
        (wave_id,),
    ).fetchall()

    results: list[InstanceProportion] = []
    for r in rows:
        n_verdict: int = r["n_verdict"]
        if n_verdict == 0:
            continue
        n_pass: int = r["n_pass"] or 0
        results.append(
            InstanceProportion(
                arm_id=r["arm_id"],
                arm_key=r["arm_key"],
                task_id=r["task_id"],
                n_runs_verdict=n_verdict,
                proportion=n_pass / n_verdict,
            )
        )
    return tuple(results)


# ---------------------------------------------------------------------
# cost_by_arm / step_cost_by_arm
# ---------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class CostSum:
    """A summed field plus how many trials actually recorded it.

    `total` is `None` exactly when `coverage == 0` -- SQL `SUM` already
    ignores NULLs and returns NULL when every contributing row was NULL,
    which this preserves rather than coercing to 0. `coverage` counts
    trials with a non-NULL value for this field, out of the arm's
    `n_trials`; a 0-total with `coverage > 0` (every recorded value was
    literally 0) is therefore distinguishable from an unrecorded field.
    """

    total: float | None
    coverage: int


@dataclass(frozen=True, slots=True)
class ArmCost:
    arm_id: str
    arm_key: str
    n_trials: int
    n_verdicts: int
    tokens_in: CostSum
    tokens_out: CostSum
    wall_seconds: CostSum
    cost_usd: CostSum
    gpu_seconds: CostSum
    #: Mean over verdict-producing trials that also recorded the field;
    #: `None` if no verdict trial recorded it, distinct from a mean of 0.
    tokens_in_mean_per_verdict: float | None
    tokens_out_mean_per_verdict: float | None
    wall_seconds_mean_per_verdict: float | None
    cost_usd_mean_per_verdict: float | None
    gpu_seconds_mean_per_verdict: float | None


#: Per-arm cost aggregate. `tokens_in`/`tokens_out`/`wall_seconds` live
#: directly on `trial` (one value per trial, possibly NULL). `cost_usd`/
#: `gpu_seconds` live in `spend`, which -- unlike `trial` -- carries no
#: `supersedes` column, so a trial could in principle accumulate more
#: than one `spend` row over time; the correlated subquery below picks
#: the most-recently-`computed_at` row per trial (ties broken by
#: `spend_id`) so a re-computed cost is used once, not summed twice.
_COST_SQL = """
    SELECT
        COUNT(*) AS n_trials,
        COUNT(g.trial_id) AS n_verdicts,
        SUM(t.tokens_in) AS sum_tokens_in,
        COUNT(t.tokens_in) AS cov_tokens_in,
        SUM(t.tokens_in) FILTER (WHERE g.trial_id IS NOT NULL) AS v_sum_tokens_in,
        COUNT(t.tokens_in) FILTER (WHERE g.trial_id IS NOT NULL) AS v_cov_tokens_in,
        SUM(t.tokens_out) AS sum_tokens_out,
        COUNT(t.tokens_out) AS cov_tokens_out,
        SUM(t.tokens_out) FILTER (WHERE g.trial_id IS NOT NULL) AS v_sum_tokens_out,
        COUNT(t.tokens_out) FILTER (WHERE g.trial_id IS NOT NULL) AS v_cov_tokens_out,
        SUM(t.wall_seconds) AS sum_wall_seconds,
        COUNT(t.wall_seconds) AS cov_wall_seconds,
        SUM(t.wall_seconds) FILTER (WHERE g.trial_id IS NOT NULL) AS v_sum_wall_seconds,
        COUNT(t.wall_seconds) FILTER (WHERE g.trial_id IS NOT NULL) AS v_cov_wall_seconds,
        SUM(sp.cost_usd) AS sum_cost_usd,
        COUNT(sp.cost_usd) AS cov_cost_usd,
        SUM(sp.cost_usd) FILTER (WHERE g.trial_id IS NOT NULL) AS v_sum_cost_usd,
        COUNT(sp.cost_usd) FILTER (WHERE g.trial_id IS NOT NULL) AS v_cov_cost_usd,
        SUM(sp.gpu_seconds) AS sum_gpu_seconds,
        COUNT(sp.gpu_seconds) AS cov_gpu_seconds,
        SUM(sp.gpu_seconds) FILTER (WHERE g.trial_id IS NOT NULL) AS v_sum_gpu_seconds,
        COUNT(sp.gpu_seconds) FILTER (WHERE g.trial_id IS NOT NULL) AS v_cov_gpu_seconds
    FROM trial t
    LEFT JOIN grade g ON g.trial_id = t.trial_id
    LEFT JOIN (
        SELECT s1.trial_id, s1.cost_usd, s1.gpu_seconds
        FROM spend s1
        WHERE s1.spend_id = (
            SELECT s2.spend_id FROM spend s2
            WHERE s2.trial_id = s1.trial_id
            ORDER BY s2.computed_at DESC, s2.spend_id DESC
            LIMIT 1
        )
    ) sp ON sp.trial_id = t.trial_id
    WHERE t.wave_id = ? AND t.arm_id = ?
"""


def _sum_field(row: sqlite3.Row, col: str) -> float | None:
    value = row[col]
    return None if value is None else float(value)


def _cov_field(row: sqlite3.Row, col: str) -> int:
    value: int = row[col]
    return value


def _mean_or_none(total: float | None, coverage: int) -> float | None:
    if coverage == 0 or total is None:
        return None
    return total / coverage


def cost_by_arm(conn: sqlite3.Connection, wave_id: str) -> tuple[ArmCost, ...]:
    """Per-arm cost sums and per-verdict-instance means.

    See `CostSum` and `_COST_SQL` for why a sum is `None` (never 0) when
    nothing recorded the field, and why `spend` needs a latest-row
    subquery that `trial`'s own columns do not.
    """
    results: list[ArmCost] = []
    for arm_id, arm_key in _arms_in_wave(conn, wave_id):
        row = conn.execute(_COST_SQL, (wave_id, arm_id)).fetchone()
        n_trials: int = row["n_trials"]
        n_verdicts: int = row["n_verdicts"]

        tokens_in = CostSum(
            _sum_field(row, "sum_tokens_in"), _cov_field(row, "cov_tokens_in")
        )
        tokens_out = CostSum(
            _sum_field(row, "sum_tokens_out"), _cov_field(row, "cov_tokens_out")
        )
        wall_seconds = CostSum(
            _sum_field(row, "sum_wall_seconds"), _cov_field(row, "cov_wall_seconds")
        )
        cost_usd = CostSum(
            _sum_field(row, "sum_cost_usd"), _cov_field(row, "cov_cost_usd")
        )
        gpu_seconds = CostSum(
            _sum_field(row, "sum_gpu_seconds"), _cov_field(row, "cov_gpu_seconds")
        )

        results.append(
            ArmCost(
                arm_id=arm_id,
                arm_key=arm_key,
                n_trials=n_trials,
                n_verdicts=n_verdicts,
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                wall_seconds=wall_seconds,
                cost_usd=cost_usd,
                gpu_seconds=gpu_seconds,
                tokens_in_mean_per_verdict=_mean_or_none(
                    _sum_field(row, "v_sum_tokens_in"),
                    _cov_field(row, "v_cov_tokens_in"),
                ),
                tokens_out_mean_per_verdict=_mean_or_none(
                    _sum_field(row, "v_sum_tokens_out"),
                    _cov_field(row, "v_cov_tokens_out"),
                ),
                wall_seconds_mean_per_verdict=_mean_or_none(
                    _sum_field(row, "v_sum_wall_seconds"),
                    _cov_field(row, "v_cov_wall_seconds"),
                ),
                cost_usd_mean_per_verdict=_mean_or_none(
                    _sum_field(row, "v_sum_cost_usd"), _cov_field(row, "v_cov_cost_usd")
                ),
                gpu_seconds_mean_per_verdict=_mean_or_none(
                    _sum_field(row, "v_sum_gpu_seconds"),
                    _cov_field(row, "v_cov_gpu_seconds"),
                ),
            )
        )
    return tuple(results)


@dataclass(frozen=True, slots=True)
class StepCost:
    arm_id: str
    arm_key: str
    step_name: str
    n_occurrences: int
    tokens_in: CostSum
    tokens_out: CostSum


def step_cost_by_arm(conn: sqlite3.Connection, wave_id: str) -> tuple[StepCost, ...]:
    """Token totals grouped by `(arm, step_name)` -- which step burned
    the extra tokens, not just which arm.
    """
    rows = conn.execute(
        """
        SELECT a.arm_id, a.arm_key, su.step_name,
               COUNT(*) AS n_occurrences,
               SUM(su.tokens_in) AS sum_tokens_in,
               COUNT(su.tokens_in) AS cov_tokens_in,
               SUM(su.tokens_out) AS sum_tokens_out,
               COUNT(su.tokens_out) AS cov_tokens_out
        FROM step_usage su
        JOIN trial t ON t.trial_id = su.trial_id
        JOIN arm a ON a.arm_id = t.arm_id
        WHERE t.wave_id = ?
        GROUP BY a.arm_id, su.step_name
        ORDER BY a.arm_key, su.step_name
        """,
        (wave_id,),
    ).fetchall()
    return tuple(
        StepCost(
            arm_id=r["arm_id"],
            arm_key=r["arm_key"],
            step_name=r["step_name"],
            n_occurrences=r["n_occurrences"],
            tokens_in=CostSum(
                _sum_field(r, "sum_tokens_in"), _cov_field(r, "cov_tokens_in")
            ),
            tokens_out=CostSum(
                _sum_field(r, "sum_tokens_out"), _cov_field(r, "cov_tokens_out")
            ),
        )
        for r in rows
    )


# ---------------------------------------------------------------------
# completeness
# ---------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MissingCell:
    task_id: str
    run_idx: int


@dataclass(frozen=True, slots=True)
class ArmCompleteness:
    arm_id: str
    arm_key: str
    n_planned: int
    n_trials: int
    n_verdicts: int
    missing: tuple[MissingCell, ...]


@dataclass(frozen=True, slots=True)
class Completeness:
    wave_id: str
    arms: tuple[ArmCompleteness, ...]


def completeness(conn: sqlite3.Connection, wave_id: str) -> Completeness:
    """Planned cells vs. trials present vs. verdicts, per arm.

    `n_planned` counts every `plan_cell` row NOT marked `'abandoned'` --
    an abandoned cell was deliberately dropped from the design, so it is
    not "missing" in the sense this reports. `missing` lists the
    `(task_id, run_idx)` pairs among those planned cells that have no
    `trial` row at all yet.
    """
    arm_results: list[ArmCompleteness] = []
    for arm_id, arm_key in _arms_in_wave(conn, wave_id):
        planned_rows = conn.execute(
            """
            SELECT task_id, run_idx FROM plan_cell
            WHERE wave_id = ? AND arm_id = ? AND status <> 'abandoned'
            """,
            (wave_id, arm_id),
        ).fetchall()
        planned_cells = {(r["task_id"], r["run_idx"]) for r in planned_rows}

        trial_rows = conn.execute(
            "SELECT task_id, run_idx FROM trial WHERE wave_id = ? AND arm_id = ?",
            (wave_id, arm_id),
        ).fetchall()
        trial_cells = {(r["task_id"], r["run_idx"]) for r in trial_rows}

        verdict_row = conn.execute(
            """
            SELECT COUNT(*) AS n_verdicts FROM trial t
            JOIN grade g ON g.trial_id = t.trial_id
            WHERE t.wave_id = ? AND t.arm_id = ?
            """,
            (wave_id, arm_id),
        ).fetchone()
        n_verdicts: int = verdict_row["n_verdicts"]

        missing = tuple(
            sorted(
                (
                    MissingCell(task_id=t, run_idx=r)
                    for t, r in planned_cells - trial_cells
                ),
                key=lambda m: (m.task_id, m.run_idx),
            )
        )
        arm_results.append(
            ArmCompleteness(
                arm_id=arm_id,
                arm_key=arm_key,
                n_planned=len(planned_cells),
                n_trials=len(trial_cells),
                n_verdicts=n_verdicts,
                missing=missing,
            )
        )
    return Completeness(wave_id=wave_id, arms=tuple(arm_results))


# ---------------------------------------------------------------------
# substrate_groups
# ---------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class WaveSummary:
    wave_id: str
    wave_no: int


@dataclass(frozen=True, slots=True)
class ArmSummary:
    arm_id: str
    arm_key: str
    role: str


@dataclass(frozen=True, slots=True)
class SubstrateGroup:
    substrate_id: str
    waves: tuple[WaveSummary, ...]
    arms: tuple[ArmSummary, ...]


def substrate_groups(
    conn: sqlite3.Connection, campaign_id: str
) -> tuple[SubstrateGroup, ...]:
    """Every distinct substrate under a campaign, with its waves and arms.

    Two waves under one campaign can run on different substrates (a
    harness upgrade, a different grader, a re-pinned task set) -- the
    ledger never merges outcomes across that difference, so this is how
    a caller sees the fault line before running any statistic that would
    span waves.
    """
    substrate_rows = conn.execute(
        "SELECT DISTINCT substrate_id FROM wave WHERE campaign_id = ? ORDER BY substrate_id",
        (campaign_id,),
    ).fetchall()

    groups: list[SubstrateGroup] = []
    for sr in substrate_rows:
        substrate_id: str = sr["substrate_id"]
        wave_rows = conn.execute(
            """
            SELECT wave_id, wave_no FROM wave
            WHERE campaign_id = ? AND substrate_id = ?
            ORDER BY wave_no
            """,
            (campaign_id, substrate_id),
        ).fetchall()
        waves = tuple(
            WaveSummary(wave_id=r["wave_id"], wave_no=r["wave_no"]) for r in wave_rows
        )

        arm_rows = conn.execute(
            """
            SELECT DISTINCT a.arm_id, a.arm_key, a.role
            FROM plan_cell pc
            JOIN arm a ON a.arm_id = pc.arm_id
            JOIN wave w ON w.wave_id = pc.wave_id
            WHERE w.campaign_id = ? AND w.substrate_id = ?
            ORDER BY a.arm_key
            """,
            (campaign_id, substrate_id),
        ).fetchall()
        arms = tuple(
            ArmSummary(arm_id=r["arm_id"], arm_key=r["arm_key"], role=r["role"])
            for r in arm_rows
        )
        groups.append(SubstrateGroup(substrate_id=substrate_id, waves=waves, arms=arms))
    return tuple(groups)


# ---------------------------------------------------------------------
# verdict
# ---------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Verdict:
    wave_id: str
    pass_rates: tuple[ArmPassRate, ...]
    #: Set when the wave has exactly 2 arms.
    paired: PairedResult | None
    #: Set when the wave has more than 2 arms.
    omnibus: OmnibusResult | None
    cost: tuple[ArmCost, ...]
    completeness: Completeness
    #: False whenever a significance result exists but should not be
    #: trusted as a conclusion -- see `caveats`.
    is_sound: bool
    caveats: tuple[str, ...]
    summary: str


def verdict(
    conn: sqlite3.Connection, wave_id: str, *, alpha: float = DEFAULT_ALPHA
) -> Verdict:
    """The wave's bottom line: pass rates, the appropriate significance
    test for the arm count, cost, completeness, and a plain-language
    summary.

    `is_sound` is False whenever the wave is incomplete (some arm is
    missing planned cells) or unbalanced (arms do not have matching
    trial/verdict counts). The significance test is still computed and
    returned either way -- nothing here is hidden -- but `summary`
    refuses to present it as a conclusion when `is_sound` is False; a
    reader must not be able to see a p-value here and mistake it for a
    sound one. `store.py` enforces arm balance at write time already;
    this is the read-time check for the wave as it actually stands.
    """
    pass_rates = arm_pass_rates(conn, wave_id)
    completeness_result = completeness(conn, wave_id)
    cost = cost_by_arm(conn, wave_id)

    caveats: list[str] = []
    incomplete_arms = [a.arm_key for a in completeness_result.arms if a.missing]
    if incomplete_arms:
        caveats.append(
            "incomplete: arm(s) "
            + ", ".join(incomplete_arms)
            + " are missing planned cells"
        )
    trial_counts = {a.n_trials for a in pass_rates}
    verdict_counts = {a.n_verdicts for a in pass_rates}
    if len(trial_counts) > 1 or len(verdict_counts) > 1:
        caveats.append("unbalanced: arms do not have matching trial/verdict counts")
    is_sound = not caveats

    k = len(pass_rates)
    paired_result: PairedResult | None = None
    omnibus_result: OmnibusResult | None = None
    if k == 2:
        paired_result = paired_outcomes(
            conn, wave_id, pass_rates[0].arm_id, pass_rates[1].arm_id
        )
    elif k > 2:
        omnibus_result = omnibus(conn, wave_id)

    summary = _summarize(
        pass_rates, paired_result, omnibus_result, is_sound, caveats, alpha
    )

    return Verdict(
        wave_id=wave_id,
        pass_rates=pass_rates,
        paired=paired_result,
        omnibus=omnibus_result,
        cost=cost,
        completeness=completeness_result,
        is_sound=is_sound,
        caveats=tuple(caveats),
        summary=summary,
    )


def _summarize(
    pass_rates: tuple[ArmPassRate, ...],
    paired: PairedResult | None,
    omni: OmnibusResult | None,
    is_sound: bool,
    caveats: list[str],
    alpha: float,
) -> str:
    if len(pass_rates) < 2:
        return f"Only {len(pass_rates)} arm(s) in this wave; no comparison possible."

    lines = [
        f"{a.arm_key}: {a.n_pass}/{a.n_verdicts} verdicts "
        f"({a.pass_rate_verdicts.point:.1%}), {a.n_trials} trials total, "
        f"{a.n_operational_failures} operational failure(s)"
        for a in pass_rates
    ]

    if not is_sound:
        return (
            "CAUTION -- "
            + "; ".join(caveats)
            + ". A significance result was computed but is NOT a sound read "
            "until the wave is complete and balanced.\n" + "\n".join(lines)
        )

    if paired is not None:
        significant = paired.mcnemar_p < alpha and paired.bootstrap_diff.point != 0
        if significant:
            leader = (
                pass_rates[1].arm_key
                if paired.bootstrap_diff.point > 0
                else pass_rates[0].arm_key
            )
            verdict_line = (
                f"VERDICT: {leader} scores higher, "
                f"McNemar p={paired.mcnemar_p:.4f} < {alpha}."
            )
        else:
            verdict_line = (
                f"VERDICT: no significant difference at alpha={alpha} "
                f"(McNemar p={paired.mcnemar_p:.4f})."
            )
        return "\n".join([*lines, verdict_line])

    if omni is not None:
        if omni.q.p_value < alpha:
            sig_pairs = [p for p in omni.pairwise if p.holm_p < alpha]
            if sig_pairs:
                detail = "; ".join(
                    f"{p.arm_a} vs {p.arm_b} (holm p={p.holm_p:.4f})" for p in sig_pairs
                )
                verdict_line = (
                    f"VERDICT: omnibus significant "
                    f"(Q={omni.q.q:.2f}, p={omni.q.p_value:.4f}); "
                    f"significant pairwise difference(s): {detail}"
                )
            else:
                verdict_line = (
                    f"VERDICT: omnibus significant "
                    f"(Q={omni.q.q:.2f}, p={omni.q.p_value:.4f}) but no pairwise "
                    "comparison survives Holm correction."
                )
        else:
            verdict_line = (
                f"VERDICT: no significant difference across arms "
                f"(Cochran's Q={omni.q.q:.2f}, p={omni.q.p_value:.4f})."
            )
        return "\n".join([*lines, verdict_line])

    return "\n".join(lines)
