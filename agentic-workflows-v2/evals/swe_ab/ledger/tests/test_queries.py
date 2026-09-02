"""Tests for ledger.queries: pass rates, paired outcomes, omnibus,
repeat aggregation, cost, completeness, substrate grouping, and verdict.

`seed_wave` below is this file's own row-seeding helper (test_schema.py
owns a similar one for its DDL/trigger tests, but this file is a
separately-owned module per the task contract, so it does not import
that one). It builds a fully-wired campaign/substrate/tasks/arms/
plan_cell grid and lets a test describe only the outcomes it cares about
via `cells`, e.g. "arm A passes tasks 1-3, arm B passes 2-4".
"""

from __future__ import annotations

import sqlite3
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

import pytest

from ledger.models import (
    Arm,
    ArmConfig,
    Blob,
    Campaign,
    Grade,
    Grader,
    Image,
    Model,
    PlanCell,
    Prompt,
    Spend,
    StepUsage,
    Substrate,
    Task,
    TaskSet,
    Trial,
    Wave,
    WaveTask,
    Workflow,
    WorkflowPrompt,
)
from ledger.queries import (
    CostSum,
    ExclusionReason,
    MissingCell,
    arm_pass_rates,
    completeness,
    cost_by_arm,
    omnibus,
    paired_outcomes,
    repeat_aggregate,
    step_cost_by_arm,
    substrate_groups,
    verdict,
)
from ledger.stats import permutation_test_paired

# ---------------------------------------------------------------------
# Row builders + seeding helper
# ---------------------------------------------------------------------


def _insert(
    conn: sqlite3.Connection,
    table: str,
    row: tuple[object, ...],
    *,
    or_ignore: bool = False,
) -> None:
    # `table` is always one of the fixed literal names below, never
    # external input, so this f-string is a table-name template rather
    # than an injection vector.
    placeholders = ",".join(["?"] * len(row))
    verb = "INSERT OR IGNORE" if or_ignore else "INSERT"
    conn.execute(f"{verb} INTO {table} VALUES ({placeholders})", row)


def make_blob(digest: str = "sha256:" + "a" * 64) -> Blob:
    return Blob(
        digest=digest,
        media_type="text/plain",
        size_bytes=10,
        retention="durable",
        stored_at="2026-01-01T00:00:00Z",
    )


def make_model(model_id: str = "mdl_test") -> Model:
    return Model(
        model_id=model_id,
        provider="acme",
        wire_ref="acme/x-1",
        family="x",
        params_b=7.0,
        quantization=None,
        context_window=8192,
        serving_mode="hosted",
        weights_probe=None,
        first_seen_at="2026-01-01T00:00:00Z",
    )


def make_prompt(prompt_id: str = "prm_test") -> Prompt:
    return Prompt(prompt_id=prompt_id, role="system", text_digest="sha256:" + "a" * 64)


def make_workflow(workflow_id: str = "wfl_test") -> Workflow:
    return Workflow(
        workflow_id=workflow_id,
        name="single-shot",
        yaml_digest="sha256:" + "b" * 64,
        step_count=1,
    )


def make_workflow_prompt(
    workflow_id: str = "wfl_test", prompt_id: str = "prm_test"
) -> WorkflowPrompt:
    return WorkflowPrompt(workflow_id=workflow_id, prompt_id=prompt_id)


def make_grader(grader_id: str = "grd_test") -> Grader:
    return Grader(
        grader_id=grader_id,
        name="exact_match",
        kind="deterministic",
        module_digest="sha256:" + "c" * 64,
        rubric_id=None,
    )


def make_image(image_id: str = "img_test") -> Image:
    return Image(
        image_id=image_id,
        repo="ghcr.io/acme/swebench-runner",
        tag="latest",
        digest="sha256:" + "d" * 64,
        pulled_at="2026-01-01T00:00:00Z",
    )


def make_task_set(task_set_id: str = "tsk_test") -> TaskSet:
    return TaskSet(
        task_set_id=task_set_id,
        name="swebench-lite",
        source="hf:princeton-nlp/SWE-bench_Lite",
        revision="v1",
        filter_expr=None,
        row_count=300,
        licence=None,
        built_at="2026-01-01T00:00:00Z",
    )


def make_task(task_id: str, instance_id: str) -> Task:
    return Task(
        task_id=task_id,
        task_set_id="tsk_test",
        instance_id=instance_id,
        repo="acme/repo",
        base_commit="deadbeef",
        target_file="src/module.py",
        image_id="img_test",
        fail_to_pass='["tests/test_module.py::test_x"]',  # noqa: S106 -- schema column, not a secret
        difficulty=None,
        contamination_risk=None,
        safe_after=None,
        problem_blob="sha256:" + "a" * 64,
        source_blob="sha256:" + "a" * 64,
        max_changed_lines=None,
    )


def make_substrate(substrate_id: str) -> Substrate:
    return Substrate(
        substrate_id=substrate_id,
        task_set_id="tsk_test",
        harness_version="1.0.0",
        runtime_digest="sha256:" + "e" * 64,
        evalkit_version="0.3.0",
        grader_id="grd_test",
        image_digest_set="f" * 16,
    )


def make_arm_config(arm_config_id: str) -> ArmConfig:
    return ArmConfig(
        arm_config_id=arm_config_id,
        model_id="mdl_test",
        temperature=0.2,
        top_p=1.0,
        top_k=None,
        max_tokens=4096,
        seed=None,
        stop_sequences='["</s>"]',
        context_window_used=8192,
        workflow_id="wfl_test",
        retrieval_mode="oracle",
        tool_policy=None,
    )


def make_campaign(campaign_id: str, name: str) -> Campaign:
    return Campaign(
        campaign_id=campaign_id,
        name=name,
        question="Does model X beat model Y?",
        primary_contrast=None,
        created_at="2026-01-01T00:00:00Z",
        status="open",
    )


def make_arm(
    arm_id: str, campaign_id: str, arm_config_id: str, arm_key: str, role: str
) -> Arm:
    return Arm(
        arm_id=arm_id,
        campaign_id=campaign_id,
        arm_key=arm_key,
        arm_config_id=arm_config_id,
        role=role,
    )


def make_wave(
    wave_id: str, campaign_id: str, substrate_id: str, wave_no: int, planned_runs: int
) -> Wave:
    return Wave(
        wave_id=wave_id,
        campaign_id=campaign_id,
        wave_no=wave_no,
        substrate_id=substrate_id,
        stratification=None,
        planned_runs=planned_runs,
        opened_at="2026-01-01T00:00:00Z",
    )


def make_wave_task(wave_id: str, task_id: str) -> WaveTask:
    return WaveTask(wave_id=wave_id, task_id=task_id)


