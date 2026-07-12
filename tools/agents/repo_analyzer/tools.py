"""Repo-specific LangChain tools for the analysis agent.

These tools wrap filesystem and git operations used exclusively by the
``RepoAnalyzer`` agent.  They complement the shared tools in
``agentic_v2.langchain.tools`` (file_read, file_list, code_analyze,
search_files) without duplicating them.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from langchain_core.tools import tool

# ---------------------------------------------------------------------------
# String constants (extracted to satisfy python:S1192)
# ---------------------------------------------------------------------------
PYPROJECT_TOML: str = "pyproject.toml"
VENV_DIR: str = ".venv"


@tool
def discover_packages(root: str) -> str:
    """Discover Python packages in a monorepo by locating pyproject.toml files.

    Args:
        root: Absolute path to the repository root directory.

    Returns:
        JSON list of dicts with keys: name, path, description, build_backend.
    """
    root_path = Path(root)
    if not root_path.is_dir():
        return json.dumps({"error": f"Not a directory: {root}"})

    packages = []
    for toml in sorted(root_path.rglob(PYPROJECT_TOML)):
        # Skip nested venvs and dist dirs
        parts = set(toml.parts)
        if parts & {VENV_DIR, "venv", "dist", "__pycache__", "node_modules"}:
            continue
        try:
            text = toml.read_text(encoding="utf-8")
        except OSError:
            continue

        name = _extract_toml_value(text, "name")
        description = _extract_toml_value(text, "description")
        build_backend = _extract_toml_value(text, "build-backend")
        packages.append(
            {
                "name": name or toml.parent.name,
                "path": str(toml.parent.relative_to(root_path)),
                "description": description or "",
                "build_backend": build_backend or "",
            }
        )

    return json.dumps(packages, indent=2)


@tool
def count_lines_of_code(package_dir: str, extensions: str = "py,ts,tsx") -> str:
    """Count lines of code in a package directory by file extension.

    Args:
        package_dir: Absolute path to the package directory.
        extensions: Comma-separated file extensions to count (default: py,ts,tsx).

    Returns:
        JSON dict: {ext: {files, lines, blank, code}} plus a total entry.
    """
    p = Path(package_dir)
    if not p.is_dir():
        return json.dumps({"error": f"Not a directory: {package_dir}"})

    exts = [e.strip().lstrip(".") for e in extensions.split(",") if e.strip()]
    stats: dict[str, dict[str, int]] = {}

    for ext in exts:
        file_count = 0
        total_lines = 0
        blank_lines = 0

        for filepath in p.rglob(f"*.{ext}"):
            parts = set(filepath.parts)
            if parts & {VENV_DIR, "venv", "dist", "__pycache__", "node_modules"}:
                continue
            try:
                lines = filepath.read_text(
                    encoding="utf-8", errors="replace"
                ).splitlines()
            except OSError:
                continue
            file_count += 1
            total_lines += len(lines)
            blank_lines += sum(1 for ln in lines if not ln.strip())

        stats[ext] = {
            "files": file_count,
            "lines": total_lines,
            "blank": blank_lines,
            "code": total_lines - blank_lines,
        }

    totals = {
        "files": sum(v["files"] for v in stats.values()),
        "lines": sum(v["lines"] for v in stats.values()),
        "code": sum(v["code"] for v in stats.values()),
    }
    return json.dumps({"by_extension": stats, "total": totals}, indent=2)


@tool
def get_git_stats(root: str, max_commits: int = 20) -> str:
    """Return recent git log and contributor statistics for a repository.

    Args:
        root: Absolute path to the git repository root.
        max_commits: Maximum number of recent commits to return (default 20).

    Returns:
        JSON dict with keys: branch, recent_commits, contributors, last_tag.
    """
    root_path = Path(root)
    if not (root_path / ".git").is_dir():
        return json.dumps({"error": "Not a git repository"})

    def _git(*args: str) -> str:
        try:
            result = subprocess.run(
                ["git", "-C", str(root_path), *args],
                capture_output=True,
                text=True,
                timeout=10,
            )
            return result.stdout.strip()
        except Exception as exc:
            return f"ERROR: {exc}"

    branch = _git("rev-parse", "--abbrev-ref", "HEAD")

    raw_log = _git(
        "log",
        f"--max-count={max_commits}",
        "--pretty=format:%h|%an|%ad|%s",
        "--date=short",
    )
    commits = []
    for line in raw_log.splitlines():
        parts = line.split("|", 3)
        if len(parts) == 4:
            commits.append(
                {
                    "hash": parts[0],
                    "author": parts[1],
                    "date": parts[2],
                    "subject": parts[3],
                }
            )

    raw_contrib = _git("shortlog", "-sn", "--no-merges", "HEAD")
    contributors = []
    for line in raw_contrib.splitlines()[:10]:
        line = line.strip()
        if "\t" in line:
            count, name = line.split("\t", 1)
            contributors.append({"name": name.strip(), "commits": int(count.strip())})

    last_tag = _git("describe", "--tags", "--abbrev=0") or "none"

    return json.dumps(
        {
            "branch": branch,
            "recent_commits": commits,
            "contributors": contributors,
            "last_tag": last_tag,
        },
        indent=2,
    )


@tool
def list_test_files(package_dir: str) -> str:
    """List all test files in a package and report coverage indicators.

    Args:
        package_dir: Absolute or relative path to the package directory.

    Returns:
        JSON dict with keys: test_files (list), test_count, has_conftest,
        has_coverage_config.
    """
    p = Path(package_dir)
    if not p.is_dir():
        return json.dumps({"error": f"Not a directory: {package_dir}"})

    test_files = []
    for filepath in sorted(p.rglob("test_*.py")):
        parts = set(filepath.parts)
        if parts & {VENV_DIR, "venv", "dist", "__pycache__"}:
            continue
        test_files.append(str(filepath.relative_to(p)))

    for filepath in sorted(p.rglob("*_test.py")):
        parts = set(filepath.parts)
        if parts & {VENV_DIR, "venv", "dist", "__pycache__"}:
            continue
        rel = str(filepath.relative_to(p))
        if rel not in test_files:
            test_files.append(rel)

    has_conftest = any(p.rglob("conftest.py"))
    has_coverage = (p / PYPROJECT_TOML).exists() and "coverage" in (
        (p / PYPROJECT_TOML).read_text(encoding="utf-8", errors="replace")
    )

    return json.dumps(
        {
            "test_files": sorted(test_files),
            "test_count": len(test_files),
            "has_conftest": has_conftest,
            "has_coverage_config": has_coverage,
        },
        indent=2,
    )


@tool
def find_key_patterns(package_dir: str) -> str:
    """Scan a package directory for architectural patterns and notable conventions.

    Checks for: async usage, protocol definitions, dataclasses, Pydantic models,
    LangChain/LangGraph imports, FastAPI routes, TypedDicts, and YAML configs.

    Args:
        package_dir: Path to scan.

    Returns:
        JSON dict mapping pattern name to count of files where it appears.
    """
    p = Path(package_dir)
    if not p.is_dir():
        return json.dumps({"error": f"Not a directory: {package_dir}"})

    patterns = {
        "async_def": "async def ",
        "protocol": "class.*Protocol",
        "dataclass": "@dataclass",
        "pydantic_model": "BaseModel",
        "langgraph": "langgraph",
        "langchain": "langchain",
        "fastapi_route": "@app\\.(?:get|post|put|delete|patch)",
        "typed_dict": "TypedDict",
        "yaml_config": "yaml.safe_load",
        "structlog": "structlog",
        "abc_abstract": "@abc.abstractmethod",
    }

    import re

    counts: dict[str, int] = {k: 0 for k in patterns}

    for filepath in p.rglob("*.py"):
        parts_set = set(filepath.parts)
        if parts_set & {VENV_DIR, "venv", "dist", "__pycache__"}:
            continue
        try:
            text = filepath.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for key, pat in patterns.items():
            if re.search(pat, text):
                counts[key] += 1

    return json.dumps(counts, indent=2)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _extract_toml_value(text: str, key: str) -> str | None:
    """Extract a simple string value from TOML text without a full parser."""
    import re

    match = re.search(rf'^{re.escape(key)}\s*=\s*"([^"]*)"', text, re.MULTILINE)
    return match.group(1) if match else None


# Public surface for the agent
REPO_TOOLS = [
    discover_packages,
    count_lines_of_code,
    get_git_stats,
    list_test_files,
    find_key_patterns,
]
