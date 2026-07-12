"""Check that every Protocol class in core/protocols.py appears in docs/ARCHITECTURE.md.

Exit 0 if all protocol names are documented, exit 1 with a clear error listing
the missing entries.

Usage:
    python scripts/check-doc-drift.py
    python scripts/check-doc-drift.py --protocols path/to/protocols.py --docs path/to/ARCHITECTURE.md
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Defaults (relative to repo root)
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PROTOCOLS_PATH = (
    REPO_ROOT / "agentic-workflows-v2" / "agentic_v2" / "core" / "protocols.py"
)
DEFAULT_DOCS_PATH = REPO_ROOT / "docs" / "ARCHITECTURE.md"


def extract_protocol_names(protocols_path: Path) -> list[str]:
    """Parse *protocols_path* with the ``ast`` module and return protocol class names.

    A class is included when it meets **either** condition:

    - Its name ends with ``Protocol``.
    - It has a ``@runtime_checkable`` decorator.

    Args:
        protocols_path: Absolute path to the Python source file to parse.

    Returns:
        Sorted list of unique class names that represent runtime-checkable
        Protocol definitions.
    """
    source = protocols_path.read_text(encoding="utf-8")
    try:
        tree = ast.parse(source, filename=str(protocols_path))
    except SyntaxError as exc:
        print(
            f"ERROR: Could not parse {protocols_path}: {exc}",
            file=sys.stderr,
        )
        sys.exit(2)

    names: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue

        has_runtime_checkable = any(
            (isinstance(d, ast.Name) and d.id == "runtime_checkable")
            or (isinstance(d, ast.Attribute) and d.attr == "runtime_checkable")
            for d in node.decorator_list
        )
        name_ends_protocol = node.name.endswith("Protocol")

        if has_runtime_checkable or name_ends_protocol:
            names.add(node.name)

    return sorted(names)


def load_doc_text(docs_path: Path) -> str:
    """Read the architecture documentation file.

    Args:
        docs_path: Absolute path to the Markdown documentation file.

    Returns:
        Full file contents as a string.
    """
    return docs_path.read_text(encoding="utf-8")


def find_missing_protocols(
    protocol_names: list[str],
    doc_text: str,
) -> list[str]:
    """Return the subset of *protocol_names* not found anywhere in *doc_text*.

    Uses a simple substring search — the protocol name just needs to appear
    somewhere in the document (code block, prose, table, etc.).

    Args:
        protocol_names: List of protocol class names to check.
        doc_text: Full text of the documentation file.

    Returns:
        Names that do NOT appear in the document.
    """
    return [name for name in protocol_names if name not in doc_text]


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments.

    Returns:
        Parsed namespace with ``protocols`` and ``docs`` Path attributes.
    """
    parser = argparse.ArgumentParser(
        description=(
            "Assert that every @runtime_checkable Protocol in protocols.py "
            "is mentioned in ARCHITECTURE.md."
        )
    )
    parser.add_argument(
        "--protocols",
        type=Path,
        default=DEFAULT_PROTOCOLS_PATH,
        help=f"Path to protocols.py (default: {DEFAULT_PROTOCOLS_PATH})",
    )
    parser.add_argument(
        "--docs",
        type=Path,
        default=DEFAULT_DOCS_PATH,
        help=f"Path to ARCHITECTURE.md (default: {DEFAULT_DOCS_PATH})",
    )
    return parser.parse_args()


def main() -> int:
    """Run the doc-drift check.

    Returns:
        0 if all protocols are documented, 1 if any are missing, 2 on
        configuration errors.
    """
    args = parse_args()

    protocols_path: Path = args.protocols.resolve()
    docs_path: Path = args.docs.resolve()

    # Validate file existence before doing anything else.
    if not protocols_path.is_file():
        print(
            f"ERROR: protocols file not found: {protocols_path}",
            file=sys.stderr,
        )
        return 2

    if not docs_path.is_file():
        print(
            f"ERROR: documentation file not found: {docs_path}",
            file=sys.stderr,
        )
        return 2

    print(f"Parsing protocols from: {protocols_path}")
    protocol_names = extract_protocol_names(protocols_path)
    print(f"Found {len(protocol_names)} protocol(s): {', '.join(protocol_names)}")

    print(f"Checking documentation at: {docs_path}")
    doc_text = load_doc_text(docs_path)

    missing = find_missing_protocols(protocol_names, doc_text)

    if not missing:
        print(
            f"OK — all {len(protocol_names)} protocol(s) are documented in "
            f"{docs_path.name}."
        )
        return 0

    # Print a clear, actionable error.
    print(
        f"\nDOC-DRIFT DETECTED — {len(missing)} protocol(s) missing from "
        f"{docs_path}:\n",
        file=sys.stderr,
    )
    for name in missing:
        print(f"  - {name}", file=sys.stderr)

    print(
        "\nAdd each missing protocol name to docs/ARCHITECTURE.md "
        "(e.g. in the 'Core protocols' section) then re-run this check.",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