def make_plan_cell(
    wave_id: str, arm_id: str, task_id: str, run_idx: int, status: str
) -> PlanCell:
    return PlanCell(
        wave_id=wave_id, arm_id=arm_id, task_id=task_id, run_idx=run_idx, status=status
    )


def make_trial(
    *,
    wave_id: str,
    arm_id: str,
    task_id: str,
    run_idx: int,
    trial_id: str,
    substrate_id: str,
    arm_config_id: str,
    op_status: str,
    tokens_in: int | None,
    tokens_out: int | None,
    wall_seconds: float | None,
) -> Trial:
    return Trial(
        wave_id=wave_id,
        arm_id=arm_id,
        task_id=task_id,
        run_idx=run_idx,
        trial_id=trial_id,
        batch_id="batch_test",
        substrate_id=substrate_id,
        arm_config_id=arm_config_id,
        model_id="mdl_test",
        models_answered='["mdl_test"]',
        started_at="2026-01-01T00:00:00Z",
        finished_at=None if op_status != "ok" else "2026-01-01T00:01:00Z",
        wall_seconds=wall_seconds,
        op_status=op_status,
        error_kind=None if op_status == "ok" else op_status,
        error_blob=None,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        trace_id=f"trace_{trial_id}",
        transcript_blob=None,
        answer_blob=None,
        supersedes=None,
    )


def make_grade(grade_id: str, trial_id: str, result: str) -> Grade:
    return Grade(
        grade_id=grade_id,
        trial_id=trial_id,
        grader_id="grd_test",
        status=result,
        outcome=result,
        score=1.0 if result == "pass" else 0.0,
        evidence_blob=None,
        oracle_provenance=None,
        graded_at="2026-01-01T00:01:30Z",
        supersedes=None,
    )


def make_spend(
    spend_id: str, trial_id: str, cost_usd: float | None, gpu_seconds: float | None
) -> Spend:
    return Spend(
        spend_id=spend_id,
        trial_id=trial_id,
        price_snapshot_id=None,
        cost_usd=cost_usd,
        gpu_seconds=gpu_seconds,
        computed_at="2026-01-01T00:01:00Z",
    )


def make_step_usage(
    trial_id: str,
    step_idx: int,
    step_name: str,
    tokens_in: int | None,
    tokens_out: int | None,
) -> StepUsage:
    return StepUsage(
        trial_id=trial_id,
        step_idx=step_idx,
        step_name=step_name,
        model_id="mdl_test",
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        latency_ms=100.0,
        status="ok",
    )


@dataclass(frozen=True)
class CellSpec:
    """One planned (arm, task, run) cell's outcome, for `seed_wave`.

    `result` is `"pass"`/`"fail"` for a normal verdict, or any other
    `trial.op_status` value (`"timeout"`, `"error"`, `"cancelled"`,
    `"unavailable"`, `"abstain"`) for an operational failure -- which
    gets a `trial` row and no `grade` row, matching the schema's own
    invariant.
    """

    result: str = "pass"
    tokens_in: int | None = 100
    tokens_out: int | None = 200
    wall_seconds: float | None = 10.0
    cost_usd: float | None = 0.01
    gpu_seconds: float | None = None


@dataclass(frozen=True)
class SeededWave:
    wave_id: str
    campaign_id: str
    substrate_id: str
    arm_ids: dict[str, str]  # arm_key -> arm_id
    task_ids: dict[int, str]  # 1-based task index -> task_id


