"""Check protocol documentation and ADR governance metadata for drift.

Exit 0 when protocol names are documented, ADR body/index statuses agree, and
the ADR reservation note does not claim a number already marked Accepted.

Usage:
    python scripts/check-doc-drift.py
    python scripts/check-doc-drift.py --protocols path/to/protocols.py --docs path/to/ARCHITECTURE.md
"""

from __future__ import annotations

import argparse
import ast
import re
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
DEFAULT_ADR_DIR = REPO_ROOT / "docs" / "adr"
DEFAULT_ADR_INDEX = DEFAULT_ADR_DIR / "ADR-INDEX.md"

ADR_INDEX_STATUS_RE = re.compile(
    r"^\|\s+\*\*(?P<number>\d{3})\*\*\s+\|.*?\|\s+"
    r"(?P<status>Accepted|Proposed|Superseded)(?:\s+→\s+\d{3})?\s+\|",
    re.MULTILINE,
)
ADR_BODY_STATUS_RE = re.compile(
    r"^\*\*Status:\*\*\s*(?P<status>Accepted|Proposed|Superseded)\b",
    re.MULTILINE,
)
ADR_FILE_NUMBER_RE = re.compile(r"^ADR-(?P<number>\d{3})-")
# Decisions whose acceptance is a repository invariant, not merely a claim that
# the body and index happen to agree. ADR-042 is shipped through a pinned extra,
# bridge implementation, boundary test, and dedicated CI lane.
REQUIRED_ADR_STATUSES = {"042": "Accepted"}


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


def extract_adr_index_statuses(index_text: str) -> dict[str, str]:
    """Return normalized ADR statuses from the index's quick-access table."""
    return {
        match.group("number"): match.group("status")
        for match in ADR_INDEX_STATUS_RE.finditer(index_text)
    }


def extract_adr_body_statuses(adr_dir: Path) -> dict[str, tuple[str, Path]]:
    """Return explicit ADR body statuses keyed by their three-digit number.

    Early bundled ADRs do not carry ``**Status:**`` metadata and are skipped.
    Every ADR that does declare the field is governed by this check.
    """
    statuses: dict[str, tuple[str, Path]] = {}
    for path in sorted(adr_dir.glob("ADR-*.md")):
        number_match = ADR_FILE_NUMBER_RE.match(path.name)
        if not number_match or path.name == "ADR-INDEX.md":
            continue
        status_match = ADR_BODY_STATUS_RE.search(path.read_text(encoding="utf-8"))
        if status_match:
            statuses[number_match.group("number")] = (
                status_match.group("status"),
                path,
            )
    return statuses


def find_adr_status_mismatches(
    index_statuses: dict[str, str],
    body_statuses: dict[str, tuple[str, Path]],
) -> list[tuple[str, str, str, Path]]:
    """Return body/index status disagreements for ADRs with explicit metadata."""
    mismatches: list[tuple[str, str, str, Path]] = []
    for number, (body_status, path) in sorted(body_statuses.items()):
        index_status = index_statuses.get(number, "MISSING")
        if body_status != index_status:
            mismatches.append((number, body_status, index_status, path))
    return mismatches


def extract_claimed_adr_numbers(index_text: str) -> set[str]:
    """Return numbers called claimed by parked or in-flight work in the note."""
    note_match = re.search(
        r"\*\*Note:\*\*(?P<note>.*?)(?:\n\n---|\Z)",
        index_text,
        re.DOTALL,
    )
    if not note_match:
        return set()
    claim_match = re.search(
        r"(?P<refs>ADR-\d{3}.*?)\s+are claimed by parked or in-flight work",
        note_match.group("note"),
        re.DOTALL,
    )
    if not claim_match:
        return set()
    return set(re.findall(r"ADR-(\d{3})", claim_match.group("refs")))


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
    parser.add_argument(
        "--adr-dir",
        type=Path,
        default=DEFAULT_ADR_DIR,
        help=f"ADR directory (default: {DEFAULT_ADR_DIR})",
    )
    parser.add_argument(
        "--adr-index",
        type=Path,
        default=DEFAULT_ADR_INDEX,
        help=f"ADR index (default: {DEFAULT_ADR_INDEX})",
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
    adr_dir: Path = args.adr_dir.resolve()
    adr_index: Path = args.adr_index.resolve()

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

    if not adr_dir.is_dir():
        print(f"ERROR: ADR directory not found: {adr_dir}", file=sys.stderr)
        return 2

    if not adr_index.is_file():
        print(f"ERROR: ADR index not found: {adr_index}", file=sys.stderr)
        return 2

    print(f"Parsing protocols from: {protocols_path}")
    protocol_names = extract_protocol_names(protocols_path)
    print(f"Found {len(protocol_names)} protocol(s): {', '.join(protocol_names)}")

    print(f"Checking documentation at: {docs_path}")
    doc_text = load_doc_text(docs_path)

    missing = find_missing_protocols(protocol_names, doc_text)

    has_drift = bool(missing)
    if not missing:
        print(
            f"OK — all {len(protocol_names)} protocol(s) are documented in "
            f"{docs_path.name}."
        )
    else:
        print(
            f"\nDOC-DRIFT DETECTED — {len(missing)} protocol(s) missing from "
            f"{docs_path}:\n",
            file=sys.stderr,
        )
        for name in missing:
            print(f"  - {name}", file=sys.stderr)

    index_text = adr_index.read_text(encoding="utf-8")
    index_statuses = extract_adr_index_statuses(index_text)
    body_statuses = extract_adr_body_statuses(adr_dir)
    mismatches = find_adr_status_mismatches(index_statuses, body_statuses)
    required_status_mismatches = sorted(
        (number, expected, index_statuses.get(number, "MISSING"))
        for number, expected in REQUIRED_ADR_STATUSES.items()
        if index_statuses.get(number) != expected
    )
    accepted_claims = sorted(
        number
        for number in extract_claimed_adr_numbers(index_text)
        if index_statuses.get(number) == "Accepted"
    )

    if mismatches:
        has_drift = True
        print("\nADR STATUS DRIFT DETECTED:", file=sys.stderr)
        for number, body_status, index_status, path in mismatches:
            print(
                f"  - ADR-{number}: body={body_status}, index={index_status} "
                f"({path.name})",
                file=sys.stderr,
            )
    else:
        print(f"OK — {len(body_statuses)} explicit ADR statuses match the index.")

    if required_status_mismatches:
        has_drift = True
        print("\nADR DECISION STATUS DRIFT DETECTED:", file=sys.stderr)
        for number, expected, actual in required_status_mismatches:
            print(
                f"  - ADR-{number}: expected={expected}, index={actual}",
                file=sys.stderr,
            )
    else:
        print("OK — required shipped ADR decisions retain their accepted status.")

    if accepted_claims:
        has_drift = True
        print(
            "\nADR RESERVATION DRIFT DETECTED — Accepted numbers are still "
            "claimed by parked or in-flight work:",
            file=sys.stderr,
        )
        for number in accepted_claims:
            print(f"  - ADR-{number}", file=sys.stderr)
    else:
        print("OK — no Accepted ADR number is claimed by parked or in-flight work.")

    if has_drift:
        print(
            "\nUpdate the architecture/protocol documentation, ADR body/index "
            "statuses, or reservation note, then re-run this check.",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
