"""Strip trailing whitespace from all source files.

Usage:
    python scripts/fix-trailing-whitespace.py [--dry-run]

Covers: .py, .ts, .tsx, .js, .jsx, .md, .yaml, .yml
Skips: node_modules, .venv, __pycache__, .git, storybook-static
"""

import argparse
import pathlib
import sys

EXTENSIONS = {".py", ".ts", ".tsx", ".js", ".jsx", ".md", ".yaml", ".yml"}
SKIP_DIRS = {
    "node_modules",
    ".venv",
    "__pycache__",
    ".git",
    "storybook-static",
    ".venv314",
}

ROOT = pathlib.Path(__file__).resolve().parent.parent


def should_skip(path: pathlib.Path) -> bool:
    return any(part in SKIP_DIRS for part in path.parts)


def fix_file(path: pathlib.Path, dry_run: bool) -> bool:
    """Return True if file was (or would be) modified."""
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines(keepends=True)
    fixed = [
        line.rstrip() + "\n" if line.rstrip() != line.rstrip("\n") else line
        for line in lines
    ]
    # Ensure file ends with single newline
    fixed_text = "".join(fixed)
    if fixed_text and not fixed_text.endswith("\n"):
        fixed_text += "\n"

    if fixed_text != text:
        if not dry_run:
            path.write_text(fixed_text, encoding="utf-8")
        return True
    return False


def _collect_modified(dry_run: bool) -> list[pathlib.Path]:
    """Fix (or preview) every candidate file and return the modified paths."""
    modified: list[pathlib.Path] = []
    for ext in sorted(EXTENSIONS):
        for path in ROOT.rglob(f"*{ext}"):
            if should_skip(path):
                continue
            if fix_file(path, dry_run):
                modified.append(path.relative_to(ROOT))
    return modified


def _print_summary(modified: list[pathlib.Path], dry_run: bool) -> None:
    """Print the human-readable summary of modified files."""
    if modified:
        verb = "Would fix" if dry_run else "Fixed"
        print(f"{verb} {len(modified)} file(s):")
        for p in sorted(modified):
            print(f"  {p}")
    else:
        print("No trailing whitespace found.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true", help="Report but don't modify"
    )
    args = parser.parse_args()

    modified = _collect_modified(args.dry_run)
    _print_summary(modified, args.dry_run)

    # Dry-run with findings is a failure (CI signal); all other cases succeed.
    if args.dry_run and modified:
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