def seed_wave(
    conn: sqlite3.Connection,
    *,
    wave_id: str = "wav_test",
    campaign_id: str = "cmp_test",
    substrate_id: str = "sub_test",
    n_tasks: int = 3,
    arm_keys: Sequence[str] = ("arm_a", "arm_b"),
    planned_runs: int = 1,
    wave_no: int | None = None,
    cells: Mapping[tuple[str, int, int], CellSpec | str] | None = None,
) -> SeededWave:
    """Seed one fully-wired wave: campaign -> substrate -> tasks -> arms
    -> plan_cell -> trial (+ grade for pass/fail cells).

    `cells` maps `(arm_key, task_idx, run_idx)` (`task_idx` and `run_idx`
    both 1-based) to a `CellSpec`, or the string shorthand `"pass"`/
    `"fail"` (expanded to a `CellSpec` with default token/cost values).
    Every `(arm_key, task_idx, run_idx)` in the full
    `arm_keys x range(1, n_tasks+1) x range(1, planned_runs+1)` grid gets
    a `plan_cell` row; only cells present in `cells` get a `trial` row.
    The rest stay `status='planned'` with no trial -- genuinely missing,
    which is what `queries.completeness` is meant to report.

    Defaults every cell to a pass when `cells` is omitted, so "a
    complete, all-passing wave with 2 arms and 3 tasks" needs no `cells`
    argument at all.
    """
    if cells is None:
        cells = {
            (arm_key, task_idx, run_idx): CellSpec(result="pass")
            for arm_key in arm_keys
            for task_idx in range(1, n_tasks + 1)
            for run_idx in range(1, planned_runs + 1)
        }

    # These are global reference rows (fixed literal ids, not scoped by
    # `wave_id`) so that multiple `seed_wave` calls on one connection --
    # e.g. two waves under one shared campaign, as in the substrate_groups
    # tests -- share one copy instead of colliding on a UNIQUE constraint.
    _insert(conn, "blob", make_blob().to_row(), or_ignore=True)
    _insert(conn, "model", make_model().to_row(), or_ignore=True)
    _insert(conn, "prompt", make_prompt().to_row(), or_ignore=True)
    _insert(conn, "workflow", make_workflow().to_row(), or_ignore=True)
    _insert(conn, "workflow_prompt", make_workflow_prompt().to_row(), or_ignore=True)
    _insert(conn, "grader", make_grader().to_row(), or_ignore=True)
    _insert(conn, "image", make_image().to_row(), or_ignore=True)
    _insert(conn, "task_set", make_task_set().to_row(), or_ignore=True)

    task_ids: dict[int, str] = {}
    for task_idx in range(1, n_tasks + 1):
        task_id = f"{wave_id}_tas_{task_idx}"
        task_ids[task_idx] = task_id
        _insert(
            conn,
            "task",
            make_task(
                task_id=task_id, instance_id=f"acme__repo-{wave_id}-{task_idx}"
            ).to_row(),
        )

    _insert(conn, "substrate", make_substrate(substrate_id).to_row(), or_ignore=True)
    # `campaign_id` is caller-supplied and deliberately reused across
    # multiple `seed_wave` calls in the substrate_groups tests (several
    # waves under one shared campaign), so this is idempotent too.
    _insert(
        conn,
        "campaign",
        make_campaign(campaign_id, name=f"{campaign_id}-name").to_row(),
        or_ignore=True,
    )
    if wave_no is None:
        # `wave` has `UNIQUE (campaign_id, wave_no)`. Auto-number so a
        # second `seed_wave` call reusing `campaign_id` (a later wave of
        # the same campaign) does not collide with wave_no=1.
        next_no_row = conn.execute(
            "SELECT COALESCE(MAX(wave_no), 0) + 1 AS next_no FROM wave WHERE campaign_id = ?",
            (campaign_id,),
        ).fetchone()
        wave_no = next_no_row["next_no"]
    _insert(
        conn,
        "wave",
        make_wave(
            wave_id,
            campaign_id,
            substrate_id,
            wave_no=wave_no,
            planned_runs=planned_runs,
        ).to_row(),
    )
    for task_id in task_ids.values():
        _insert(conn, "wave_task", make_wave_task(wave_id, task_id).to_row())

    # `arm` is campaign-scoped, not wave-scoped -- `schema.sql` enforces
    # `UNIQUE (campaign_id, arm_key)` because the same arm can run across
    # more than one wave of a campaign. Id it by `campaign_id` (not
    # `wave_id`) and insert idempotently so a second `seed_wave` call
    # reusing `campaign_id` with the same `arm_key` (a later wave of the
    # same campaign, as in the substrate_groups tests) reuses the arm
    # instead of colliding with it.
    arm_ids: dict[str, str] = {}
    for i, arm_key in enumerate(arm_keys):
        arm_id = f"{campaign_id}_a_{arm_key}"
        arm_config_id = f"{campaign_id}_arc_{arm_key}"
        arm_ids[arm_key] = arm_id
        _insert(
            conn, "arm_config", make_arm_config(arm_config_id).to_row(), or_ignore=True
        )
        role = "control" if i == 0 else "treatment"
        _insert(
            conn,
            "arm",
            make_arm(arm_id, campaign_id, arm_config_id, arm_key, role).to_row(),
            or_ignore=True,
        )

    trial_seq = 0
    for arm_key in arm_keys:
        arm_id = arm_ids[arm_key]
        arm_config_id = f"{campaign_id}_arc_{arm_key}"
        for task_idx in range(1, n_tasks + 1):
            task_id = task_ids[task_idx]
            for run_idx in range(1, planned_runs + 1):
                key = (arm_key, task_idx, run_idx)
                raw_spec = cells.get(key)
                status = "done" if raw_spec is not None else "planned"
                _insert(
                    conn,
                    "plan_cell",
                    make_plan_cell(wave_id, arm_id, task_id, run_idx, status).to_row(),
                )
                if raw_spec is None:
                    continue
                spec = (
                    CellSpec(result=raw_spec) if isinstance(raw_spec, str) else raw_spec
                )
                trial_seq += 1
                trial_id = f"{wave_id}_trl_{trial_seq}"
                op_status = "ok" if spec.result in ("pass", "fail") else spec.result
                _insert(
                    conn,
                    "trial",
                    make_trial(
                        wave_id=wave_id,
                        arm_id=arm_id,
                        task_id=task_id,
                        run_idx=run_idx,
                        trial_id=trial_id,
                        substrate_id=substrate_id,
                        arm_config_id=arm_config_id,
                        op_status=op_status,
                        tokens_in=spec.tokens_in,
                        tokens_out=spec.tokens_out,
                        wall_seconds=spec.wall_seconds,
                    ).to_row(),
                )
                if op_status == "ok":
                    _insert(
                        conn,
                        "grade",
                        make_grade(
                            f"{wave_id}_gra_{trial_seq}", trial_id, spec.result
                        ).to_row(),
                    )
                if spec.cost_usd is not None or spec.gpu_seconds is not None:
                    _insert(
                        conn,
                        "spend",
                        make_spend(
                            f"{wave_id}_spd_{trial_seq}",
                            trial_id,
                            spec.cost_usd,
                            spec.gpu_seconds,
                        ).to_row(),
                    )

    return SeededWave(
        wave_id=wave_id,
        campaign_id=campaign_id,
        substrate_id=substrate_id,
        arm_ids=arm_ids,
        task_ids=task_ids,
    )


# ---------------------------------------------------------------------
# arm_pass_rates
# ---------------------------------------------------------------------


def test_arm_pass_rates_with_only_clean_passes_and_fails(
    ledger_conn: sqlite3.Connection,
) -> None:
    seeded = seed_wave(
        ledger_conn,
        n_tasks=4,
        arm_keys=("arm_a", "arm_b"),
        cells={
            ("arm_a", 1, 1): "pass",
            ("arm_a", 2, 1): "pass",
            ("arm_a", 3, 1): "fail",
            ("arm_a", 4, 1): "fail",
            ("arm_b", 1, 1): "pass",
            ("arm_b", 2, 1): "pass",
            ("arm_b", 3, 1): "pass",
            ("arm_b", 4, 1): "fail",
        },
    )
    rates = arm_pass_rates(ledger_conn, seeded.wave_id)
    by_key = {r.arm_key: r for r in rates}

    a = by_key["arm_a"]
    assert a.n_trials == 4
    assert a.n_verdicts == 4
    assert a.n_pass == 2
    assert a.pass_rate_verdicts.point == pytest.approx(0.5)
    assert a.pass_rate_all_trials.point == pytest.approx(0.5)
    assert a.n_operational_failures == 0
    assert a.operational_failures == ()

    b = by_key["arm_b"]
    assert b.n_pass == 3
    assert b.pass_rate_verdicts.point == pytest.approx(0.75)


def _supersede_the_grade(
    conn: sqlite3.Connection, *, trial_id: str, new_outcome: str
) -> None:
    """Insert a correction grade for `trial_id`'s existing grade, with
    `supersedes` set to the row it replaces -- the one shape `make_grade`
    cannot build (it always sets `outcome = status = result` on a single,
    unlinked row).
    """
    old = conn.execute(
        "SELECT grade_id, grader_id FROM grade WHERE trial_id = ?", (trial_id,)
    ).fetchone()
    _insert(
        conn,
        "grade",
        Grade(
            grade_id=f"{old['grade_id']}_corrected",
            trial_id=trial_id,
            grader_id=old["grader_id"],
            status=new_outcome,
            outcome=new_outcome,
            score=1.0 if new_outcome == "pass" else 0.0,
            evidence_blob=None,
            oracle_provenance=None,
            graded_at="2026-01-02T00:00:00Z",
            supersedes=old["grade_id"],
        ).to_row(),
    )


