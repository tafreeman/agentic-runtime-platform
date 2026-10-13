"""Shared helpers for the repo inventory extractors (stdlib only)."""

from __future__ import annotations

import json
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# The checkout these scripts live in; output always lands here.
HOME_REPO = Path(__file__).resolve().parents[2]
# The revision being inventoried. Point ARP_INVENTORY_REPO at a clean
# origin/main worktree so feature-branch WIP does not skew the results.
REPO = Path(os.environ.get("ARP_INVENTORY_REPO", HOME_REPO)).resolve()
OUT_DIR = HOME_REPO / "docs" / "inventory" / "data"
SKIP_DIRS = frozenset(
    {
        ".git",
        "node_modules",
        ".venv",
        "__pycache__",
        ".mypy_cache",
        ".ruff_cache",
        ".pytest_cache",
        ".hypothesis",
        "dist",
        "site",
        ".cache",
        "coverage",
        "playwright-report",
        "test-results",
    }
)
STALE_DAYS = 90


def git(*args: str, cwd: Path = REPO) -> str:
    """Run a git command and return stdout ('' on failure)."""
    proc = subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    return proc.stdout.strip() if proc.returncode == 0 else ""


def tracked_files() -> list[str]:
    return [p for p in git("ls-files", "-z").split("\0") if p]


def untracked_files() -> list[str]:
    out = git("ls-files", "--others", "--exclude-standard", "-z")
    return [p for p in out.split("\0") if p]


def last_commit_dates() -> dict[str, str]:
    """Map every tracked path to its last commit ISO date in one git log pass."""
    out = git("log", "--name-only", "--format=@@%cI", "--no-renames")
    dates: dict[str, str] = {}
    current = ""
    for line in out.splitlines():
        if line.startswith("@@"):
            current = line[2:]
        elif line and line not in dates:
            dates[line] = current
    return dates


def age_days(iso: str) -> int | None:
    if not iso:
        return None
    then = datetime.fromisoformat(iso)
    return (datetime.now(timezone.utc) - then).days


def write_json(name: str, data: Any) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / f"{name}.json"
    path.write_text(json.dumps(data, indent=2, default=str), encoding="utf-8")
    return path


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
