"""Enforce a ratchet on ruff suppressions and mypy strictness overrides.

`pyproject.toml` documents a dated, targeted backlog of ruff `ignore` rules,
`per-file-ignores` entries, and mypy `[[tool.mypy.overrides]]` relaxations.
Nothing previously stopped that backlog from silently growing — a suppression
could be added in a PR without anyone noticing the tech-debt count going up.

This script counts the current suppressions, compares them against a
committed baseline, and fails when the count exceeds the baseline (a
"ratchet": counts may shrink freely, but may never grow). Shrinking the count
below the baseline exits 0 but prints a reminder to lower the baseline, so the
improvement is locked in rather than allowing silent regrowth back to the old
ceiling.

Usage:
    python scripts/check_suppression_ratchet.py
    python scripts/check_suppression_ratchet.py --update-baseline
"""

from __future__ import annotations

import argparse
import json
import sys
import tomllib
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Defaults (relative to this script's location: agentic-workflows-v2/scripts/)
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PYPROJECT_PATH = REPO_ROOT / "pyproject.toml"
DEFAULT_BASELINE_PATH = REPO_ROOT / ".ruff-suppression-baseline.json"

# Keys tracked in the baseline, in stable report order.
_COUNT_KEYS: tuple[str, ...] = (
    "ruff_lint_ignore",
    "ruff_per_file_ignores_files",
    "ruff_per_file_ignores_rules",
    "mypy_override_blocks",
    "mypy_ignore_errors_modules",
)


def load_pyproject(pyproject_path: Path) -> dict[str, Any]:
    """Parse *pyproject_path* as TOML.

    Args:
        pyproject_path: Absolute path to the ``pyproject.toml`` file.

    Returns:
        The parsed TOML document as nested dicts.
    """
    with pyproject_path.open("rb") as handle:
        return tomllib.load(handle)


def count_suppressions(config: dict[str, Any]) -> dict[str, int]:
    """Count ruff and mypy suppressions declared in a parsed pyproject config.

    Args:
        config: The dict returned by :func:`load_pyproject`.

    Returns:
        A mapping of count name to current count, covering:
        - ``ruff_lint_ignore``: entries in ``[tool.ruff.lint].ignore``.
        - ``ruff_per_file_ignores_files``: files listed under
          ``[tool.ruff.lint.per-file-ignores]``.
        - ``ruff_per_file_ignores_rules``: total rule codes across all
          per-file-ignore entries.
        - ``mypy_override_blocks``: number of ``[[tool.mypy.overrides]]``
          tables.
        - ``mypy_ignore_errors_modules``: total module patterns covered by
          overrides that set ``ignore_errors = true`` (the broadest relaxation
          — a full opt-out of type checking for that module).
    """
    ruff_lint = config.get("tool", {}).get("ruff", {}).get("lint", {})
    ruff_ignore: list[str] = ruff_lint.get("ignore", [])
    per_file_ignores: dict[str, list[str]] = ruff_lint.get("per-file-ignores", {})
    per_file_rule_total = sum(len(rules) for rules in per_file_ignores.values())

    mypy_overrides: list[dict[str, Any]] = config.get("tool", {}).get(
        "mypy", {}
    ).get("overrides", [])
    ignore_errors_modules = sum(
        len(override.get("module", []))
        for override in mypy_overrides
        if override.get("ignore_errors") is True
    )

    return {
        "ruff_lint_ignore": len(ruff_ignore),
        "ruff_per_file_ignores_files": len(per_file_ignores),
        "ruff_per_file_ignores_rules": per_file_rule_total,
        "mypy_override_blocks": len(mypy_overrides),
        "mypy_ignore_errors_modules": ignore_errors_modules,
    }


def load_baseline(baseline_path: Path) -> dict[str, int]:
    """Load the committed baseline counts.

    Args:
        baseline_path: Absolute path to the baseline JSON file.

    Returns:
        Mapping of count name to the baseline (maximum allowed) value.
    """
    with baseline_path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    return {key: int(data[key]) for key in _COUNT_KEYS}


def write_baseline(baseline_path: Path, counts: dict[str, int]) -> None:
    """Write *counts* to *baseline_path* as pretty-printed, sorted-key JSON.

    Args:
        baseline_path: Absolute path to the baseline JSON file to (re)write.
        counts: Mapping of count name to value, as produced by
            :func:`count_suppressions`.
    """
    ordered = {key: counts[key] for key in _COUNT_KEYS}
    baseline_path.write_text(
        json.dumps(ordered, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )


def find_regressions(
    current: dict[str, int], baseline: dict[str, int]
) -> list[tuple[str, int, int]]:
    """Return counters where *current* exceeds *baseline*.

    Args:
        current: Freshly computed counts.
        baseline: Committed ceiling counts.

    Returns:
        A list of ``(key, baseline_value, current_value)`` tuples for every
        key where the current count is strictly greater than baseline.
    """
    return [
        (key, baseline[key], current[key])
        for key in _COUNT_KEYS
        if current[key] > baseline.get(key, 0)
    ]


def find_improvements(
    current: dict[str, int], baseline: dict[str, int]
) -> list[tuple[str, int, int]]:
    """Return counters where *current* is strictly below *baseline*.

    Args:
        current: Freshly computed counts.
        baseline: Committed ceiling counts.

    Returns:
        A list of ``(key, baseline_value, current_value)`` tuples for every
        key where the current count has shrunk below the committed baseline.
    """
    return [
        (key, baseline[key], current[key])
        for key in _COUNT_KEYS
        if current[key] < baseline.get(key, 0)
    ]


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments.

    Returns:
        Parsed namespace with ``pyproject``, ``baseline``, and
        ``update_baseline`` attributes.
    """
    parser = argparse.ArgumentParser(
        description=(
            "Ratchet check: fail if ruff ignore / mypy override counts in "
            "pyproject.toml exceed the committed baseline."
        )
    )
    parser.add_argument(
        "--pyproject",
        type=Path,
        default=DEFAULT_PYPROJECT_PATH,
        help=f"Path to pyproject.toml (default: {DEFAULT_PYPROJECT_PATH})",
    )
    parser.add_argument(
        "--baseline",
        type=Path,
        default=DEFAULT_BASELINE_PATH,
        help=f"Path to the baseline JSON file (default: {DEFAULT_BASELINE_PATH})",
    )
    parser.add_argument(
        "--update-baseline",
        action="store_true",
        help=(
            "Write the current counts to the baseline file instead of "
            "checking them. Use this deliberately after a cleanup that "
            "shrinks a count, to lock in the improvement."
        ),
    )
    return parser.parse_args()


def main() -> int:
    """Run the suppression ratchet check (or update the baseline).

    Returns:
        0 on success (no regression, or baseline updated). 1 if any counter
        exceeds its baseline. 2 on configuration/file errors.
    """
    args = parse_args()

    pyproject_path: Path = args.pyproject.resolve()
    baseline_path: Path = args.baseline.resolve()

    if not pyproject_path.is_file():
        print(f"ERROR: pyproject.toml not found: {pyproject_path}", file=sys.stderr)
        return 2

    config = load_pyproject(pyproject_path)
    current = count_suppressions(config)

    if args.update_baseline:
        write_baseline(baseline_path, current)
        print(f"Baseline written to {baseline_path}:")
        for key in _COUNT_KEYS:
            print(f"  {key}: {current[key]}")
        return 0

    if not baseline_path.is_file():
        print(
            f"ERROR: baseline file not found: {baseline_path}\n"
            "Create it with: python scripts/check_suppression_ratchet.py "
            "--update-baseline",
            file=sys.stderr,
        )
        return 2

    baseline = load_baseline(baseline_path)

    print("Suppression counts (current vs. baseline):")
    for key in _COUNT_KEYS:
        print(f"  {key}: {current[key]} (baseline: {baseline[key]})")

    regressions = find_regressions(current, baseline)
    if regressions:
        print(
            f"\nRATCHET FAILED — {len(regressions)} counter(s) exceed the "
            f"committed baseline in {baseline_path.name}:\n",
            file=sys.stderr,
        )
        for key, base_value, current_value in regressions:
            print(
                f"  - {key}: {current_value} > baseline {base_value} "
                f"(+{current_value - base_value})",
                file=sys.stderr,
            )
        print(
            "\nEither remove the new suppression(s), or — if the growth is "
            "deliberate and justified in the PR description — update the "
            "baseline with:\n"
            "  python scripts/check_suppression_ratchet.py --update-baseline\n"
            "and commit the result alongside a comment in pyproject.toml "
            "explaining the new suppression.",
            file=sys.stderr,
        )
        return 1

    improvements = find_improvements(current, baseline)
    if improvements:
        print(
            "\nCounts have IMPROVED below baseline for: "
            + ", ".join(key for key, _, _ in improvements)
            + ". Consider locking this in with:\n"
            "  python scripts/check_suppression_ratchet.py --update-baseline"
        )

    print("\nOK — no suppression counter exceeds its baseline.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