def test_arm_pass_rates_counts_only_the_correction_not_the_superseded_grade(
    ledger_conn: sqlite3.Connection,
) -> None:
    seeded = seed_wave(
        ledger_conn, n_tasks=1, arm_keys=("arm_a",), cells={("arm_a", 1, 1): "pass"}
    )
    trial_id = ledger_conn.execute(
        "SELECT trial_id FROM trial WHERE wave_id = ?", (seeded.wave_id,)
    ).fetchone()["trial_id"]
    _supersede_the_grade(ledger_conn, trial_id=trial_id, new_outcome="fail")

    rates = arm_pass_rates(ledger_conn, seeded.wave_id)
    assert len(rates) == 1
    a = rates[0]
    # One trial, one grade *history* of two rows -- but exactly one active
    # verdict, and it reflects the correction (fail), not the original
    # (pass) or both.
    assert a.n_trials == 1
    assert a.n_verdicts == 1
    assert a.n_pass == 0


def test_arm_pass_rates_excludes_operational_failures_from_verdict_rate_but_not_all_trials_rate(
    ledger_conn: sqlite3.Connection,
) -> None:
    # arm_a: 2 passes, 1 timeout. The verdict-only rate must be computed
    # over the 2 verdicts (100%); the all-trials rate must be computed
    # over all 3 trials (67%), treating the timeout as "did not pass" for
    # the operational read without ever calling it a "fail" grade.
    seeded = seed_wave(
        ledger_conn,
        n_tasks=3,
        arm_keys=("arm_a",),
        cells={
            ("arm_a", 1, 1): "pass",
            ("arm_a", 2, 1): "pass",
            ("arm_a", 3, 1): "timeout",
        },
    )
    rates = arm_pass_rates(ledger_conn, seeded.wave_id)
    assert len(rates) == 1
    a = rates[0]
    assert a.n_trials == 3
    assert a.n_verdicts == 2
    assert a.n_pass == 2
    assert a.pass_rate_verdicts.point == pytest.approx(1.0)
    assert a.pass_rate_all_trials.point == pytest.approx(2 / 3)
    assert a.n_operational_failures == 1
    assert len(a.operational_failures) == 1
    assert a.operational_failures[0].op_status == "timeout"
    assert a.operational_failures[0].count == 1


def test_arm_pass_rates_excludes_ok_trials_the_grader_could_not_score(
    ledger_conn: sqlite3.Connection,
) -> None:
    # 1 clean pass, 1 trial that ran fine but the grader errored on
    # (op_status='ok', grade.outcome=NULL). n_verdicts must count only the
    # pass -- an ungraded-but-ok trial is not a verdict any more than a
    # timeout is, and n_trials must still count both.
    seeded = seed_wave(
        ledger_conn,
        n_tasks=2,
        arm_keys=("arm_a",),
        cells={("arm_a", 1, 1): "pass"},
    )
    _insert_ok_no_verdict_trial(
        ledger_conn,
        wave_id=seeded.wave_id,
        arm_id=seeded.arm_ids["arm_a"],
        task_id=seeded.task_ids[2],
        run_idx=1,
        trial_id=f"{seeded.wave_id}_trl_ok_no_verdict",
        substrate_id=seeded.substrate_id,
    )

    rates = arm_pass_rates(ledger_conn, seeded.wave_id)
    assert len(rates) == 1
    a = rates[0]
    assert a.n_trials == 2
    assert a.n_verdicts == 1
    assert a.n_pass == 1
    assert a.pass_rate_verdicts.point == pytest.approx(1.0)
    # No trial op_status here is anything but 'ok', so the operational-
    # failure tally stays empty even though a verdict is still missing.
    assert a.n_operational_failures == 0


def test_arm_pass_rates_breaks_down_multiple_op_statuses(
    ledger_conn: sqlite3.Connection,
) -> None:
    seeded = seed_wave(
        ledger_conn,
        n_tasks=4,
        arm_keys=("arm_a",),
        cells={
            ("arm_a", 1, 1): "pass",
            ("arm_a", 2, 1): "timeout",
            ("arm_a", 3, 1): "timeout",
            ("arm_a", 4, 1): "error",
        },
    )
    rates = arm_pass_rates(ledger_conn, seeded.wave_id)
    a = rates[0]
    assert a.n_operational_failures == 3
    breakdown = {f.op_status: f.count for f in a.operational_failures}
    assert breakdown == {"timeout": 2, "error": 1}


def test_arm_pass_rates_includes_arms_with_zero_trials(
    ledger_conn: sqlite3.Connection,
) -> None:
    # A wave that has been planned but not yet run must still surface
    # the arm, at n_trials=0, rather than silently omitting it.
    seeded = seed_wave(ledger_conn, n_tasks=2, arm_keys=("arm_a", "arm_b"), cells={})
    rates = arm_pass_rates(ledger_conn, seeded.wave_id)
    assert {r.arm_key for r in rates} == {"arm_a", "arm_b"}
    for r in rates:
        assert r.n_trials == 0
        assert r.n_verdicts == 0
        assert r.pass_rate_verdicts.point == 0.0
        assert r.pass_rate_all_trials.point == 0.0


# ---------------------------------------------------------------------
# paired_outcomes
# ---------------------------------------------------------------------


def test_paired_outcomes_counts_the_2x2_table(ledger_conn: sqlite3.Connection) -> None:
    # arm_a passes 1,2; arm_b passes 2,3 (n_tasks=4, both run 4 tasks).
    seeded = seed_wave(
        ledger_conn,
        n_tasks=4,
        arm_keys=("arm_a", "arm_b"),
        cells={
            ("arm_a", 1, 1): "pass",
            ("arm_a", 2, 1): "pass",
            ("arm_a", 3, 1): "fail",
            ("arm_a", 4, 1): "fail",
            ("arm_b", 1, 1): "fail",
            ("arm_b", 2, 1): "pass",
            ("arm_b", 3, 1): "pass",
            ("arm_b", 4, 1): "fail",
        },
    )
    result = paired_outcomes(
        ledger_conn, seeded.wave_id, seeded.arm_ids["arm_a"], seeded.arm_ids["arm_b"]
    )
    assert result.n_compared == 4
    assert result.both_pass == 1  # task 2
    assert result.only_a == 1  # task 1
    assert result.only_b == 1  # task 3
    assert result.neither == 1  # task 4
    assert result.n_excluded == 0
    assert result.excluded_reasons == ()


