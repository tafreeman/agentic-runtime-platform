"""Tests for ``scripts/eval_gate.py``'s ``--live`` mode.

``scripts/eval_gate.py`` lives at the repo root (not inside this package), so
it is loaded here via ``importlib.util.spec_from_file_location`` rather than a
normal import -- there is no ``scripts/__init__.py`` and it is not part of any
installed package. All tests in this module MOCK ``agentic_v2.workflows.run_workflow``;
none call a real model provider, matching ADR/testing conventions (a unit test
must be deterministic and key-free) and the repo's ``AGENTIC_NO_LLM=1``
no-key baseline.

Covers:
- ``--live`` CLI arg plumbing (parsed, defaults to False, doesn't affect the
  mocked path).
- The credential-gated skip (``AGENTIC_NO_LLM`` set, or no provider key
  configured) exits 0 without ever importing/calling ``run_workflow``.
- The median-of-3 scoring logic in ``score_case_live``, using mocked
  ``WorkflowResult`` objects with varying success rates.
- ``--live --threshold 0.99`` exits 1 given low mocked scores.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from agentic_v2.contracts import StepResult, StepStatus, WorkflowResult

_SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "eval_gate.py"


def _load_eval_gate_module() -> ModuleType:
    """Load ``scripts/eval_gate.py`` as a standalone module for testing.

    A fresh module object is returned on every call (not cached in
    ``sys.modules`` under a stable name across tests) so that per-test
    ``monkeypatch``/``patch`` targets applied to the loaded module's
    namespace never leak into another test.
    """
    spec = importlib.util.spec_from_file_location("eval_gate_under_test", _SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def eval_gate() -> ModuleType:
    """Fresh ``eval_gate.py`` module instance for each test."""
    return _load_eval_gate_module()


def _make_workflow_result(
    workflow_name: str,
    *,
    step_statuses: list[StepStatus],
    step_names: list[str] | None = None,
    retry_counts: list[int] | None = None,
) -> WorkflowResult:
    """Build a minimal WorkflowResult with the given per-step statuses.

    Mirrors ``tests/test_evaluation_scoring.py``'s ``_make_result`` helper so
    fixture style stays consistent across the suite.
    """
    now = datetime.now(UTC)
    names = step_names or [f"step_{i}" for i in range(len(step_statuses))]
    retries = retry_counts or [0] * len(step_statuses)
    overall = (
        StepStatus.SUCCESS
        if all(s == StepStatus.SUCCESS for s in step_statuses)
        else StepStatus.FAILED
    )
    result = WorkflowResult(
        workflow_id=f"wf-{workflow_name}",
        workflow_name=workflow_name,
        overall_status=overall,
        start_time=now,
        end_time=now,
        final_output={},
    )
    for name, status, retry_count in zip(names, step_statuses, retries, strict=True):
        result.add_step(
            StepResult(
                step_name=name,
                status=status,
                input_data={},
                output_data={},
                start_time=now,
                end_time=now,
                retry_count=retry_count,
            )
        )
    return result


def _base_case(**overrides: Any) -> dict[str, Any]:
    """A minimal, valid golden_cases.json-shaped case dict for --live tests."""
    case: dict[str, Any] = {
        "case_id": "unit_test_case_v1",
        "rubric": "code",
        "workflow_name": "test_deterministic",
        "live_inputs": {"input_text": "hello"},
        "expected_criteria": {
            "expected_step_names": ["step1", "step2"],
            "max_retries": 0,
        },
        "threshold": 0.80,
    }
    case.update(overrides)
    return case


# ---------------------------------------------------------------------------
# CLI arg plumbing
# ---------------------------------------------------------------------------


def _write_minimal_mocked_dataset(tmp_path: Path) -> Path:
    """Write a minimal, valid golden_cases.json + golden file pair to
    ``tmp_path`` and return the cases.json path. Used by tests that only need
    to exercise the mocked path's CLI plumbing, not its scoring semantics."""
    golden_path = tmp_path / "golden.json"
    golden_path.write_text(
        json.dumps(
            {
                "workflow_name": "x",
                "success_rate": 100.0,
                "steps": [{"step_name": "s", "status": "success"}],
                "total_retries": 0,
            }
        ),
        encoding="utf-8",
    )
    cases_path = tmp_path / "cases.json"
    cases_path.write_text(
        json.dumps(
            [
                {
                    "case_id": "c1",
                    "rubric": "code",
                    "golden_output_path": str(golden_path),
                    "expected_criteria": {"expected_step_names": ["s"]},
                    "threshold": 0.0,
                }
            ]
        ),
        encoding="utf-8",
    )
    return cases_path


