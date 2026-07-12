#!/usr/bin/env python3
"""Score a workflow run trace by agent type.

Reads a trace JSON file, extracts each step's output, routes each step to the
appropriate rubric based on agent type, scores with ``agentic_v2_eval.Scorer``,
and prints a console summary.  Optionally writes an HTML, Markdown, or JSON
report.

Usage:
    python scripts/score-trace.py trace.json
    python scripts/score-trace.py trace.json --output report.html --format html
    python scripts/score-trace.py trace.json --rubric code --format markdown
    python scripts/score-trace.py trace.json --output result.json --format json
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# agentic_v2_eval optional import
# ---------------------------------------------------------------------------
try:
    from agentic_v2_eval.rubrics import get_rubric_path, load_rubric
    from agentic_v2_eval.scorer import Scorer, ScoringResult

    _EVAL_AVAILABLE = True
except ImportError:
    _EVAL_AVAILABLE = False

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.WARNING,
    format="%(levelname)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
PASS_THRESHOLD_DEFAULT = 0.70
PASS_THRESHOLD_CODE = 0.75

# Maps (lowercase) agent-type strings to rubric names.
AGENT_RUBRIC_MAP: dict[str, str] = {
    "coder": "code",
    "code_generator": "code",
    "codegenerator": "code",
    "architect": "agent",
    "designer": "agent",
    "reviewer": "agent",
    "critic": "agent",
    "orchestrator": "agent",
    "planner": "agent",
    "researcher": "agent",
}

# Rubric criterion weights used for heuristic scoring when rubric has no
# preset values.  Heuristic scores are computed from output text features.
_RUBRIC_CRITERIA_HINTS: dict[str, list[str]] = {
    "code": ["Correctness", "Completeness", "Code Quality", "Efficiency", "Security"],
    "agent": [
        "Correctness",
        "Completeness",
        "Clarity",
        "Relevance",
        "Efficiency",
        "Safety",
    ],
    "default": ["Accuracy", "Completeness", "Efficiency"],
}


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class StepRecord:
    """Normalised representation of a single trace step."""

    step_name: str
    agent_type: str
    output_text: str
    status: str
    duration_seconds: float | None


@dataclass
class StepScore:
    """Scoring outcome for a single step."""

    step_name: str
    agent_type: str
    rubric_name: str
    weighted_score: float
    passed: bool
    criterion_scores: dict[str, float]
    missing_criteria: list[str]


# ---------------------------------------------------------------------------
# Trace parsing
# ---------------------------------------------------------------------------


def _extract_text(value: Any) -> str:
    """Recursively extract a string from a possibly nested structure."""
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        for key in ("text", "content", "output", "response", "result", "message"):
            if key in value:
                return _extract_text(value[key])
        # Fallback: concatenate all string values
        parts = [_extract_text(v) for v in value.values() if v is not None]
        return " ".join(p for p in parts if p)
    if isinstance(value, list):
        parts = [_extract_text(item) for item in value if item is not None]
        return " ".join(p for p in parts if p)
    return str(value) if value is not None else ""


def _parse_duration(raw: dict[str, Any]) -> float | None:
    """Extract a duration in seconds from a raw step dict."""
    raw_dur = raw.get("duration_seconds") or raw.get("duration_ms")
    if not isinstance(raw_dur, (int, float)):
        return None
    if "duration_ms" in raw and "duration_seconds" not in raw:
        return float(raw_dur) / 1000.0
    return float(raw_dur)


def _parse_output_text(raw: dict[str, Any]) -> str:
    """Extract output text from a raw step dict, trying multiple locations."""
    for key in ("output_data", "outputs", "output", "result"):
        if raw.get(key):
            candidate = _extract_text(raw[key])
            if candidate.strip():
                return candidate

    # If still empty, try the step's top-level text fields
    output_text = ""
    for key in ("content", "text", "response", "message"):
        if raw.get(key):
            output_text = _extract_text(raw[key])
            if output_text.strip():
                break

    return output_text


def _parse_step_from_dict(raw: dict[str, Any]) -> StepRecord | None:
    """Convert a raw step dict (many possible schemas) into a StepRecord."""
    # Determine step name
    step_name: str = (
        raw.get("step_name")
        or raw.get("name")
        or raw.get("id")
        or raw.get("step_id")
        or "unknown"
    )

    # Determine agent type
    agent_type: str = (
        raw.get("agent_role")
        or raw.get("agent_type")
        or raw.get("agent")
        or raw.get("role")
        or "unknown"
    )

    # Status
    status: str = str(
        raw.get("status") or raw.get("step_status") or raw.get("state") or "unknown"
    )

    return StepRecord(
        step_name=str(step_name),
        agent_type=str(agent_type),
        output_text=_parse_output_text(raw),
        status=status,
        duration_seconds=_parse_duration(raw),
    )


def _unwrap_envelope(raw: Any) -> Any:
    """Unwrap a server response envelope (``data``/``result``/``payload``)."""
    if isinstance(raw, dict):
        for wrapper in ("data", "result", "payload"):
            if wrapper in raw and isinstance(raw[wrapper], dict):
                return raw[wrapper]
    return raw


def _locate_steps(raw: Any) -> list[dict[str, Any]]:
    """Locate the list of raw step dicts within a parsed trace payload."""
    if isinstance(raw, list):
        return raw  # type: ignore[return-value]
    if isinstance(raw, dict):
        for key in ("steps", "step_results", "results"):
            if key in raw and isinstance(raw[key], list):
                return raw[key]  # type: ignore[return-value]
    return []


def parse_trace(trace_path: Path) -> list[StepRecord]:
    """Load and parse the trace JSON into a list of StepRecords.

    Handles two primary shapes:
    1. WorkflowResult dict (``{"workflow_id": ..., "steps": [...]}``).
    2. Server ``/api/runs/{run_id}`` response (may wrap under ``"data"`` or
       ``"result"`` key, or return steps as the top-level list).

    Args:
        trace_path: Path to the trace JSON file.

    Returns:
        List of parsed step records.

    Raises:
        FileNotFoundError: If the trace file does not exist.
        json.JSONDecodeError: If the file is not valid JSON.
        ValueError: If no steps can be extracted from the file.
    """
    if not trace_path.exists():
        raise FileNotFoundError(f"Trace file not found: {trace_path}")

    with trace_path.open("r", encoding="utf-8") as fh:
        raw: Any = json.load(fh)

    raw = _unwrap_envelope(raw)
    steps_raw = _locate_steps(raw)

    if not steps_raw:
        raise ValueError(
            f"Could not locate a 'steps' list in {trace_path}. "
            "Expected a WorkflowResult dict with a 'steps' key or a top-level list."
        )

    records: list[StepRecord] = []
    for i, raw_step in enumerate(steps_raw):
        if not isinstance(raw_step, dict):
            logger.warning(
                "Step %d is not a dict (got %s); skipping.", i, type(raw_step)
            )
            continue
        record = _parse_step_from_dict(raw_step)
        if record is not None:
            records.append(record)

    return records


# ---------------------------------------------------------------------------
# Rubric routing
# ---------------------------------------------------------------------------


def resolve_rubric_name(agent_type: str, override: str | None) -> str:
    """Map an agent-type string to a rubric name.

    Args:
        agent_type: Raw agent type string from the trace.
        override: User-supplied ``--rubric`` flag value.

    Returns:
        Rubric name (without ``.yaml`` extension).
    """
    if override:
        return override
    normalized = agent_type.lower().strip().replace("-", "_").replace(" ", "_")
    return AGENT_RUBRIC_MAP.get(normalized, "default")


# ---------------------------------------------------------------------------
# Heuristic text scoring
# ---------------------------------------------------------------------------


def _heuristic_completeness(word_count: int) -> float:
    """Reward longer, structured responses up to a sweet-spot."""
    if word_count == 0:
        return 0.0
    if word_count < 20:
        return 0.3
    if word_count < 60:
        return 0.5
    if word_count < 200:
        return 0.75
    return 0.85


def _heuristic_correctness(text: str, word_count: int) -> float:
    """Proxy correctness from presence of code blocks / structured data."""
    has_code_block = "```" in text or "    " in text
    has_numbered = any(
        line.strip()[:2].rstrip(".").isdigit() for line in text.splitlines()
    )
    has_bullets = any(
        line.strip().startswith(("-", "*", "•")) for line in text.splitlines()
    )
    structure_bonus = (0.1 if has_code_block else 0) + (
        0.05 if has_numbered or has_bullets else 0
    )
    return min(1.0, 0.65 + structure_bonus + (0.05 if word_count > 100 else 0))


def _heuristic_clarity(text: str, line_count: int) -> float:
    """Reward structured, readable content (headers, code blocks)."""
    has_code_block = "```" in text or "    " in text
    has_headers = any(line.strip().startswith("#") for line in text.splitlines())
    return min(
        1.0,
        0.60
        + (0.15 if has_code_block else 0)
        + (0.1 if has_headers else 0)
        + (0.05 if line_count > 5 else 0),
    )


def _heuristic_relevance(word_count: int) -> float:
    """Placeholder relevance based on non-emptiness and minimum substance."""
    if word_count > 30:
        return 0.85
    if word_count > 5:
        return 0.6
    return 0.2


def _heuristic_time_score(duration_seconds: float | None) -> float:
    """Map execution duration to a time-efficiency sub-score."""
    if duration_seconds is None:
        return 0.75
    if duration_seconds < 2:
        return 1.0
    if duration_seconds < 10:
        return 0.85
    if duration_seconds < 30:
        return 0.70
    if duration_seconds < 60:
        return 0.55
    return 0.40


def _heuristic_efficiency(word_count: int, duration_seconds: float | None) -> float:
    """Combine time score with a verbosity penalty for very long responses."""
    time_score = _heuristic_time_score(duration_seconds)
    verbosity_penalty = (
        max(0.0, (word_count - 1500) / 10000) if word_count > 1500 else 0.0
    )
    return max(0.0, time_score - verbosity_penalty)


def _score_text_heuristic(
    output_text: str, _rubric_name: str, duration_seconds: float | None
) -> dict[str, float]:
    """Produce a heuristic ``{criterion_name: score}`` dict from text features.

    This is a lightweight, dependency-free analysis designed to give broadly
    reasonable scores without an LLM judge.  Scores are in ``[0.0, 1.0]``.

    Args:
        output_text: The step's output text.
        rubric_name: Which rubric category is being used.
        duration_seconds: Execution duration, used for efficiency scoring.

    Returns:
        Dict mapping criterion name to a float in [0.0, 1.0].
    """
    text = output_text.strip()
    word_count = len(text.split())
    line_count = len(text.splitlines())

    # --- Generic sub-scores ---
    completeness = _heuristic_completeness(word_count)
    correctness = _heuristic_correctness(text, word_count)
    clarity = _heuristic_clarity(text, line_count)
    relevance = _heuristic_relevance(word_count)
    efficiency = _heuristic_efficiency(word_count, duration_seconds)

    # Safety: cannot truly assess without an LLM; assume safe unless obvious red flags
    safety = 0.90

    # Security: code rubric — reward absence of obvious dangerous patterns
    dangerous_patterns = [
        "os.system",
        "eval(",
        "exec(",
        "subprocess.call",
        "shell=True",
    ]
    security_penalty = sum(0.1 for p in dangerous_patterns if p in text)
    security = max(0.0, 0.90 - security_penalty)

    # Accuracy (default rubric name)
    accuracy = correctness

    mapping: dict[str, float] = {
        "Accuracy": accuracy,
        "Correctness": correctness,
        "Completeness": completeness,
        "Clarity": clarity,
        "Code Quality": clarity,  # proxy
        "Relevance": relevance,
        "Efficiency": efficiency,
        "Safety": safety,
        "Security": security,
    }

    return mapping


# ---------------------------------------------------------------------------
# Scoring
# ---------------------------------------------------------------------------


def score_step(
    record: StepRecord,
    rubric_name: str,
    _rubric_override: str | None,
) -> StepScore:
    """Score a single step using the ``Scorer`` class.

    Args:
        record: The parsed step record.
        rubric_name: Resolved rubric name.
        rubric_override: CLI ``--rubric`` flag (used only for pass-threshold).

    Returns:
        StepScore with weighted score and pass/fail result.

    Raises:
        FileNotFoundError: If the rubric YAML cannot be found.
    """
    rubric_path = get_rubric_path(rubric_name)
    rubric_dict = load_rubric(rubric_name)
    scorer = Scorer(rubric_path)

    # Heuristic text scores
    heuristic = _score_text_heuristic(
        record.output_text, rubric_name, record.duration_seconds
    )

    # Build the criterion results that Scorer expects
    results: dict[str, float] = {}
    for criterion in scorer.criteria:
        name = criterion.name
        value = heuristic.get(name)
        if value is not None:
            # Rescale from [0,1] to [min_value, max_value] for the criterion
            range_size = criterion.max_value - criterion.min_value
            results[name] = criterion.min_value + value * range_size
        else:
            logger.debug("No heuristic value for criterion %r; leaving absent.", name)

    scoring_result: ScoringResult = scorer.score(results)

    # Determine pass threshold from rubric thresholds section
    thresholds: dict[str, Any] = rubric_dict.get("thresholds", {})
    pass_threshold: float = float(thresholds.get("pass", PASS_THRESHOLD_DEFAULT))
    passed = scoring_result.weighted_score >= pass_threshold

    return StepScore(
        step_name=record.step_name,
        agent_type=record.agent_type,
        rubric_name=rubric_name,
        weighted_score=scoring_result.weighted_score,
        passed=passed,
        criterion_scores=scoring_result.criterion_scores,
        missing_criteria=scoring_result.missing_criteria,
    )


# ---------------------------------------------------------------------------
# Console output
# ---------------------------------------------------------------------------

_COL_STEP = 22
_COL_AGENT = 14
_COL_RUBRIC = 10
_COL_SCORE = 8
_COL_STATUS = 7


def _trunc(text: str, width: int) -> str:
    """Truncate ``text`` to ``width`` characters, padding with spaces."""
    if len(text) > width:
        return text[: width - 1] + "…"
    return text.ljust(width)


def print_console_summary(
    trace_path: Path,
    step_scores: list[StepScore],
    *,
    skipped_count: int = 0,
) -> None:
    """Print the console scoring summary table.

    Args:
        trace_path: Path to the trace file (used in header).
        step_scores: Scored step results.
        skipped_count: Number of steps skipped due to missing output.
    """
    total = len(step_scores)
    passed = sum(1 for s in step_scores if s.passed)
    avg = sum(s.weighted_score for s in step_scores) / total if total else 0.0

    print()
    print("=== Workflow Trace Scoring ===")
    print(f"Trace:  {trace_path.name}")
    skipped_suffix = (
        f"  (skipped {skipped_count} with no output)" if skipped_count else ""
    )
    print(f"Steps:  {total}{skipped_suffix}")
    print()

    header = (
        _trunc("Step", _COL_STEP)
        + _trunc("Agent", _COL_AGENT)
        + _trunc("Rubric", _COL_RUBRIC)
        + _trunc("Score", _COL_SCORE)
        + "Status"
    )
    separator = "-" * (len(header) + 2)
    print(header)
    print(separator)

    for step in step_scores:
        status_label = "PASS" if step.passed else "FAIL"
        row = (
            _trunc(step.step_name, _COL_STEP)
            + _trunc(step.agent_type, _COL_AGENT)
            + _trunc(step.rubric_name, _COL_RUBRIC)
            + _trunc(f"{step.weighted_score:.2f}", _COL_SCORE)
            + status_label
        )
        print(row)

    print()
    print(f"Summary: {passed}/{total} passed | avg score: {avg:.2f}")
    print()


# ---------------------------------------------------------------------------
# Report generation
# ---------------------------------------------------------------------------


def _build_report_rows(step_scores: list[StepScore]) -> list[dict[str, Any]]:
    """Convert step scores into the ``list[dict]`` format reporters expect."""
    rows: list[dict[str, Any]] = []
    for step in step_scores:
        row: dict[str, Any] = {
            "step_name": step.step_name,
            "agent_type": step.agent_type,
            "rubric": step.rubric_name,
            "weighted_score": step.weighted_score,
            "passed": step.passed,
        }
        # Flatten criterion scores with a prefix so they appear as columns
        for crit_name, crit_val in step.criterion_scores.items():
            row[f"score_{crit_name.lower().replace(' ', '_')}"] = round(crit_val, 4)
        if step.missing_criteria:
            row["missing_criteria"] = ", ".join(step.missing_criteria)
        rows.append(row)
    return rows


def write_report(
    step_scores: list[StepScore],
    output_path: Path,
    fmt: str,
    trace_path: Path,
) -> None:
    """Write a report file using the existing agentic_v2_eval reporters.

    Args:
        step_scores: Scored step results.
        output_path: Destination file path.
        fmt: Report format — ``"html"``, ``"markdown"``, or ``"json"``.
        trace_path: Source trace path (embedded in metadata).

    Raises:
        ImportError: If ``agentic_v2_eval`` reporters cannot be imported.
        ValueError: If ``fmt`` is not a supported format.
    """
    try:
        from agentic_v2_eval.reporters.html import HtmlReporter
        from agentic_v2_eval.reporters.json import JsonReporter
        from agentic_v2_eval.reporters.markdown import MarkdownReporter
    except ImportError as exc:
        raise ImportError(
            "Could not import agentic_v2_eval reporters. "
            "Install with: pip install -e agentic-v2-eval/.[dev]"
        ) from exc

    rows = _build_report_rows(step_scores)
    metadata: dict[str, Any] = {
        "trace_file": str(trace_path),
        "steps_scored": len(step_scores),
        "steps_passed": sum(1 for s in step_scores if s.passed),
    }

    if fmt == "html":
        reporter = HtmlReporter()
        reporter.generate(rows, output_path, metadata=metadata)
    elif fmt == "markdown":
        reporter = MarkdownReporter()  # type: ignore[assignment]
        reporter.generate(rows, output_path, metadata=metadata)  # type: ignore[attr-defined]
    elif fmt == "json":
        reporter = JsonReporter()  # type: ignore[assignment]
        reporter.generate(rows, output_path, metadata=metadata)  # type: ignore[attr-defined]
    else:
        raise ValueError(
            f"Unsupported report format: {fmt!r}. Choose html, markdown, or json."
        )

    print(f"Report written to: {output_path}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_arg_parser() -> argparse.ArgumentParser:
    """Build and return the CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="score-trace",
        description="Score a workflow run trace by agent type using rubric-based evaluation.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "trace",
        type=Path,
        help="Path to the trace JSON file.",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=None,
        help="Output path for the report file (optional).",
    )
    parser.add_argument(
        "--format",
        "-f",
        dest="fmt",
        choices=["html", "markdown", "json"],
        default="html",
        help="Report format when --output is specified (default: html).",
    )
    parser.add_argument(
        "--rubric",
        "-r",
        default=None,
        help="Override rubric for all steps (e.g. code, agent, default). "
        "If omitted, each step is routed automatically by agent type.",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable debug logging.",
    )
    return parser