def test_paired_outcomes_uses_the_correction_not_the_superseded_grade(
    ledger_conn: sqlite3.Connection,
) -> None:
    # Same 2x2 as test_paired_outcomes_counts_the_2x2_table, except arm_a's
    # task-1 "pass" is later corrected to "fail" -- both_pass/only_a must
    # shift accordingly rather than a stale or duplicated row leaking in.
    seeded = seed_wave(
        ledger_conn,
        n_tasks=4,
        arm_keys=("arm_a", "arm_b"),
        cells={
            ("arm_a", 1, 1): "pass",
            ("arm_a", 2, 1): "pass",
            ("arm_a", 3, 1): "fail",
            ("arm_a", 4, 1): "fail",
            ("arm_b", 1, 1): "fail",
            ("arm_b", 2, 1): "pass",
            ("arm_b", 3, 1): "pass",
            ("arm_b", 4, 1): "fail",
        },
    )
    arm_a_task_1_trial = ledger_conn.execute(
        "SELECT trial_id FROM trial WHERE wave_id = ? AND arm_id = ? AND task_id = ?",
        (seeded.wave_id, seeded.arm_ids["arm_a"], seeded.task_ids[1]),
    ).fetchone()["trial_id"]
    _supersede_the_grade(ledger_conn, trial_id=arm_a_task_1_trial, new_outcome="fail")

    result = paired_outcomes(
        ledger_conn, seeded.wave_id, seeded.arm_ids["arm_a"], seeded.arm_ids["arm_b"]
    )
    assert result.n_compared == 4
    assert result.both_pass == 1  # task 2, unaffected
    assert result.only_a == 0  # task 1: arm_a corrected to fail, arm_b already fail
    assert result.only_b == 1  # task 3, unaffected
    assert result.neither == 2  # tasks 1 (corrected) and 4


def test_paired_outcomes_excludes_half_the_tasks_when_one_arm_times_out(
    ledger_conn: sqlite3.Connection,
) -> None:
    # arm_a times out on tasks 3-4; arm_b has a clean verdict everywhere.
    # Those two instances must be excluded from the 2x2, counted, and
    # attributed to the timeout -- never scored as a loss for arm_a.
    seeded = seed_wave(
        ledger_conn,
        n_tasks=4,
        arm_keys=("arm_a", "arm_b"),
        cells={
            ("arm_a", 1, 1): "pass",
            ("arm_a", 2, 1): "fail",
            ("arm_a", 3, 1): "timeout",
            ("arm_a", 4, 1): "timeout",
            ("arm_b", 1, 1): "pass",
            ("arm_b", 2, 1): "pass",
            ("arm_b", 3, 1): "pass",
            ("arm_b", 4, 1): "fail",
        },
    )
    result = paired_outcomes(
        ledger_conn, seeded.wave_id, seeded.arm_ids["arm_a"], seeded.arm_ids["arm_b"]
    )
    assert result.n_compared == 2  # only tasks 1, 2
    assert result.n_excluded == 2  # tasks 3, 4
    assert result.excluded_reasons == (
        ExclusionReason(arm_a_status="timeout", arm_b_status="verdict", count=2),
    )
    # The paired statistics are computed on the 2 surviving instances only.
    assert result.both_pass == 1  # task 1
    assert result.only_b == 1  # task 2
    assert result.only_a == 0
    assert result.neither == 0


def test_paired_outcomes_excludes_missing_trials_as_no_trial(
    ledger_conn: sqlite3.Connection,
) -> None:
    seeded = seed_wave(
        ledger_conn,
        n_tasks=2,
        arm_keys=("arm_a", "arm_b"),
        cells={
            ("arm_a", 1, 1): "pass",
            # arm_a has no cell at all for task 2 (never even planned to
            # run there in this scenario's cell map); arm_b has both.
            ("arm_b", 1, 1): "pass",
            ("arm_b", 2, 1): "pass",
        },
    )
    result = paired_outcomes(
        ledger_conn, seeded.wave_id, seeded.arm_ids["arm_a"], seeded.arm_ids["arm_b"]
    )
    assert result.n_compared == 1
    assert result.n_excluded == 1
    assert result.excluded_reasons == (
        ExclusionReason(arm_a_status="no_trial", arm_b_status="verdict", count=1),
    )


def _insert_ok_no_verdict_trial(
    conn: sqlite3.Connection,
    *,
    wave_id: str,
    arm_id: str,
    task_id: str,
    run_idx: int,
    trial_id: str,
    substrate_id: str,
) -> None:
    """A trial that ran cleanly (`op_status='ok'`) but whose grader gave no
    pass/fail verdict (`status='error'`, `outcome=NULL`) -- the case
    `make_grade` cannot express, since it always sets `outcome = status`.
    Not an operational failure (the schema would refuse a grade row on one
    of those); a real gap `_instance_statuses` and its consumers must
    treat as "no verdict", not as "ok, therefore comparable".
    """
    arm_config_id = conn.execute(
        "SELECT arm_config_id FROM arm WHERE arm_id = ?", (arm_id,)
    ).fetchone()["arm_config_id"]
    _insert(
        conn,
        "trial",
        make_trial(
            wave_id=wave_id,
            arm_id=arm_id,
            task_id=task_id,
            run_idx=run_idx,
            trial_id=trial_id,
            substrate_id=substrate_id,
            arm_config_id=arm_config_id,
            op_status="ok",
            tokens_in=100,
            tokens_out=200,
            wall_seconds=10.0,
        ).to_row(),
    )
    _insert(
        conn,
        "grade",
        Grade(
            grade_id=f"{trial_id}_gde",
            trial_id=trial_id,
            grader_id="grd_test",
            status="error",
            outcome=None,
            score=None,
            evidence_blob=None,
            oracle_provenance=None,
            graded_at="2026-01-01T00:01:30Z",
            supersedes=None,
        ).to_row(),
    )


def test_paired_outcomes_excludes_ok_trials_the_grader_could_not_score(
    ledger_conn: sqlite3.Connection,
) -> None:
    # arm_a's task 2 ran fine but the grader errored on it (outcome=NULL);
    # that must be excluded from the 2x2, not scored as "arm_a failed".
    seeded = seed_wave(
        ledger_conn,
        n_tasks=2,
        arm_keys=("arm_a", "arm_b"),
        cells={
            ("arm_a", 1, 1): "pass",
            ("arm_b", 1, 1): "fail",
            ("arm_b", 2, 1): "pass",
        },
    )
    _insert_ok_no_verdict_trial(
        ledger_conn,
        wave_id=seeded.wave_id,
        arm_id=seeded.arm_ids["arm_a"],
        task_id=seeded.task_ids[2],
        run_idx=1,
        trial_id=f"{seeded.wave_id}_trl_ok_no_verdict",
        substrate_id=seeded.substrate_id,
    )

    result = paired_outcomes(
        ledger_conn, seeded.wave_id, seeded.arm_ids["arm_a"], seeded.arm_ids["arm_b"]
    )
    assert result.n_compared == 1  # only task 1
    assert result.n_excluded == 1  # task 2
    assert result.excluded_reasons == (
        ExclusionReason(arm_a_status="ok_no_verdict", arm_b_status="verdict", count=1),
    )
    assert result.only_a == 1  # task 1: arm_a passes, arm_b fails


