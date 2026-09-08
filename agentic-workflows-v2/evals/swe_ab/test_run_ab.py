"""Unit tests for run_ab.py's wave-progress printer and case counter.

Run from the kit, under EvalKit's venv (``run_ab`` imports
``agentic_evalkit``): ``uv run python -m pytest test_run_ab.py -q``.

Lives next to ``run_ab.py`` for the same reason ``tools/test_wave_guards.py``
lives next to the scripts it tests: pytest's rootdir insertion is what puts
the kit root on ``sys.path``, which is how the kit's modules import each
other when run directly.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest
import run_ab
from agentic_evalkit.events import (
    ExecutionCompleted,
    GradeCompleted,
    RunCompleted,
    SampleCompleted,
)
from agentic_evalkit.models.execution import ExecutionStatus
from agentic_evalkit.models.grades import GradeStatus

if TYPE_CHECKING:
    from pathlib import Path

NOW = datetime(2026, 9, 6, 12, 0, tzinfo=UTC)
RUN_ID = "run-1"


def _executed(sample_id: str, status: ExecutionStatus, attempt: int = 1) -> ExecutionCompleted:
    return ExecutionCompleted(
        run_id=RUN_ID,
        sample_id=sample_id,
        attempt=attempt,
        status=status,
        completed_at=NOW,
    )


def _graded(sample_id: str, status: GradeStatus, attempt: int = 1) -> GradeCompleted:
    return GradeCompleted(
        run_id=RUN_ID,
        sample_id=sample_id,
        attempt=attempt,
        status=status,
        completed_at=NOW,
    )


def _completed(sample_id: str, attempt: int = 1) -> SampleCompleted:
    return SampleCompleted(run_id=RUN_ID, sample_id=sample_id, attempt=attempt, completed_at=NOW)


def _lines(capsys: pytest.CaptureFixture[str]) -> list[str]:
    """Progress output only -- it goes to stderr so stdout stays parseable."""
    captured = capsys.readouterr()
    assert captured.out == ""
    return [line for line in captured.err.splitlines() if line]


def test_reports_one_line_per_completed_sample(capsys: pytest.CaptureFixture[str]) -> None:
    progress = run_ab.WaveProgress(total=2)

    for sample_id, grade in (("EVK-MUT-001", GradeStatus.PASS), ("EVK-MUT-002", GradeStatus.FAIL)):
        progress(_executed(sample_id, ExecutionStatus.COMPLETED))
        progress(_graded(sample_id, grade))
        progress(_completed(sample_id))

    first, second = _lines(capsys)
    assert first.startswith("[   1/2] EVK-MUT-001 exec=completed grade=pass ")
    assert "| pass=1 |" in first
    assert second.startswith("[   2/2] EVK-MUT-002 exec=completed grade=fail ")
    # The tally is cumulative across the wave, not per line.
    assert "| fail=1 pass=1 |" in second


def test_ungraded_sample_is_not_counted_as_a_verdict(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """A failed execution is never graded, so no GradeCompleted arrives for it.

    That has to read as "no verdict", never as a pass -- the same distinction
    ADR-0008 draws between operational and task outcomes.
    """
    progress = run_ab.WaveProgress(total=1)

    progress(_executed("EVK-MUT-003", ExecutionStatus.FAILED))
    progress(_completed("EVK-MUT-003"))

    (line,) = _lines(capsys)
    assert "exec=failed grade=-" in line
    assert "| -=1 |" in line
    assert "pass" not in line


def test_unknown_total_renders_a_placeholder(capsys: pytest.CaptureFixture[str]) -> None:
    progress = run_ab.WaveProgress(total=None)

    progress(_executed("EVK-MUT-004", ExecutionStatus.COMPLETED))
    progress(_graded("EVK-MUT-004", GradeStatus.PASS))
    progress(_completed("EVK-MUT-004"))

    (line,) = _lines(capsys)
    assert line.startswith("[   1/?] EVK-MUT-004 ")


def test_attempts_of_one_sample_are_tracked_separately(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The runner emits one work item per (sample, attempt), so attempt is part of the key."""
    progress = run_ab.WaveProgress(total=2)

    progress(_executed("EVK-MUT-005", ExecutionStatus.COMPLETED, attempt=1))
    progress(_executed("EVK-MUT-005", ExecutionStatus.FAILED, attempt=2))
    progress(_graded("EVK-MUT-005", GradeStatus.PASS, attempt=1))
    progress(_completed("EVK-MUT-005", attempt=2))
    progress(_completed("EVK-MUT-005", attempt=1))

    second_attempt, first_attempt = _lines(capsys)
    assert "exec=failed grade=-" in second_attempt
    assert "exec=completed grade=pass" in first_attempt


