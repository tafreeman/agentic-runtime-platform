#!/usr/bin/env python3
"""Derive the homepage "by the numbers" stats from source, not hand-typed copy.

``docs/index.md`` carried hand-maintained literals (ADR count, production
workflow count) that silently drifted from reality — the
ADR count was hard-typed as 38 while the repo had already grown to 43 formal
ADRs. This script recomputes each value from the actual repository state and
rewrites the two spots in ``docs/index.md`` that quote it (the "By the
numbers" stat strip and the "written decision record" blurb), so the copy
can never go stale silently again. The ``README.md`` coverage badge is
stamped the same way, from the enforced ``fail_under`` gate in
``agentic-workflows-v2/pyproject.toml``.

The backend test count was dropped on purpose: it changed on almost every PR,
so each test-adding PR failed ``--check`` and conflicted with every other open
PR on the same line, which cost far more than the number was worth.

Usage:
    python scripts/generate_doc_stats.py            # regenerate in place
    python scripts/generate_doc_stats.py --check     # CI/pre-push: exit 1 on drift, write nothing
"""

from __future__ import annotations

import argparse
import re
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ADR_DIR = REPO_ROOT / "docs" / "adr"
WORKFLOW_DEFS_DIR = (
    REPO_ROOT / "agentic-workflows-v2" / "agentic_v2" / "workflows" / "definitions"
)
INDEX_MD = REPO_ROOT / "docs" / "index.md"
README_MD = REPO_ROOT / "README.md"
RUNTIME_PYPROJECT = REPO_ROOT / "agentic-workflows-v2" / "pyproject.toml"

ADR_FILENAME_RE = re.compile(r"^ADR((?:-\d{3})+)-")


@dataclass(frozen=True)
class DocStats:
    """Counts derived from the repository, quoted on the docs homepage."""

    adr_count: int
    production_workflow_count: int
    coverage_gate: int


def count_adrs(adr_dir: Path = ADR_DIR) -> int:
    """Count individual ADRs directly under ``docs/adr/`` (non-recursive).

    A single filename can bundle several ADRs (``ADR-001-002-003-*.md`` holds
    three), so this parses the leading run of ``-NNN`` groups rather than
    counting files. Non-recursive glob excludes ``drafts/`` — per
    ``ADR-INDEX.md``, the ADR-023 working notes under ``drafts/`` are
    superseded notes, not formal ADRs. ``ADR-INDEX.md`` itself does not match
    the ``-NNN`` pattern and is excluded automatically.
    """
    total = 0
    for path in sorted(adr_dir.glob("ADR-*.md")):
        match = ADR_FILENAME_RE.match(path.name)
        if not match:
            continue
        total += len(match.group(1).split("-")) - 1
    return total


def count_production_workflows(defs_dir: Path = WORKFLOW_DEFS_DIR) -> int:
    """Count shipped workflow YAML defs, excluding the ``test_*`` fixtures.

    Mirrors the split already documented by hand in ``docs/workflows/index.md``
    ("six production workflows plus two deterministic test fixtures") — the
    two fixtures are literally named ``test_deterministic.yaml`` and
    ``test_workflow.yaml``.
    """
    return sum(
        1 for path in defs_dir.glob("*.yaml") if not path.name.startswith("test_")
    )


def read_coverage_gate(pyproject: Path = RUNTIME_PYPROJECT) -> int:
    """Read the enforced coverage floor from ``[tool.coverage.report] fail_under``.

    This is the same value the dedicated ``coverage report --fail-under`` CI
    step enforces, so the README badge stamped from it states exactly what CI
    gates — no separate number to keep in sync by hand.
    """
    with pyproject.open("rb") as fh:
        data = tomllib.load(fh)
    fail_under = data["tool"]["coverage"]["report"]["fail_under"]
    return int(fail_under)


def gather_stats() -> DocStats:
    """Recompute every derived homepage stat from the current repo state."""
    return DocStats(
        adr_count=count_adrs(),
        production_workflow_count=count_production_workflows(),
        coverage_gate=read_coverage_gate(),
    )


def _replace_stat_value(text: str, label: str, new_value: str) -> str:
    """Replace the numeral in the ``stat-item`` whose sibling label is *label*."""
    pattern = re.compile(
        r'(<div class="stat-value">)[\d,]+(</div>\s*<div class="stat-label">'
        + re.escape(label)
        + r"</div>)"
    )
    match = pattern.search(text)
    if not match:
        raise ValueError(f"stat-value anchor not found for label {label!r}")
    return (
        text[: match.start()]
        + match.group(1)
        + new_value
        + match.group(2)
        + text[match.end() :]
    )


def _replace_prose_adr_count(text: str, new_value: str) -> str:
    """Replace the leading digits in "<N> architecture decision records capture"."""
    pattern = re.compile(r"[\d,]+( architecture decision records capture)")
    match = pattern.search(text)
    if not match:
        raise ValueError("prose ADR-count anchor not found")
    return text[: match.start()] + new_value + match.group(1) + text[match.end() :]


def render_index_md(text: str, stats: DocStats) -> str:
    """Return ``docs/index.md`` with every derived stat substituted in place."""
    text = _replace_stat_value(text, "ADRs", str(stats.adr_count))
    text = _replace_stat_value(
        text, "Production workflows", str(stats.production_workflow_count)
    )
    text = _replace_prose_adr_count(text, str(stats.adr_count))
    return text


def _replace_coverage_badge(text: str, new_value: str) -> str:
    """Replace the percentage in the README's static coverage badge URL."""
    pattern = re.compile(r"(shields\.io/badge/coverage-)\d+(%25%20gated%20subset-)")
    match = pattern.search(text)
    if not match:
        raise ValueError("README coverage-badge anchor not found")
    return (
        text[: match.start()]
        + match.group(1)
        + new_value
        + match.group(2)
        + text[match.end() :]
    )


def render_readme_md(text: str, stats: DocStats) -> str:
    """Return ``README.md`` with the coverage badge stamped from the gate."""
    return _replace_coverage_badge(text, str(stats.coverage_gate))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help=(
            "Exit 1 if docs/index.md or README.md stats differ from the "
            "freshly derived values, without writing anything."
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    targets = ((INDEX_MD, render_index_md), (README_MD, render_readme_md))
    for path, _ in targets:
        if not path.is_file():
            print(f"ERROR: not found: {path}", file=sys.stderr)
            return 2

    stats = gather_stats()
    drifted: list[str] = []
    for path, render in targets:
        rel = str(path.relative_to(REPO_ROOT))
        original = path.read_text(encoding="utf-8")
        try:
            rendered = render(original, stats)
        except ValueError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)
            return 2

        if rendered == original:
            if not args.check:
                print(f"{rel} already current.")
            continue
        if args.check:
            drifted.append(rel)
        else:
            path.write_text(rendered, encoding="utf-8")
            print(f"Updated {rel}.")

    if args.check:
        if drifted:
            print(
                f"DOC-STATS DRIFT DETECTED in {', '.join(drifted)}:",
                file=sys.stderr,
            )
            print(
                f"  ADRs={stats.adr_count} "
                f"production_workflows={stats.production_workflow_count} "
                f"coverage_gate={stats.coverage_gate}",
                file=sys.stderr,
            )
            print(
                "\nRun `python scripts/generate_doc_stats.py` to regenerate.",
                file=sys.stderr,
            )
            return 1
        print("OK: derived doc stats are current.")
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
