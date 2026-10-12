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

Run data is not committed (AGENTS.md), so the four logged reply shapes are
rebuilt from a synthetic report: masked the way the sanitizer masked them on
2026-10-11, then cut where the logged replies were cut. Each is parsed through both engines' entrypoints.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any

import pytest

from agentic_v2.engine.llm_output_parsing import (
    _repair_json_object,
    parse_llm_json_output,
    parse_sentinel_output,
)
from agentic_v2.langchain.graph_wiring import parse_step_outputs

# Declared outputs of fullstack_generation.yaml's review_code step.
REVIEW_OUTPUT_KEYS = [
    "review_report",
    "code_review",
    "overall_status",
    "suggested_fixes",
    "fixes",
]

MASK = "[REDACTED:env_variable]"


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


# The env_secret mask as shipped on 2026-10-11: greedy up to whitespace, so
# inside a JSON string it also removed the closing quote and the comma. It is
# reproduced here so these parser tests do not depend on sanitizer changes.
_SHIPPED_ENV_SECRET_MASK = re.compile(
    r"(?i)(?:password|secret|token|credential)\s*[=:]\s*\S{8,}"
)


def _masked(text: str) -> str:
    return _SHIPPED_ENV_SECRET_MASK.sub(MASK, text)


def _cut_inside(text: str, marker: str, keep: int) -> str:
    """Truncate *text* *keep* characters into *marker*, as a token cap would."""
    return text[: text.index(marker) + keep]


REPORT: dict[str, Any] = {
    "overall_status": "NEEDS_FIXES",
    "quality_score": 7.0,
    "summary": {"critical": 1, "high": 1, "medium": 1, "low": 0},
    "findings": [
        {
            "finding_id": "F-001",
            "severity": "critical",
            "title": "Connection string holds a password",
            "code_before": (
                '"DefaultConnection": "Host=db;Username=app;Password=app-secret"'
            ),
            "code_after": (
                '"DefaultConnection": "Host=db;Username=app;Password=${DB_PASSWORD}"'
            ),
            "references": ["CWE-312"],
        },
        {
            "finding_id": "F-002",
            "severity": "high",
            "title": "Missing input validation",
            "suggested_fix": "Validate request bodies.",
            "references": ["CWE-20"],
        },
        {
            "finding_id": "F-003",
            "severity": "medium",
            "title": "In-memory database in production",
            "suggested_fix": "Use a persistent provider.",
            "code_before": "services.AddDbContext(o => o.UseInMemoryDatabase());",
            "references": ["CWE-805", "OWASP A04:2021"],
        },
    ],
    "positive_observations": ["Async I/O throughout"],
}

FINDING_IDS = ["F-001", "F-002", "F-003"]


def _wrapper(report: dict[str, Any], **extra: Any) -> str:
    payload = {"review_report": report, **extra}
    return "```json\n" + json.dumps(payload, indent=2) + "\n```"


def _artifact(report: dict[str, Any]) -> str:
    body = json.dumps(report, indent=2)
    return f"<<<ARTIFACT review_report>>>\n{body}\n<<<ENDARTIFACT>>>"


# ---------------------------------------------------------------------------
# The four reply shapes from the 2026-10-11 run logs
# ---------------------------------------------------------------------------


def _prose_then_fenced_wrapper_cut_in_string() -> str:
    """Run befa1f22: prose, a fenced wrapper, cut inside a code string."""
    text = _masked(
        "The input describes a .NET project, so I reviewed the code shown.\n\n"
        "---\n\n### Review Report\n\n" + _wrapper(REPORT)
    )
    return _cut_inside(text, '"code_before": "services', len('"code_before": "serv'))


def _prose_then_artifact_cut_in_array() -> str:
    """Run ba718cdc: prose, a fenced artifact, cut inside references."""
    text = _masked(
        "I could not open the files, so the review covers the snippets.\n\n"
        "---\n\n```\n" + _artifact(REPORT) + "\n```"
    )
    return _cut_inside(text, '"OWASP A04', len('"OWASP '))


def _fenced_wrapper_with_trailing_members_cut() -> str:
    """Run 2a88e1c9: a fenced wrapper plus sibling outputs, cut in the last."""
    text = _masked(
        _wrapper(
            REPORT,
            code_review={"backend": {"status": "NEEDS_FIXES"}},
            overall_status="NEEDS_FIXES",
            suggested_fixes=[{"finding_id": "F-001", "description": "Move it out"}],
        )
    )
    return _cut_inside(text, '"description": "Move', len('"description": "Mo'))


def _fenced_artifact_then_cut_second_artifact() -> str:
    """Run 41b29538: a whole artifact, then a second one cut short."""
    second = json.dumps({"backend": {"config": {"status": "NEEDS_FIXES"}}}, indent=2)
    text = _masked(
        "```\n" + _artifact(REPORT) + "\n\n---\n<<<ARTIFACT code_review>>>\n" + second
    )
    return _cut_inside(text, '"config"', len('"config"'))


LOGGED_SHAPES: dict[str, Callable[[], str]] = {
    "prose_then_fenced_wrapper": _prose_then_fenced_wrapper_cut_in_string,
    "prose_then_artifact_block": _prose_then_artifact_cut_in_array,
    "fenced_wrapper": _fenced_wrapper_with_trailing_members_cut,
    "fenced_artifact_block": _fenced_artifact_then_cut_second_artifact,
}