def test_paired_outcomes_mcnemar_p_matches_stats_module(
    ledger_conn: sqlite3.Connection,
) -> None:
    from ledger.stats import mcnemar_exact

    seeded = seed_wave(
        ledger_conn,
        n_tasks=10,
        arm_keys=("arm_a", "arm_b"),
        cells={
            **{("arm_a", i, 1): "pass" for i in range(1, 10)},  # 9 passes
            ("arm_a", 10, 1): "fail",
            **{("arm_b", i, 1): "fail" for i in range(1, 10)},  # 9 fails
            ("arm_b", 10, 1): "pass",
        },
    )
    result = paired_outcomes(
        ledger_conn, seeded.wave_id, seeded.arm_ids["arm_a"], seeded.arm_ids["arm_b"]
    )
    assert result.only_a == 9
    assert result.only_b == 1
    assert result.mcnemar_p == pytest.approx(mcnemar_exact(9, 1))


# ---------------------------------------------------------------------
# omnibus
# ---------------------------------------------------------------------


def test_omnibus_restricts_to_instances_all_arms_verdicted(
    ledger_conn: sqlite3.Connection,
) -> None:
    seeded = seed_wave(
        ledger_conn,
        n_tasks=3,
        arm_keys=("arm_a", "arm_b", "arm_c"),
        cells={
            ("arm_a", 1, 1): "pass",
            ("arm_a", 2, 1): "pass",
            ("arm_a", 3, 1): "pass",
            ("arm_b", 1, 1): "pass",
            ("arm_b", 2, 1): "fail",
            ("arm_b", 3, 1): "pass",
            # arm_c has no verdict at task 3 (operational failure), so
            # task 3 must be excluded from the omnibus subset entirely.
            ("arm_c", 1, 1): "fail",
            ("arm_c", 2, 1): "pass",
            ("arm_c", 3, 1): "timeout",
        },
    )
    result = omnibus(ledger_conn, seeded.wave_id)
    assert result.arm_keys == ("arm_a", "arm_b", "arm_c")
    assert result.n_instances == 2  # tasks 1, 2 only
    assert isinstance(result.q.p_value, float)
    assert len(result.pairwise) == 3  # C(3,2)


def test_omnibus_excludes_instances_where_an_arm_ran_ok_but_got_no_verdict(
    ledger_conn: sqlite3.Connection,
) -> None:
    # Same shape as test_omnibus_restricts_to_instances_all_arms_verdicted,
    # but arm_c's task-3 gap is a grader error on an otherwise-ok trial
    # rather than an operational failure -- `complete_instances` must
    # exclude it exactly the same way.
    seeded = seed_wave(
        ledger_conn,
        n_tasks=3,
        arm_keys=("arm_a", "arm_b", "arm_c"),
        cells={
            ("arm_a", 1, 1): "pass",
            ("arm_a", 2, 1): "pass",
            ("arm_b", 1, 1): "pass",
            ("arm_b", 2, 1): "fail",
            ("arm_c", 1, 1): "fail",
            ("arm_c", 2, 1): "pass",
        },
    )
    for arm_key in ("arm_a", "arm_b"):
        _insert_ok_no_verdict_trial(
            ledger_conn,
            wave_id=seeded.wave_id,
            arm_id=seeded.arm_ids[arm_key],
            task_id=seeded.task_ids[3],
            run_idx=1,
            trial_id=f"{seeded.wave_id}_trl_{arm_key}_ok_no_verdict",
            substrate_id=seeded.substrate_id,
        )
    _insert_ok_no_verdict_trial(
        ledger_conn,
        wave_id=seeded.wave_id,
        arm_id=seeded.arm_ids["arm_c"],
        task_id=seeded.task_ids[3],
        run_idx=1,
        trial_id=f"{seeded.wave_id}_trl_arm_c_ok_no_verdict",
        substrate_id=seeded.substrate_id,
    )

    result = omnibus(ledger_conn, seeded.wave_id)
    assert result.n_instances == 2  # tasks 1, 2 only; task 3 excluded


def test_omnibus_holm_adjusted_pvalues_are_never_below_raw(
    ledger_conn: sqlite3.Connection,
) -> None:
    seeded = seed_wave(
        ledger_conn,
        n_tasks=6,
        arm_keys=("arm_a", "arm_b", "arm_c"),
        cells={
            **{("arm_a", i, 1): "pass" for i in range(1, 7)},
            **{("arm_b", i, 1): ("pass" if i <= 3 else "fail") for i in range(1, 7)},
            **{("arm_c", i, 1): ("fail" if i <= 4 else "pass") for i in range(1, 7)},
        },
    )
    result = omnibus(ledger_conn, seeded.wave_id)
    for pc in result.pairwise:
        assert pc.holm_p >= pc.mcnemar_p - 1e-12
        assert pc.holm_p <= 1.0


def test_omnibus_requires_at_least_two_arms(ledger_conn: sqlite3.Connection) -> None:
    seeded = seed_wave(ledger_conn, n_tasks=2, arm_keys=("arm_a",))
    with pytest.raises(ValueError):
        omnibus(ledger_conn, seeded.wave_id)


# ---------------------------------------------------------------------
# repeat_aggregate
# ---------------------------------------------------------------------


def test_repeat_aggregate_with_planned_runs_three(
    ledger_conn: sqlite3.Connection,
) -> None:
    seeded = seed_wave(
        ledger_conn,
        n_tasks=1,
        arm_keys=("arm_a",),
        planned_runs=3,
        cells={
            ("arm_a", 1, 1): "pass",
            ("arm_a", 1, 2): "fail",
            ("arm_a", 1, 3): "pass",
        },
    )
    result = repeat_aggregate(ledger_conn, seeded.wave_id)
    assert len(result) == 1
    row = result[0]
    assert row.n_runs_verdict == 3
    assert row.proportion == pytest.approx(2 / 3)


def test_repeat_aggregate_with_planned_runs_one_degenerates_cleanly(
    ledger_conn: sqlite3.Connection,
) -> None:
    seeded = seed_wave(
        ledger_conn,
        n_tasks=2,
        arm_keys=("arm_a",),
        planned_runs=1,
        cells={("arm_a", 1, 1): "pass", ("arm_a", 2, 1): "fail"},
    )
    result = repeat_aggregate(ledger_conn, seeded.wave_id)
    by_task = {r.task_id: r for r in result}
    assert len(result) == 2
    for r in result:
        assert r.n_runs_verdict == 1
        assert r.proportion in (0.0, 1.0)
    assert by_task[seeded.task_ids[1]].proportion == 1.0
    assert by_task[seeded.task_ids[2]].proportion == 0.0


