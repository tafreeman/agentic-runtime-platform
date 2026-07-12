#!/usr/bin/env python3
"""Validate markdown file path references inside this package."""

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


def markdown_files(root: Path) -> list[Path]:
    return [root / rel for rel in TARGET_FILES if (root / rel).exists()]


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
    missing: list[tuple[Path, str]] = []

    for md_file in markdown_files(root):
        text = md_file.read_text(encoding="utf-8")
        for token in PATH_TOKEN.findall(text):
            if not is_local_path(token):
                continue
            if token in KNOWN_FUTURE_PATHS:
                continue
            if not any(
                candidate.exists()
                for candidate in candidate_paths(root, md_file, token)
            ):
                missing.append((md_file.relative_to(root), token))

    if not missing:
        print("OK: no broken local path references found.")
        return 0

    print("Broken local path references:")
    for md_file, token in missing:
        print(f"  - {md_file}: `{token}`")
    return 1


if __name__ == "__main__":
    sys.exit(main())