def _parse_trace_or_exit(trace_path: Path) -> list[StepRecord] | int:
    """Parse a trace, returning records or an exit code on failure."""
    try:
        return parse_trace(trace_path)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except json.JSONDecodeError as exc:
        print(f"ERROR: Invalid JSON in {trace_path}: {exc}", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


def _score_with_fallback(
    record: StepRecord, rubric_override: str | None
) -> StepScore | None:
    """Score a record, falling back to the default rubric if needed."""
    rubric_name = resolve_rubric_name(record.agent_type, rubric_override)
    try:
        return score_step(record, rubric_name, rubric_override)
    except FileNotFoundError as exc:
        print(
            f"WARNING: Rubric not found for step {record.step_name!r}: {exc}",
            file=sys.stderr,
        )

    # Fall back to default rubric
    try:
        result = score_step(record, "default", rubric_override)
        return StepScore(
            step_name=result.step_name,
            agent_type=result.agent_type,
            rubric_name="default (fallback)",
            weighted_score=result.weighted_score,
            passed=result.passed,
            criterion_scores=result.criterion_scores,
            missing_criteria=result.missing_criteria,
        )
    except Exception as inner_exc:
        logger.error(
            "Failed to score step %r with fallback rubric: %s",
            record.step_name,
            inner_exc,
        )
        return None


def _score_records(
    records: list[StepRecord], rubric_override: str | None
) -> tuple[list[StepScore], int]:
    """Score all records, returning ``(step_scores, skipped_count)``."""
    step_scores: list[StepScore] = []
    skipped = 0
    for record in records:
        if not record.output_text.strip():
            logger.warning(
                "Step %r has no output text; skipping scoring.", record.step_name
            )
            skipped += 1
            continue
        result = _score_with_fallback(record, rubric_override)
        if result is not None:
            step_scores.append(result)
    return step_scores, skipped


def main(argv: list[str] | None = None) -> int:
    """Entry point for the score-trace CLI.

    Args:
        argv: Argument list (defaults to ``sys.argv``).

    Returns:
        Exit code: 0 if all steps pass, 1 if any step fails or an error occurs.
    """
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    if not _EVAL_AVAILABLE:
        print(
            "ERROR: agentic_v2_eval is not installed.\n"
            "Install with:\n"
            "    pip install -e agentic-v2-eval/.[dev]\n"
            "(run from the repo root)",
            file=sys.stderr,
        )
        return 1

    trace_path: Path = args.trace

    # Parse trace
    records = _parse_trace_or_exit(trace_path)
    if isinstance(records, int):
        return records

    if not records:
        print(f"ERROR: No steps found in {trace_path}.", file=sys.stderr)
        return 1

    # Score each step
    step_scores, skipped = _score_records(records, args.rubric)

    # Console output (always printed)
    print_console_summary(trace_path, step_scores, skipped_count=skipped)

    # Optional report
    if args.output and step_scores:
        try:
            write_report(step_scores, args.output, args.fmt, trace_path)
        except (ImportError, ValueError) as exc:
            print(f"ERROR writing report: {exc}", file=sys.stderr)
            return 1

    # Exit code
    all_passed = all(s.passed for s in step_scores)
    return 0 if all_passed else 1


if __name__ == "__main__":
    sys.exit(main())
