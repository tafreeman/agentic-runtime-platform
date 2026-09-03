#!/usr/bin/env python3
"""Validate current-facing markdown paths and retired runtime references."""

from __future__ import annotations

import re
import sys
from pathlib import Path

PATH_TOKEN = re.compile(
    r"`([A-Za-z0-9_./-]+\.(?:md|py|yaml|yml|json|toml|sh|ps1|ts|tsx))`"
)
KNOWN_FUTURE_PATHS = {
    "engine/strategy.py",
    "engine/iterative.py",
}


def is_local_path(token: str) -> bool:
    if token.startswith(("http://", "https://")):
        return False
    if ":" in token:
        # Windows absolute paths in historical docs.
        return False
    return True


TARGET_FILES = (
    "README.md",
    "CONTRIBUTING.md",
    "CODE_OF_CONDUCT.md",
    "SECURITY.md",
    "SUPPORT.md",
    "examples/README.md",
    "docs/README.md",
    "docs/ARCHITECTURE.md",
    "docs/WORKFLOWS.md",
    "docs/DEVELOPMENT.md",
    "docs/REPO_MAP.md",
    "docs/DOCS_BEST_PRACTICES.md",
    "docs/API_REFERENCE.md",
    "docs/MODEL_LAYER.md",
    "docs/reports/ACTIVE_VS_LEGACY_TOOLING_MAP.md",
)
WORKSPACE_TARGET_FILES = (
    "AI_EVIDENCE_STANDARD.md",
    "CONTRIBUTING.md",
    "docs/KNOWN_LIMITATIONS.md",
    "docs/ROADMAP.md",
)
RETIRED_RAG_SURFACE_PATTERNS = (
    re.compile(r"\bagentic\s+rag\b", re.IGNORECASE),
    re.compile(r"agentic_v2[\\/]rag(?:[\\/]|`|\b)", re.IGNORECASE),
    re.compile(r"docs[\\/]rag(?:[\\/]|\b)", re.IGNORECASE),
    re.compile(r"\bRAG CLI\b", re.IGNORECASE),
    re.compile(r"^\s*\|\s*`rag/?`\s*\|", re.IGNORECASE),
    re.compile(r"\bincluding\s+RAG\b", re.IGNORECASE),
    re.compile(r"\bserver,\s+RAG,\s+integrations\b", re.IGNORECASE),
    re.compile(r"\bcovers\b.*\bRAG\b", re.IGNORECASE),
)


def markdown_files(root: Path) -> list[Path]:
    workspace_root = root.parent
    package_files = [root / rel for rel in TARGET_FILES if (root / rel).exists()]
    workspace_files = [
        workspace_root / rel
        for rel in WORKSPACE_TARGET_FILES
        if (workspace_root / rel).exists()
    ]
    return package_files + workspace_files


def retired_rag_references(text: str) -> list[tuple[int, str]]:
    """Return current-facing lines that advertise the removed ARP RAG surface."""
    matches: list[tuple[int, str]] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if any(pattern.search(line) for pattern in RETIRED_RAG_SURFACE_PATTERNS):
            matches.append((line_number, line.strip()))
    return matches


def candidate_paths(root: Path, md_file: Path, token: str) -> list[Path]:
    workspace_root = root.parent
    # Resolve links as written in each markdown file first. This matches how
    # Markdown renderers resolve relative paths.
    file_relative = (md_file.parent / token).resolve()
    candidates = [
        file_relative,
        root / token,
        root / "agentic_v2" / token,
        root / "tests" / token,
        root / "scripts" / token,
        root / "docs" / token,
        workspace_root / token,
    ]
    return [candidate.resolve() for candidate in candidates]


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    workspace_root = root.parent
    missing: list[tuple[Path, str]] = []
    retired: list[tuple[Path, int, str]] = []

    for md_file in markdown_files(root):
        text = md_file.read_text(encoding="utf-8")
        # The existing path-token heuristics are curated for package docs.
        # Workspace-level prose contains illustrative filenames that are not
        # intended as resolvable links, but it is still scanned for retired
        # runtime surfaces below.
        if md_file.is_relative_to(root):
            for token in PATH_TOKEN.findall(text):
                if not is_local_path(token):
                    continue
                if token in KNOWN_FUTURE_PATHS:
                    continue
                if not any(
                    candidate.exists()
                    for candidate in candidate_paths(root, md_file, token)
                ):
                    missing.append((md_file.relative_to(workspace_root), token))
        for line_number, line in retired_rag_references(text):
            retired.append((md_file.relative_to(workspace_root), line_number, line))

    if not missing and not retired:
        print("OK: no broken local paths or retired ARP RAG references found.")
        return 0

    if missing:
        print("Broken local path references:")
        for md_file, token in missing:
            print(f"  - {md_file}: `{token}`")
    if retired:
        print("Retired ARP RAG references in current-facing documentation:")
        for md_file, line_number, line in retired:
            print(f"  - {md_file}:{line_number}: {line}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
