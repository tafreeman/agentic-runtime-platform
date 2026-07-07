"""Route tests for POST /api/eval/compare (head-to-head run scoring)."""

from __future__ import annotations

import json
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from agentic_v2.server.routes import runs as runs_routes
from agentic_v2.workflows.run_logger import RunLogger

_FILE_A = "20260706T120000000000Z_code_review_run-a_success.json"
_FILE_B = "20260706T130000000000Z_code_review_run-b_success.json"


def _run_record(run_id: str, review: str) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "workflow_name": "code_review",
        "status": "success",
        "steps": [
            {
                "step_name": "review_code",
                "status": "success",
                "tier": 2,
                "model_used": "gh:openai/gpt-4o-mini",
                "duration_ms": 900.0,
                "retry_count": 0,
                "tokens_used": 100,
                "input": {"code": "print(1)"},
                "output": {"review": review},
                "error": None,
                "error_type": None,
                "start_time": "2026-07-06T12:00:00+00:00",
                "end_time": "2026-07-06T12:00:00.900000+00:00",
                "metadata": None,
            }
        ],
        "final_output": {"review": review},
        "extra": {"evaluation_requested": False, "evaluation": None},
    }


def _scored(weighted: float, correctness: float) -> dict[str, Any]:
    return {
        "enabled": True,
        "rubric": "Code Review v1",
        "rubric_id": "code_review_v1",
        "rubric_version": "1",
        "criteria": [
            {
                "criterion": "correctness",
                "weight": 0.5,
                "raw_score": correctness,
                "normalized_score": correctness,
                "weighted_contribution": correctness * 0.5,
            }
        ],
        "overall_score": weighted,
        "weighted_score": weighted,
        "grade": "B" if weighted >= 80 else "C",
        "passed": weighted >= 70,
        "pass_threshold": 70.0,
    }


@pytest.fixture()
def compare_client(monkeypatch, tmp_path) -> TestClient:
    (tmp_path / _FILE_A).write_text(
        json.dumps(_run_record("run-a", "thorough review")), encoding="utf-8"
    )
    (tmp_path / _FILE_B).write_text(
        json.dumps(_run_record("run-b", "shallow review")), encoding="utf-8"
    )
    monkeypatch.setattr(runs_routes, "run_logger", RunLogger(runs_dir=tmp_path))

    scores = {"run-a": _scored(84.5, 90.0), "run-b": _scored(72.0, 60.0)}

    def _fake_score(result, **kwargs):
        _fake_score.calls.append({"result": result, "kwargs": kwargs})
        return dict(scores[result.workflow_id])

    _fake_score.calls = []
    monkeypatch.setattr(
        "agentic_v2.server.evaluation.score_workflow_result", _fake_score
    )
    monkeypatch.setattr("agentic_v2.scoring.judge.LLMJudge", lambda *a, **k: object())

    app = FastAPI()
    app.include_router(runs_routes.router, prefix="/api")
    client = TestClient(app)
    client.fake_score = _fake_score
    return client


class TestCompareRuns:
    def test_scores_both_candidates_and_picks_winner(self, compare_client):
        response = compare_client.post(
            "/api/eval/compare", json={"run_a": _FILE_A, "run_b": _FILE_B}
        )

        assert response.status_code == 200
        payload = response.json()
        assert payload["winner"] == "a"
        assert payload["weighted_score_delta"] == pytest.approx(12.5)
        assert payload["candidate_a"]["run_id"] == "run-a"
        assert payload["candidate_a"]["grade"] == "B"
        assert payload["candidate_b"]["run_id"] == "run-b"
        assert payload["rubric_id"] == "code_review_v1"

        deltas = {d["criterion"]: d for d in payload["criteria_deltas"]}
        assert deltas["correctness"]["delta"] == pytest.approx(30.0)

    def test_rubric_override_applies_to_both_candidates(self, compare_client):
        response = compare_client.post(
            "/api/eval/compare",
            json={"run_a": _FILE_A, "run_b": _FILE_B, "rubric_id": "custom"},
        )

        assert response.status_code == 200
        rubrics = [c["kwargs"]["rubric"] for c in compare_client.fake_score.calls]
        assert rubrics == ["custom", "custom"]

    def test_missing_candidate_returns_404(self, compare_client):
        response = compare_client.post(
            "/api/eval/compare", json={"run_a": _FILE_A, "run_b": "missing.json"}
        )
        assert response.status_code == 404

    def test_unreplayable_candidate_returns_422(
        self, compare_client, monkeypatch, tmp_path
    ):
        broken = _run_record("run-b", "x")
        broken["steps"] = None
        (tmp_path / _FILE_B).write_text(json.dumps(broken), encoding="utf-8")

        response = compare_client.post(
            "/api/eval/compare", json={"run_a": _FILE_A, "run_b": _FILE_B}
        )

        assert response.status_code == 422
        assert "Candidate B" in response.json()["detail"]

    def test_comparison_does_not_persist_scores(self, compare_client, tmp_path):
        compare_client.post(
            "/api/eval/compare", json={"run_a": _FILE_A, "run_b": _FILE_B}
        )
        on_disk = json.loads((tmp_path / _FILE_A).read_text(encoding="utf-8"))
        assert on_disk["extra"]["evaluation"] is None
