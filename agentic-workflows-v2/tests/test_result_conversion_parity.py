"""F6: runner and server must preserve the same step evidence."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta, timezone
from types import MappingProxyType, SimpleNamespace

import pytest

from agentic_v2.contracts import StepStatus
from agentic_v2.langchain.result_builder import (
    build_workflow_result,
    extract_metadata,
    steps_dict_to_list,
)
from agentic_v2.server.result_normalization import (
    build_step_results,
    extract_tokens,
    normalize_workflow_result,
)
from agentic_v2.workflows.run_logger import build_step_record

START = datetime(2026, 9, 10, 12, tzinfo=UTC)
END = START + timedelta(seconds=2)
CONVERTERS = (steps_dict_to_list, build_step_results)


@pytest.mark.parametrize(
    "raw,expected",
    [
        (None, StepStatus.FAILED),
        ("completed", StepStatus.SUCCESS),
        ("running", StepStatus.RUNNING),
        ("pending", StepStatus.PENDING),
        ("retrying", StepStatus.RETRYING),
        ("error", StepStatus.FAILED),
    ],
)
def test_workflow_status_matches_step_evidence_for_cli_and_server(raw, expected):
    state = {"step": {"status": raw, "start_time": START, "end_time": END}}
    runner_result = build_workflow_result(
        workflow_name="wf",
        run_id="run",
        started_at=START,
        elapsed_seconds=2,
        steps=steps_dict_to_list(state),
    )
    server_result = normalize_workflow_result(
        SimpleNamespace(steps=state, status="success"), workflow_name="wf", run_id="run"
    )
    assert runner_result.overall_status is server_result.overall_status is expected
    assert build_step_record(runner_result.steps[0]) == build_step_record(
        server_result.steps[0]
    )


def convert_both(step, *, token_counts=None, models_used=None):
    """Compare complete results when timestamps are recorded, including log fields."""
    state = {
        "step": {"start_time": START.isoformat(), "end_time": END.isoformat(), **step}
    }
    before = deepcopy((state, token_counts, models_used))
    results = [
        convert(state, token_counts=token_counts, models_used=models_used)[0]
        for convert in CONVERTERS
    ]
    assert results[0].model_dump() == results[1].model_dump()
    assert build_step_record(results[0]) == build_step_record(results[1])
    assert (state, token_counts, models_used) == before
    return results[0]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("success", StepStatus.SUCCESS),
        ("succeeded", StepStatus.SUCCESS),
        ("completed", StepStatus.SUCCESS),
        (" Completed ", StepStatus.SUCCESS),
        ("failed", StepStatus.FAILED),
        ("error", StepStatus.FAILED),
        ("skipped", StepStatus.SKIPPED),
        ("skip", StepStatus.SKIPPED),
        ("pending", StepStatus.PENDING),
        ("queued", StepStatus.PENDING),
        ("running", StepStatus.RUNNING),
        ("in_progress", StepStatus.RUNNING),
        ("retrying", StepStatus.RETRYING),
        ("unknown", StepStatus.FAILED),
        ("", StepStatus.FAILED),
        (None, StepStatus.FAILED),
        (True, StepStatus.FAILED),
        (1, StepStatus.FAILED),
        ([], StepStatus.FAILED),
        ({"status": "success"}, StepStatus.FAILED),
        *[(status, status) for status in StepStatus],
    ],
)
def test_status_parity(raw, expected):
    result = convert_both({"status": raw})
    assert result.status is expected


def test_missing_status_is_failed_even_with_outputs():
    result = convert_both({"outputs": {"answer": 42}})
    assert result.status is StepStatus.FAILED
    assert result.output_data == {"answer": 42}


def test_normal_step_preserves_log_evidence():
    result = convert_both(
        {
            "status": "completed",
            "agent": "reviewer",
            "tier": 2,
            "inputs": {"question": "check"},
            "outputs": {"answer": "ok"},
            "metadata": {"input_tokens": 10, "output_tokens": 4, "model": "model-a"},
        }
    )
    record = build_step_record(result)
    assert record["status"] == "success"
    assert record["tokens_used"] == 14
    assert record["duration_ms"] == 2000
    assert record["start_time"] == START.isoformat()
    assert record["end_time"] == END.isoformat()
    assert record["agent_role"] == "reviewer"
    assert record["model_used"] == "model-a"
    assert record["tier"] == 2
    assert record["input"] == {"question": "check"}
    assert record["output"] == {"answer": "ok"}


@pytest.mark.parametrize("total_key", ["tokens_used", "total_tokens"])
def test_recorded_totals_and_components_win(total_key):
    recorded = {
        "input_tokens": 10,
        "output_tokens": 4,
        total_key: 21,
        "contract_diagnostics": [{"code": "invalid_output"}],
    }
    result = convert_both(
        {"status": "failed", "metadata": recorded, "model_used": "recorded"},
        token_counts={"step": {"input": 100, "output": 200}},
        models_used={"step": "supplemental"},
    )
    assert result.model_used == "recorded"
    assert all(result.metadata[key] == value for key, value in recorded.items())
    assert result.metadata["tokens_used"] == 21


def test_total_uses_merged_components_without_overwriting_recorded_values():
    result = convert_both(
        {"status": "success", "metadata": {"input_tokens": 10}},
        token_counts={"step": {"input": 100, "output": 4}},
    )
    assert result.metadata == {
        "input_tokens": 10,
        "output_tokens": 4,
        "tokens_used": 14,
    }


@pytest.mark.parametrize(
    ("step", "models", "expected"),
    [
        (
            {"model_used": "canonical", "model": "alias"},
            {"step": "external"},
            "canonical",
        ),
        ({"model": "alias"}, {}, "alias"),
        ({"metadata": {"model": "metadata"}}, {"step": "external"}, "metadata"),
        ({"metadata": {"model_used": "metadata"}}, {}, "metadata"),
        ({}, {"step": "external"}, "external"),
        ({"model_used": 42, "metadata": {"model": "valid"}}, {}, "valid"),
        ({"model_used": []}, {"step": {}}, None),
    ],
)
def test_model_aliases_and_precedence(step, models, expected):
    assert (
        convert_both({"status": "success", **step}, models_used=models).model_used
        == expected
    )


@pytest.mark.parametrize(
    ("step", "expected"),
    [
        ({"agent": "alias"}, "alias"),
        ({"agent_role": "canonical", "agent": "alias"}, "canonical"),
        ({"agent_role": None, "agent": "alias"}, "alias"),
        ({"agent_role": [], "agent": {}}, None),
    ],
)
def test_agent_aliases(step, expected):
    assert convert_both(step).agent_role == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, {}),
        ("text", {"value": "text"}),
        ([1, 2], {"value": [1, 2]}),
        (0, {"value": 0}),
        ({"x": 1}, {"x": 1}),
        ({1: "x"}, {"1": "x"}),
    ],
)
def test_inputs_outputs_are_preserved_as_dicts(value, expected):
    result = convert_both({"inputs": value, "outputs": value})
    assert result.input_data == result.output_data == expected


def test_contract_input_output_aliases():
    result = convert_both({"input_data": {"x": 1}, "output_data": {"y": 2}})
    assert result.input_data == {"x": 1}
    assert result.output_data == {"y": 2}


@pytest.mark.parametrize("error", ["boom", {"message": "boom"}, ["boom"], 0, False])
def test_errors_are_retained(error):
    result = convert_both(
        {"status": "error", "error": error, "error_type": "ToolError", "retry_count": 2}
    )
    assert result.status is StepStatus.FAILED
    assert result.error == str(error)
    assert result.error_type == "ToolError"
    assert result.retry_count == 2


@pytest.mark.parametrize("value", [None, [], "bad", -1, 6, True, 2.5])
def test_invalid_tier_does_not_abort_conversion(value):
    assert convert_both({"tier": value}).tier is None


@pytest.mark.parametrize("value", [None, [], "bad", -1, True, 2.5])
def test_invalid_retry_count_does_not_abort_conversion(value):
    assert convert_both({"retry_count": value}).retry_count == 0


@pytest.mark.parametrize(
    ("metadata", "tokens", "expected"),
    [
        ({}, None, None),
        ({}, {"step": {}}, None),
        (None, {"step": {"input": 10, "output": 4}}, 14),
        ([], {"step": {"input": "10", "output": "4"}}, 14),
        ({"input_tokens": 0, "output_tokens": 0}, None, 0),
        ({"tokens_used": 0, "input_tokens": 10}, None, 0),
        ({"input_tokens": 10}, None, 10),
        ({"output_tokens": 4}, None, 4),
        ({"input_tokens": 10, "output_tokens": "bad"}, None, None),
        ({"input_tokens": True}, None, None),
        ({"input_tokens": -1}, None, None),
        ({"input_tokens": 1.5}, None, None),
        ({}, {"step": {"input": "bad", "output": []}}, None),
        ({}, {"step": {"input": True, "output": -1}}, None),
        ({}, {"step": []}, None),
        ({}, [], None),
        ({}, "bad", None),
    ],
)
def test_token_metadata_robustness(metadata, tokens, expected):
    result = convert_both({"metadata": metadata}, token_counts=tokens)
    assert result.metadata.get("tokens_used") == expected
    assert extract_tokens(result.metadata) == expected
    assert result.status is StepStatus.FAILED


@pytest.mark.parametrize("metadata", [None, [], 1, "bad"])
def test_extract_tokens_accepts_malformed_metadata(metadata):
    assert extract_tokens(metadata) is None


@pytest.mark.parametrize(
    ("start", "end"),
    [
        (START, END),
        (START.isoformat(), END.isoformat()),
        ("2026-09-10T12:00:00Z", "2026-09-10T12:00:02Z"),
        (START.replace(tzinfo=None), END),
        (START, END.replace(tzinfo=None).isoformat()),
        (START.astimezone(timezone(timedelta(hours=2))), END),
    ],
)
def test_recorded_timestamp_formats(start, end):
    result = convert_both({"start_time": start, "end_time": end})
    assert result.start_time == START
    assert result.end_time == END
    assert result.duration_ms == 2000


@pytest.mark.parametrize("value", [None, "invalid", {}, 42])
@pytest.mark.parametrize("convert", CONVERTERS)
def test_missing_or_malformed_timestamps_are_safe(convert, value):
    before = datetime.now(UTC)
    result = convert({"step": {"start_time": value, "end_time": value}})[0]
    assert before <= result.start_time <= datetime.now(UTC)
    assert result.end_time is None
    assert result.duration_ms is None
    assert result.status is StepStatus.FAILED
    assert build_step_record(result)["status"] == "failed"


@pytest.mark.parametrize("convert", CONVERTERS)
def test_mapping_inputs_order_and_malformed_entries(convert):
    step = MappingProxyType(
        {
            "status": "pending",
            "start_time": START,
            "metadata": MappingProxyType({"input_tokens": 10, "output_tokens": 4}),
        }
    )
    state = MappingProxyType({"a": step, "bad": None, "": {}, 7: step, "b": "bad"})
    result = convert(state)
    assert [s.step_name for s in result] == ["a", "7"]
    assert all(s.status is StepStatus.PENDING for s in result)
    assert all(s.metadata["tokens_used"] == 14 for s in result)


@pytest.mark.parametrize("value", [None, [], "bad", 1])
@pytest.mark.parametrize("convert", CONVERTERS)
def test_malformed_step_container(convert, value):
    assert convert(value) == []


@pytest.mark.parametrize(
    "state",
    [
        None,
        [],
        {},
        {"steps": None},
        {"steps": []},
        {"steps": {"bad": None, "other": {"metadata": []}}},
    ],
)
def test_extract_metadata_handles_malformed_state(state):
    assert extract_metadata(state) == ({}, {})


def test_metadata_extraction_and_conversion_preserve_zero_counts_and_model():
    state = {
        "steps": {
            "step": {
                "status": "completed",
                "metadata": {
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "model": "recorded",
                },
            }
        }
    }
    tokens, models = extract_metadata(state)
    assert tokens == {"step": {"input": 0, "output": 0}}
    assert models == {"step": "recorded"}
    result = convert_both(
        state["steps"]["step"], token_counts=tokens, models_used=models
    )
    assert result.metadata["tokens_used"] == 0
    assert result.model_used == "recorded"
