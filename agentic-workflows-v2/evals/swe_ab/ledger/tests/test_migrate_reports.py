"""Tests for `migrate_reports`: report JSON -> ledger rows, end to end.

Fixture prefix `mig_` avoids colliding with fixtures other test modules in
this same `tests/` package define, per `conftest.py`'s own note about
cross-module fixture collisions.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import migrate_reports as mr
import pytest

import ledger
from ledger.blobs import BlobStore
from ledger.store import LedgerStore, open_ledger

# ---------------------------------------------------------------------
# resolve_model_ref
# ---------------------------------------------------------------------


def test_resolve_model_ref_prefers_manifest_target_fingerprint() -> None:
    report = {"manifest": {"target_fingerprint": "nvidia:deepseek-v4-flash@abc123"}}
    assert mr.resolve_model_ref(report) == ("nvidia", "deepseek-v4-flash")


def test_resolve_model_ref_falls_back_to_sample_requested_model() -> None:
    report = {
        "manifest": {"target_fingerprint": None},
        "samples": [
            {
                "execution": {
                    "output": {"requested_model": "ollama:deepseek-v4-flash:cloud"}
                }
            }
        ],
    }
    assert mr.resolve_model_ref(report) == ("ollama", "deepseek-v4-flash:cloud")


def test_resolve_model_ref_falls_back_to_sample_model_name() -> None:
    report = {
        "manifest": {},
        "samples": [{"execution": {"output": None, "model_name": "solo-model"}}],
    }
    assert mr.resolve_model_ref(report) == ("unknown", "solo-model")


def test_resolve_model_ref_unknown_when_nothing_names_a_model() -> None:
    report = {"manifest": {}, "samples": [{"execution": {"output": None}}]}
    assert mr.resolve_model_ref(report) == ("unknown", "unknown")


# ---------------------------------------------------------------------
# PendingBlobChannel
# ---------------------------------------------------------------------


def test_pending_blob_channel_flush_writes_one_json_object_per_line(
    tmp_path: Path,
) -> None:
    channel = mr.PendingBlobChannel()
    channel.push(digest="sha256:aaaa", reason="not found", context="report-a.json")
    channel.push(digest="sha256:bbbb", reason="hash mismatch", context="report-b.json")

    out_path = tmp_path / "pending_blobs.jsonl"
    count = channel.flush_to(out_path)

    assert count == 2
    lines = out_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2
    rows = [json.loads(line) for line in lines]
    assert {row["digest"] for row in rows} == {"sha256:aaaa", "sha256:bbbb"}
    assert all({"digest", "reason", "context", "seen_at"} == set(row) for row in rows)


def test_pending_blob_channel_tombstone_row_is_zero_byte_and_prunable() -> None:
    blob = mr.PendingBlobChannel.tombstone_row("sha256:cccc")
    assert blob.digest == "sha256:cccc"
    assert blob.size_bytes == 0
    assert blob.media_type == "application/x-ledger-pending"
    assert blob.retention == "prunable"


# ---------------------------------------------------------------------
# make_output_resolver
# ---------------------------------------------------------------------


@pytest.fixture
def mig_store() -> LedgerStore:
    return LedgerStore(open_ledger(":memory:"))


@pytest.fixture
def mig_blob_store(tmp_path: Path) -> BlobStore:
    return BlobStore(root=tmp_path / "blobs")


def test_resolver_reads_and_registers_a_real_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mig_store: LedgerStore,
    mig_blob_store: BlobStore,
) -> None:
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    payload = b'{"models_used": ["m1"], "step_count": 1}'
    digest = ledger.digest_bytes(payload)
    hex_part = digest.rsplit(":", 1)[-1]
    (artifacts_dir / f"{hex_part}.bin").write_bytes(payload)
    (artifacts_dir / f"{hex_part}.json").write_text(
        json.dumps({"media_type": "application/json"}), encoding="utf-8"
    )
    monkeypatch.setattr(mr, "ARTIFACTS_DIR", artifacts_dir)

    pending = mr.PendingBlobChannel()
    resolve = mr.make_output_resolver(
        report_name="r.json",
        blob_store=mig_blob_store,
        ledger_store=mig_store,
        pending=pending,
    )
    result = resolve(digest)

    assert result == {"models_used": ["m1"], "step_count": 1}
    assert len(pending) == 0
    row = mig_store.connection.execute(
        "SELECT * FROM blob WHERE digest = ?", (digest,)
    ).fetchone()
    assert row["media_type"] == "application/json"
    assert row["size_bytes"] == len(payload)
    assert mig_blob_store.get(digest) == payload


def test_resolver_falls_back_to_literal_eval_for_python_repr_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mig_store: LedgerStore,
    mig_blob_store: BlobStore,
) -> None:
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    payload = str({"models_used": ["m2"], "step_count": 2}).encode("utf-8")
    digest = ledger.digest_bytes(payload)
    hex_part = digest.rsplit(":", 1)[-1]
    (artifacts_dir / f"{hex_part}.bin").write_bytes(payload)
    monkeypatch.setattr(mr, "ARTIFACTS_DIR", artifacts_dir)

    pending = mr.PendingBlobChannel()
    resolve = mr.make_output_resolver(
        report_name="r.json",
        blob_store=mig_blob_store,
        ledger_store=mig_store,
        pending=pending,
    )
    result = resolve(digest)

    assert result == {"models_used": ["m2"], "step_count": 2}
    assert len(pending) == 0


def test_resolver_tombstones_a_digest_missing_from_artifacts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mig_store: LedgerStore,
    mig_blob_store: BlobStore,
) -> None:
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    monkeypatch.setattr(mr, "ARTIFACTS_DIR", artifacts_dir)
    digest = "sha256:" + "0" * 64

    pending = mr.PendingBlobChannel()
    resolve = mr.make_output_resolver(
        report_name="r.json",
        blob_store=mig_blob_store,
        ledger_store=mig_store,
        pending=pending,
    )
    result = resolve(digest)

    assert result is None
    assert len(pending) == 1
    row = mig_store.connection.execute(
        "SELECT * FROM blob WHERE digest = ?", (digest,)
    ).fetchone()
    assert row is not None
    assert row["media_type"] == "application/x-ledger-pending"
    assert row["size_bytes"] == 0


def test_resolver_tombstones_a_digest_whose_bytes_do_not_match(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mig_store: LedgerStore,
    mig_blob_store: BlobStore,
) -> None:
    artifacts_dir = tmp_path / "artifacts"
    artifacts_dir.mkdir()
    claimed_digest = "sha256:" + "1" * 64
    hex_part = claimed_digest.rsplit(":", 1)[-1]
    (artifacts_dir / f"{hex_part}.bin").write_bytes(
        b"not the bytes that hash to that digest"
    )
    monkeypatch.setattr(mr, "ARTIFACTS_DIR", artifacts_dir)

    pending = mr.PendingBlobChannel()
    resolve = mr.make_output_resolver(
        report_name="r.json",
        blob_store=mig_blob_store,
        ledger_store=mig_store,
        pending=pending,
    )
    result = resolve(claimed_digest)

    assert result is None
    assert len(pending) == 1


# ---------------------------------------------------------------------
# register_task_set_and_tasks
# ---------------------------------------------------------------------


def test_register_task_set_and_tasks_reads_oracle_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mig_store: LedgerStore
) -> None:
    dataset_dir = tmp_path / "dataset"
    case_dir = dataset_dir / "swebench_cases" / "proj__repo-1"
    case_dir.mkdir(parents=True)
    oracle: dict[str, Any] = {
        "repo": "proj/repo",
        "base_commit": "deadbeef",
        "target_file": "proj/mod.py",
        "fail_to_pass": ["test_a", "test_b"],
        "difficulty": "easy",
        "contamination_risk": "low",
        "max_changed_lines": 10,
    }
    (case_dir / "oracle.json").write_text(json.dumps(oracle), encoding="utf-8")
    monkeypatch.setattr(mr, "DATASET_DIR", dataset_dir)
    image_id = mr.register_sentinel_image(mig_store)

    task_set_id, task_ids = mr.register_task_set_and_tasks(
        mig_store, ["proj__repo-1"], image_id
    )

    assert task_ids == {"proj__repo-1": task_ids["proj__repo-1"]}
    row = mig_store.connection.execute(
        "SELECT * FROM task WHERE task_id = ?", (task_ids["proj__repo-1"],)
    ).fetchone()
    assert row["task_set_id"] == task_set_id
    assert row["repo"] == "proj/repo"
    assert row["base_commit"] == "deadbeef"
    assert json.loads(row["fail_to_pass"]) == ["test_a", "test_b"]
    assert row["image_id"] == image_id

    task_set_row = mig_store.connection.execute(
        "SELECT row_count FROM task_set WHERE task_set_id = ?", (task_set_id,)
    ).fetchone()
    assert task_set_row["row_count"] == 1


def test_register_task_set_and_tasks_raises_on_missing_oracle_json(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mig_store: LedgerStore
) -> None:
    monkeypatch.setattr(mr, "DATASET_DIR", tmp_path / "empty-dataset")
    with pytest.raises(mr.MigrationError, match="no dataset/swebench_cases"):
        mr.register_task_set_and_tasks(
            mig_store, ["missing__instance-1"], image_id="img_test"
        )


# ---------------------------------------------------------------------
# Reference row registration is idempotent (register() dedupes by content id)
# ---------------------------------------------------------------------


def test_register_grader_and_workflows_and_image_are_idempotent(
    mig_store: LedgerStore,
) -> None:
    grader_id_1 = mr.register_grader(mig_store)
    grader_id_2 = mr.register_grader(mig_store)
    assert grader_id_1 == grader_id_2

    workflow_ids_1 = mr.register_workflows(mig_store)
    workflow_ids_2 = mr.register_workflows(mig_store)
    assert workflow_ids_1 == workflow_ids_2
    assert set(workflow_ids_1) == {"swe_fix_direct", "swe_fix_review_loop"}

    image_id_1 = mr.register_sentinel_image(mig_store)
    image_id_2 = mr.register_sentinel_image(mig_store)
    assert image_id_1 == image_id_2


# ---------------------------------------------------------------------
# End to end: one synthetic two-arm wave through migrate_wave
# ---------------------------------------------------------------------


def _synthetic_report(*, run_name: str, instance_id: str, model: str) -> dict[str, Any]:
    return {
        "generated_at": "2026-01-01T00:00:00Z",
        "manifest": {"run_name": run_name, "target_fingerprint": None},
        "samples": [
            {
                "sample": {
                    "sample_id": instance_id,
                    "metadata": {"instance_id": instance_id},
                },
                "execution": {
                    "attempt": 1,
                    "status": "completed",
                    "started_at": "2026-01-01T00:00:00Z",
                    "finished_at": "2026-01-01T00:01:00Z",
                    "output": {"models_used": [model], "workflow": run_name},
                    "artifacts": {},
                },
                "grade": {
                    "status": "pass",
                    "score": 1.0,
                    "created_at": "2026-01-01T00:01:00Z",
                    "evidence": {},
                },
            }
        ],
    }


def test_migrate_wave_end_to_end_with_synthetic_reports(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    dataset_dir = tmp_path / "dataset"
    case_dir = dataset_dir / "swebench_cases" / "proj__repo-1"
    case_dir.mkdir(parents=True)
    (case_dir / "oracle.json").write_text(
        json.dumps(
            {
                "repo": "proj/repo",
                "base_commit": "deadbeef",
                "target_file": "proj/mod.py",
                "fail_to_pass": ["test_a"],
                "difficulty": "easy",
                "contamination_risk": "low",
                "max_changed_lines": 5,
            }
        ),
        encoding="utf-8",
    )

    a_report = _synthetic_report(
        run_name="arm-a-direct", instance_id="proj__repo-1", model="ollama:test-model"
    )
    b_report = _synthetic_report(
        run_name="arm-b-review-loop",
        instance_id="proj__repo-1",
        model="ollama:test-model",
    )
    (reports_dir / "a.json").write_text(json.dumps(a_report), encoding="utf-8")
    (reports_dir / "b.json").write_text(json.dumps(b_report), encoding="utf-8")

    monkeypatch.setattr(mr, "REPORTS_DIR", reports_dir)
    monkeypatch.setattr(mr, "DATASET_DIR", dataset_dir)
    monkeypatch.setattr(mr, "ARTIFACTS_DIR", tmp_path / "artifacts")

    conn = open_ledger(":memory:")
    store = LedgerStore(conn)
    blob_store = BlobStore(root=tmp_path / "blobs")
    pending = mr.PendingBlobChannel()

    grader_id = mr.register_grader(store)
    workflow_ids = mr.register_workflows(store)
    image_id = mr.register_sentinel_image(store)
    task_set_id, task_ids_by_instance = mr.register_task_set_and_tasks(
        store, ["proj__repo-1"], image_id
    )

    campaign_id = mr._campaign_row_id("test-campaign")
    store.register(
        ledger.Campaign(
            campaign_id=campaign_id,
            name="test-campaign",
            question="does it work?",
            primary_contrast="workflow",
            created_at="2026-01-01T00:00:00Z",
            status=ledger.CampaignStatus.CLOSED.value,
        )
    )

    wave_plan = mr.WavePlan(
        wave_no=1,
        substrate_label="test",
        arms={"arm-a-direct": "a.json", "arm-b-review-loop": "b.json"},
    )
    result = mr.migrate_wave(
        store,
        campaign_id=campaign_id,
        wave_plan=wave_plan,
        grader_id=grader_id,
        task_set_id=task_set_id,
        task_ids_by_instance=task_ids_by_instance,
        workflow_ids=workflow_ids,
        blob_store=blob_store,
        pending=pending,
    )

    assert result.trials == 2
    assert result.grades == 2
    assert result.balance_note is None

    trials = conn.execute("SELECT arm_id, op_status FROM trial").fetchall()
    assert len(trials) == 2
    assert all(row["op_status"] == "ok" for row in trials)
    grades = conn.execute("SELECT outcome FROM grade").fetchall()
    assert [row["outcome"] for row in grades] == ["pass", "pass"]

    verdict = _verdict_pass_rate(conn, wave_id=mr._wave_row_id(campaign_id, 1))
    assert verdict == {"arm-a-direct": (1, 1), "arm-b-review-loop": (1, 1)}


def _verdict_pass_rate(
    conn: sqlite3.Connection, *, wave_id: str
) -> dict[str, tuple[int, int]]:
    """`{arm_key: (n_pass, n_verdicts)}` -- a minimal local read, not a copy
    of `ledger.queries.arm_pass_rates`, so this test does not depend on that
    module's own correctness to check migrate_wave's output.
    """
    rows = conn.execute(
        "SELECT arm.arm_key AS arm_key, grade.outcome AS outcome "
        "FROM trial "
        "JOIN arm ON arm.arm_id = trial.arm_id "
        "LEFT JOIN grade ON grade.trial_id = trial.trial_id "
        "WHERE trial.wave_id = ?",
        (wave_id,),
    ).fetchall()
    tally: dict[str, tuple[int, int]] = {}
    for row in rows:
        n_pass, n_verdicts = tally.get(row["arm_key"], (0, 0))
        if row["outcome"] is not None:
            n_verdicts += 1
            if row["outcome"] == "pass":
                n_pass += 1
        tally[row["arm_key"]] = (n_pass, n_verdicts)
    return tally
