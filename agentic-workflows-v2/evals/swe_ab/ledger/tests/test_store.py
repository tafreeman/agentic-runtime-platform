"""Tests for ledger.store: connection setup, register/append semantics,
cross-row validation, and JSONL export/import.

Row builders here are named with an `mk_` prefix (rather than
`test_schema.py`'s `make_*`) precisely so nothing here can be confused
with, or accidentally shadow, that module's identically-shaped helpers —
see `ledger/tests/conftest.py`'s docstring on why same-named things across
this package's test modules are worth avoiding on principle, even though
plain module-level functions (unlike fixtures) do not actually collide via
pytest's namespace.
"""

from __future__ import annotations

import dataclasses
import itertools
import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from ledger.models import (
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
    Substrate,
    Task,
    TaskSet,
    Trial,
    Wave,
    WaveTask,
    Workflow,
    WorkflowPrompt,
)
from ledger.store import (
    JUDGE_TNR_FLOOR,
    JUDGE_TPR_FLOOR,
    ArmsUnbalanced,
    JudgeNotCalibrated,
    LedgerIntegrityError,
    LedgerStore,
    SchemaVersionMismatch,
    UnknownWave,
    open_ledger,
)

# ---------------------------------------------------------------------
# Row builders: minimal-but-valid defaults, overridable via **kwargs.
# ---------------------------------------------------------------------


def mk_blob(digest: str = "sha256:" + "a" * 64, **overrides: object) -> Blob:
    fields: dict[str, Any] = dict(
        digest=digest,
        media_type="text/plain",
        size_bytes=10,
        retention="durable",
        stored_at="2026-01-01T00:00:00Z",
    )
    fields.update(overrides)
    return Blob(**fields)


def mk_model(model_id: str = "mdl_test", **overrides: object) -> Model:
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


