"""Runtime scoring regression tests: no evidence must never become a pass."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

from agentic_v2.engine.executor import ExecutorEvent
from agentic_v2.scoring import evalkit_bridge
from agentic_v2.scoring import step_scoring as ss
from agentic_v2.scoring.rubrics import load_rubric

requires_evk = pytest.mark.skipif(
    not evalkit_bridge.EVALKIT_AVAILABLE, reason="optional eval extra absent"
)


def test_helpers() -> None:
    assert ss._rubric_for_agent("coder") == "code"
    assert ss._rubric_for_agent("unknown") == "default"
    assert ss._pass_threshold("code", {"thresholds": {"pass": "0.8"}}) == 0.8
    assert ss._pass_threshold("missing", {}) == 0.6
    assert ss._infer_agent_type("Tier2_Coder_Step") == "coder"
    assert ss._output_to_text(None) == ""
    assert ss._output_to_text({"a": "one", "b": 2}) == "one\n2"
    assert ss._output_to_text(42) == "42"


@pytest.mark.parametrize(
    "output", ["", "  ", "meaningless text", '{"passed": true, "score": 1}']
)
def test_output_never_implies_quality(output: str) -> None:
    score = ss.score_step("researcher", "researcher", output)
    assert score.status is ss.ScoreStatus.UNAVAILABLE
    assert score.weighted_score is None and score.passed is None
    assert score.criterion_scores == {}
    assert score.output_present is bool(output.strip())


def test_optional_dependency_absent_is_explicit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(evalkit_bridge, "EVALKIT_AVAILABLE", False)
    listener = ss.build_step_scoring_listener()
    listener(ExecutorEvent.STEP_END, {"step": "coder", "output": "text"})
    assert listener.get_scores()[0].reason == "evalkit_not_installed"
    assert listener.get_summary()["avg_score"] is None
    assert listener.get_summary()["passed"] == 0


@pytest.mark.parametrize("score", [float("nan"), float("inf"), -0.1, 1.1, True])
def test_invalid_evidence_rejected(score: float) -> None:
    with pytest.raises(ValueError):
        ss.CriterionEvidence(score, "check")


def test_blank_evidence_rejected() -> None:
    with pytest.raises(ValueError):
        ss.CriterionEvidence(1, "  ")


@requires_evk
@pytest.mark.parametrize("name", ["code", "agent", "default"])
def test_complete_evidence_uses_bridge(name: str) -> None:
    rubric = load_rubric(name)
    agent = {"code": "coder", "agent": "researcher", "default": "unknown"}[name]
    evidence = {
        item["name"]: ss.CriterionEvidence(
            0.9, "Fixture: deterministic criterion measurement"
        )
        for item in rubric["criteria"]
    }
    result = ss.score_step("step", agent, "text", criterion_evidence=evidence)
    expected = evalkit_bridge.score_criteria(
        rubric, {key: e.score for key, e in evidence.items()}
    )
    assert result.status is ss.ScoreStatus.SCORED
    assert result.weighted_score == pytest.approx(expected)
    assert result.passed is (expected >= ss._pass_threshold(name, rubric))
    assert result.evidence == {key: e.evidence for key, e in evidence.items()}


@requires_evk
def test_partial_evidence_cannot_pass() -> None:
    result = ss.score_step(
        "step",
        "unknown",
        "text",
        criterion_evidence={"Accuracy": ss.CriterionEvidence(1, "deterministic check")},
    )
    assert result.reason == "criterion_evidence_incomplete"
    assert result.passed is None and result.weighted_score is None


@requires_evk
def test_fallback_and_missing_resources(monkeypatch: pytest.MonkeyPatch) -> None:
    real_loader = load_rubric
    calls = []

    def fallback(name: str) -> dict[str, Any]:
        calls.append(name)
        if name == "code":
            raise FileNotFoundError(name)
        return real_loader(name)

    monkeypatch.setattr(ss, "load_rubric", fallback)
    assert ss.score_step("coder", "coder", "text").rubric_name == "default"
    assert calls == ["code", "default"]

    def missing(_name: str) -> dict[str, Any]:
        raise FileNotFoundError

    monkeypatch.setattr(ss, "load_rubric", missing)
    assert ss.score_step("coder", "coder", "text").reason == "rubric_unavailable"


@requires_evk
@pytest.mark.asyncio
async def test_deterministic_grader_and_unavailable_summary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Exact match proves only this explicitly defined criterion, not broad quality.
    monkeypatch.setattr(
        ss,
        "load_rubric",
        lambda _name: {
            "criteria": [
                {
                    "name": "Exact match",
                    "weight": 1,
                    "description": "Text equals the expected answer",
                }
            ],
            "thresholds": {"pass": 1},
        },
    )

    def grader(step: str, _agent: str, output: str) -> dict[str, ss.CriterionEvidence]:
        return (
            {"Exact match": ss.exact_match_evidence("42", output)}
            if step != "missing"
            else {}
        )

    listener = ss.build_step_scoring_listener(grader=grader)
    for step, output in [("match", "42"), ("different", "junk"), ("missing", "text")]:
        await listener.handle_update(
            {"type": "step_end", "step": step, "output": output, "status": "success"}
        )
    summary = listener.get_summary()
    assert summary["scored_steps"] == 2 and summary["unavailable"] == 1
    assert summary["passed"] == 1 and summary["avg_score"] == 0.5
    assert summary["step_scores"][1]["passed"] is False
    assert summary["step_scores"][2]["passed"] is None
    json.dumps(summary, allow_nan=False)


@pytest.mark.asyncio
async def test_listener_ignores_untrusted_scores_and_failed_execution() -> None:
    listener = ss.build_step_scoring_listener()
    await listener.handle_update(
        {
            "type": "step_end",
            "step": "researcher",
            "output": "text",
            "criterion_evidence": {"Correctness": 1},
            "passed": True,
        }
    )
    assert listener.get_scores()[0].passed is None
    await listener.handle_update(
        {"type": "step_end", "step": "failed", "status": "failed", "output": "text"}
    )
    assert listener.get_scores()[1].reason == "execution_not_completed"
    await listener.handle_update({"type": "heartbeat"})
    listener(ExecutorEvent.WORKFLOW_START, {"step": "ignored"})
    listener(ExecutorEvent.STEP_END, {})
    assert len(listener.get_scores()) == 2
    listener.enabled = False
    listener(ExecutorEvent.STEP_END, {"step": "disabled"})
    assert len(listener.get_scores()) == 2


@pytest.mark.asyncio
async def test_grader_failure_does_not_become_task_failure() -> None:
    def broken(*_args: str) -> dict[str, ss.CriterionEvidence]:
        raise ValueError("invalid evidence")

    listener = ss.build_step_scoring_listener(grader=broken)
    await listener.handle_update(
        {"type": "step_end", "step": "coder", "status": "success"}
    )
    assert listener.get_scores()[0].reason == "grader_failed"
    assert listener.get_scores()[0].passed is None


@requires_evk
def test_runtime_without_legacy_package() -> None:
    # A fresh process prevents cached imports from disguising a legacy dependency.
    code = """
