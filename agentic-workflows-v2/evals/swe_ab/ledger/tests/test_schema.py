"""Tests for schema.sql: DDL, FK enforcement, and the ledger's triggers.

The triggers are the point of this schema (append-only history, substrate
consistency, no grading a failed trial) so they get the most coverage.
"""

from __future__ import annotations

import sqlite3
from typing import Any

import pytest

from ledger.models import (
    TABLE_ORDER,
    Arm,
    ArmConfig,
    Blob,
    Campaign,
    Grade,
    Grader,
    Image,
    JudgeCalibration,
    Model,
    PlanCell,
    PriceSnapshot,
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

# ---------------------------------------------------------------------
# Row builders: one minimal-but-valid row per table, so the happy-path
# test reads as a plain list of "insert this" rather than a wall of
# hand-rolled tuples. Each builder accepts overrides via **kwargs so
# negative tests can mutate exactly the field under test.
# ---------------------------------------------------------------------


def _insert(conn: sqlite3.Connection, table: str, row: tuple[object, ...]) -> None:
    # `table` is always one of the fixed literal names this module passes in
    # (never external input), so the f-string is a table-name template, not
    # an injection vector.
    placeholders = ",".join(["?"] * len(row))
    conn.execute(f"INSERT INTO {table} VALUES ({placeholders})", row)  # noqa: S608


def make_blob(digest: str = "sha256:" + "a" * 64, **overrides: object) -> Blob:
    fields: dict[str, Any] = dict(
        digest=digest,
        media_type="text/plain",
        size_bytes=10,
        retention="durable",
        stored_at="2026-01-01T00:00:00Z",
    )
    fields.update(overrides)
    return Blob(**fields)


def make_model(model_id: str = "mdl_test", **overrides: object) -> Model:
    fields: dict[str, Any] = dict(
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
    fields.update(overrides)
    return Model(**fields)


def make_price_snapshot(
    snapshot_id: str = "snp_test", model_id: str = "mdl_test", **overrides: object
) -> PriceSnapshot:
    fields: dict[str, Any] = dict(
        snapshot_id=snapshot_id,
        model_id=model_id,
        observed_at="2026-01-01T00:00:00Z",
        price_in=1.0,
        price_out=2.0,
        source="acme-pricing-page",
    )
    fields.update(overrides)
    return PriceSnapshot(**fields)


def make_prompt(
    prompt_id: str = "prm_test",
    text_digest: str = "sha256:" + "a" * 64,
    **overrides: object,
) -> Prompt:
    fields: dict[str, Any] = dict(
        prompt_id=prompt_id, role="system", text_digest=text_digest
    )
    fields.update(overrides)
    return Prompt(**fields)


def make_workflow(workflow_id: str = "wfl_test", **overrides: object) -> Workflow:
    fields: dict[str, Any] = dict(
        workflow_id=workflow_id,
        name="single-shot",
        yaml_digest="sha256:" + "b" * 64,
        step_count=1,
    )
    fields.update(overrides)
    return Workflow(**fields)


def make_workflow_prompt(
    workflow_id: str = "wfl_test", prompt_id: str = "prm_test"
) -> WorkflowPrompt:
    return WorkflowPrompt(workflow_id=workflow_id, prompt_id=prompt_id)


def make_grader(grader_id: str = "grd_test", **overrides: object) -> Grader:
    fields: dict[str, Any] = dict(
        grader_id=grader_id,
        name="exact_match",
        kind="deterministic",
        module_digest="sha256:" + "c" * 64,
        rubric_id=None,
    )
    fields.update(overrides)
    return Grader(**fields)


def make_judge_calibration(
    calibration_id: str = "cal_test",
    grader_id: str = "grd_test",
    judge_model_id: str = "mdl_test",
    **overrides: object,
) -> JudgeCalibration:
    fields: dict[str, Any] = dict(
        calibration_id=calibration_id,
        grader_id=grader_id,
        judge_model_id=judge_model_id,
        tnr=0.97,
        tpr=0.9,
        wilson_lower=0.86,
        n=200,
        calibrated_at="2026-01-01T00:00:00Z",
        expires_at="2026-04-01T00:00:00Z",
    )
    fields.update(overrides)
    return JudgeCalibration(**fields)


def make_image(
    image_id: str = "img_test", digest: str = "sha256:" + "d" * 64, **overrides: object
) -> Image:
    fields: dict[str, Any] = dict(
        image_id=image_id,
        repo="ghcr.io/acme/swebench-runner",
        tag="latest",
        digest=digest,
        pulled_at="2026-01-01T00:00:00Z",
    )
    fields.update(overrides)
    return Image(**fields)


def make_task_set(task_set_id: str = "tsk_test", **overrides: object) -> TaskSet:
    fields: dict[str, Any] = dict(
        task_set_id=task_set_id,
        name="swebench-lite",
        source="hf:princeton-nlp/SWE-bench_Lite",
        revision="v1",
        filter_expr=None,
        row_count=300,
        licence=None,
        built_at="2026-01-01T00:00:00Z",
    )
    fields.update(overrides)
    return TaskSet(**fields)


def make_task(
    task_id: str = "tas_test",
    task_set_id: str = "tsk_test",
    image_id: str = "img_test",
    problem_blob: str | None = "sha256:" + "a" * 64,
    source_blob: str | None = "sha256:" + "a" * 64,
    **overrides: object,
) -> Task:
    fields: dict[str, Any] = dict(
        task_id=task_id,
        task_set_id=task_set_id,
        instance_id="acme__repo-123",
        repo="acme/repo",
        base_commit="deadbeef",
        target_file="src/module.py",
        image_id=image_id,
        fail_to_pass='["tests/test_module.py::test_x"]',  # noqa: S106 -- schema column, not a secret
        difficulty=None,
        contamination_risk=None,
        safe_after=None,
        problem_blob=problem_blob,
        source_blob=source_blob,
        max_changed_lines=None,
    )
    fields.update(overrides)
    return Task(**fields)


def make_substrate(
    substrate_id: str = "sub_test",
    task_set_id: str = "tsk_test",
    grader_id: str = "grd_test",
    **overrides: object,
) -> Substrate:
    fields: dict[str, Any] = dict(
        substrate_id=substrate_id,
        task_set_id=task_set_id,
        harness_version="1.0.0",
        runtime_digest="sha256:" + "e" * 64,
        evalkit_version="0.3.0",
        grader_id=grader_id,
        image_digest_set="f" * 16,
    )
    fields.update(overrides)
    return Substrate(**fields)


def make_arm_config(
    arm_config_id: str = "arc_test",
    model_id: str = "mdl_test",
    workflow_id: str = "wfl_test",
    **overrides: object,
) -> ArmConfig:
    fields: dict[str, Any] = dict(
        arm_config_id=arm_config_id,
        model_id=model_id,
        temperature=0.2,
        top_p=1.0,
        top_k=None,
        max_tokens=4096,
        seed=None,
        stop_sequences='["</s>"]',
        context_window_used=8192,
        workflow_id=workflow_id,
        retrieval_mode="oracle",
        tool_policy=None,
    )
    fields.update(overrides)
    return ArmConfig(**fields)


def make_campaign(
    campaign_id: str = "cmp_test", name: str = "wave-1-campaign", **overrides: object
) -> Campaign:
    fields: dict[str, Any] = dict(
        campaign_id=campaign_id,
        name=name,
        question="Does model X beat model Y on SWE-bench Lite?",
        primary_contrast=None,
        created_at="2026-01-01T00:00:00Z",
        status="open",
    )
    fields.update(overrides)
    return Campaign(**fields)


def make_arm(
    arm_id: str = "a_test",
    campaign_id: str = "cmp_test",
    arm_config_id: str = "arc_test",
    arm_key: str = "control",
    **overrides: object,
) -> Arm:
    fields: dict[str, Any] = dict(
        arm_id=arm_id,
        campaign_id=campaign_id,
        arm_key=arm_key,
        arm_config_id=arm_config_id,
        role="control",
    )
    fields.update(overrides)
    return Arm(**fields)


def make_wave(
    wave_id: str = "wav_test",
    campaign_id: str = "cmp_test",
    substrate_id: str = "sub_test",
    wave_no: int = 1,
    **overrides: object,
) -> Wave:
    fields: dict[str, Any] = dict(
        wave_id=wave_id,
        campaign_id=campaign_id,
        wave_no=wave_no,
        substrate_id=substrate_id,
        stratification=None,
        planned_runs=1,
        opened_at="2026-01-01T00:00:00Z",
    )
    fields.update(overrides)
    return Wave(**fields)


def make_wave_task(wave_id: str = "wav_test", task_id: str = "tas_test") -> WaveTask:
    return WaveTask(wave_id=wave_id, task_id=task_id)


def make_plan_cell(
    wave_id: str = "wav_test",
    arm_id: str = "a_test",
    task_id: str = "tas_test",
    run_idx: int = 1,
    **overrides: object,
) -> PlanCell:
    fields: dict[str, Any] = dict(
        wave_id=wave_id,
        arm_id=arm_id,
        task_id=task_id,
        run_idx=run_idx,
        status="planned",
    )
    fields.update(overrides)
    return PlanCell(**fields)


def make_trial(
    wave_id: str = "wav_test",
    arm_id: str = "a_test",
    task_id: str = "tas_test",
    run_idx: int = 1,
    trial_id: str = "trl_test",
    substrate_id: str = "sub_test",
    arm_config_id: str = "arc_test",
    model_id: str = "mdl_test",
    **overrides: object,
) -> Trial:
    fields: dict[str, Any] = dict(
        wave_id=wave_id,
        arm_id=arm_id,
        task_id=task_id,
        run_idx=run_idx,
        trial_id=trial_id,
        batch_id="batch_test",
        substrate_id=substrate_id,
        arm_config_id=arm_config_id,
        model_id=model_id,
        models_answered='["mdl_test"]',
        started_at="2026-01-01T00:00:00Z",
        finished_at="2026-01-01T00:01:00Z",
        wall_seconds=60.0,
        op_status="ok",
        error_kind=None,
        error_blob=None,
        tokens_in=100,
        tokens_out=200,
        trace_id="trace_test",
        transcript_blob=None,
        answer_blob=None,
        supersedes=None,
    )
    fields.update(overrides)
    return Trial(**fields)


def make_step_usage(
    trial_id: str = "trl_test", step_idx: int = 0, **overrides: object
) -> StepUsage:
    fields: dict[str, Any] = dict(
        trial_id=trial_id,
        step_idx=step_idx,
        step_name="generate_patch",
        model_id="mdl_test",
        tokens_in=100,
        tokens_out=200,
        latency_ms=500.0,
        status="ok",
    )
    fields.update(overrides)
    return StepUsage(**fields)


def make_spend(
    spend_id: str = "spd_test", trial_id: str = "trl_test", **overrides: object
) -> Spend:
    fields: dict[str, Any] = dict(
        spend_id=spend_id,
        trial_id=trial_id,
        price_snapshot_id="snp_test",
        cost_usd=0.05,
        gpu_seconds=None,
        computed_at="2026-01-01T00:01:00Z",
    )
    fields.update(overrides)
    return Spend(**fields)


def make_grade(
    grade_id: str = "gra_test", trial_id: str = "trl_test", **overrides: object
) -> Grade:
    fields: dict[str, Any] = dict(
        grade_id=grade_id,
        trial_id=trial_id,
        grader_id="grd_test",
        status="pass",
        outcome="pass",
        score=1.0,
        evidence_blob=None,
        oracle_provenance=None,
        graded_at="2026-01-01T00:01:30Z",
        supersedes=None,
    )
    fields.update(overrides)
    return Grade(**fields)


def insert_base_chain(conn: sqlite3.Connection) -> None:
    """Insert one valid row into every reference/design table up through
    plan_cell, using the builders' defaults. Tests build on top of this
    with their own trial/grade rows.
    """
    _insert(conn, "blob", make_blob().to_row())
    _insert(conn, "model", make_model().to_row())
    _insert(conn, "price_snapshot", make_price_snapshot().to_row())
    _insert(conn, "prompt", make_prompt().to_row())
    _insert(conn, "workflow", make_workflow().to_row())
    _insert(conn, "workflow_prompt", make_workflow_prompt().to_row())
    _insert(conn, "grader", make_grader().to_row())
    _insert(conn, "judge_calibration", make_judge_calibration().to_row())
    _insert(conn, "image", make_image().to_row())
    _insert(conn, "task_set", make_task_set().to_row())
    _insert(conn, "task", make_task().to_row())
    _insert(conn, "substrate", make_substrate().to_row())
    _insert(conn, "arm_config", make_arm_config().to_row())
    _insert(conn, "campaign", make_campaign().to_row())
    _insert(conn, "arm", make_arm().to_row())
    _insert(conn, "wave", make_wave().to_row())
    _insert(conn, "wave_task", make_wave_task().to_row())
    _insert(conn, "plan_cell", make_plan_cell().to_row())


# ---------------------------------------------------------------------
# Basic DDL sanity
# ---------------------------------------------------------------------


def test_schema_applies_cleanly_and_version_is_1(
    ledger_conn: sqlite3.Connection,
) -> None:
    row = ledger_conn.execute(
        "SELECT value FROM schema_meta WHERE key = 'schema_version'"
    ).fetchone()
    assert row is not None
    assert row["value"] == "1"


def test_foreign_keys_pragma_is_on(ledger_conn: sqlite3.Connection) -> None:
    assert ledger_conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1


# ---------------------------------------------------------------------
# Foreign key enforcement
# ---------------------------------------------------------------------


def test_foreign_key_violation_is_rejected(ledger_conn: sqlite3.Connection) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        _insert(
            ledger_conn,
            "price_snapshot",
            make_price_snapshot(model_id="mdl_does_not_exist").to_row(),
        )


# ---------------------------------------------------------------------
# Full happy path: one valid row per table, in TABLE_ORDER
# ---------------------------------------------------------------------


def test_full_valid_insert_path_across_every_table(
    ledger_conn: sqlite3.Connection,
) -> None:
    insert_base_chain(ledger_conn)
    _insert(ledger_conn, "trial", make_trial().to_row())
    _insert(ledger_conn, "step_usage", make_step_usage().to_row())
    _insert(ledger_conn, "spend", make_spend().to_row())
    _insert(ledger_conn, "grade", make_grade().to_row())
    ledger_conn.commit()

    # `table` iterates the fixed TABLE_ORDER tuple, never external input.
    for table in TABLE_ORDER:
        count = ledger_conn.execute(
            f"SELECT COUNT(*) FROM {table}"  # noqa: S608
        ).fetchone()[0]
        assert count == 1, f"expected exactly one row in {table}"


# ---------------------------------------------------------------------
# Append-only triggers
# ---------------------------------------------------------------------


def test_trial_update_raises(ledger_conn: sqlite3.Connection) -> None:
    insert_base_chain(ledger_conn)
    _insert(ledger_conn, "trial", make_trial().to_row())
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        ledger_conn.execute(
            "UPDATE trial SET op_status = 'error' WHERE trial_id = 'trl_test'"
        )


def test_trial_delete_raises(ledger_conn: sqlite3.Connection) -> None:
    insert_base_chain(ledger_conn)
    _insert(ledger_conn, "trial", make_trial().to_row())
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        ledger_conn.execute("DELETE FROM trial WHERE trial_id = 'trl_test'")


def test_grade_update_raises(ledger_conn: sqlite3.Connection) -> None:
    insert_base_chain(ledger_conn)
    _insert(ledger_conn, "trial", make_trial().to_row())
    _insert(ledger_conn, "grade", make_grade().to_row())
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        ledger_conn.execute("UPDATE grade SET score = 0.0 WHERE grade_id = 'gra_test'")


def test_grade_delete_raises(ledger_conn: sqlite3.Connection) -> None:
    insert_base_chain(ledger_conn)
    _insert(ledger_conn, "trial", make_trial().to_row())
    _insert(ledger_conn, "grade", make_grade().to_row())
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        ledger_conn.execute("DELETE FROM grade WHERE grade_id = 'gra_test'")


def test_spend_update_raises(ledger_conn: sqlite3.Connection) -> None:
    insert_base_chain(ledger_conn)
    _insert(ledger_conn, "trial", make_trial().to_row())
    _insert(ledger_conn, "spend", make_spend().to_row())
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        ledger_conn.execute(
            "UPDATE spend SET cost_usd = 1.0 WHERE spend_id = 'spd_test'"
        )


def test_spend_delete_raises(ledger_conn: sqlite3.Connection) -> None:
    insert_base_chain(ledger_conn)
    _insert(ledger_conn, "trial", make_trial().to_row())
    _insert(ledger_conn, "spend", make_spend().to_row())
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        ledger_conn.execute("DELETE FROM spend WHERE spend_id = 'spd_test'")


def test_step_usage_update_raises(ledger_conn: sqlite3.Connection) -> None:
    insert_base_chain(ledger_conn)
    _insert(ledger_conn, "trial", make_trial().to_row())
    _insert(ledger_conn, "step_usage", make_step_usage().to_row())
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        ledger_conn.execute(
            "UPDATE step_usage SET status = 'error' WHERE trial_id = 'trl_test' AND step_idx = 0"
        )


def test_step_usage_delete_raises(ledger_conn: sqlite3.Connection) -> None:
    insert_base_chain(ledger_conn)
    _insert(ledger_conn, "trial", make_trial().to_row())
    _insert(ledger_conn, "step_usage", make_step_usage().to_row())
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        ledger_conn.execute(
            "DELETE FROM step_usage WHERE trial_id = 'trl_test' AND step_idx = 0"
        )


# ---------------------------------------------------------------------
# Substrate-match trigger
# ---------------------------------------------------------------------


def test_trial_with_mismatched_substrate_raises(
    ledger_conn: sqlite3.Connection,
) -> None:
    insert_base_chain(ledger_conn)
    # A second, real substrate that is simply not the one on `wav_test`.
    _insert(
        ledger_conn,
        "substrate",
        make_substrate(substrate_id="sub_other", harness_version="2.0.0").to_row(),
    )
    with pytest.raises(sqlite3.IntegrityError, match="substrate_id must match"):
        _insert(ledger_conn, "trial", make_trial(substrate_id="sub_other").to_row())


def test_trial_with_matching_substrate_succeeds(
    ledger_conn: sqlite3.Connection,
) -> None:
    insert_base_chain(ledger_conn)
    # Sanity check for the positive case, so the negative test above is
    # known to be testing the mismatch and not some unrelated failure.
    _insert(ledger_conn, "trial", make_trial(substrate_id="sub_test").to_row())
    row = ledger_conn.execute(
        "SELECT trial_id FROM trial WHERE trial_id = 'trl_test'"
    ).fetchone()
    assert row is not None


# ---------------------------------------------------------------------
# No-grade-on-failed-trial trigger
# ---------------------------------------------------------------------


def test_grade_on_non_ok_trial_raises(ledger_conn: sqlite3.Connection) -> None:
    insert_base_chain(ledger_conn)
    _insert(
        ledger_conn,
        "trial",
        make_trial(op_status="timeout", finished_at=None, wall_seconds=None).to_row(),
    )
    with pytest.raises(sqlite3.IntegrityError, match="op_status is not ok"):
        _insert(ledger_conn, "grade", make_grade().to_row())


@pytest.mark.parametrize(
    "op_status", ["error", "timeout", "cancelled", "unavailable", "abstain"]
)
def test_grade_on_every_non_ok_op_status_raises(
    ledger_conn: sqlite3.Connection, op_status: str
) -> None:
    insert_base_chain(ledger_conn)
    _insert(
        ledger_conn,
        "trial",
        make_trial(op_status=op_status, finished_at=None, wall_seconds=None).to_row(),
    )
    with pytest.raises(sqlite3.IntegrityError, match="op_status is not ok"):
        _insert(ledger_conn, "grade", make_grade().to_row())


def test_grade_on_ok_trial_succeeds(ledger_conn: sqlite3.Connection) -> None:
    insert_base_chain(ledger_conn)
    _insert(ledger_conn, "trial", make_trial(op_status="ok").to_row())
    _insert(ledger_conn, "grade", make_grade().to_row())
    row = ledger_conn.execute(
        "SELECT grade_id FROM grade WHERE grade_id = 'gra_test'"
    ).fetchone()
    assert row is not None


# ---------------------------------------------------------------------
# grade status/outcome CHECK constraints
# ---------------------------------------------------------------------


def test_grade_abstain_with_non_null_outcome_raises(
    ledger_conn: sqlite3.Connection,
) -> None:
    insert_base_chain(ledger_conn)
    _insert(ledger_conn, "trial", make_trial().to_row())
    with pytest.raises(sqlite3.IntegrityError):
        _insert(
            ledger_conn,
            "grade",
            make_grade(status="abstain", outcome="pass").to_row(),
        )


def test_grade_pass_with_null_outcome_raises(ledger_conn: sqlite3.Connection) -> None:
    insert_base_chain(ledger_conn)
    _insert(ledger_conn, "trial", make_trial().to_row())
    with pytest.raises(sqlite3.IntegrityError):
        _insert(ledger_conn, "grade", make_grade(status="pass", outcome=None).to_row())


def test_grade_pass_with_mismatched_outcome_raises(
    ledger_conn: sqlite3.Connection,
) -> None:
    insert_base_chain(ledger_conn)
    _insert(ledger_conn, "trial", make_trial().to_row())
    with pytest.raises(sqlite3.IntegrityError):
        _insert(
            ledger_conn,
            "grade",
            make_grade(status="pass", outcome="fail").to_row(),
        )


def test_grade_abstain_with_null_outcome_succeeds(
    ledger_conn: sqlite3.Connection,
) -> None:
    insert_base_chain(ledger_conn)
    _insert(ledger_conn, "trial", make_trial().to_row())
    _insert(
        ledger_conn,
        "grade",
        make_grade(status="abstain", outcome=None, score=None).to_row(),
    )
    row = ledger_conn.execute(
        "SELECT status FROM grade WHERE grade_id = 'gra_test'"
    ).fetchone()
    assert row["status"] == "abstain"


# ---------------------------------------------------------------------
# image digest CHECK constraint
# ---------------------------------------------------------------------


def test_image_digest_without_sha256_prefix_raises(
    ledger_conn: sqlite3.Connection,
) -> None:
    with pytest.raises(sqlite3.IntegrityError):
        _insert(ledger_conn, "image", make_image(digest="not-a-real-digest").to_row())


def test_image_digest_with_sha256_prefix_succeeds(
    ledger_conn: sqlite3.Connection,
) -> None:
    _insert(ledger_conn, "image", make_image().to_row())
    row = ledger_conn.execute(
        "SELECT digest FROM image WHERE image_id = 'img_test'"
    ).fetchone()
    assert row["digest"].startswith("sha256:")
