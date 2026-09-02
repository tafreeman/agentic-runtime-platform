"""Tests for `ledger.load_report`: report JSON -> ledger dataclass rows.

Fixtures used here are hand-written minimal reports under
`tests/fixtures/*.json` -- deliberately small (1-5 samples), not copies of a
full real report, so each exercises a specific branch. The one exception is
`test_ledger_real_report_loads_without_raising`, which reads the real
`reports/arm-a-direct-wave11.json` file to catch drift between the fixtures
and reality.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from ledger import ids
from ledger.load_report import (
    LoadedBatch,
    UnknownInstanceError,
    load_report,
    parse_model_ref,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"
REAL_REPORTS_DIR = Path(__file__).resolve().parents[2] / "reports"


def _load_fixture(name: str) -> dict[str, Any]:
    result: dict[str, Any] = json.loads(
        (FIXTURES_DIR / name).read_text(encoding="utf-8")
    )
    return result


# ---------------------------------------------------------------------
# ledger_-prefixed fixtures
# ---------------------------------------------------------------------


@pytest.fixture
def ledger_call_kwargs() -> dict[str, Any]:
    """The caller-supplied context common to every `load_report` call here.

    See `load_report`'s "Deliberate signature extensions" docstring note
    for why `task_set_id`/`harness_version`/`evalkit_version`/`grader_id`/
    `model_id`/`workflow_id`/`retrieval_mode` are required alongside the
    brief's literal `campaign_id`/`wave_id`/`arm_id`/`batch_id`.
    """
    return {
        "campaign_id": "cmp_test",
        "wave_id": "wav_test",
        "arm_id": "arm_test",
        "batch_id": "bat_test",
        "task_set_id": "tsk_test",
        "harness_version": "arp@0.0.0-test",
        "evalkit_version": "0.3.0",
        "grader_id": "grd_test",
        "model_id": "mdl_test",
        "workflow_id": "wfl_test",
        "retrieval_mode": "oracle",
    }


@pytest.fixture
def ledger_basic_batch() -> dict[str, Any]:
    return _load_fixture("basic_batch.json")


@pytest.fixture
def ledger_basic_task_ids() -> dict[str, str]:
    return {
        "proj__pass-1": "tas_pass1",
        "proj__timeout-1": "tas_timeout1",
        "proj__baddata-1": "tas_baddata1",
        "proj__spilled-1": "tas_spilled1",
        "proj__subsec-1": "tas_subsec1",
    }


@pytest.fixture
def ledger_basic_result(
    ledger_basic_batch: dict[str, Any],
    ledger_basic_task_ids: dict[str, str],
    ledger_call_kwargs: dict[str, Any],
) -> LoadedBatch:
    return load_report(
        ledger_basic_batch,
        task_ids=ledger_basic_task_ids,
        **ledger_call_kwargs,
    )


def _trial_for(result: LoadedBatch, task_id: str) -> Any:
    matches = [t for t in result.trials if t.task_id == task_id]
    assert len(matches) == 1, f"expected exactly one trial for {task_id}, got {matches}"
    return matches[0]


def _grade_for(result: LoadedBatch, trial_id: str) -> Any:
    matches = [g for g in result.grades if g.trial_id == trial_id]
    assert len(matches) <= 1, (
        f"expected at most one grade for {trial_id}, got {matches}"
    )
    return matches[0] if matches else None


# ---------------------------------------------------------------------
# Passing sample -> one trial (op_status ok) + one grade (outcome pass)
# ---------------------------------------------------------------------


def test_ledger_passing_sample_produces_ok_trial_and_pass_grade(
    ledger_basic_result: LoadedBatch,
) -> None:
    trial = _trial_for(ledger_basic_result, "tas_pass1")
    assert trial.op_status == "ok"
    assert trial.run_idx == 1

    grade = _grade_for(ledger_basic_result, trial.trial_id)
    assert grade is not None
    assert grade.status == "pass"
    assert grade.outcome == "pass"
    assert grade.score == 1.0


# ---------------------------------------------------------------------
# Timeout sample -> trial with op_status 'timeout', NO grade row
# ---------------------------------------------------------------------


def test_ledger_timeout_sample_produces_trial_with_no_grade(
    ledger_basic_result: LoadedBatch,
) -> None:
    trial = _trial_for(ledger_basic_result, "tas_timeout1")
    assert trial.op_status == "timeout"
    assert trial.error_kind == "target_timeout"
    assert trial.wall_seconds == pytest.approx(900.0)

    assert _grade_for(ledger_basic_result, trial.trial_id) is None


# ---------------------------------------------------------------------
# Grade present despite non-ok execution -> dropped, warning names sample
# ---------------------------------------------------------------------


def test_ledger_grade_dropped_when_execution_not_ok_and_warns(
    ledger_basic_result: LoadedBatch,
) -> None:
    trial = _trial_for(ledger_basic_result, "tas_baddata1")
    assert trial.op_status == "error"
    assert trial.error_kind == "target_failure"

    # The trigger `trg_grade_requires_ok_trial` in schema.sql would reject
    # this insert outright; the loader must never even try it.
    assert _grade_for(ledger_basic_result, trial.trial_id) is None

    matching = [
        w
        for w in ledger_basic_result.warnings
        if "proj__baddata-1" in w and "dropping" in w
    ]
    assert len(matching) == 1, ledger_basic_result.warnings


# ---------------------------------------------------------------------
# Spilled sample, no resolver -> trial produced, warning, nothing invented
# ---------------------------------------------------------------------


def test_ledger_spilled_sample_without_resolver_warns_and_no_invented_values(
    ledger_basic_result: LoadedBatch,
) -> None:
    trial = _trial_for(ledger_basic_result, "tas_spilled1")
    assert trial.op_status == "ok"
    assert trial.answer_blob == (
        "sha256:8c2bbf9dc89854257f3c5142ba2da8bc02b77c3ecd9654921a373f14efa92f4f"
    )
    # No invented models -- the trial says "no models known", not a guess.
    assert trial.models_answered == "[]"

    matching = [
        w
        for w in ledger_basic_result.warnings
        if "proj__spilled-1" in w and "no resolver supplied" in w
    ]
    assert len(matching) == 1, ledger_basic_result.warnings
    assert "workflow, requested_model, models_used and elapsed_seconds" in matching[0]

    # The grade for this sample (op_status ok) is unaffected by the spill.
    grade = _grade_for(ledger_basic_result, trial.trial_id)
    assert grade is not None
    assert grade.status == "fail"


def test_ledger_spilled_sample_with_resolver_populates_fields(
    ledger_basic_batch: dict[str, Any],
    ledger_basic_task_ids: dict[str, str],
    ledger_call_kwargs: dict[str, Any],
) -> None:
    ref = "sha256:8c2bbf9dc89854257f3c5142ba2da8bc02b77c3ecd9654921a373f14efa92f4f"
    resolved_payload = {
        "workflow": "swe_fix_direct",
        "requested_model": "ollama:deepseek-v4-flash:0731-cloud",
        "models_used": ["ollama:deepseek-v4-flash:0731-cloud"],
        "step_count": 3,
        "elapsed_seconds": 42.0,
    }

    def resolve_output(candidate_ref: str) -> Mapping[str, Any] | None:
        return resolved_payload if candidate_ref == ref else None

    result = load_report(
        ledger_basic_batch,
        task_ids=ledger_basic_task_ids,
        resolve_output=resolve_output,
        **ledger_call_kwargs,
    )

    trial = _trial_for(result, "tas_spilled1")
    assert trial.answer_blob == ref
    assert trial.models_answered == '["ollama:deepseek-v4-flash:0731-cloud"]'

    unavailable_warnings = [
        w for w in result.warnings if "proj__spilled-1" in w and "no resolver" in w
    ]
    assert unavailable_warnings == []


# ---------------------------------------------------------------------
# wall_seconds derivation, including a sub-second duration
# ---------------------------------------------------------------------


def test_ledger_wall_seconds_subsecond(ledger_basic_result: LoadedBatch) -> None:
    trial = _trial_for(ledger_basic_result, "tas_subsec1")
    assert trial.wall_seconds == pytest.approx(0.25)


# ---------------------------------------------------------------------
# tokens/cost -> None with a warning; and the inverse when they ARE present
# ---------------------------------------------------------------------


def test_ledger_tokens_and_cost_map_to_none_with_warning(
    ledger_basic_result: LoadedBatch,
) -> None:
    trial = _trial_for(ledger_basic_result, "tas_pass1")
    assert trial.tokens_in is None
    assert trial.tokens_out is None

    matching = [
        w
        for w in ledger_basic_result.warnings
        if "proj__pass-1" in w and "input_tokens/output_tokens/cost_usd" in w
    ]
    assert len(matching) == 1, ledger_basic_result.warnings

    # No spend row at all when there is no cost to record.
    assert all(s.trial_id != trial.trial_id for s in ledger_basic_result.spends)


def test_ledger_cost_present_produces_spend_row(
    ledger_call_kwargs: dict[str, Any],
) -> None:
    report = _load_fixture("cost_present.json")
    result = load_report(
        report,
        task_ids={"proj__cost-1": "tas_cost1"},
        **ledger_call_kwargs,
    )

    trial = _trial_for(result, "tas_cost1")
    assert trial.tokens_in == 1000
    assert trial.tokens_out == 200

    matching_spends = [s for s in result.spends if s.trial_id == trial.trial_id]
    assert len(matching_spends) == 1
    assert matching_spends[0].cost_usd == pytest.approx(0.0123)

    assert not any("input_tokens/output_tokens/cost_usd" in w for w in result.warnings)


# ---------------------------------------------------------------------
# parse_model_ref against every real shape, plus null/malformed
# ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("fingerprint", "expected"),
    [
        (
            "ollama:deepseek-v4-flash:0731-cloud@20ace0a669f0",
            ("ollama", "deepseek-v4-flash:0731-cloud"),
        ),
        (
            "nvidia:deepseek-ai/deepseek-v4-flash-0731@321891f06917",
            ("nvidia", "deepseek-ai/deepseek-v4-flash-0731"),
        ),
        (
            "openrouter:minimax/minimax-m3:free@a6fd1fce537d",
            ("openrouter", "minimax/minimax-m3:free"),
        ),
        (None, ("unknown", "unknown")),
        ("no-at-sign-here", ("unknown", "unknown")),
        ("", ("unknown", "unknown")),
    ],
)
def test_ledger_parse_model_ref(
    fingerprint: str | None, expected: tuple[str, str]
) -> None:
    assert parse_model_ref(fingerprint) == expected


# ---------------------------------------------------------------------
# run_idx from attempt; two attempts -> two distinct trials
# ---------------------------------------------------------------------


def test_ledger_two_attempts_produce_two_distinct_trials(
    ledger_call_kwargs: dict[str, Any],
) -> None:
    report = _load_fixture("two_attempts.json")
    result = load_report(
        report,
        task_ids={"proj__retry-1": "tas_retry1"},
        **ledger_call_kwargs,
    )

    assert len(result.trials) == 2
    run_idxs = sorted(t.run_idx for t in result.trials)
    assert run_idxs == [1, 2]

    trial_ids = {t.trial_id for t in result.trials}
    trace_ids = {t.trace_id for t in result.trials}
    assert len(trial_ids) == 2, "attempts must produce distinct trial_id values"
    assert len(trace_ids) == 2, "attempts must produce distinct trace_id values"

    statuses = {t.run_idx: t.op_status for t in result.trials}
    assert statuses == {1: "ok", 2: "ok"}

    outcomes = {g.score for g in result.grades}
    assert outcomes == {0.0, 1.0}


# ---------------------------------------------------------------------
# Missing instance_id -> raises, naming the instance
# ---------------------------------------------------------------------


def test_ledger_missing_instance_id_raises(ledger_call_kwargs: dict[str, Any]) -> None:
    report = _load_fixture("single_pass.json")

    with pytest.raises(UnknownInstanceError, match="proj__solo-1"):
        load_report(report, task_ids={}, **ledger_call_kwargs)


# ---------------------------------------------------------------------
# trial_id / trace_id are deterministic content ids, not opaque strings
# ---------------------------------------------------------------------


def test_ledger_trial_id_and_trace_id_are_deterministic_content_ids(
    ledger_basic_result: LoadedBatch, ledger_call_kwargs: dict[str, Any]
) -> None:
    trial = _trial_for(ledger_basic_result, "tas_pass1")

    expected_trial_id = ids.content_id(
        "trl",
        {
            "wave_id": ledger_call_kwargs["wave_id"],
            "arm_id": ledger_call_kwargs["arm_id"],
            "task_id": "tas_pass1",
            "run_idx": 1,
        },
    )
    expected_trace_id = ids.content_id(
        "trc",
        {
            "wave_id": ledger_call_kwargs["wave_id"],
            "arm_id": ledger_call_kwargs["arm_id"],
            "task_id": "tas_pass1",
            "run_idx": 1,
        },
    )
    assert trial.trial_id == expected_trial_id
    assert trial.trace_id == expected_trace_id
    assert trial.trial_id != trial.trace_id


# ---------------------------------------------------------------------
# Substrate / ArmConfig derivation
# ---------------------------------------------------------------------


def test_ledger_substrate_and_arm_config_are_derived_and_referenced(
    ledger_basic_result: LoadedBatch, ledger_call_kwargs: dict[str, Any]
) -> None:
    assert (
        ledger_basic_result.substrate.task_set_id == ledger_call_kwargs["task_set_id"]
    )
    assert ledger_basic_result.substrate.grader_id == ledger_call_kwargs["grader_id"]

    assert ledger_basic_result.arm_config.model_id == ledger_call_kwargs["model_id"]
    assert ledger_basic_result.arm_config.temperature == pytest.approx(0.0)
    assert ledger_basic_result.arm_config.seed == 12345
    assert ledger_basic_result.arm_config.top_p is None
    assert ledger_basic_result.arm_config.tool_policy is None

    # Every trial in the batch references the same substrate/arm_config/model.
    for trial in ledger_basic_result.trials:
        assert trial.substrate_id == ledger_basic_result.substrate.substrate_id
        assert trial.arm_config_id == ledger_basic_result.arm_config.arm_config_id
        assert trial.model_id == ledger_call_kwargs["model_id"]

    assert any(
        "top_p, top_k, max_tokens, context_window_used, tool_policy" in w
        for w in ledger_basic_result.warnings
    )


# ---------------------------------------------------------------------
# Real report: catches drift between the hand-written fixtures and reality
# ---------------------------------------------------------------------


_REAL_REPORT_PATH = REAL_REPORTS_DIR / "arm-a-direct-wave11.json"


@pytest.mark.skipif(
    not _REAL_REPORT_PATH.exists(),
    reason=f"real report fixture not present at {_REAL_REPORT_PATH}",
)
def test_ledger_real_report_loads_without_raising(
    ledger_call_kwargs: dict[str, Any],
) -> None:
    report = json.loads(_REAL_REPORT_PATH.read_text(encoding="utf-8"))

    task_ids = {}
    for entry in report["samples"]:
        instance_id = entry["sample"]["metadata"]["instance_id"]
        task_ids[instance_id] = ids.content_id("tas", {"instance_id": instance_id})

    result = load_report(report, task_ids=task_ids, **ledger_call_kwargs)

    assert len(result.trials) == 18
    assert len({t.trial_id for t in result.trials}) == 18
    assert len({t.trace_id for t in result.trials}) == 18
    # Every real sample in this file completes; every completed sample has
    # a real (non-partial) grade, per the summary block in the report.
    assert all(t.op_status == "ok" for t in result.trials)
    assert len(result.grades) == 18