@pytest.mark.parametrize("shape", LOGGED_SHAPES)
def test_replica_carries_the_logged_damage(shape: str) -> None:
    """Precondition: the mask ate a closing quote, as in the logged replies."""
    text = LOGGED_SHAPES[shape]()

    assert "Password=" not in text
    assert re.search(re.escape(MASK) + r'\n\s+"code_after"', text)


@both_engines
@pytest.mark.parametrize("shape", LOGGED_SHAPES)
def test_logged_shape_keeps_full_report(parse: Any, shape: str) -> None:
    report = parse(LOGGED_SHAPES[shape]())["review_report"]

    assert report["overall_status"] == "NEEDS_FIXES"
    assert report["quality_score"] == 7.0
    assert report["summary"] == REPORT["summary"]
    assert [f["finding_id"] for f in report["findings"]] == FINDING_IDS
    masked = report["findings"][0]
    assert masked["code_before"].endswith(MASK)
    assert masked["code_after"].endswith(MASK)
    assert masked["references"] == ["CWE-312"]


@both_engines
def test_cut_in_a_string_drops_only_that_member(parse: Any) -> None:
    text = _prose_then_fenced_wrapper_cut_in_string()

    last = parse(text)["review_report"]["findings"][-1]

    assert "code_before" not in last
    assert last["suggested_fix"] == "Use a persistent provider."


@both_engines
def test_cut_in_an_array_keeps_its_complete_elements(parse: Any) -> None:
    text = _prose_then_artifact_cut_in_array()

    last = parse(text)["review_report"]["findings"][-1]

    assert last["references"] == ["CWE-805"]


@pytest.mark.parametrize("shape", LOGGED_SHAPES)
def test_engines_agree_on_logged_shapes(shape: str) -> None:
    text = LOGGED_SHAPES[shape]()

    native = _native_parse(text)["review_report"]
    langchain = _langchain_parse(text)["review_report"]

    assert native == langchain


# ---------------------------------------------------------------------------
# Complete responses with the shipped mask's damage
# ---------------------------------------------------------------------------

SHAPES: dict[str, Callable[[dict[str, Any]], str]] = {
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


def test_shipped_mask_breaks_the_report_json() -> None:
    """Precondition: masking removes the closing quote and the comma."""
    masked = _masked(json.dumps(REPORT, indent=2))

    assert "Password=" not in masked
    with pytest.raises(json.JSONDecodeError):
        json.loads(masked, strict=False)


@both_engines
@pytest.mark.parametrize("shape", SHAPES)
def test_masked_report_keeps_all_fields(parse: Any, shape: str) -> None:
    outputs = parse(_masked(SHAPES[shape](REPORT)))
    report = outputs["review_report"]

    assert report["overall_status"] == "NEEDS_FIXES"
    assert report["quality_score"] == 7.0
    assert report["summary"] == REPORT["summary"]
    assert report["findings"][1:] == REPORT["findings"][1:]
    assert report["positive_observations"] == ["Async I/O throughout"]
    assert "Password=" not in json.dumps(outputs)


# ---------------------------------------------------------------------------
# Status gating and remaining shapes
# ---------------------------------------------------------------------------


@both_engines
def test_damaged_approved_report_stays_approved(parse: Any) -> None:
    approved = {**REPORT, "overall_status": "APPROVED"}

    report = parse(_masked(_wrapper(approved)))["review_report"]

    assert report["overall_status"] == "APPROVED"
    assert report["quality_score"] == 7.0


@both_engines
def test_bare_fenced_report_is_the_review_report(parse: Any) -> None:
    """A fenced report without the review_report wrapper keeps its fields."""
    approved = {**REPORT, "overall_status": "APPROVED"}
    text = "```json\n" + json.dumps(approved, indent=2) + "\n```"

    report = parse(text)["review_report"]

    assert report["overall_status"] == "APPROVED"
    assert report["quality_score"] == 7.0
    assert len(report["findings"]) == 3


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


# ---------------------------------------------------------------------------
# Bounded work on adversarial replies
# ---------------------------------------------------------------------------

# Just under the parser's 256 KiB input cap.
_ADVERSARIAL_LEN = 250_000


@pytest.mark.timeout(10)
@both_engines
@pytest.mark.parametrize(
    "unit",
    ["```json {", '"review_report": {"a": "'],
    ids=["unclosed_fences", "repeated_report_keys"],
)
def test_unclosed_openings_parse_in_linear_time(parse: Any, unit: str) -> None:
    """Each opening that never closes must not rescan the rest of the reply.

    A lazy DOTALL fence regex and a repair per ``"review_report":`` key were
    both quadratic here: a reply of this size took minutes.
    """
    text = unit * (_ADVERSARIAL_LEN // len(unit))

    report = parse(text)["review_report"]

    assert report["overall_status"] == "NEEDS_FIXES"


def test_fence_scan_finds_a_block_after_an_odd_fence() -> None:
    """A stray inline fence must not shift which gaps are read as blocks."""
    text = 'Wrap code in ``` fences.\n```json\n{"key": "value"}\n```\n'

    assert parse_llm_json_output(text, None) == {"key": "value"}