def mk_price_snapshot(
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


def mk_prompt(
    prompt_id: str = "prm_test",
    text_digest: str = "sha256:" + "a" * 64,
    **overrides: object,
) -> Prompt:
    fields: dict[str, Any] = dict(
        prompt_id=prompt_id, role="system", text_digest=text_digest
    )
    fields.update(overrides)
    return Prompt(**fields)


def mk_workflow(workflow_id: str = "wfl_test", **overrides: object) -> Workflow:
    fields: dict[str, Any] = dict(
        workflow_id=workflow_id,
        name="single-shot",
        yaml_digest="sha256:" + "b" * 64,
        step_count=1,
    )
    fields.update(overrides)
    return Workflow(**fields)


def mk_workflow_prompt(
    workflow_id: str = "wfl_test", prompt_id: str = "prm_test"
) -> WorkflowPrompt:
    return WorkflowPrompt(workflow_id=workflow_id, prompt_id=prompt_id)


def mk_grader(grader_id: str = "grd_test", **overrides: object) -> Grader:
    fields: dict[str, Any] = dict(
        grader_id=grader_id,
        name="exact_match",
        kind="deterministic",
        module_digest="sha256:" + "c" * 64,
        rubric_id=None,
    )
    fields.update(overrides)
    return Grader(**fields)


def mk_judge_calibration(
    calibration_id: str = "cal_test",
    grader_id: str = "grd_judge",
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
        expires_at="2026-12-01T00:00:00Z",
    )
    fields.update(overrides)
    return JudgeCalibration(**fields)


def mk_image(
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


def mk_task_set(task_set_id: str = "tsk_test", **overrides: object) -> TaskSet:
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


def mk_task(
    task_id: str = "tas_test",
    task_set_id: str = "tsk_test",
    image_id: str = "img_test",
    instance_id: str = "acme__repo-123",
    **overrides: object,
) -> Task:
    fields: dict[str, Any] = dict(
        task_id=task_id,
        task_set_id=task_set_id,
        instance_id=instance_id,
        repo="acme/repo",
        base_commit="deadbeef",
        target_file="src/module.py",
        image_id=image_id,
        fail_to_pass='["tests/test_module.py::test_x"]',  # noqa: S106
        difficulty=None,
        contamination_risk=None,
        safe_after=None,
        problem_blob=None,
        source_blob=None,
        max_changed_lines=None,
    )
    fields.update(overrides)
    return Task(**fields)


def mk_substrate(
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


def mk_arm_config(
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


def mk_campaign(
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


def mk_arm(
    arm_id: str = "arm_control",
    campaign_id: str = "cmp_test",
    arm_config_id: str = "arc_test",
    arm_key: str = "control",
    role: str = "control",
    **overrides: object,
) -> Arm:
    fields: dict[str, Any] = dict(
        arm_id=arm_id,
        campaign_id=campaign_id,
        arm_key=arm_key,
        arm_config_id=arm_config_id,
        role=role,
    )
    fields.update(overrides)
    return Arm(**fields)


def mk_wave(
    wave_id: str = "wav_test",
    campaign_id: str = "cmp_test",
    substrate_id: str = "sub_test",
    wave_no: int = 1,
    opened_at: str = "2026-02-01T00:00:00Z",
    **overrides: object,
) -> Wave:
    fields: dict[str, Any] = dict(
        wave_id=wave_id,
        campaign_id=campaign_id,
        wave_no=wave_no,
        substrate_id=substrate_id,
        stratification=None,
        planned_runs=1,
        opened_at=opened_at,
    )
    fields.update(overrides)
    return Wave(**fields)


def mk_wave_task(wave_id: str = "wav_test", task_id: str = "tas_test") -> WaveTask:
    return WaveTask(wave_id=wave_id, task_id=task_id)


def mk_plan_cell(
    wave_id: str = "wav_test",
    arm_id: str = "arm_control",
    task_id: str = "tas_test",
    run_idx: int = 1,
    status: str = "planned",
) -> PlanCell:
    return PlanCell(
        wave_id=wave_id, arm_id=arm_id, task_id=task_id, run_idx=run_idx, status=status
    )


def mk_trial(
    wave_id: str = "wav_test",
    arm_id: str = "arm_control",
    task_id: str = "tas_test",
    run_idx: int = 1,
    trial_id: str = "trl_test",
    substrate_id: str = "sub_test",
    arm_config_id: str = "arc_control",
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
        started_at="2026-02-01T00:00:00Z",
        finished_at="2026-02-01T00:01:00Z",
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


def mk_grade(
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
        graded_at="2026-02-01T00:01:30Z",
        supersedes=None,
    )
    fields.update(overrides)
    return Grade(**fields)


# ---------------------------------------------------------------------
# Fixture bundle: registers one full, valid design chain (two tasks, two
# arms) and returns the ids tests need. Built with `LedgerStore.register`
# itself, so every test that uses it also exercises register().
# ---------------------------------------------------------------------


@dataclasses.dataclass(frozen=True)
class WaveFixture:
    campaign_id: str
    wave_id: str
    substrate_id: str
    grader_id: str
    task_ids: tuple[str, str]
    arm_control_id: str
    arm_treatment_id: str
    model_id: str


def seed_wave_fixture(store: LedgerStore) -> WaveFixture:
    store.register(mk_blob())
    store.register(mk_model())
    store.register(mk_prompt())
    store.register(mk_workflow())
    store.register(mk_workflow_prompt())
    store.register(mk_grader())
    store.register(mk_image())
    store.register(mk_task_set())
    store.register(mk_task(task_id="tas_1", instance_id="acme__repo-1"))
    store.register(mk_task(task_id="tas_2", instance_id="acme__repo-2"))
    store.register(mk_substrate())
    store.register(mk_arm_config(arm_config_id="arc_control"))
    store.register(mk_arm_config(arm_config_id="arc_treat"))
    store.register(mk_campaign())
    store.register(
        mk_arm(arm_id="arm_control", arm_key="control", arm_config_id="arc_control")
    )
    store.register(
        mk_arm(
            arm_id="arm_treat",
            arm_key="treatment",
            arm_config_id="arc_treat",
            role="treatment",
        )
    )
    store.register(mk_wave())
    store.register(mk_wave_task(task_id="tas_1"))
    store.register(mk_wave_task(task_id="tas_2"))
    for arm_id in ("arm_control", "arm_treat"):
        for task_id in ("tas_1", "tas_2"):
            store.register(mk_plan_cell(arm_id=arm_id, task_id=task_id))
    return WaveFixture(
        campaign_id="cmp_test",
        wave_id="wav_test",
        substrate_id="sub_test",
        grader_id="grd_test",
        task_ids=("tas_1", "tas_2"),
        arm_control_id="arm_control",
        arm_treatment_id="arm_treat",
        model_id="mdl_test",
    )


@pytest.fixture
def ledger_store(ledger_conn: sqlite3.Connection) -> LedgerStore:
    return LedgerStore(ledger_conn)


# ---------------------------------------------------------------------
# open_ledger: pragmas
# ---------------------------------------------------------------------


def test_open_ledger_enables_foreign_keys(tmp_path: Path) -> None:
    conn = open_ledger(tmp_path / "fk.db")
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO price_snapshot "
            "(snapshot_id, model_id, observed_at, price_in, price_out, source) "
            "VALUES ('snp_x', 'mdl_does_not_exist', '2026-01-01T00:00:00Z', 1, 2, 'x')"
        )
    conn.close()


def test_open_ledger_memory_has_foreign_keys_on() -> None:
    conn = open_ledger(":memory:")
    assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    conn.close()


def test_open_ledger_journal_mode_is_wal_for_file_backed_db(tmp_path: Path) -> None:
    conn = open_ledger(tmp_path / "wal.db")
    mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert str(mode).lower() == "wal"
    conn.close()


def test_open_ledger_sets_busy_timeout(tmp_path: Path) -> None:
    conn = open_ledger(tmp_path / "busy.db")
    assert conn.execute("PRAGMA busy_timeout").fetchone()[0] >= 5000
    conn.close()


def test_open_ledger_row_factory_is_row(tmp_path: Path) -> None:
    conn = open_ledger(tmp_path / "row.db")
    assert conn.row_factory is sqlite3.Row
    conn.close()


def test_open_ledger_accepts_memory_and_applies_schema() -> None:
    conn = open_ledger(":memory:")
    row = conn.execute(
        "SELECT value FROM schema_meta WHERE key = 'schema_version'"
    ).fetchone()
    assert row["value"] == "1"
    conn.close()


def test_open_ledger_missing_file_with_create_false_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        open_ledger(tmp_path / "does-not-exist.db", create=False)


def test_open_ledger_reopen_reuses_existing_data(tmp_path: Path) -> None:
    db_path = tmp_path / "reopen.db"
    conn1 = open_ledger(db_path)
    LedgerStore(conn1).register(mk_blob())
    conn1.commit()
    conn1.close()

    conn2 = open_ledger(db_path, create=False)
    row = conn2.execute(
        "SELECT digest FROM blob WHERE digest = ?", (mk_blob().digest,)
    ).fetchone()
    assert row is not None
    conn2.close()


def test_open_ledger_schema_version_mismatch_raises(tmp_path: Path) -> None:
    db_path = tmp_path / "stale.db"
    conn = open_ledger(db_path)
    conn.execute("UPDATE schema_meta SET value = '999' WHERE key = 'schema_version'")
    conn.commit()
    conn.close()

    with pytest.raises(SchemaVersionMismatch):
        open_ledger(db_path, create=False)


def test_open_ledger_closes_connection_on_schema_version_mismatch(
    tmp_path: Path,
) -> None:
    """A failed `open_ledger` must not strand an open connection: the file
    handle it briefly opened to check `schema_version` has to be closed
    before it re-raises, or every failed open leaks one.
    """
    db_path = tmp_path / "stale2.db"
    seed_conn = open_ledger(db_path)
    seed_conn.execute(
        "UPDATE schema_meta SET value = '999' WHERE key = 'schema_version'"
    )
    seed_conn.commit()
    seed_conn.close()

    with pytest.raises(SchemaVersionMismatch):
        open_ledger(db_path, create=False)

    # On Windows, an sqlite3 connection still holding the file open would
    # make this delete fail (PermissionError / WinError 32); it succeeding
    # is direct proof the failed open_ledger() call closed its connection.
    db_path.unlink()


# ---------------------------------------------------------------------
# register(): idempotency
# ---------------------------------------------------------------------


def test_register_is_idempotent_same_id_one_row(ledger_store: LedgerStore) -> None:
    first = ledger_store.register(mk_model())
    second = ledger_store.register(mk_model())
    assert first == second
    count = ledger_store.connection.execute("SELECT COUNT(*) FROM model").fetchone()[0]
    assert count == 1


def test_register_returns_the_primary_key(ledger_store: LedgerStore) -> None:
    result = ledger_store.register(mk_blob(digest="sha256:" + "9" * 64))
    assert result == "sha256:" + "9" * 64


def test_register_composite_key_entity_is_idempotent(
    ledger_store: LedgerStore,
) -> None:
    ledger_store.register(mk_blob())
    ledger_store.register(mk_workflow())
    ledger_store.register(mk_prompt())
    first = ledger_store.register(mk_workflow_prompt())
    second = ledger_store.register(mk_workflow_prompt())
    assert first == second
    count = ledger_store.connection.execute(
        "SELECT COUNT(*) FROM workflow_prompt"
    ).fetchone()[0]
    assert count == 1


def test_register_rejects_unsupported_type(ledger_store: LedgerStore) -> None:
    with pytest.raises(TypeError):
        ledger_store.register(mk_trial())  # type: ignore[arg-type]


def test_register_full_wave_fixture_inserts_expected_row_counts(
    ledger_store: LedgerStore,
) -> None:
    seed_wave_fixture(ledger_store)
    conn = ledger_store.connection
    assert conn.execute("SELECT COUNT(*) FROM task").fetchone()[0] == 2
    assert conn.execute("SELECT COUNT(*) FROM arm").fetchone()[0] == 2
    assert conn.execute("SELECT COUNT(*) FROM plan_cell").fetchone()[0] == 4


# ---------------------------------------------------------------------
# append_*: happy path + append-only surfaces as a typed ledger error
# ---------------------------------------------------------------------


def test_append_trial_then_grade_succeeds(ledger_store: LedgerStore) -> None:
    fixture = seed_wave_fixture(ledger_store)
    ledger_store.append_trial(
        mk_trial(task_id=fixture.task_ids[0], arm_id=fixture.arm_control_id)
    )
    ledger_store.append_grade(mk_grade(grader_id=fixture.grader_id))
    conn = ledger_store.connection
    assert conn.execute("SELECT COUNT(*) FROM trial").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM grade").fetchone()[0] == 1


def test_append_trial_duplicate_identity_raises_ledger_integrity_error(
    ledger_store: LedgerStore,
) -> None:
    fixture = seed_wave_fixture(ledger_store)
    trial = mk_trial(task_id=fixture.task_ids[0], arm_id=fixture.arm_control_id)
    ledger_store.append_trial(trial)
    with pytest.raises(LedgerIntegrityError) as excinfo:
        ledger_store.append_trial(trial)
    # A clear, ledger-typed error, not a bare driver exception.
    assert not isinstance(excinfo.value, sqlite3.IntegrityError)
    assert str(excinfo.value)


def test_append_trial_same_cell_new_trial_id_without_supersedes_raises(
    ledger_store: LedgerStore,
) -> None:
    """A second, non-correcting trial claiming the same design cell (same
    wave_id/arm_id/task_id/run_idx) must still be rejected even with a
    distinct trial_id -- `idx_trial_active_cell` covers what the old
    composite PRIMARY KEY used to."""
    fixture = seed_wave_fixture(ledger_store)
    ledger_store.append_trial(
        mk_trial(
            trial_id="trl_first",
            task_id=fixture.task_ids[0],
            arm_id=fixture.arm_control_id,
        )
    )
    with pytest.raises(LedgerIntegrityError):
        ledger_store.append_trial(
            mk_trial(
                trial_id="trl_second",
                task_id=fixture.task_ids[0],
                arm_id=fixture.arm_control_id,
            )
        )


def test_append_trial_correction_via_supersedes_succeeds(
    ledger_store: LedgerStore,
) -> None:
    """A correction -- new trial_id, `supersedes` pointing at the row it
    replaces, same design cell -- must be insertable; this is the whole
    reason `trial.supersedes` exists."""
    fixture = seed_wave_fixture(ledger_store)
    ledger_store.append_trial(
        mk_trial(
            trial_id="trl_original",
            task_id=fixture.task_ids[0],
            arm_id=fixture.arm_control_id,
        )
    )
    ledger_store.append_trial(
        mk_trial(
            trial_id="trl_correction",
            task_id=fixture.task_ids[0],
            arm_id=fixture.arm_control_id,
            supersedes="trl_original",
        )
    )
    conn = ledger_store.connection
    assert conn.execute("SELECT COUNT(*) FROM trial").fetchone()[0] == 2
    row = conn.execute(
        "SELECT supersedes FROM trial WHERE trial_id = 'trl_correction'"
    ).fetchone()
    assert row["supersedes"] == "trl_original"


def test_append_grade_on_non_ok_trial_raises_ledger_integrity_error(
    ledger_store: LedgerStore,
) -> None:
    fixture = seed_wave_fixture(ledger_store)
    ledger_store.append_trial(
        mk_trial(
            task_id=fixture.task_ids[0],
            arm_id=fixture.arm_control_id,
            op_status="timeout",
            finished_at=None,
            wall_seconds=None,
        )
    )
    with pytest.raises(LedgerIntegrityError):
        ledger_store.append_grade(mk_grade(grader_id=fixture.grader_id))


def test_append_batch_is_atomic_on_partial_failure(ledger_store: LedgerStore) -> None:
    fixture = seed_wave_fixture(ledger_store)
    good_trial = mk_trial(
        trial_id="trl_good",
        task_id=fixture.task_ids[0],
        arm_id=fixture.arm_control_id,
        run_idx=1,
    )
    bad_trial = mk_trial(
        trial_id="trl_bad",
        task_id=fixture.task_ids[1],
        arm_id=fixture.arm_control_id,
        run_idx=1,
        op_status="timeout",
        finished_at=None,
        wall_seconds=None,
    )
    # A grade for the *good* trial would succeed on its own, but batching
    # it alongside a grade for the timed-out trial (rejected by
    # trg_grade_requires_ok_trial) must roll back the whole batch,
    # including the otherwise-valid trial/grade pair.
    bad_grade = mk_grade(
        grade_id="gra_bad", trial_id="trl_bad", grader_id=fixture.grader_id
    )
    good_grade = mk_grade(
        grade_id="gra_good", trial_id="trl_good", grader_id=fixture.grader_id
    )

    with pytest.raises(LedgerIntegrityError):
        ledger_store.append_batch(
            trials=[good_trial, bad_trial],
            grades=[good_grade, bad_grade],
        )

    conn = ledger_store.connection
    assert conn.execute("SELECT COUNT(*) FROM trial").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM grade").fetchone()[0] == 0


def test_append_batch_all_valid_commits_everything(ledger_store: LedgerStore) -> None:
    fixture = seed_wave_fixture(ledger_store)
    trial = mk_trial(task_id=fixture.task_ids[0], arm_id=fixture.arm_control_id)
    grade = mk_grade(grader_id=fixture.grader_id)
    ledger_store.append_batch(trials=[trial], grades=[grade])
    conn = ledger_store.connection
    assert conn.execute("SELECT COUNT(*) FROM trial").fetchone()[0] == 1
    assert conn.execute("SELECT COUNT(*) FROM grade").fetchone()[0] == 1


# ---------------------------------------------------------------------
# check_judge_gating
# ---------------------------------------------------------------------

# `wave` has UNIQUE (campaign_id, wave_no); seed_wave_fixture already
# claims wave_no=1 on "cmp_test", and register()'s bare `ON CONFLICT DO
# NOTHING` swallows *any* unique-constraint clash, not just a primary-key
# one -- so reusing wave_no=1 here would silently no-op the insert (the
# wave_id passed in would never actually land, and register() would still
# hand back that wave_id as if it had). Each judge-wave variant gets its
# own wave_no to stay a genuinely distinct row.
_judge_wave_numbers = itertools.count(2)


def _seed_judge_wave(
    store: LedgerStore,
    *,
    suffix: str,
    tnr: float = 0.97,
    tpr: float = 0.9,
    expires_at: str = "2026-12-01T00:00:00Z",
    wave_opened_at: str = "2026-02-01T00:00:00Z",
    with_calibration: bool = True,
) -> str:
    """Seed a wave whose substrate uses a fresh judge-kind grader, plus
    (unless `with_calibration` is False) one calibration row for it, and
    return the wave_id.
    """
    grader_id = f"grd_judge_{suffix}"
    substrate_id = f"sub_judge_{suffix}"
    wave_id = f"wav_judge_{suffix}"
    store.register(mk_grader(grader_id=grader_id, kind="judge"))
    store.register(mk_substrate(substrate_id=substrate_id, grader_id=grader_id))
    store.register(
        mk_wave(
            wave_id=wave_id,
            substrate_id=substrate_id,
            wave_no=next(_judge_wave_numbers),
            opened_at=wave_opened_at,
        )
    )
    if with_calibration:
        store.register(
            mk_judge_calibration(
                calibration_id=f"cal_{suffix}",
                grader_id=grader_id,
                tnr=tnr,
                tpr=tpr,
                expires_at=expires_at,
            )
        )
    return wave_id


def test_check_judge_gating_passes_with_valid_calibration(
    ledger_store: LedgerStore,
) -> None:
    seed_wave_fixture(ledger_store)
    wave_id = _seed_judge_wave(ledger_store, suffix="ok")
    ledger_store.check_judge_gating(wave_id)  # must not raise


def test_check_judge_gating_raises_when_tnr_below_floor(
    ledger_store: LedgerStore,
) -> None:
    seed_wave_fixture(ledger_store)
    wave_id = _seed_judge_wave(
        ledger_store, suffix="lowtnr", tnr=JUDGE_TNR_FLOOR - 0.01
    )
    with pytest.raises(JudgeNotCalibrated):
        ledger_store.check_judge_gating(wave_id)


def test_check_judge_gating_raises_when_tpr_below_floor(
    ledger_store: LedgerStore,
) -> None:
    seed_wave_fixture(ledger_store)
    wave_id = _seed_judge_wave(
        ledger_store, suffix="lowtpr", tpr=JUDGE_TPR_FLOOR - 0.01
    )
    with pytest.raises(JudgeNotCalibrated):
        ledger_store.check_judge_gating(wave_id)


def test_check_judge_gating_raises_when_calibration_expired_before_wave_opened(
    ledger_store: LedgerStore,
) -> None:
    seed_wave_fixture(ledger_store)
    wave_id = _seed_judge_wave(
        ledger_store,
        suffix="expired",
        expires_at="2026-01-01T00:00:00Z",
        wave_opened_at="2026-02-01T00:00:00Z",
    )
    with pytest.raises(JudgeNotCalibrated):
        ledger_store.check_judge_gating(wave_id)


def test_check_judge_gating_raises_when_no_calibration_at_all(
    ledger_store: LedgerStore,
) -> None:
    seed_wave_fixture(ledger_store)
    wave_id = _seed_judge_wave(ledger_store, suffix="none", with_calibration=False)
    with pytest.raises(JudgeNotCalibrated):
        ledger_store.check_judge_gating(wave_id)


def test_check_judge_gating_ignores_non_judge_grader(
    ledger_store: LedgerStore,
) -> None:
    fixture = seed_wave_fixture(ledger_store)
    ledger_store.check_judge_gating(fixture.wave_id)  # deterministic grader: no-op


def test_check_judge_gating_unknown_wave_raises(ledger_store: LedgerStore) -> None:
    with pytest.raises(UnknownWave):
        ledger_store.check_judge_gating("wav_does_not_exist")


# ---------------------------------------------------------------------
# check_arm_balance
# ---------------------------------------------------------------------


def test_check_arm_balance_passes_when_arms_match(ledger_store: LedgerStore) -> None:
    fixture = seed_wave_fixture(ledger_store)
    for arm_id in (fixture.arm_control_id, fixture.arm_treatment_id):
        for task_id in fixture.task_ids:
            ledger_store.append_trial(
                mk_trial(
                    trial_id=f"trl_{arm_id}_{task_id}",
                    arm_id=arm_id,
                    task_id=task_id,
                    run_idx=1,
                )
            )
    ledger_store.check_arm_balance(fixture.wave_id)  # must not raise


def test_check_arm_balance_raises_when_arm_missing_a_task(
    ledger_store: LedgerStore,
) -> None:
    fixture = seed_wave_fixture(ledger_store)
    # Control arm gets both tasks; treatment arm only gets the first.
    ledger_store.append_trial(
        mk_trial(
            trial_id="trl_c1",
            arm_id=fixture.arm_control_id,
            task_id=fixture.task_ids[0],
            run_idx=1,
        )
    )
    ledger_store.append_trial(
        mk_trial(
            trial_id="trl_c2",
            arm_id=fixture.arm_control_id,
            task_id=fixture.task_ids[1],
            run_idx=1,
        )
    )
    ledger_store.append_trial(
        mk_trial(
            trial_id="trl_t1",
            arm_id=fixture.arm_treatment_id,
            task_id=fixture.task_ids[0],
            run_idx=1,
        )
    )
    with pytest.raises(ArmsUnbalanced):
        ledger_store.check_arm_balance(fixture.wave_id)


def test_check_arm_balance_ignores_non_ok_trials(ledger_store: LedgerStore) -> None:
    fixture = seed_wave_fixture(ledger_store)
    ledger_store.append_trial(
        mk_trial(
            trial_id="trl_c1",
            arm_id=fixture.arm_control_id,
            task_id=fixture.task_ids[0],
            run_idx=1,
        )
    )
    # Treatment arm's only trial for this task errored, so it must not
    # count as balanced against the control arm's `ok` trial.
    ledger_store.append_trial(
        mk_trial(
            trial_id="trl_t1",
            arm_id=fixture.arm_treatment_id,
            task_id=fixture.task_ids[0],
            run_idx=1,
            op_status="error",
            finished_at=None,
            wall_seconds=None,
        )
    )
    with pytest.raises(ArmsUnbalanced):
        ledger_store.check_arm_balance(fixture.wave_id)


def test_check_arm_balance_unknown_wave_raises(ledger_store: LedgerStore) -> None:
    with pytest.raises(UnknownWave):
        ledger_store.check_arm_balance("wav_does_not_exist")


# ---------------------------------------------------------------------
# check_wave_complete
# ---------------------------------------------------------------------


def test_check_wave_complete_reports_planned_done_missing(
    ledger_store: LedgerStore,
) -> None:
    fixture = seed_wave_fixture(ledger_store)
    conn = ledger_store.connection
    # 4 plan cells total (2 arms x 2 tasks) from the fixture; mark 2 done.
    conn.execute(
        "UPDATE plan_cell SET status = 'done' "
        "WHERE wave_id = ? AND arm_id = ? AND task_id = ?",
        (fixture.wave_id, fixture.arm_control_id, fixture.task_ids[0]),
    )
    conn.execute(
        "UPDATE plan_cell SET status = 'done' "
        "WHERE wave_id = ? AND arm_id = ? AND task_id = ?",
        (fixture.wave_id, fixture.arm_treatment_id, fixture.task_ids[0]),
    )
    conn.commit()

    report = ledger_store.check_wave_complete(fixture.wave_id)
    assert report.wave_id == fixture.wave_id
    assert report.planned == 4
    assert report.done == 2
    assert report.missing == 2
    assert len(report.per_arm) == 2
    by_arm = {a.arm_id: a for a in report.per_arm}
    assert by_arm[fixture.arm_control_id].planned == 2
    assert by_arm[fixture.arm_control_id].done == 1
    assert by_arm[fixture.arm_control_id].missing == 1
    assert by_arm[fixture.arm_treatment_id].done == 1


def test_check_wave_complete_never_raises_for_unknown_wave(
    ledger_store: LedgerStore,
) -> None:
    report = ledger_store.check_wave_complete("wav_does_not_exist")
    assert report.planned == 0
    assert report.done == 0
    assert report.missing == 0
    assert report.per_arm == ()


# ---------------------------------------------------------------------
# export_jsonl / import_jsonl
# ---------------------------------------------------------------------


def test_export_jsonl_writes_one_file_per_table_with_correct_counts(
    ledger_store: LedgerStore, tmp_path: Path
) -> None:
    seed_wave_fixture(ledger_store)
    counts = ledger_store.export_jsonl(tmp_path / "export1")
    assert counts["task"] == 2
    assert counts["arm"] == 2
    assert counts["plan_cell"] == 4
    assert counts["trial"] == 0
    for table in counts:
        assert (tmp_path / "export1" / f"{table}.jsonl").is_file()


def test_export_jsonl_rows_are_sorted_by_primary_key(
    ledger_store: LedgerStore, tmp_path: Path
) -> None:
    ledger_store.register(mk_task_set(task_set_id="tsk_a"))
    seed_wave_fixture(ledger_store)
    ledger_store.export_jsonl(tmp_path / "export2")
    lines = (
        (tmp_path / "export2" / "task_set.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    )
    ids = [json.loads(line)["task_set_id"] for line in lines]
    assert ids == sorted(ids)


def test_export_then_fresh_db_import_then_export_is_byte_identical(
    ledger_store: LedgerStore, tmp_path: Path
) -> None:
    seed_wave_fixture(ledger_store)
    ledger_store.append_batch(
        trials=[mk_trial(task_id="tas_1", arm_id="arm_control")],
        grades=[mk_grade(grader_id="grd_test")],
    )

    first_dir = tmp_path / "first"
    first_counts = ledger_store.export_jsonl(first_dir)

    fresh_conn = open_ledger(":memory:")
    fresh_store = LedgerStore(fresh_conn)
    import_counts = fresh_store.import_jsonl(first_dir)
    assert import_counts == first_counts

    second_dir = tmp_path / "second"
    second_counts = fresh_store.export_jsonl(second_dir)
    assert second_counts == first_counts

    for table in first_counts:
        first_bytes = (first_dir / f"{table}.jsonl").read_bytes()
        second_bytes = (second_dir / f"{table}.jsonl").read_bytes()
        assert first_bytes == second_bytes, f"{table}.jsonl differs after round-trip"
    fresh_conn.close()


def test_import_jsonl_missing_file_counts_as_zero(
    ledger_store: LedgerStore, tmp_path: Path
) -> None:
    empty_dir = tmp_path / "empty"
    empty_dir.mkdir()
    counts = ledger_store.import_jsonl(empty_dir)
    assert all(n == 0 for n in counts.values())


# ---------------------------------------------------------------------
# register() must never report success for a row it did not persist.
# `ON CONFLICT DO NOTHING` suppresses every unique collision, not only a
# primary-key one, so a caller inventing a fresh id for a slot that is
# already occupied would otherwise get that id back and fail later, far
# from the cause.
# ---------------------------------------------------------------------


def test_register_raises_when_another_unique_constraint_suppresses_insert(
    ledger_store: LedgerStore,
) -> None:
    seed_wave_fixture(ledger_store)
    # Same UNIQUE(campaign_id, wave_no) slot as the seeded wave, different pk.
    intruder = mk_wave(wave_id="wav_other", campaign_id="cmp_test", wave_no=1)
    with pytest.raises(LedgerIntegrityError) as excinfo:
        ledger_store.register(intruder)
    message = str(excinfo.value)
    assert "wav_other" in message
    assert "wave" in message
    row = ledger_store.connection.execute(
        "SELECT COUNT(*) AS n FROM wave WHERE wave_id = ?", ("wav_other",)
    ).fetchone()
    assert row["n"] == 0


def test_register_stays_idempotent_for_an_identical_row(
    ledger_store: LedgerStore,
) -> None:
    seed_wave_fixture(ledger_store)
    same = mk_wave()
    assert ledger_store.register(same) == "wav_test"
    assert ledger_store.register(same) == "wav_test"
    row = ledger_store.connection.execute(
        "SELECT COUNT(*) AS n FROM wave WHERE wave_id = ?", ("wav_test",)
    ).fetchone()
    assert row["n"] == 1


def test_register_composite_key_roundtrips_and_is_idempotent(
    ledger_store: LedgerStore,
) -> None:
    seed_wave_fixture(ledger_store)
    link = mk_wave_task(wave_id="wav_test", task_id="tas_1")
    assert ledger_store.register(link) == "wav_test:tas_1"
    assert ledger_store.register(link) == "wav_test:tas_1"