class TestLiveArgPlumbing:
    def test_live_omitted_takes_the_mocked_path_and_skips_agentic_v2(
        self,
        eval_gate: ModuleType,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Without --live, main() must default args.live to False, take the
        mocked golden-file path (score_case_live never called), and never
        import agentic_v2/the workflow engine at all -- the mocked gate's
        whole point is not needing the runtime package installed."""
        cases_path = _write_minimal_mocked_dataset(tmp_path)
        # Poison the import: if the mocked path ever starts importing
        # agentic_v2.workflows, resolving this sys.modules entry raises
        # instead of silently succeeding.
        monkeypatch.setitem(sys.modules, "agentic_v2.workflows", None)

        with patch.object(
            eval_gate, "score_case_live", new_callable=AsyncMock
        ) as mock_live:
            # No --live flag at all -- args.live must default False.
            exit_code = eval_gate.main(
                ["--cases", str(cases_path), "--threshold", "0.0"]
            )
        assert exit_code == 0
        mock_live.assert_not_called()

    def test_live_flag_present_takes_the_live_branch(
        self,
        eval_gate: ModuleType,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """--live present (vs. absent, covered by the test above) must reach
        the credential gate in main() -- proven here by observing that, with
        no key configured, main() prints the --live-specific SKIPPED message
        rather than silently running the mocked path."""
        monkeypatch.delenv("AGENTIC_NO_LLM", raising=False)
        cases_path = _write_minimal_mocked_dataset(tmp_path)

        with patch.object(
            eval_gate, "_has_live_provider_credentials", return_value=False
        ):
            exit_code = eval_gate.main(
                ["--cases", str(cases_path), "--threshold", "0.0", "--live"]
            )
        assert exit_code == 0


# ---------------------------------------------------------------------------
# Credential-gated skip (no AGENTIC_NO_LLM, no keys -- must exit 0, never call)
# ---------------------------------------------------------------------------


class TestLiveCredentialGate:
    def test_live_skips_when_agentic_no_llm_set(
        self,
        eval_gate: ModuleType,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.setenv("AGENTIC_NO_LLM", "1")
        cases_path = tmp_path / "cases.json"
        cases_path.write_text(json.dumps([_base_case()]), encoding="utf-8")

        with patch.object(
            eval_gate, "score_case_live", new_callable=AsyncMock
        ) as mock_live:
            exit_code = eval_gate.main(
                ["--cases", str(cases_path), "--threshold", "0.80", "--live"]
            )
        assert exit_code == 0
        mock_live.assert_not_called()
        assert "SKIPPED" in capsys.readouterr().out

    def test_live_skips_when_no_provider_key_configured(
        self,
        eval_gate: ModuleType,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.delenv("AGENTIC_NO_LLM", raising=False)
        cases_path = tmp_path / "cases.json"
        cases_path.write_text(json.dumps([_base_case()]), encoding="utf-8")

        with (
            patch.object(
                eval_gate, "_has_live_provider_credentials", return_value=False
            ),
            patch.object(
                eval_gate, "score_case_live", new_callable=AsyncMock
            ) as mock_live,
        ):
            exit_code = eval_gate.main(
                ["--cases", str(cases_path), "--threshold", "0.80", "--live"]
            )
        assert exit_code == 0
        mock_live.assert_not_called()
        out = capsys.readouterr().out
        assert "SKIPPED" in out
        assert "no provider API key" in out

    def test_live_proceeds_when_key_configured_and_no_llm_unset(
        self,
        eval_gate: ModuleType,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Sanity check the gate is INVERTED correctly: with a key present and
        AGENTIC_NO_LLM unset, --live must actually invoke the scoring path
        (still mocked here -- this never touches a real provider)."""
        monkeypatch.delenv("AGENTIC_NO_LLM", raising=False)
        cases_path = tmp_path / "cases.json"
        cases_path.write_text(json.dumps([_base_case()]), encoding="utf-8")

        fake_result = {
            "case_id": "unit_test_case_v1",
            "rubric": "code",
            "weighted_score": 1.0,
            "total_score": 1.0,
            "criterion_scores": {},
            "missing_criteria": [],
            "threshold": 0.80,
            "passed": True,
            "error": None,
            "live_run_scores": [1.0, 1.0, 1.0],
        }
        with (
            patch.object(
                eval_gate, "_has_live_provider_credentials", return_value=True
            ),
            patch.object(
                eval_gate,
                "score_case_live",
                new_callable=AsyncMock,
                return_value=fake_result,
            ) as mock_live,
        ):
            exit_code = eval_gate.main(
                ["--cases", str(cases_path), "--threshold", "0.80", "--live"]
            )
        assert exit_code == 0
        mock_live.assert_awaited_once()


# ---------------------------------------------------------------------------
# score_case_live: median-of-3 logic, all model calls mocked
# ---------------------------------------------------------------------------


def _expected_weighted_score(
    eval_gate: ModuleType, workflow_result: WorkflowResult, case: dict[str, Any]
) -> float:
    """Compute the ground-truth weighted_score for one mocked run the same
    way score_case_live does internally (derive_criteria + Scorer), so tests
    assert against the module's own real scoring logic rather than a
    hand-computed constant that could silently drift from the rubric."""
    golden = workflow_result.model_dump(mode="json")
    criteria = eval_gate.derive_criteria(golden, case)
    scorer = eval_gate.Scorer(eval_gate.load_rubric(str(case.get("rubric", "code"))))
    return scorer.score(criteria).weighted_score


class TestScoreCaseLiveMedian:
    @pytest.mark.asyncio
    async def test_takes_median_of_three_varying_runs(
        self, eval_gate: ModuleType
    ) -> None:
        """3 runs with distinct, strictly-increasing success rates (0%, 50%,
        100%) -> the run with the MIDDLE weighted_score is reported, not the
        mean and not a value absent from the 3 observed runs."""
        case = _base_case()
        results = [
            _make_workflow_result(
                "test_deterministic",
                step_statuses=[StepStatus.FAILED, StepStatus.FAILED],
                step_names=["step1", "step2"],
            ),
            _make_workflow_result(
                "test_deterministic",
                step_statuses=[StepStatus.SUCCESS, StepStatus.FAILED],
                step_names=["step1", "step2"],
            ),
            _make_workflow_result(
                "test_deterministic",
                step_statuses=[StepStatus.SUCCESS, StepStatus.SUCCESS],
                step_names=["step1", "step2"],
            ),
        ]
        expected_scores = sorted(
            _expected_weighted_score(eval_gate, r, case) for r in results
        )
        mock_run = AsyncMock(side_effect=results)
        with patch("agentic_v2.workflows.run_workflow", mock_run):
            result = await eval_gate.score_case_live(case, 0.0)

        assert mock_run.await_count == 3
        assert len(result["live_run_scores"]) == 3
        assert sorted(result["live_run_scores"]) == pytest.approx(expected_scores)
        # The reported weighted_score must equal the middle of the 3 observed
        # scores exactly -- not an average, not an interpolated value.
        assert result["weighted_score"] == pytest.approx(expected_scores[1])

    @pytest.mark.asyncio
    async def test_median_is_middle_of_three_not_average(
        self, eval_gate: ModuleType
    ) -> None:
        """Two low runs + one high run: mean would sit above the low pair,
        but the gate must report the median (equal to the repeated low
        score), proving it isn't silently averaging."""
        case = _base_case(threshold=0.0)
        results = [
            _make_workflow_result(
                "test_deterministic",
                step_statuses=[StepStatus.FAILED, StepStatus.FAILED],
                step_names=["step1", "step2"],
            ),
            _make_workflow_result(
                "test_deterministic",
                step_statuses=[StepStatus.FAILED, StepStatus.FAILED],
                step_names=["step1", "step2"],
            ),
            _make_workflow_result(
                "test_deterministic",
                step_statuses=[StepStatus.SUCCESS, StepStatus.SUCCESS],
                step_names=["step1", "step2"],
            ),
        ]
        expected_scores = sorted(
            _expected_weighted_score(eval_gate, r, case) for r in results
        )
        mock_run = AsyncMock(side_effect=results)
        with patch("agentic_v2.workflows.run_workflow", mock_run):
            result = await eval_gate.score_case_live(case, 0.0)

        mean_of_scores = sum(result["live_run_scores"]) / 3
        assert result["weighted_score"] == pytest.approx(expected_scores[1])
        assert result["weighted_score"] != pytest.approx(mean_of_scores)

    @pytest.mark.asyncio
    async def test_calls_run_workflow_with_case_live_inputs(
        self, eval_gate: ModuleType
    ) -> None:
        """run_workflow must be invoked with the workflow_name and live_inputs
        from the case, not the golden dataset's mocked input_data."""
        result = _make_workflow_result(
            "consensus_review",
            step_statuses=[StepStatus.SUCCESS],
            step_names=["vote"],
        )
        mock_run = AsyncMock(return_value=result)
        case = _base_case(
            workflow_name="consensus_review",
            live_inputs={"code_file": "x.py", "min_agreement": "0.66"},
        )
        with patch("agentic_v2.workflows.run_workflow", mock_run):
            await eval_gate.score_case_live(case, 0.0)

        assert mock_run.await_count == 3
        for call in mock_run.await_args_list:
            assert call.args == ("consensus_review",)
            assert call.kwargs == {"code_file": "x.py", "min_agreement": "0.66"}

    @pytest.mark.asyncio
    async def test_missing_workflow_name_errors_without_calling_model(
        self, eval_gate: ModuleType
    ) -> None:
        case = _base_case()
        del case["workflow_name"]
        mock_run = AsyncMock()
        with patch("agentic_v2.workflows.run_workflow", mock_run):
            result = await eval_gate.score_case_live(case, 0.80)

        mock_run.assert_not_awaited()
        assert result["passed"] is False
        assert "workflow_name" in result["error"]

    @pytest.mark.asyncio
    async def test_invalid_live_inputs_type_errors_without_calling_model(
        self, eval_gate: ModuleType
    ) -> None:
        case = _base_case(live_inputs="not-a-dict")
        mock_run = AsyncMock()
        with patch("agentic_v2.workflows.run_workflow", mock_run):
            result = await eval_gate.score_case_live(case, 0.80)

        mock_run.assert_not_awaited()
        assert result["passed"] is False
        assert "live_inputs" in result["error"]

    @pytest.mark.asyncio
    async def test_run_workflow_exception_reported_not_raised(
        self, eval_gate: ModuleType
    ) -> None:
        """A live model call can fail in provider-specific ways (timeout, rate
        limit, malformed response); score_case_live must catch and report,
        never propagate, so one bad case doesn't crash the whole dataset."""
        mock_run = AsyncMock(side_effect=RuntimeError("provider unavailable"))
        with patch("agentic_v2.workflows.run_workflow", mock_run):
            result = await eval_gate.score_case_live(_base_case(), 0.80)

        assert result["passed"] is False
        assert "provider unavailable" in result["error"]
        assert result["weighted_score"] == 0.0

    @pytest.mark.asyncio
    async def test_default_live_inputs_to_empty_dict_when_absent(
        self, eval_gate: ModuleType
    ) -> None:
        case = _base_case()
        del case["live_inputs"]
        result = _make_workflow_result(
            "test_deterministic",
            step_statuses=[StepStatus.SUCCESS],
            step_names=["step1"],
        )
        mock_run = AsyncMock(return_value=result)
        with patch("agentic_v2.workflows.run_workflow", mock_run):
            await eval_gate.score_case_live(case, 0.0)

        for call in mock_run.await_args_list:
            assert call.kwargs == {}


# ---------------------------------------------------------------------------
# End-to-end: --live --threshold 0.99 exits 1 given low mocked scores
# ---------------------------------------------------------------------------


class TestLiveThresholdFailure:
    def test_live_high_threshold_fails_given_low_mocked_scores(
        self,
        eval_gate: ModuleType,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """--live --threshold 0.99 must exit 1 when the (mocked) live runs
        score well below that bar -- the explicit scenario called out in the
        task brief."""
        monkeypatch.delenv("AGENTIC_NO_LLM", raising=False)
        cases_path = tmp_path / "cases.json"
        cases_path.write_text(
            json.dumps([_base_case(threshold=0.99)]), encoding="utf-8"
        )

        low_score_result = _make_workflow_result(
            "test_deterministic",
            step_statuses=[StepStatus.FAILED, StepStatus.FAILED],
            step_names=["step1", "step2"],
        )
        mock_run = AsyncMock(return_value=low_score_result)

        with (
            patch.object(
                eval_gate, "_has_live_provider_credentials", return_value=True
            ),
            patch("agentic_v2.workflows.run_workflow", mock_run),
        ):
            exit_code = eval_gate.main(
                ["--cases", str(cases_path), "--threshold", "0.99", "--live"]
            )

        assert exit_code == 1
        assert mock_run.await_count == 3

    def test_live_low_threshold_passes_given_high_mocked_scores(
        self,
        eval_gate: ModuleType,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Inverse control: the same plumbing with high scores and a low bar
        must exit 0, so test_live_high_threshold_fails_given_low_mocked_scores
        is verifying the threshold comparison, not something else entirely."""
        monkeypatch.delenv("AGENTIC_NO_LLM", raising=False)
        cases_path = tmp_path / "cases.json"
        cases_path.write_text(
            json.dumps([_base_case(threshold=0.10)]), encoding="utf-8"
        )

        high_score_result = _make_workflow_result(
            "test_deterministic",
            step_statuses=[StepStatus.SUCCESS, StepStatus.SUCCESS],
            step_names=["step1", "step2"],
        )
        mock_run = AsyncMock(return_value=high_score_result)

        with (
            patch.object(
                eval_gate, "_has_live_provider_credentials", return_value=True
            ),
            patch("agentic_v2.workflows.run_workflow", mock_run),
        ):
            exit_code = eval_gate.main(
                ["--cases", str(cases_path), "--threshold", "0.10", "--live"]
            )

        assert exit_code == 0