def test_repeat_aggregate_omits_task_with_zero_verdict_runs(
    ledger_conn: sqlite3.Connection,
) -> None:
    seeded = seed_wave(
        ledger_conn,
        n_tasks=1,
        arm_keys=("arm_a",),
        planned_runs=2,
        cells={("arm_a", 1, 1): "timeout", ("arm_a", 1, 2): "error"},
    )
    result = repeat_aggregate(ledger_conn, seeded.wave_id)
    assert result == ()


def test_repeat_aggregate_feeds_permutation_test_paired(
    ledger_conn: sqlite3.Connection,
) -> None:
    seeded = seed_wave(
        ledger_conn,
        n_tasks=4,
        arm_keys=("arm_a", "arm_b"),
        planned_runs=3,
        cells={
            **{("arm_a", t, r): "fail" for t in range(1, 5) for r in range(1, 4)},
            **{("arm_b", t, r): "pass" for t in range(1, 5) for r in range(1, 4)},
        },
    )
    result = repeat_aggregate(ledger_conn, seeded.wave_id)
    a_by_task = {r.task_id: r.proportion for r in result if r.arm_key == "arm_a"}
    b_by_task = {r.task_id: r.proportion for r in result if r.arm_key == "arm_b"}
    pairs = [(a_by_task[t], b_by_task[t]) for t in a_by_task]
    p = permutation_test_paired(pairs, samples=500, seed=1)
    assert p < 0.5  # a consistent, maximal gap should read as unlikely under the null


# ---------------------------------------------------------------------
# cost_by_arm / step_cost_by_arm
# ---------------------------------------------------------------------


def test_cost_by_arm_sums_and_returns_none_not_zero_when_unrecorded(
    ledger_conn: sqlite3.Connection,
) -> None:
    seeded = seed_wave(
        ledger_conn,
        n_tasks=2,
        arm_keys=("arm_a",),
        cells={
            ("arm_a", 1, 1): CellSpec(
                result="pass",
                tokens_in=100,
                tokens_out=200,
                wall_seconds=5.0,
                cost_usd=0.02,
                gpu_seconds=None,
            ),
            # No token/cost data recorded at all for this trial -- must
            # surface as None, not as a silent 0 that looks like a free run.
            ("arm_a", 2, 1): CellSpec(
                result="pass",
                tokens_in=None,
                tokens_out=None,
                wall_seconds=None,
                cost_usd=None,
                gpu_seconds=None,
            ),
        },
    )
    costs = cost_by_arm(ledger_conn, seeded.wave_id)
    assert len(costs) == 1
    c = costs[0]
    assert c.n_trials == 2
    assert c.tokens_in == CostSum(total=100.0, coverage=1)
    assert c.tokens_out == CostSum(total=200.0, coverage=1)
    assert c.wall_seconds == CostSum(total=5.0, coverage=1)
    assert c.cost_usd == CostSum(total=0.02, coverage=1)
    # Nobody recorded gpu_seconds at all: must be None, never 0.0.
    assert c.gpu_seconds == CostSum(total=None, coverage=0)
    assert c.gpu_seconds.total is None
    assert c.tokens_in_mean_per_verdict == pytest.approx(100.0)
    assert c.gpu_seconds_mean_per_verdict is None


def test_cost_by_arm_uses_latest_spend_row_when_a_trial_has_more_than_one(
    ledger_conn: sqlite3.Connection,
) -> None:
    seeded = seed_wave(
        ledger_conn,
        n_tasks=1,
        arm_keys=("arm_a",),
        cells={("arm_a", 1, 1): CellSpec(result="pass", cost_usd=0.01)},
    )
    trial_id = f"{seeded.wave_id}_trl_1"
    # A second, later-computed spend row for the same trial -- must win
    # over the original rather than being summed with it.
    _insert(
        ledger_conn,
        "spend",
        make_spend(
            f"{seeded.wave_id}_spd_2",
            trial_id,
            cost_usd=0.05,
            gpu_seconds=None,
        ).to_row(),
    )
    costs = cost_by_arm(ledger_conn, seeded.wave_id)
    assert costs[0].cost_usd.total == pytest.approx(0.05)
    assert costs[0].cost_usd.coverage == 1  # one trial, one (latest) value


def test_step_cost_by_arm_groups_by_step_name(ledger_conn: sqlite3.Connection) -> None:
    seeded = seed_wave(
        ledger_conn,
        n_tasks=2,
        arm_keys=("arm_a",),
        cells={("arm_a", 1, 1): "pass", ("arm_a", 2, 1): "pass"},
    )
    trial_1 = f"{seeded.wave_id}_trl_1"
    trial_2 = f"{seeded.wave_id}_trl_2"
    _insert(
        ledger_conn,
        "step_usage",
        make_step_usage(trial_1, 0, "generate_patch", 100, 50).to_row(),
    )
    _insert(
        ledger_conn,
        "step_usage",
        make_step_usage(trial_1, 1, "review", 30, 10).to_row(),
    )
    _insert(
        ledger_conn,
        "step_usage",
        make_step_usage(trial_2, 0, "generate_patch", 120, 60).to_row(),
    )

    steps = step_cost_by_arm(ledger_conn, seeded.wave_id)
    by_name = {s.step_name: s for s in steps}
    assert by_name["generate_patch"].n_occurrences == 2
    assert by_name["generate_patch"].tokens_in.total == pytest.approx(220.0)
    assert by_name["review"].n_occurrences == 1
    assert by_name["review"].tokens_in.total == pytest.approx(30.0)


# ---------------------------------------------------------------------
# completeness
# ---------------------------------------------------------------------


def test_completeness_lists_exact_missing_cells(
    ledger_conn: sqlite3.Connection,
) -> None:
    seeded = seed_wave(
        ledger_conn,
        n_tasks=3,
        arm_keys=("arm_a",),
        cells={("arm_a", 1, 1): "pass"},  # tasks 2, 3 never run
    )
    result = completeness(ledger_conn, seeded.wave_id)
    assert len(result.arms) == 1
    a = result.arms[0]
    assert a.n_planned == 3
    assert a.n_trials == 1
    assert a.n_verdicts == 1
    assert set(a.missing) == {
        MissingCell(task_id=seeded.task_ids[2], run_idx=1),
        MissingCell(task_id=seeded.task_ids[3], run_idx=1),
    }


def test_completeness_full_wave_has_no_missing_cells(
    ledger_conn: sqlite3.Connection,
) -> None:
    seeded = seed_wave(ledger_conn, n_tasks=3, arm_keys=("arm_a", "arm_b"))
    result = completeness(ledger_conn, seeded.wave_id)
    for a in result.arms:
        assert a.missing == ()
        assert a.n_trials == a.n_planned


# ---------------------------------------------------------------------
# substrate_groups
# ---------------------------------------------------------------------


