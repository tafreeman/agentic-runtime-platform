"""Runtime golden gate regressions, including unavailable evaluator packages."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def gate():
    spec = importlib.util.spec_from_file_location(
        "gate_test", ROOT / "scripts/eval_gate.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def case(gate):
    return gate._load_json(gate._DEFAULT_CASES)[0]


def test_committed_scores_and_json_contract(gate):
    cases = gate._load_json(gate._DEFAULT_CASES)
    results = [gate.score_case(case, gate._DEFAULT_CASES.parent, 0.8) for case in cases]
    assert [r["weighted_score"] for r in results] == pytest.approx([1, 0.8, 0.8, 0.8])
    assert all(r["passed"] for r in results)
    assert all(isinstance(r["criterion_scores"], dict) for r in results)
    assert all(r["missing_criteria"] == [] for r in results)
    assert json.loads(json.dumps(results, allow_nan=False)) == results
    assert gate.main([]) == 0
    assert gate.main(["--threshold", "0.99"]) == 1


@pytest.mark.parametrize(
    "value",
    [float("nan"), float("inf"), -float("inf"), "bad", True, [], -0.1, 1.1],
)
def test_invalid_thresholds_fail_without_live_call(gate, case, value):
    case["threshold"] = value
    result = gate.score_case(case, gate._DEFAULT_CASES.parent, 0.8)
    assert not result["passed"] and result["error"]
    json.dumps(result, allow_nan=False)
    with patch("agentic_v2.workflows.run_workflow", new_callable=AsyncMock) as run:
        result = asyncio.run(gate.score_case_live(case, 0.8))
    run.assert_not_awaited()
    assert not result["passed"] and result["error"]


@pytest.mark.parametrize("value", ["nan", "inf", "-inf", "-0.1", "1.1", "bad"])
def test_invalid_global_thresholds_fail_even_on_live_skip(gate, monkeypatch, value):
    monkeypatch.setenv("AGENTIC_NO_LLM", "1")
    assert gate.main(["--threshold=" + value, "--live"]) == 1


@pytest.mark.parametrize("field", ["success_rate", "total_retries"])
@pytest.mark.parametrize(
    "value", [float("nan"), float("inf"), -float("inf"), "bad", None, True, {}]
)
def test_invalid_numbers_fail_golden_and_mocked_live(
    gate, case, tmp_path, field, value
):
    golden = gate._load_json(gate._DEFAULT_CASES.parent / case["golden_output_path"])
    golden[field] = value
    path = tmp_path / "golden.json"
    path.write_text(json.dumps(golden), encoding="utf-8")
    case["golden_output_path"] = str(path)
    result = gate.score_case(case, tmp_path, 0.0)
    assert not result["passed"] and result["error"]
    mocked = SimpleNamespace(model_dump=lambda **kwargs: golden)
    with patch("agentic_v2.workflows.run_workflow", AsyncMock(return_value=mocked)):
        result = asyncio.run(gate.score_case_live(case, 0.0))
    assert not result["passed"] and result["error"]
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize(
    "updates",
    [
        {"rubric": "missing"},
        {"golden_output_path": None},
        {"expected_criteria": []},
        {"expected_criteria": {"max_retries": "nan"}},
        {"expected_criteria": {"expected_step_names": [[]]}},
    ],
)
def test_invalid_case_data_fails_cleanly(gate, case, updates):
    case.update(updates)
    result = gate.score_case(case, gate._DEFAULT_CASES.parent, 0)
    assert not result["passed"] and result["error"]


def test_missing_criteria_remain_failure_and_json_list(gate):
    result = gate._score_criteria("missing", "code", {"Correctness": 1}, 0)
    assert not result["passed"]
    assert isinstance(result["missing_criteria"], list)
    assert len(result["missing_criteria"]) == 4
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_criteria_cannot_be_clamped_to_success(gate, value):
    result = gate._score_criteria("bad", "code", {"Correctness": value}, 0)
    assert not result["passed"] and result["error"]


def test_gate_runs_without_legacy_or_evalkit():
    program = r"""
import asyncio
import importlib.abc
import importlib.util
import json
import sys
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock
class BlockEvaluators(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'agentic_v2_eval', 'agentic_evalkit'}:
            raise ModuleNotFoundError(fullname)
sys.meta_path.insert(0, BlockEvaluators())
spec = importlib.util.spec_from_file_location('gate', 'scripts/eval_gate.py')
gate = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gate)
assert gate.main([]) == 0
assert gate.main(['--threshold', '.99']) == 1
case = gate._load_json(gate._DEFAULT_CASES)[0]
golden = gate._load_json(gate._DEFAULT_CASES.parent / case['golden_output_path'])
workflows = ModuleType('agentic_v2.workflows')
workflows.run_workflow = AsyncMock(return_value=SimpleNamespace(model_dump=lambda **kw: golden))
sys.modules['agentic_v2.workflows'] = workflows
result = asyncio.run(gate.score_case_live(case, .8))
assert result['passed'] and result['live_run_scores'] == [1., 1., 1.]
assert workflows.run_workflow.await_count == 3
json.dumps(result, allow_nan=False)
assert not any(n.split('.')[0] in {'agentic_v2_eval', 'agentic_evalkit'} for n in sys.modules)
"""
    env = dict(
        os.environ, PYTHONPATH=str(ROOT / "agentic-workflows-v2"), AGENTIC_NO_LLM="1"
    )
    result = subprocess.run(
        [sys.executable, "-c", program],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_null_case_threshold_uses_global(gate, case):
    case["threshold"] = None
    result = gate.score_case(case, gate._DEFAULT_CASES.parent, 0.9)
    assert result["passed"] and result["threshold"] == 0.9
    golden = gate._load_json(gate._DEFAULT_CASES.parent / case["golden_output_path"])
    mocked = SimpleNamespace(model_dump=lambda **kwargs: golden)
    with patch("agentic_v2.workflows.run_workflow", AsyncMock(return_value=mocked)):
        result = asyncio.run(gate.score_case_live(case, 0.9))
    assert result["passed"] and result["threshold"] == 0.9