import importlib.abc, sys
class BlockLegacy(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == 'agentic_v2_eval' or fullname.startswith('agentic_v2_eval.'):
            raise ModuleNotFoundError('legacy evaluation package deliberately absent')
sys.meta_path.insert(0, BlockLegacy())
from agentic_v2.scoring.step_scoring import score_step, CriterionEvidence, ScoreStatus
from agentic_v2.scoring.rubrics import load_rubric
for name, agent in [('code', 'coder'), ('agent', 'researcher'), ('default', 'unknown')]:
    evidence = {c['name']: CriterionEvidence(1, 'deterministic fixture') for c in load_rubric(name)['criteria']}
    result = score_step('step', agent, 'text', criterion_evidence=evidence)
    assert result.status is ScoreStatus.SCORED and result.passed is True
assert not any(n == 'agentic_v2_eval' or n.startswith('agentic_v2_eval.') for n in sys.modules)
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_rubric_loader_rejects_paths() -> None:
    with pytest.raises(FileNotFoundError):
        load_rubric("../default")


def test_scoring_has_no_legacy_imports() -> None:
    import ast

    package = Path(ss.__file__).parent
    for path in package.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8-sig"))):
            if isinstance(node, ast.ImportFrom):
                assert not (node.module or "").startswith("agentic_v2_eval")
            elif isinstance(node, ast.Import):
                assert not any(
                    alias.name.startswith("agentic_v2_eval") for alias in node.names
                )


@pytest.mark.asyncio
async def test_server_preserves_unavailable_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from unittest.mock import AsyncMock

    from agentic_v2.contracts import WorkflowResult
    from agentic_v2.server import execution

    async def adapter(*_args, on_update):
        await on_update(
            {
                "type": "step_end",
                "step": "researcher",
                "status": "success",
                "output": "nonempty but unmeasured",
            }
        )
        return WorkflowResult(
            workflow_name="fixture", workflow_id="fixture", overall_status="success"
        )

    monkeypatch.setattr(execution, "_run_via_native_adapter", adapter)
    monkeypatch.setattr(execution.websocket.manager, "broadcast", AsyncMock())
    result = await execution._run_native_stream("native", "fixture", "fixture", {})
    summary = result.metadata["step_scores"]
    assert summary["passed"] == 0 and summary["avg_score"] is None
    assert summary["step_scores"][0]["status"] == "unavailable"
    assert summary["step_scores"][0]["passed"] is None
