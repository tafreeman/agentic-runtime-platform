"""Tests for ARP-2: checkpoint resume, fork_session, and changed-file detection.

Covers the additions in ``agentic_v2/engine/context.py``:
- ``ExecutionContext.fork_session`` branches an isolated divergent run.
- ``save_checkpoint(tracked_files=...)`` fingerprints files.
- ``detect_changed_files`` / ``build_changed_files_notice`` surface staleness.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from agentic_v2.engine import ExecutionContext


def _write_checkpoint(path: Path, **overrides: Any) -> Path:
    """Write a minimal checkpoint JSON file with caller-supplied fields.

    Used to craft attacker-controlled payloads for the identity-hardening
    tests without going through ``save_checkpoint``.
    """
    payload: dict[str, Any] = {
        "workflow_id": "wf",
        "run_id": "run",
        "variables": {},
        "completed_steps": [],
        "failed_steps": [],
        "metadata": {},
    }
    payload.update(overrides)
    path.write_text(json.dumps(payload))
    return path


class TestForkSession:
    """fork_session branches a divergent run off a shared baseline."""

    async def test_fork_isolates_writes_from_baseline(self) -> None:
        baseline = ExecutionContext()
        await baseline.set("plan", ["a", "b"])

        fork = baseline.fork_session("experiment")
        await fork.set("plan", ["a", "b", "c"])

        # Baseline is untouched; fork sees its own override.
        assert await baseline.get("plan") == ["a", "b"]
        assert await fork.get("plan") == ["a", "b", "c"]

    async def test_fork_records_lineage_and_fresh_run_id(self) -> None:
        baseline = ExecutionContext()
        fork = baseline.fork_session("branch_x")

        assert fork.run_id != baseline.run_id
        assert fork.workflow_id == baseline.workflow_id  # same definition
        assert fork.metadata["fork_name"] == "branch_x"
        assert fork.metadata["forked_from_run"] == baseline.run_id

    async def test_fork_inherits_baseline_variables_on_read(self) -> None:
        baseline = ExecutionContext()
        await baseline.set("shared", 42)

        fork = baseline.fork_session("inherit")
        # Not written locally — read falls through to the baseline.
        assert await fork.get("shared") == 42

    def test_fork_rejects_empty_name(self) -> None:
        baseline = ExecutionContext()
        with pytest.raises(ValueError, match="non-empty name"):
            baseline.fork_session("   ")


class TestChangedFileDetection:
    """save_checkpoint fingerprints files; resume detects what changed."""

    async def test_detects_modified_file(self, tmp_path: Path) -> None:
        tracked = tmp_path / "config.txt"
        tracked.write_text("v1")

        ctx = ExecutionContext(checkpoint_dir=tmp_path / "ckpt")
        path = await ctx.save_checkpoint("run", tracked_files=[tracked])

        tracked.write_text("v2-changed")

        changed = ExecutionContext.detect_changed_files(path)
        assert str(tracked) in changed

    async def test_unchanged_file_not_reported(self, tmp_path: Path) -> None:
        tracked = tmp_path / "stable.txt"
        tracked.write_text("constant")

        ctx = ExecutionContext(checkpoint_dir=tmp_path / "ckpt")
        path = await ctx.save_checkpoint("run", tracked_files=[tracked])

        # No edit happens.
        assert ExecutionContext.detect_changed_files(path) == []

    async def test_deleted_file_reported_as_changed(self, tmp_path: Path) -> None:
        tracked = tmp_path / "gone.txt"
        tracked.write_text("here")

        ctx = ExecutionContext(checkpoint_dir=tmp_path / "ckpt")
        path = await ctx.save_checkpoint("run", tracked_files=[tracked])

        tracked.unlink()
        assert str(tracked) in ExecutionContext.detect_changed_files(path)

    async def test_checkpoint_without_tracked_files_reports_nothing(
        self, tmp_path: Path
    ) -> None:
        ctx = ExecutionContext(checkpoint_dir=tmp_path / "ckpt")
        path = await ctx.save_checkpoint("run")  # no tracked_files
        assert ExecutionContext.detect_changed_files(path) == []

    def test_notice_is_empty_when_nothing_changed(self) -> None:
        assert ExecutionContext.build_changed_files_notice([]) == ""

    def test_notice_lists_changed_files(self) -> None:
        notice = ExecutionContext.build_changed_files_notice(["a.py", "b.py"])
        assert "a.py" in notice and "b.py" in notice
        assert "re-read" in notice.lower()


class TestResumeRoundTrip:
    """Resume rehydrates variables and step status into a fresh context."""

    async def test_resume_restores_state(self, tmp_path: Path) -> None:
        ckpt_dir = tmp_path / "ckpt"
        ctx = ExecutionContext(checkpoint_dir=ckpt_dir)
        await ctx.set("plan", ["analyze", "fix"])
        await ctx.mark_step_complete("analyze")
        path = await ctx.save_checkpoint("resume_me")

        resumed = ExecutionContext(checkpoint_dir=ckpt_dir)
        await resumed.restore_checkpoint(path)

        assert await resumed.get("plan") == ["analyze", "fix"]
        assert "analyze" in resumed.completed_steps

    async def test_resume_then_fork_keeps_baseline_intact(self, tmp_path: Path) -> None:
        ckpt_dir = tmp_path / "ckpt"
        ctx = ExecutionContext(checkpoint_dir=ckpt_dir)
        await ctx.set("plan", ["a"])
        path = await ctx.save_checkpoint("base")

        resumed = ExecutionContext(checkpoint_dir=ckpt_dir)
        await resumed.restore_checkpoint(path)
        fork = resumed.fork_session("divergent")
        await fork.set("plan", ["a", "b"])

        assert await resumed.get("plan") == ["a"]
        assert await fork.get("plan") == ["a", "b"]

    async def test_resume_restores_run_id_and_workflow_id(self, tmp_path: Path) -> None:
        ckpt_dir = tmp_path / "ckpt"
        ctx = ExecutionContext(checkpoint_dir=ckpt_dir)
        original_run_id = ctx.run_id
        original_workflow_id = ctx.workflow_id
        path = await ctx.save_checkpoint("identity_run")

        # A fresh context starts with its own distinct identity.
        resumed = ExecutionContext(checkpoint_dir=ckpt_dir)
        assert resumed.run_id != original_run_id

        await resumed.restore_checkpoint(path)

        # Resume rehydrates the saved identity, not the fresh one.
        assert resumed.run_id == original_run_id
        assert resumed.workflow_id == original_workflow_id

    async def test_fork_after_resume_lineages_to_original_run_id(
        self, tmp_path: Path
    ) -> None:
        ckpt_dir = tmp_path / "ckpt"
        ctx = ExecutionContext(checkpoint_dir=ckpt_dir)
        original_run_id = ctx.run_id
        path = await ctx.save_checkpoint("lineage_run")

        resumed = ExecutionContext(checkpoint_dir=ckpt_dir)
        await resumed.restore_checkpoint(path)
        fork = resumed.fork_session("post_resume_branch")

        # The fork lineage points at the ORIGINAL saved run_id, not a fresh uuid.
        assert fork.metadata["forked_from_run"] == original_run_id
        assert fork.run_id != original_run_id


class TestCheckpointIdentityHardening:
    """restore_checkpoint must reject hijacked identity / type confusion (C-04)."""

    async def test_running_context_rejects_foreign_workflow_id(
        self, tmp_path: Path
    ) -> None:
        # A context that has already run a step is a bound running identity.
        ctx = ExecutionContext(checkpoint_dir=tmp_path)
        await ctx.mark_step_complete("step_a")
        original_workflow_id = ctx.workflow_id

        path = _write_checkpoint(
            tmp_path / "evil.json",
            workflow_id="attacker-workflow",
            run_id=ctx.run_id,
        )

        with pytest.raises(ValueError, match="does not match the running context"):
            await ctx.restore_checkpoint(path)

        # Identity is unchanged — the tampered value was rejected pre-mutation.
        assert ctx.workflow_id == original_workflow_id

    async def test_running_context_rejects_foreign_run_id(self, tmp_path: Path) -> None:
        ctx = ExecutionContext(checkpoint_dir=tmp_path)
        await ctx.mark_step_complete("step_a")
        original_run_id = ctx.run_id

        path = _write_checkpoint(
            tmp_path / "evil.json",
            workflow_id=ctx.workflow_id,
            run_id="attacker-run",
        )

        with pytest.raises(ValueError, match="does not match the running context"):
            await ctx.restore_checkpoint(path)

        assert ctx.run_id == original_run_id

    async def test_rejects_non_string_workflow_id(self, tmp_path: Path) -> None:
        ctx = ExecutionContext(checkpoint_dir=tmp_path)
        path = _write_checkpoint(tmp_path / "bad.json", workflow_id=42)

        with pytest.raises(ValueError, match="expected str"):
            await ctx.restore_checkpoint(path)

    async def test_rejects_non_list_completed_steps(self, tmp_path: Path) -> None:
        ctx = ExecutionContext(checkpoint_dir=tmp_path)
        path = _write_checkpoint(tmp_path / "bad.json", completed_steps={"step": True})

        with pytest.raises(ValueError, match="expected a list"):
            await ctx.restore_checkpoint(path)

    async def test_rejects_non_string_completed_step_entry(
        self, tmp_path: Path
    ) -> None:
        ctx = ExecutionContext(checkpoint_dir=tmp_path)
        path = _write_checkpoint(
            tmp_path / "bad.json", completed_steps=["ok", {"nested": "obj"}]
        )

        with pytest.raises(ValueError, match="expected str entries"):
            await ctx.restore_checkpoint(path)

    async def test_fresh_resume_context_still_adopts_saved_identity(
        self, tmp_path: Path
    ) -> None:
        # A pristine resume context (no steps run) legitimately adopts the
        # checkpoint identity — the hardening must not break normal resume.
        path = _write_checkpoint(
            tmp_path / "good.json",
            workflow_id="saved-wf",
            run_id="saved-run",
            completed_steps=["analyze"],
        )

        resumed = ExecutionContext(checkpoint_dir=tmp_path)
        await resumed.restore_checkpoint(path)

        assert resumed.workflow_id == "saved-wf"
        assert resumed.run_id == "saved-run"
        assert resumed.completed_steps == ["analyze"]
