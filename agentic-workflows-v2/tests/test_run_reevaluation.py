"""Tests for re-evaluating a previously-completed run from its captured log.

Covers the record -> WorkflowResult replay converter, the run-log
annotation writer, and ``POST /api/runs/{filename}/evaluate``.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentic_v2.contracts import StepStatus
from agentic_v2.server.routes import runs as runs_routes
from agentic_v2.workflows.run_logger import (
    RunLogger,
    run_record_to_workflow_result,
)

_RUN_FILENAME = "20260706T120000000000Z_code_review_rerun-1_success.json"


def _run_record(**overrides: Any) -> dict[str, Any]:
    """A minimal but realistic on-disk run record."""
    record: dict[str, Any] = {
        "run_id": "rerun-1",
        "workflow_name": "code_review",
        "status": "success",
        "score": 100.0,
        "success_rate": 100.0,
        "total_duration_ms": 1200.0,
        "total_retries": 0,
        "step_count": 2,
        "failed_step_count": 0,
        "start_time": "2026-07-06T12:00:00+00:00",
        "end_time": "2026-07-06T12:00:01+00:00",
        "dataset": {"source": "local", "task_id": "t-1"},
        "inputs": {"code_file": "app.py"},
        "steps": [
            {
                "step_name": "parse_code",
                "status": "success",
                "tier": 0,
                "model_used": None,
                "duration_ms": 5.0,
                "retry_count": 0,
                "tokens_used": None,
                "input": {"file_path": "app.py"},
                "output": {"ast": "{}"},
                "error": None,
                "error_type": None,
                "start_time": "2026-07-06T12:00:00+00:00",
                "end_time": "2026-07-06T12:00:00.005000+00:00",
                "metadata": None,
            },
            {
                "step_name": "review_code",
                "status": "success",
                "tier": 2,
                "model_used": "gemini:gemini-2.5-flash",
                "duration_ms": 900.0,
                "retry_count": 1,
                "tokens_used": 321,
                "input": {"ast": "{}"},
                "output": {"review": "looks fine"},
                "error": None,
                "error_type": None,
                "start_time": "2026-07-06T12:00:00+00:00",
                "end_time": "2026-07-06T12:00:00.905000+00:00",
                "metadata": {"attempted_models": ["gemini:gemini-2.5-flash"]},
            },
        ],
        "final_output": {"review": "looks fine"},
        "extra": {"evaluation_requested": False, "evaluation": None},
    }
    record.update(overrides)
    return record


def _write_run(runs_dir, record: dict[str, Any]) -> None:
    (runs_dir / _RUN_FILENAME).write_text(json.dumps(record), encoding="utf-8")


def _client(monkeypatch, tmp_path) -> TestClient:
    monkeypatch.setattr(runs_routes, "run_logger", RunLogger(runs_dir=tmp_path))
    app = FastAPI()
    app.include_router(runs_routes.router, prefix="/api")
    return TestClient(app)


_SCORED = {
    "enabled": True,
    "rubric": "Code Review v1",
    "rubric_id": "code_review_v1",
    "rubric_version": "1",
    "criteria": [],
    "overall_score": 82.0,
    "weighted_score": 84.5,
    "grade": "B",
    "passed": True,
    "pass_threshold": 70.0,
    "hard_gate_failures": [],
    "step_scores": [],
    "judge_skipped": True,
    "judge_skip_reason": "no judge configured",
    "generated_at": "2026-07-06T13:00:00+00:00",
}


class TestRunRecordToWorkflowResult:
    """Replay converter: on-disk record back into a scoreable result."""

    def test_roundtrip_rebuilds_steps_and_outputs(self):
        result = run_record_to_workflow_result(_run_record())

        assert result.workflow_id == "rerun-1"
        assert result.workflow_name == "code_review"
        assert result.overall_status == StepStatus.SUCCESS
        assert result.final_output == {"review": "looks fine"}
        assert [s.step_name for s in result.steps] == ["parse_code", "review_code"]

        review = result.steps[1]
        assert review.input_data == {"ast": "{}"}
        assert review.output_data == {"review": "looks fine"}
        assert review.retry_count == 1
        assert review.metadata["tokens_used"] == 321
        assert review.duration_ms is not None and review.duration_ms > 0

    def test_unknown_step_status_coerces_to_failed(self):
        record = _run_record()
        record["steps"][0]["status"] = "error"
        result = run_record_to_workflow_result(record)
        assert result.steps[0].status == StepStatus.FAILED

    def test_record_without_steps_raises(self):
        with pytest.raises(ValueError, match="steps"):
            run_record_to_workflow_result(_run_record(steps=None))

    def test_record_without_identity_raises(self):
        with pytest.raises(ValueError, match="run_id"):
            run_record_to_workflow_result(_run_record(run_id=""))


class TestAnnotateRun:
    """RunLogger.annotate_run persists a rescore onto the existing log."""

    def test_persists_evaluation_and_refreshes_score(self, tmp_path):
        _write_run(tmp_path, _run_record(extra={"custom": "kept"}))
        logger = RunLogger(runs_dir=tmp_path)
        path = tmp_path / _RUN_FILENAME

        updated = logger.annotate_run(path, evaluation=dict(_SCORED))

        on_disk = json.loads(path.read_text(encoding="utf-8"))
        assert on_disk == updated
        assert on_disk["extra"]["evaluation"]["weighted_score"] == 84.5
        assert on_disk["extra"]["evaluation_requested"] is True
        assert on_disk["extra"]["custom"] == "kept"
        assert on_disk["score"] == 84.5


class TestEvaluateRunEndpoint:
    """POST /api/runs/{filename}/evaluate."""

    @pytest.fixture(autouse=True)
    def _stub_scoring(self, monkeypatch):
        """Deterministic scoring + judge; no LLM involvement."""
        captured: dict[str, Any] = {}

        def _fake_score(result, **kwargs):
            captured["result"] = result
            captured["kwargs"] = kwargs
            return dict(_SCORED)

        monkeypatch.setattr(
            "agentic_v2.server.evaluation.score_workflow_result", _fake_score
        )
        monkeypatch.setattr(
            "agentic_v2.scoring.judge.LLMJudge", lambda *a, **k: object()
        )
        self.captured = captured

    def test_scores_and_persists_rescore(self, monkeypatch, tmp_path):
        _write_run(tmp_path, _run_record())
        client = _client(monkeypatch, tmp_path)

        response = client.post(f"/api/runs/{_RUN_FILENAME}/evaluate")

        assert response.status_code == 200
        payload = response.json()
        assert payload["filename"] == _RUN_FILENAME
        assert payload["evaluation_requested"] is True
        assert payload["evaluation"]["weighted_score"] == 84.5
        assert payload["evaluation"]["grade"] == "B"
        # Judge-skip visibility survives the response model round-trip
        # (RunEvaluationDetail must not drop the fields).
        assert payload["evaluation"]["judge_skipped"] is True
        assert payload["evaluation"]["judge_skip_reason"] == "no judge configured"

        # The replayed result fed to the scorer came from the log.
        scored_result = self.captured["result"]
        assert scored_result.workflow_id == "rerun-1"
        assert scored_result.steps[1].output_data == {"review": "looks fine"}

        # Rescore persisted: the evaluation detail endpoint now serves it.
        detail = client.get(f"/api/runs/{_RUN_FILENAME}/evaluation")
        assert detail.status_code == 200
        assert detail.json()["evaluation"]["weighted_score"] == 84.5

        # Runs list surfaces the refreshed score fields.
        listed = client.get("/api/runs").json()
        assert listed[0]["evaluation_score"] == 84.5
        assert listed[0]["evaluation_grade"] == "B"

    def test_rubric_override_is_forwarded(self, monkeypatch, tmp_path):
        _write_run(tmp_path, _run_record())
        client = _client(monkeypatch, tmp_path)

        response = client.post(
            f"/api/runs/{_RUN_FILENAME}/evaluate",
            json={"rubric_id": "custom_rubric", "enforce_hard_gates": False},
        )

        assert response.status_code == 200
        kwargs = self.captured["kwargs"]
        assert kwargs["rubric"] == "custom_rubric"
        assert kwargs["enforce_hard_gates"] is False

    def test_dataset_sample_rehydrated_from_run_meta(self, monkeypatch, tmp_path):
        """Re-evaluation reloads the local dataset sample (issue #172).

        The persisted run log stores only dataset metadata; the scorer must
        get the actual sample back — including the loader-inlined
        ``golden_output_text`` — or replayed scores lose the overlap term.
        """
        record = _run_record(
            dataset={
                "source": "local",
                "dataset_id": (
                    "agentic-workflows-v2/tests/fixtures/datasets/"
                    "golden_cases_smoke.json"
                ),
                "sample_index": 0,
                "task_id": "golden_smoke_ok",
            }
        )
        _write_run(tmp_path, record)
        client = _client(monkeypatch, tmp_path)

        response = client.post(f"/api/runs/{_RUN_FILENAME}/evaluate")

        assert response.status_code == 200
        sample = self.captured["kwargs"]["dataset_sample"]
        assert sample is not None
        assert sample["case_id"] == "golden_smoke_ok"
        assert "boundary contract" in sample["golden_output_text"]
        assert "rehydration_error" not in self.captured["kwargs"]["dataset_meta"]

    def test_dataset_sample_none_when_meta_unresolvable(self, monkeypatch, tmp_path):
        _write_run(tmp_path, _run_record())  # meta has no dataset_id
        client = _client(monkeypatch, tmp_path)

        response = client.post(f"/api/runs/{_RUN_FILENAME}/evaluate")

        assert response.status_code == 200
        assert self.captured["kwargs"]["dataset_sample"] is None

    def test_rehydration_failure_recorded_in_dataset_meta(self, monkeypatch, tmp_path):
        """A rehydration that degrades must be visible in the scored payload's dataset
        block, not just a server log line."""
        record = _run_record(
            dataset={
                "source": "local",
                "dataset_id": (
                    "agentic-workflows-v2/tests/fixtures/datasets/"
                    "golden_cases_smoke.json"
                ),
                "sample_index": 0,
                "task_id": "some_other_task",
            }
        )
        _write_run(tmp_path, record)
        client = _client(monkeypatch, tmp_path)

        response = client.post(f"/api/runs/{_RUN_FILENAME}/evaluate")

        assert response.status_code == 200
        kwargs = self.captured["kwargs"]
        assert kwargs["dataset_sample"] is None
        assert "task_id mismatch" in kwargs["dataset_meta"]["rehydration_error"]

    def test_persisted_evaluation_error_served_by_detail_endpoint(
        self, monkeypatch, tmp_path
    ):
        """A judge_required failure recorded at run time must stay visible after the
        live stream is gone (issue #172 review, round 7)."""
        record = _run_record(
            extra={
                "evaluation_requested": True,
                "evaluation": None,
                "evaluation_error": "judge_required unmet: no judge configured",
            }
        )
        _write_run(tmp_path, record)
        client = _client(monkeypatch, tmp_path)

        detail = client.get(f"/api/runs/{_RUN_FILENAME}/evaluation")

        assert detail.status_code == 200
        payload = detail.json()
        assert payload["evaluation"] is None
        assert "judge_required" in payload["evaluation_error"]

    def test_successful_rescore_clears_persisted_evaluation_error(
        self, monkeypatch, tmp_path
    ):
        record = _run_record(
            extra={
                "evaluation_requested": True,
                "evaluation": None,
                "evaluation_error": "judge_required unmet: no judge configured",
            }
        )
        _write_run(tmp_path, record)
        client = _client(monkeypatch, tmp_path)

        response = client.post(f"/api/runs/{_RUN_FILENAME}/evaluate")
        assert response.status_code == 200

        detail = client.get(f"/api/runs/{_RUN_FILENAME}/evaluation").json()
        assert detail["evaluation_error"] is None
        assert detail["evaluation"]["weighted_score"] == 84.5

    def test_judge_required_policy_maps_to_422(self, monkeypatch, tmp_path):
        from agentic_v2.scoring.evaluation_scoring import JudgeRequiredError

        def _raise_policy(result, **kwargs):
            raise JudgeRequiredError(
                "LLM judge is required (evaluation.scoring.judge_required=true) "
                "but unavailable: no judge configured"
            )

        monkeypatch.setattr(
            "agentic_v2.server.evaluation.score_workflow_result", _raise_policy
        )
        _write_run(tmp_path, _run_record())
        client = _client(monkeypatch, tmp_path)

        response = client.post(f"/api/runs/{_RUN_FILENAME}/evaluate")

        assert response.status_code == 422
        assert "judge_required_unmet" in response.json()["detail"]

    def test_unknown_run_returns_404(self, monkeypatch, tmp_path):
        client = _client(monkeypatch, tmp_path)
        response = client.post("/api/runs/nope.json/evaluate")
        assert response.status_code == 404

    def test_unreplayable_record_returns_422(self, monkeypatch, tmp_path):
        _write_run(tmp_path, _run_record(steps=None))
        client = _client(monkeypatch, tmp_path)

        response = client.post(f"/api/runs/{_RUN_FILENAME}/evaluate")

        assert response.status_code == 422
        assert "cannot be replayed" in response.json()["detail"]