def test_per_sample_state_is_released_once_reported() -> None:
    """Over a 200-sample wave these dicts would otherwise retain every status."""
    progress = run_ab.WaveProgress(total=1)

    progress(_executed("EVK-MUT-006", ExecutionStatus.COMPLETED))
    progress(_graded("EVK-MUT-006", GradeStatus.PASS))
    progress(_completed("EVK-MUT-006"))

    assert progress._executions == {}
    assert progress._grades == {}


def test_run_completed_reports_elapsed_time(capsys: pytest.CaptureFixture[str]) -> None:
    progress = run_ab.WaveProgress(total=1)

    progress(RunCompleted(run_id=RUN_ID, total_samples=1, finished_at=NOW))

    (line,) = _lines(capsys)
    assert line.startswith("run finished after 0:00:")


def test_case_count_ignores_blank_lines(tmp_path: Path) -> None:
    cases = tmp_path / "cases.jsonl"
    cases.write_text('{"sample_id": "a"}\n\n{"sample_id": "b"}\n   \n', encoding="utf-8")

    assert run_ab.case_count(cases) == 2


def test_child_env_sets_the_free_cost_lane_ceiling(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("AGENTIC_MAX_COST_LANE", raising=False)

    env = run_ab.build_child_env("swe_fix_direct", "openrouter:cohere/north-mini-code:free", 300.0)

    assert env["AGENTIC_MAX_COST_LANE"] == "free"


def test_child_env_still_blanks_paid_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    """The ceiling is layered on the credential strip, never a replacement.

    ADR-059's own Consequences keep the strip: the two controls catch
    different things, and a credential reaching the child by a path this
    process does not set (ARP's own .env) is only stopped by blanking.
    """
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-real-key")
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-real-key")

    # An `ollama:` model deliberately: that prefix has no entry in
    # _OWN_CREDENTIALS_BY_PREFIX, so nothing is exempted and every listed
    # credential must be blanked. (See the next test for the exemption path.)
    env = run_ab.build_child_env("swe_fix_direct", "ollama:deepseek-v4-flash:0731-cloud", 300.0)

    # Blanked, not deleted -- a deleted name is re-hydrated by load_dotenv.
    assert env["ANTHROPIC_API_KEY"] == ""
    assert env["OPENROUTER_API_KEY"] == ""


def test_child_env_exempts_the_model_under_test_own_credential(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Blanking a provider's key would break the primary call when it is the target."""
    monkeypatch.setenv("OPENROUTER_API_KEY", "or-real-key")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-real-key")

    env = run_ab.build_child_env("swe_fix_direct", "openrouter:cohere/north-mini-code:free", 300.0)

    assert env["OPENROUTER_API_KEY"] == "or-real-key"
    assert env["ANTHROPIC_API_KEY"] == ""


def test_child_env_ceiling_defaults_to_free() -> None:
    env = run_ab.build_child_env("swe_fix_direct", "openrouter:cohere/north-mini-code:free", 300.0)

    assert env["AGENTIC_MAX_COST_LANE"] == "free"


def test_child_env_ceiling_can_be_opted_out_of() -> None:
    """Spending a prepaid plan allowance is a legitimate, recorded choice.

    Ollama Cloud bills against a subscription allowance, so ``paid`` here can
    mean drawing down credits the operator already bought. The escape hatch is
    an argument precisely so it lands in the command line rather than in a
    registry entry that lies about a metered model being free.
    """
    env = run_ab.build_child_env(
        "swe_fix_direct", "ollama:deepseek-v4-flash:0731-cloud", 300.0, "paid"
    )

    assert env["AGENTIC_MAX_COST_LANE"] == "paid"
