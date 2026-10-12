"""Regression tests: review_report keeps the reviewer's full report.

fullstack_generation runs on 2026-10-11 stored the ``review_code`` step's
``review_report`` as only ``{"overall_status": ...}`` although
``raw_response`` held the whole report. Two things combined:

* The response sanitizer masks ``password=<non-space run>`` before parsing.
  The run swallows a JSON string's closing quote and the member's comma, so
  the report no longer parses.
* Every fallback then rebuilt ``review_report`` from the status alone: the
  JSON-path salvage overwrote it, and the sentinel path dropped an
  ``<<<ARTIFACT review_report>>>`` body that failed to parse.

The logged responses are replayed through both engines' parse entrypoints.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest

from agentic_v2.engine.llm_output_parsing import (
    _repair_json_object,
    parse_llm_json_output,
    parse_sentinel_output,
)
from agentic_v2.langchain.graph_wiring import parse_step_outputs
from agentic_v2.middleware.response_sanitizer import ResponseSanitizer

FIXTURES = Path(__file__).parent / "fixtures"

# Declared outputs of fullstack_generation.yaml's review_code step.
REVIEW_OUTPUT_KEYS = [
    "review_report",
    "code_review",
    "overall_status",
    "suggested_fixes",
    "fixes",
]

# The run logger cuts strings at 10,000 chars and appends this marker.
_LOG_TRUNCATION_SUFFIX = re.compile(r"\.\.\. \(\d+ chars\)$")


def _native_parse(text: str) -> dict[str, Any]:
    """Parse order of the native engine (agent_resolver)."""
    return parse_sentinel_output(text, REVIEW_OUTPUT_KEYS) or parse_llm_json_output(
        text, REVIEW_OUTPUT_KEYS
    )


def _langchain_parse(text: str) -> dict[str, Any]:
    """Parse entrypoint of the LangGraph engine."""
    return parse_step_outputs(text, REVIEW_OUTPUT_KEYS, warn_on_missing=False)


both_engines = pytest.mark.parametrize(
    "parse", [_native_parse, _langchain_parse], ids=["native", "langchain"]
)


def _logged_responses() -> list[dict[str, Any]]:
    path = FIXTURES / "review_report_raw_responses.json"
    return json.loads(path.read_text(encoding="utf-8"))["responses"]


LOGGED = _logged_responses()


def _parser_input(entry: dict[str, Any]) -> str:
    """Strip the run logger's marker: what remains is a prefix of the reply."""
    return _LOG_TRUNCATION_SUFFIX.sub("", entry["raw_response"])


# ---------------------------------------------------------------------------
# Logged responses
# ---------------------------------------------------------------------------

# (quality_score, finding count) read from each logged raw_response, keyed by
# the run id's hash suffix.
EXPECTED_FROM_LOG = {
    "befa1f22": (6.8, 7),
    "ba718cdc": (7.0, 9),
    "2a88e1c9": (8.5, 7),
    "41b29538": (7.8, 9),
}


def _run_suffix(entry: dict[str, Any]) -> str:
    return str(entry["run_id"]).rsplit("-", 1)[-1]


def test_fixture_records_the_reduced_report() -> None:
    """Each fixture is a run whose stored report kept only overall_status."""
    assert {_run_suffix(e) for e in LOGGED} == set(EXPECTED_FROM_LOG)
    for entry in LOGGED:
        assert entry["logged_review_report"] == {"overall_status": "NEEDS_FIXES"}


@both_engines
@pytest.mark.parametrize("entry", LOGGED, ids=lambda e: e["shape"])
def test_logged_response_keeps_full_report(parse: Any, entry: dict[str, Any]) -> None:
    report = parse(_parser_input(entry))["review_report"]

    score, finding_count = EXPECTED_FROM_LOG[_run_suffix(entry)]
    assert report["overall_status"] == "NEEDS_FIXES"
    assert report["quality_score"] == score
    assert set(report["summary"]) >= {"critical", "high", "medium", "low"}
    ids = [finding["finding_id"] for finding in report["findings"]]
    assert ids == [f"F-{n:03d}" for n in range(1, finding_count + 1)]


@both_engines
def test_masked_member_is_closed_without_losing_neighbours(parse: Any) -> None:
    """A masked string is closed at the end of its line; the next members stay."""
    entry = next(e for e in LOGGED if _run_suffix(e) == "2a88e1c9")

    findings = parse(_parser_input(entry))["review_report"]["findings"]

    masked = next(f for f in findings if f["finding_id"] == "F-002")
    assert masked["code_before"].endswith("[REDACTED:env_variable]")
    assert masked["code_after"].endswith("[REDACTED:env_variable]")
    assert masked["references"] == ["OWASP A07:2021", "CWE-312"]


@pytest.mark.parametrize("entry", LOGGED, ids=lambda e: e["shape"])
def test_engines_agree_on_logged_responses(entry: dict[str, Any]) -> None:
    text = _parser_input(entry)
    native = _native_parse(text)["review_report"]
    langchain = _langchain_parse(text)["review_report"]
    assert native == langchain


# ---------------------------------------------------------------------------
# Complete responses masked by the real response sanitizer
# ---------------------------------------------------------------------------

REPORT: dict[str, Any] = {
    "overall_status": "NEEDS_FIXES",
    "quality_score": 7.5,
    "summary": {"critical": 1, "high": 1, "medium": 0, "low": 0},
    "findings": [
        {
            "finding_id": "F-001",
            "severity": "critical",
            "title": "Hardcoded database password",
            "code_before": (
                '"DefaultConnection": '
                '"Host=localhost;Username=postgres;Password=postgres"'
            ),
            "code_after": '"DefaultConnection": "${DB_CONNECTION}"',
            "references": ["CWE-798"],
        },
        {
            "finding_id": "F-002",
            "severity": "high",
            "title": "Missing input validation",
            "references": ["CWE-20"],
        },
    ],
    "positive_observations": ["Async I/O throughout"],
}


