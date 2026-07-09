#!/usr/bin/env python3
"""Derive the homepage "by the numbers" stats from source, not hand-typed copy.

``docs/index.md`` carried hand-maintained literals (ADR count, production
workflow count, backend test count) that silently drifted from reality — the
ADR count was hard-typed as 38 while the repo had already grown to 43 formal
ADRs. This script recomputes each value from the actual repository state and
rewrites the two spots in ``docs/index.md`` that quote it (the "By the
numbers" stat strip and the "written decision record" blurb), so the copy
can never go stale silently again.

Usage:
    python scripts/generate_doc_stats.py            # regenerate in place
    python scripts/generate_doc_stats.py --check     # CI/pre-push: exit 1 on drift, write nothing
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ADR_DIR = REPO_ROOT / "docs" / "adr"
WORKFLOW_DEFS_DIR = (
    REPO_ROOT / "agentic-workflows-v2" / "agentic_v2" / "workflows" / "definitions"
)
TEST_ROOTS = (
    REPO_ROOT / "agentic-workflows-v2" / "tests",
    REPO_ROOT / "agentic-v2-eval" / "tests",
    REPO_ROOT / "tests",
)
INDEX_MD = REPO_ROOT / "docs" / "index.md"

ADR_FILENAME_RE = re.compile(r"^ADR((?:-\d{3})+)-")


@dataclass(frozen=True)
class DocStats:
    """Counts derived from the repository, quoted on the docs homepage."""

    adr_count: int
    production_workflow_count: int
    backend_test_count: int


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


def _count_test_functions_in_file(path: Path) -> int:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError:
        return 0
    return sum(
        1
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        and node.name.startswith("test_")
    )


def count_backend_tests(test_roots: tuple[Path, ...] = TEST_ROOTS) -> int:
    """Count Python test functions (``def test_*`` / ``async def test_*``).

    A static AST count across the three pytest roots (runtime unit suite,
    eval package, repo-root e2e) — a proxy for "tests in the repo", not a
    claim that every one currently passes (verifying that would mean
    executing the full suite, network- and slow-marked tests included, at
    docs-build time). UI (Vitest) tests are intentionally out of scope: the
    Python suite is the large majority of the count, and AST parsing keeps
    this exact rather than an approximation over JS/TS `it`/`test`/`it.each`
    call forms.
    """
    total = 0
    for root in test_roots:
        if not root.exists():
            continue
        for path in sorted(root.rglob("test_*.py")):
            if "__pycache__" in path.parts:
                continue
            total += _count_test_functions_in_file(path)
    return total


def gather_stats() -> DocStats:
    """Recompute every derived homepage stat from the current repo state."""
    return DocStats(
        adr_count=count_adrs(),
        production_workflow_count=count_production_workflows(),
        backend_test_count=count_backend_tests(),
    )


def _format_int(value: int) -> str:
    return f"{value:,}"


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
    text = _replace_stat_value(
        text, "Backend tests", _format_int(stats.backend_test_count)
    )
    text = _replace_stat_value(text, "ADRs", str(stats.adr_count))
    text = _replace_stat_value(
        text, "Production workflows", str(stats.production_workflow_count)
    )
    text = _replace_prose_adr_count(text, str(stats.adr_count))
    return text


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help=(
            "Exit 1 if docs/index.md stats differ from the freshly derived "
            "values, without writing anything."
        ),
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    if not INDEX_MD.is_file():
        print(f"ERROR: not found: {INDEX_MD}", file=sys.stderr)
        return 2

    stats = gather_stats()
    original = INDEX_MD.read_text(encoding="utf-8")
    try:
        rendered = render_index_md(original, stats)
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    if args.check:
        if rendered != original:
            print("DOC-STATS DRIFT DETECTED in docs/index.md:", file=sys.stderr)
            print(
                f"  ADRs={stats.adr_count} "
                f"production_workflows={stats.production_workflow_count} "
                f"backend_tests={stats.backend_test_count}",
                file=sys.stderr,
            )
            print(
                "\nRun `python scripts/generate_doc_stats.py` to regenerate.",
                file=sys.stderr,
            )
            return 1
        print("OK: docs/index.md stats are current.")
        return 0

    if rendered != original:
        INDEX_MD.write_text(rendered, encoding="utf-8")
        print(f"Updated {INDEX_MD.relative_to(REPO_ROOT)}.")
    else:
        print(f"{INDEX_MD.relative_to(REPO_ROOT)} already current.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
