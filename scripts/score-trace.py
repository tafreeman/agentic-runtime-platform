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

    # Duration
    duration_seconds: float | None = None
    raw_dur = raw.get("duration_seconds") or raw.get("duration_ms")
    if isinstance(raw_dur, (int, float)):
        if "duration_ms" in raw and "duration_seconds" not in raw:
            duration_seconds = float(raw_dur) / 1000.0
        else:
            duration_seconds = float(raw_dur)

    # Output text — try multiple locations
    output_text = ""
    for key in ("output_data", "outputs", "output", "result"):
        if key in raw and raw[key]:
            candidate = _extract_text(raw[key])
            if candidate.strip():
                output_text = candidate
                break

    # If still empty, try the step's top-level text fields
    if not output_text:
        for key in ("content", "text", "response", "message"):
            if key in raw and raw[key]:
                output_text = _extract_text(raw[key])
                if output_text.strip():
                    break

    return StepRecord(
        step_name=str(step_name),
        agent_type=str(agent_type),
        output_text=output_text,
        status=status,
        duration_seconds=duration_seconds,
    )


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

    # Unwrap server envelope if present
    if isinstance(raw, dict):
        for wrapper in ("data", "result", "payload"):
            if wrapper in raw and isinstance(raw[wrapper], dict):
                raw = raw[wrapper]
                break

    # Locate the steps list
    steps_raw: list[dict[str, Any]] = []
    if isinstance(raw, list):
        steps_raw = raw  # type: ignore[assignment]
    elif isinstance(raw, dict):
        for key in ("steps", "step_results", "results"):
            if key in raw and isinstance(raw[key], list):
                steps_raw = raw[key]  # type: ignore[assignment]
                break

    if not steps_raw:
        raise ValueError(
            f"Could not locate a 'steps' list in {trace_path}. "
            "Expected a WorkflowResult dict with a 'steps' key or a top-level list."
        )

    records: list[StepRecord] = []
    for i, raw_step in enumerate(steps_raw):
        if not isinstance(raw_step, dict):
            logger.warning("Step %d is not a dict (got %s); skipping.", i, type(raw_step))
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
    _char_count = len(text)
    line_count = len(text.splitlines())

    # --- Generic sub-scores ---

    # Completeness: reward longer, structured responses up to a sweet-spot
    if word_count == 0:
        completeness = 0.0
    elif word_count < 20:
        completeness = 0.3
    elif word_count < 60:
        completeness = 0.5
    elif word_count < 200:
        completeness = 0.75
    else:
        completeness = 0.85

    # Accuracy / Correctness: presence of code blocks, structured data, or
    # concrete assertions is a proxy for concrete, accurate output.
    has_code_block = "```" in text or "    " in text
    has_numbered = any(line.strip()[:2].rstrip(".").isdigit() for line in text.splitlines())
    has_bullets = any(line.strip().startswith(("-", "*", "•")) for line in text.splitlines())
    structure_bonus = (0.1 if has_code_block else 0) + (0.05 if has_numbered or has_bullets else 0)
    correctness = min(1.0, 0.65 + structure_bonus + (0.05 if word_count > 100 else 0))

    # Clarity / Code Quality: reward structured, readable content
    has_headers = any(line.strip().startswith("#") for line in text.splitlines())
    clarity = min(1.0, 0.60 + (0.15 if has_code_block else 0) + (0.1 if has_headers else 0) + (0.05 if line_count > 5 else 0))

    # Relevance: placeholder — without a reference answer we assume relevance
    # based on non-emptiness and minimum substance.
    if word_count > 30:
        relevance = 0.85
    elif word_count > 5:
        relevance = 0.6
    else:
        relevance = 0.2

    # Efficiency (time + response length)
    if duration_seconds is None:
        time_score = 0.75
    elif duration_seconds < 2:
        time_score = 1.0
    elif duration_seconds < 10:
        time_score = 0.85
    elif duration_seconds < 30:
        time_score = 0.70
    elif duration_seconds < 60:
        time_score = 0.55
    else:
        time_score = 0.40

    # Penalise very verbose responses (over 1500 words) slightly
    verbosity_penalty = max(0.0, (word_count - 1500) / 10000) if word_count > 1500 else 0.0
    efficiency = max(0.0, time_score - verbosity_penalty)

    # Safety: cannot truly assess without an LLM; assume safe unless obvious red flags
    safety = 0.90

    # Security: code rubric — reward absence of obvious dangerous patterns
    dangerous_patterns = ["os.system", "eval(", "exec(", "subprocess.call", "shell=True"]
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
    print(f"Steps:  {total}{f'  (skipped {skipped_count} with no output)' if skipped_count else ''}")
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
        raise ValueError(f"Unsupported report format: {fmt!r}. Choose html, markdown, or json.")

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
    try:
        records = parse_trace(trace_path)
    except FileNotFoundError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except json.JSONDecodeError as exc:
        print(f"ERROR: Invalid JSON in {trace_path}: {exc}", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if not records:
        print(f"ERROR: No steps found in {trace_path}.", file=sys.stderr)
        return 1

    # Score each step
    step_scores: list[StepScore] = []
    skipped: int = 0

    for record in records:
        if not record.output_text.strip():
            logger.warning(
                "Step %r has no output text; skipping scoring.", record.step_name
            )
            skipped += 1
            continue

        rubric_name = resolve_rubric_name(record.agent_type, args.rubric)

        try:
            result = score_step(record, rubric_name, args.rubric)
            step_scores.append(result)
        except FileNotFoundError as exc:
            print(
                f"WARNING: Rubric not found for step {record.step_name!r}: {exc}",
                file=sys.stderr,
            )
            # Fall back to default rubric
            try:
                result = score_step(record, "default", args.rubric)
                result = StepScore(
                    step_name=result.step_name,
                    agent_type=result.agent_type,
                    rubric_name="default (fallback)",
                    weighted_score=result.weighted_score,
                    passed=result.passed,
                    criterion_scores=result.criterion_scores,
                    missing_criteria=result.missing_criteria,
                )
                step_scores.append(result)
            except Exception as inner_exc:
                logger.error(
                    "Failed to score step %r with fallback rubric: %s",
                    record.step_name,
                    inner_exc,
                )

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