def test_substrate_groups_shows_two_groups_for_two_substrates(
    ledger_conn: sqlite3.Connection,
) -> None:
    seed_wave(
        ledger_conn,
        wave_id="wav_1",
        campaign_id="cmp_shared",
        substrate_id="sub_1",
        n_tasks=2,
        arm_keys=("arm_a", "arm_b"),
    )
    seed_wave(
        ledger_conn,
        wave_id="wav_2",
        campaign_id="cmp_shared",
        substrate_id="sub_2",
        n_tasks=2,
        arm_keys=("arm_c",),
    )
    groups = substrate_groups(ledger_conn, "cmp_shared")
    assert len(groups) == 2
    by_id = {g.substrate_id: g for g in groups}
    assert {w.wave_id for w in by_id["sub_1"].waves} == {"wav_1"}
    assert {a.arm_key for a in by_id["sub_1"].arms} == {"arm_a", "arm_b"}
    assert {w.wave_id for w in by_id["sub_2"].waves} == {"wav_2"}
    assert {a.arm_key for a in by_id["sub_2"].arms} == {"arm_c"}


def test_verdict_refuses_to_treat_two_substrates_as_one_comparison(
    ledger_conn: sqlite3.Connection,
) -> None:
    # verdict() operates on a single wave_id, which is itself pinned to
    # one substrate_id by the schema's own trigger -- so the "refusal to
    # combine" is structural: there is no call that could span both.
    seeded_1 = seed_wave(
        ledger_conn,
        wave_id="wav_1",
        campaign_id="cmp_shared",
        substrate_id="sub_1",
        n_tasks=2,
        arm_keys=("arm_a", "arm_b"),
    )
    seed_wave(
        ledger_conn,
        wave_id="wav_2",
        campaign_id="cmp_shared",
        substrate_id="sub_2",
        n_tasks=2,
        arm_keys=("arm_a", "arm_b"),
    )
    groups = substrate_groups(ledger_conn, "cmp_shared")
    assert len(groups) == 2
    v = verdict(ledger_conn, seeded_1.wave_id)
    assert v.wave_id == seeded_1.wave_id  # only ever describes its own wave/substrate


# ---------------------------------------------------------------------
# verdict
# ---------------------------------------------------------------------


def test_verdict_on_a_complete_balanced_two_arm_wave_is_sound(
    ledger_conn: sqlite3.Connection,
) -> None:
    seeded = seed_wave(
        ledger_conn,
        n_tasks=10,
        arm_keys=("arm_a", "arm_b"),
        cells={
            **{("arm_a", i, 1): "fail" for i in range(1, 11)},
            **{("arm_b", i, 1): "pass" for i in range(1, 11)},
        },
    )
    v = verdict(ledger_conn, seeded.wave_id)
    assert v.is_sound is True
    assert v.caveats == ()
    assert v.paired is not None
    assert v.omnibus is None
    assert "VERDICT" in v.summary


def test_verdict_flags_unbalanced_when_cells_differ_but_counts_match(
    ledger_conn: sqlite3.Connection,
) -> None:
    # Both arms run exactly 3 tasks each -- equal n_trials, equal
    # n_verdicts -- but arm_a's is {1,2,3} and arm_b's is {2,3,4}. A
    # count-only comparison would call this balanced; it is not.
    seeded = seed_wave(
        ledger_conn,
        n_tasks=4,
        arm_keys=("arm_a", "arm_b"),
        cells={
            ("arm_a", 1, 1): "pass",
            ("arm_a", 2, 1): "pass",
            ("arm_a", 3, 1): "fail",
            ("arm_b", 2, 1): "pass",
            ("arm_b", 3, 1): "fail",
            ("arm_b", 4, 1): "pass",
        },
    )
    rates = arm_pass_rates(ledger_conn, seeded.wave_id)
    assert {r.n_trials for r in rates} == {3}
    assert {r.n_verdicts for r in rates} == {3}

    v = verdict(ledger_conn, seeded.wave_id)
    assert v.is_sound is False
    assert any("unbalanced" in c for c in v.caveats)


def test_verdict_on_unbalanced_wave_flags_it_rather_than_reporting_significance(
    ledger_conn: sqlite3.Connection,
) -> None:
    # arm_a completes all 6 tasks; arm_b only ran 3 of them. Even though
    # the paired test over the shared instances might come out
    # "significant", the verdict must refuse to present that as sound.
    seeded = seed_wave(
        ledger_conn,
        n_tasks=6,
        arm_keys=("arm_a", "arm_b"),
        cells={
            **{("arm_a", i, 1): "fail" for i in range(1, 7)},
            **{("arm_b", i, 1): "pass" for i in range(1, 4)},
        },
    )
    v = verdict(ledger_conn, seeded.wave_id)
    assert v.is_sound is False
    assert any("unbalanced" in c or "incomplete" in c for c in v.caveats)
    assert "CAUTION" in v.summary
    assert "VERDICT" not in v.summary
    # The statistic itself is still computed and available, just not
    # presented as a conclusion.
    assert v.paired is not None


def test_verdict_on_incomplete_wave_is_flagged(ledger_conn: sqlite3.Connection) -> None:
    seeded = seed_wave(
        ledger_conn,
        n_tasks=4,
        arm_keys=("arm_a", "arm_b"),
        cells={
            ("arm_a", 1, 1): "pass",
            ("arm_a", 2, 1): "pass",
            ("arm_a", 3, 1): "pass",
            ("arm_a", 4, 1): "pass",
            ("arm_b", 1, 1): "pass",
            ("arm_b", 2, 1): "pass",
            # arm_b is missing tasks 3 and 4 entirely.
        },
    )
    v = verdict(ledger_conn, seeded.wave_id)
    assert v.is_sound is False
    assert any(c.startswith("incomplete") for c in v.caveats)
    missing_arm_b = next(a for a in v.completeness.arms if a.arm_key == "arm_b").missing
    assert len(missing_arm_b) == 2


def test_verdict_with_more_than_two_arms_uses_omnibus(
    ledger_conn: sqlite3.Connection,
) -> None:
    seeded = seed_wave(ledger_conn, n_tasks=3, arm_keys=("arm_a", "arm_b", "arm_c"))
    v = verdict(ledger_conn, seeded.wave_id)
    assert v.paired is None
    assert v.omnibus is not None
    assert v.is_sound is True


def test_verdict_with_a_single_arm_reports_no_comparison(
    ledger_conn: sqlite3.Connection,
) -> None:
    seeded = seed_wave(ledger_conn, n_tasks=2, arm_keys=("arm_a",))
    v = verdict(ledger_conn, seeded.wave_id)
    assert v.paired is None
    assert v.omnibus is None
    assert "no comparison possible" in v.summary
