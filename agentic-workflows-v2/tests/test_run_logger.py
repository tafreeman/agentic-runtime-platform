"""Tests for workflow run logger record shaping.

ADR-008 Phase 3 — Tier 1 (branching, error paths) and Tier 2 (contracts,
boundaries) tests for _safe_serialize, _truncate, build_step_record,
build_run_record, and RunLogger.
"""

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from agentic_v2.contracts import StepResult, StepStatus, WorkflowResult
from agentic_v2.workflows.run_logger import (
    RunLogger,
    _safe_serialize,
    _truncate,
    build_run_record,
    build_step_record,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _result(
    *,
    status: StepStatus = StepStatus.SUCCESS,
    steps: list[StepResult] | None = None,
    end_time: datetime | None = None,
    workflow_id: str = "wf-test-1",
) -> WorkflowResult:
    return WorkflowResult(
        workflow_id=workflow_id,
        workflow_name="test_workflow",
        overall_status=status,
        steps=steps or [],
        final_output={},
        end_time=end_time,
    )


def _step(
    *,
    name: str = "step-1",
    status: StepStatus = StepStatus.SUCCESS,
    metadata: dict[str, Any] | None = None,
) -> StepResult:
    return StepResult(
        step_name=name,
        status=status,
        agent_role="coder",
        tier=2,
        model_used="gpt-4o",
        retry_count=0,
        input_data={"prompt": "hello"},
        output_data={"code": "print('hi')"},
        metadata=metadata or {},
    )


# ---------------------------------------------------------------------------
# Existing tests (preserved)
# ---------------------------------------------------------------------------


def test_build_run_record_score_falls_back_to_success_rate():
    result = _result()

    record = build_run_record(result)

    assert "score" in record
    assert record["score"] == result.success_rate


def test_build_run_record_score_uses_evaluation_weighted_score():
    result = _result()

    record = build_run_record(
        result,
        extra={"evaluation": {"weighted_score": 87.5, "overall_score": 71.0}},
    )

    assert record["score"] == pytest.approx(87.5)


def test_summary_ignores_non_run_json_artifacts(tmp_path):
    logger = RunLogger(runs_dir=tmp_path)

    valid = build_run_record(_result())
    (tmp_path / "20260222T120000Z_test_workflow_success.json").write_text(
        json.dumps(valid),
        encoding="utf-8",
    )

    # Utility artifact (not a run record) should not crash summary().
    (tmp_path / "provider_limits.json").write_text(
        json.dumps({"checked": {"openai": {"ok": True}}}),
        encoding="utf-8",
    )

    summary = logger.summary()

    assert summary["total_runs"] == 1
    assert summary["success"] == 1
    assert summary["failed"] == 0
    assert summary["workflows"] == ["test_workflow"]


# ---------------------------------------------------------------------------
# _safe_serialize — Tier 1 branching tests
# ---------------------------------------------------------------------------


class TestSafeSerialize:
    """Tests for the _safe_serialize JSON fallback function."""

    def test_datetime_to_isoformat(self):
        """ADR-008 Phase 3: datetime objects serialize to ISO 8601 string."""
        dt = datetime(2026, 3, 17, 12, 0, 0, tzinfo=UTC)
        assert _safe_serialize(dt) == dt.isoformat()

    def test_step_status_to_value(self):
        """ADR-008 Phase 3: StepStatus serializes to its string value."""
        assert _safe_serialize(StepStatus.SUCCESS) == "success"
        assert _safe_serialize(StepStatus.FAILED) == "failed"

    def test_null_safe_sentinel(self):
        """ADR-008 Phase 3: _NullSafe sentinels serialize as None."""

        class _NullSafe:
            pass

        assert _safe_serialize(_NullSafe()) is None

    def test_pydantic_model_dump(self):
        """ADR-008 Phase 3: objects with model_dump() are serialized via it."""
        mock_obj = MagicMock()
        mock_obj.model_dump.return_value = {"key": "value"}
        assert _safe_serialize(mock_obj) == {"key": "value"}

    def test_path_to_string(self):
        """ADR-008 Phase 3: Path objects serialize to string."""
        p = Path("/some/path")
        assert _safe_serialize(p) == str(p)

    def test_fallback_to_str(self):
        """ADR-008 Phase 3: unknown types fall back to str()."""
        assert _safe_serialize(42) == "42"
        assert _safe_serialize(set()) == str(set())


# ---------------------------------------------------------------------------
# _truncate — Tier 1 branching tests
# ---------------------------------------------------------------------------


class TestTruncate:
    """Tests for the _truncate value limiter."""

    def test_short_string_unchanged(self):
        """ADR-008 Phase 3: strings under limit are untouched."""
        assert _truncate("short", max_len=100) == "short"

    def test_long_string_truncated(self):
        """ADR-008 Phase 3: strings over limit are truncated with count."""
        long_str = "x" * 200
        result = _truncate(long_str, max_len=50)
        assert result.startswith("x" * 50)
        assert "200 chars" in result

    def test_dict_values_truncated_recursively(self):
        """ADR-008 Phase 3: dict values are truncated recursively."""
        data = {"key": "a" * 100}
        result = _truncate(data, max_len=20)
        assert "100 chars" in result["key"]

    def test_list_values_truncated_recursively(self):
        """ADR-008 Phase 3: list items are truncated recursively."""
        data = ["b" * 100, "short"]
        result = _truncate(data, max_len=20)
        assert "100 chars" in result[0]
        assert result[1] == "short"

    def test_non_string_passthrough(self):
        """ADR-008 Phase 3: non-string/dict/list values pass through."""
        assert _truncate(42, max_len=5) == 42
        assert _truncate(None, max_len=5) is None


# ---------------------------------------------------------------------------
# build_step_record — Tier 2 contract tests
# ---------------------------------------------------------------------------


class TestBuildStepRecord:
    """Tests for build_step_record() output shape."""

    def test_includes_required_fields(self):
        """ADR-008 Phase 3: record contains all expected keys."""
        step = _step()
        record = build_step_record(step)
        required = {
            "step_name",
            "status",
            "agent_role",
            "tier",
            "model_used",
            "duration_ms",
            "retry_count",
            "tokens_used",
            "input",
            "output",
            "error",
            "error_type",
            "start_time",
            "end_time",
            "metadata",
        }
        assert required.issubset(record.keys())

    def test_tokens_used_extracted_from_metadata(self):
        """ADR-008 Phase 3: tokens_used pulled from metadata, then excluded from metadata dict."""
        step = _step(metadata={"tokens_used": 150, "latency": 42})
        record = build_step_record(step)
        assert record["tokens_used"] == 150
        # tokens_used should NOT appear in the metadata sub-dict
        assert record["metadata"] == {"latency": 42}

    def test_metadata_none_when_only_tokens_used(self):
        """ADR-008 Phase 3: metadata is None when tokens_used is the only key."""
        step = _step(metadata={"tokens_used": 100})
        record = build_step_record(step)
        assert record["metadata"] is None

    def test_status_value_serialized(self):
        """ADR-008 Phase 3: enum status serializes to its .value string."""
        step = _step(status=StepStatus.FAILED)
        record = build_step_record(step)
        assert record["status"] == "failed"

    def test_validation_failure_returns_fallback_record(self, caplog):
        """Defensive ValidationError handling: a malformed step yields a
        minimal fallback record instead of raising. The original validation
        error must surface in metadata so it remains visible in the run log.
        """
        import logging

        # Use a duck-typed step whose ``tier`` is a non-coercible value to
        # provoke a ValidationError inside StepResultRecord.
        bad_step = MagicMock()
        bad_step.step_name = "bad-step"
        bad_step.status = StepStatus.SUCCESS
        bad_step.agent_role = "coder"
        bad_step.tier = ["not", "an", "int"]
        bad_step.model_used = "gpt-4o"
        bad_step.duration_ms = 12.3
        bad_step.retry_count = 0
        bad_step.metadata = {}
        bad_step.input_data = {}
        bad_step.output_data = {}
        bad_step.error = None
        bad_step.error_type = None
        bad_step.start_time = None
        bad_step.end_time = None

        with caplog.at_level(logging.WARNING, logger="agentic_v2.workflows.run_logger"):
            record = build_step_record(bad_step)

        assert record["step_name"] == "bad-step"
        assert record["status"] == "error"
        assert record["error_type"] == "ValidationError"
        assert record["metadata"] is not None
        assert "validation_error" in record["metadata"]
        # Original status surfaced for forensics
        assert record["metadata"]["original_status"] == "success"
        # Loudly logged — never silently swallowed
        assert any(
            "validation failed" in r.message.lower() for r in caplog.records
        )

    def test_validation_success_still_returns_validated_dict(self):
        """A well-formed step round-trips through StepResultRecord without
        the fallback path firing.
        """
        step = _step(metadata={"tokens_used": 42})
        record = build_step_record(step)
        # Happy path: no validation_error metadata key, real status preserved.
        assert record["status"] == "success"
        if record.get("metadata") is not None:
            assert "validation_error" not in record["metadata"]


# ---------------------------------------------------------------------------
# build_run_record — Tier 2 boundary tests
# ---------------------------------------------------------------------------


class TestBuildRunRecord:
    """Tests for build_run_record() output shape and scoring logic."""

    def test_uses_overall_score_when_no_weighted(self):
        """ADR-008 Phase 3: overall_score used when weighted_score absent."""
        result = _result()
        record = build_run_record(result, extra={"evaluation": {"overall_score": 65.0}})
        assert record["score"] == pytest.approx(65.0)

    def test_non_numeric_evaluation_scores_ignored(self):
        """ADR-008 Phase 3: non-numeric scores fall back to success_rate."""
        result = _result()
        record = build_run_record(
            result, extra={"evaluation": {"weighted_score": "N/A"}}
        )
        assert record["score"] == result.success_rate

    def test_extra_dict_attached(self):
        """ADR-008 Phase 3: extra dict is included in output when provided."""
        result = _result()
        record = build_run_record(result, extra={"tag": "nightly"})
        assert record["extra"] == {"tag": "nightly"}

    def test_no_extra_when_none(self):
        """ADR-008 Phase 3: 'extra' key absent when None."""
        result = _result()
        record = build_run_record(result)
        assert "extra" not in record

    def test_dataset_meta_included(self):
        """ADR-008 Phase 3: dataset metadata appears in record."""
        result = _result()
        meta = {"source": "benchmark", "task_id": "t-001"}
        record = build_run_record(result, dataset_meta=meta)
        assert record["dataset"] == meta

    def test_steps_serialized(self):
        """ADR-008 Phase 3: steps list contains build_step_record output."""
        step = _step(name="analyze")
        result = _result(steps=[step])
        record = build_run_record(result)
        assert len(record["steps"]) == 1
        assert record["steps"][0]["step_name"] == "analyze"


# ---------------------------------------------------------------------------
# RunLogger — Tier 1/2 integration tests
# ---------------------------------------------------------------------------


class TestRunLogger:
    """Tests for the RunLogger file persistence class."""

    def test_creates_directory_on_init(self, tmp_path):
        """ADR-008 Phase 3: RunLogger creates runs_dir if absent."""
        runs_dir = tmp_path / "sub" / "runs"
        assert not runs_dir.exists()
        RunLogger(runs_dir=runs_dir)
        assert runs_dir.exists()

    def test_log_creates_json_file(self, tmp_path):
        """ADR-008 Phase 3: log() writes a JSON file to runs_dir."""
        rl = RunLogger(runs_dir=tmp_path)
        result = _result()
        path = rl.log(result)
        assert path.exists()
        assert path.suffix == ".json"
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["workflow_name"] == "test_workflow"

    def test_log_filename_contains_workflow_and_status(self, tmp_path):
        """ADR-008 Phase 3: filename encodes workflow name and status."""
        rl = RunLogger(runs_dir=tmp_path)
        path = rl.log(_result())
        assert "test_workflow" in path.name
        assert "wf-test-1" in path.name
        assert "success" in path.name

    def test_log_filenames_do_not_collide_for_same_timestamp(self, tmp_path, monkeypatch):
        """ADR-008 Phase 3: concurrent logs keep distinct filenames per run id."""
        rl = RunLogger(runs_dir=tmp_path)
        frozen_now = datetime(2026, 5, 2, 18, 20, 21, 123456, tzinfo=UTC)

        class _FrozenDateTime(datetime):
            @classmethod
            def now(cls, tz=None):
                return frozen_now if tz is not None else frozen_now.replace(tzinfo=None)

        monkeypatch.setattr("agentic_v2.workflows.run_logger.datetime", _FrozenDateTime)

        first = rl.log(_result(workflow_id="wf-test-1"))
        second = rl.log(_result(workflow_id="wf-test-2"))

        assert first != second
        assert first.exists()
        assert second.exists()

    def test_list_runs_returns_all(self, tmp_path):
        """ADR-008 Phase 3: list_runs returns all JSON files."""
        rl = RunLogger(runs_dir=tmp_path)
        rl.log(_result())
        rl.log(_result(status=StepStatus.FAILED))
        assert len(rl.list_runs()) == 2

    def test_list_runs_filters_by_workflow_name(self, tmp_path):
        """ADR-008 Phase 3: list_runs filters by workflow name."""
        rl = RunLogger(runs_dir=tmp_path)
        rl.log(_result())
        # Create a file with a different workflow name pattern
        (tmp_path / "20260317T000000Z_other_wf_success.json").write_text(
            json.dumps({"workflow_name": "other_wf", "status": "success"}),
            encoding="utf-8",
        )
        filtered = rl.list_runs(workflow_name="test_workflow")
        assert all("test_workflow" in p.name for p in filtered)

    def test_load_run_roundtrips(self, tmp_path):
        """ADR-008 Phase 3: load_run reads back what log() wrote."""
        rl = RunLogger(runs_dir=tmp_path)
        path = rl.log(_result())
        loaded = rl.load_run(path)
        assert loaded["run_id"] == "wf-test-1"

    def test_resolve_run_path_accepts_exact_filename(self, tmp_path):
        """ADR-008 Phase 3: resolve_run_path returns exact filenames unchanged."""
        rl = RunLogger(runs_dir=tmp_path)
        path = rl.log(_result())

        assert rl.resolve_run_path(path.name) == path

    def test_resolve_run_path_finds_timestamped_file_by_run_id(self, tmp_path):
        """ADR-008 Phase 3: resolve_run_path maps run_id.json to the logged file."""
        rl = RunLogger(runs_dir=tmp_path)
        path = rl.log(_result())

        assert rl.resolve_run_path("wf-test-1.json") == path

    def test_resolve_run_path_rejects_path_traversal(self, tmp_path):
        """ADR-008 Phase 3: resolve_run_path rejects path traversal attempts."""
        rl = RunLogger(runs_dir=tmp_path)
        rl.log(_result())

        assert rl.resolve_run_path("../wf-test-1.json") is None

    def test_summary_empty_directory(self, tmp_path):
        """ADR-008 Phase 3: summary returns total_runs=0 for empty dir."""
        rl = RunLogger(runs_dir=tmp_path)
        assert rl.summary() == {"total_runs": 0}

    def test_summary_skips_corrupt_json(self, tmp_path):
        """ADR-008 Phase 3: summary skips files that fail JSON parse."""
        rl = RunLogger(runs_dir=tmp_path)
        rl.log(_result())
        (tmp_path / "corrupt.json").write_text("NOT JSON{{{", encoding="utf-8")
        summary = rl.summary()
        assert summary["total_runs"] == 1

    def test_summary_avg_duration(self, tmp_path):
        """ADR-008 Phase 3: summary computes average duration from records."""
        rl = RunLogger(runs_dir=tmp_path)
        now = datetime.now(UTC)
        r = _result(end_time=now)
        path = rl.log(r)
        # Patch the file to have a known duration
        data = json.loads(path.read_text(encoding="utf-8"))
        data["total_duration_ms"] = 500
        path.write_text(json.dumps(data), encoding="utf-8")
        summary = rl.summary()
        assert summary["avg_duration_ms"] == pytest.approx(500.0)

    def test_runs_dir_property(self, tmp_path):
        """ADR-008 Phase 3: runs_dir property returns configured path."""
        rl = RunLogger(runs_dir=tmp_path)
        assert rl.runs_dir == tmp_path

    def test_accepts_string_path(self, tmp_path):
        """ADR-008 Phase 3: RunLogger accepts string path, not just Path."""
        rl = RunLogger(runs_dir=str(tmp_path))
        assert isinstance(rl.runs_dir, Path)