def _wrapper(report: dict[str, Any]) -> str:
    return "```json\n" + json.dumps({"review_report": report}, indent=2) + "\n```"


def _artifact(report: dict[str, Any]) -> str:
    body = json.dumps(report, indent=2)
    return f"<<<ARTIFACT review_report>>>\n{body}\n<<<ENDARTIFACT>>>"


SHAPES = {
    "fenced_wrapper": _wrapper,
    "artifact_block": _artifact,
    "prose_then_fenced_wrapper": lambda r: (
        "The input is a .NET project.\n\n### Review Report\n\n" + _wrapper(r)
    ),
    "prose_then_artifact_block": lambda r: (
        "I could not read the files, so I reviewed the snippets.\n\n---\n\n```\n"
        + _artifact(r)
        + "\n```"
    ),
}


def _masked(text: str) -> str:
    return ResponseSanitizer().sanitize_response_sync(text).sanitized_text or text


def test_sanitizer_mask_breaks_the_report_json() -> None:
    """Precondition: masking removes the closing quote and the comma."""
    masked = _masked(json.dumps(REPORT, indent=2))

    assert "Password=postgres" not in masked
    assert re.search(r"\[REDACTED:env_variable\]\n\s+\"code_after\"", masked)
    with pytest.raises(json.JSONDecodeError):
        json.loads(masked, strict=False)


@both_engines
@pytest.mark.parametrize("shape", SHAPES)
def test_masked_report_keeps_all_fields(parse: Any, shape: str) -> None:
    outputs = parse(_masked(SHAPES[shape](REPORT)))
    report = outputs["review_report"]

    assert report["overall_status"] == "NEEDS_FIXES"
    assert report["quality_score"] == 7.5
    assert report["summary"] == REPORT["summary"]
    assert [f["finding_id"] for f in report["findings"]] == ["F-001", "F-002"]
    assert report["findings"][0]["references"] == ["CWE-798"]
    assert report["positive_observations"] == ["Async I/O throughout"]
    assert "Password=postgres" not in json.dumps(outputs)


@both_engines
def test_truncated_report_keeps_complete_members(parse: Any) -> None:
    """An output-token cap mid-finding keeps everything before the cut."""
    text = _wrapper(REPORT)
    cut = text.index('"title": "Missing input validation"') + len('"title": "Miss')

    report = parse(text[:cut])["review_report"]

    assert report["quality_score"] == 7.5
    assert [f["finding_id"] for f in report["findings"]] == ["F-001", "F-002"]
    assert report["findings"][1] == {"finding_id": "F-002", "severity": "high"}


# ---------------------------------------------------------------------------
# Status gating and remaining shapes
# ---------------------------------------------------------------------------


@both_engines
def test_damaged_approved_report_stays_approved(parse: Any) -> None:
    approved = {**REPORT, "overall_status": "APPROVED"}

    report = parse(_masked(_wrapper(approved)))["review_report"]

    assert report["overall_status"] == "APPROVED"
    assert report["quality_score"] == 7.5


@both_engines
def test_bare_fenced_report_is_the_review_report(parse: Any) -> None:
    """A fenced report without the review_report wrapper keeps its fields."""
    approved = {**REPORT, "overall_status": "APPROVED"}
    text = "```json\n" + json.dumps(approved, indent=2) + "\n```"

    report = parse(text)["review_report"]

    assert report["overall_status"] == "APPROVED"
    assert report["quality_score"] == 7.5
    assert len(report["findings"]) == 2


@both_engines
def test_prose_artifact_status_is_read_from_the_artifact(parse: Any) -> None:
    """A non-JSON artifact body still supplies the status it states."""
    text = (
        "<<<ARTIFACT review_report>>>\n"
        "overall_status: APPROVED. The code is ready to ship.\n"
        "<<<ENDARTIFACT>>>"
    )

    assert parse(text)["review_report"]["overall_status"] == "APPROVED"


@both_engines
def test_unrecoverable_text_still_defaults_to_needs_fixes(parse: Any) -> None:
    report = parse("The reviewer wrote prose only {and a stray brace.")["review_report"]

    assert report == {"overall_status": "NEEDS_FIXES"}


def test_native_parser_reads_fence_after_braced_prose() -> None:
    """The mid-text fence scan used to exist only on the LangGraph path."""
    text = 'Context {unbalanced.\n```json\n{"key": "value", "n": 2}\n```\nDone.'

    # No declared keys, so per-key salvage cannot stand in for the parse.
    assert parse_llm_json_output(text, None) == {"key": "value", "n": 2}
    assert parse_step_outputs(text)["n"] == 2


# ---------------------------------------------------------------------------
# _repair_json_object
# ---------------------------------------------------------------------------


def test_repair_leaves_valid_json_unchanged() -> None:
    text = '{\n  "code": "if x {\n  \\"a\\": 1\n}",\n  "n": [1, {"b": 2}]\n}'

    assert _repair_json_object(text, 0) == text


def test_repair_stops_at_the_object_end() -> None:
    text = 'prefix {"a": 1} trailing {"b": 2}'

    assert _repair_json_object(text, text.index("{")) == '{"a": 1}'


def test_repair_rejects_mismatched_brackets() -> None:
    assert _repair_json_object('{"a": [1, 2}', 0) is None


def test_repair_closes_open_containers_after_truncation() -> None:
    repaired = _repair_json_object('{"a": [1, 2, {"b": "tru', 0)

    assert repaired is not None
    assert json.loads(repaired) == {"a": [1, 2, {}]}
