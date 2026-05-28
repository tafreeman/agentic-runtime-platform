from __future__ import annotations

from types import SimpleNamespace

import pytest

from agentic_v2.engine.executor import ExecutorEvent
from agentic_v2.server import step_scoring


def test_step_scoring_helpers_cover_mapping_and_output_conversion() -> None:
    assert step_scoring._rubric_for_agent("coder") == "code"
    assert step_scoring._rubric_for_agent("unknown") == "default"

    assert step_scoring._pass_threshold("code", {"thresholds": {"pass": "0.8"}}) == 0.8
    assert step_scoring._pass_threshold("agent", {"thresholds": {"pass": "bad"}}) == 0.70
    assert step_scoring._pass_threshold("missing", {}) == 0.60

    assert step_scoring._infer_agent_type("Tier2_Coder_Step") == "coder"
    assert step_scoring._infer_agent_type("mystery-step") == "unknown"

    assert step_scoring._output_to_text(None) == ""
    assert step_scoring._output_to_text("hello") == "hello"
    assert step_scoring._output_to_text({"a": "one", "b": 2}) == "one\n2"
    assert step_scoring._output_to_text(42) == "42"


def test_score_step_handles_eval_unavailable_and_missing_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(step_scoring, "_EVAL_AVAILABLE", False)
    assert step_scoring.score_step("coder_step", "coder", "output") is None

    monkeypatch.setattr(step_scoring, "_EVAL_AVAILABLE", True)
    monkeypatch.setattr(step_scoring, "load_rubric", lambda _name: (_ for _ in ()).throw(FileNotFoundError()))
    assert step_scoring.score_step("coder_step", "coder", "output") is None


def test_score_step_falls_back_to_default_rubric(monkeypatch: pytest.MonkeyPatch) -> None:
    rubric_calls: list[str] = []

    def _load_rubric(name: str):
        rubric_calls.append(name)
        if name == "code":
            raise FileNotFoundError()
        return {"thresholds": {"pass": "0.5"}}

    class _FakeScorer:
        def __init__(self, _rubric):
            self.criteria = [SimpleNamespace(name="quality"), SimpleNamespace(name="safety")]

        def score(self, results):
            assert results == {"quality": 0.7, "safety": 0.7}
            return SimpleNamespace(
                weighted_score=0.7,
                criterion_scores={"quality": 0.7, "safety": 0.7},
            )

    monkeypatch.setattr(step_scoring, "_EVAL_AVAILABLE", True)
    monkeypatch.setattr(step_scoring, "load_rubric", _load_rubric)
    monkeypatch.setattr(step_scoring, "Scorer", _FakeScorer)

    score = step_scoring.score_step("coder_step", "coder", "useful output")

    assert rubric_calls == ["code", "default"]
    assert score is not None
    assert score.rubric_name == "default"
    assert score.passed is True
    assert score.criterion_scores == {"quality": 0.7, "safety": 0.7}


@pytest.mark.asyncio
async def test_step_scoring_listener_and_factory_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(step_scoring, "_EVAL_AVAILABLE", False)
    disabled = step_scoring.StepScoringListener(enabled=True)
    assert disabled.enabled is False
    assert step_scoring.build_step_scoring_listener() is None

    fake_score = step_scoring.StepScore(
        step_name="coder_step",
        agent_type="coder",
        rubric_name="code",
        weighted_score=0.9,
        criterion_scores={"quality": 0.9},
        passed=True,
        timestamp="2026-05-23T00:00:00+00:00",
    )

    monkeypatch.setattr(step_scoring, "_EVAL_AVAILABLE", True)
    monkeypatch.setattr(step_scoring, "score_step", lambda *_args, **_kwargs: fake_score)

    listener = step_scoring.StepScoringListener(enabled=True)
    listener(ExecutorEvent.WORKFLOW_START, {"step": "ignored"})
    listener(ExecutorEvent.STEP_END, {})
    listener(ExecutorEvent.STEP_END, {"step": "coder_step", "output": {"body": "ok"}})
    await listener.handle_update({"type": "heartbeat"})
    await listener.handle_update({"type": "step_end", "step": "coder_step", "output": "ok"})

    scores = listener.get_scores()
    assert len(scores) == 2

    summary = listener.get_summary()
    assert summary["total_steps"] == 2
    assert summary["passed"] == 2
    assert summary["avg_score"] == 0.9
    assert summary["step_scores"][0]["step_name"] == "coder_step"

    empty_listener = step_scoring.StepScoringListener(enabled=True)
    empty_listener.scores = []
    assert empty_listener.get_summary() == {
        "total_steps": 0,
        "passed": 0,
        "avg_score": 0.0,
        "step_scores": [],
    }

    created = step_scoring.build_step_scoring_listener()
    assert isinstance(created, step_scoring.StepScoringListener)
