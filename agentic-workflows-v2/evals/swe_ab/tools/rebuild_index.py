"""Rebuild ``dataset/cases.jsonl`` from the case directories on disk.

The case directories are the source of truth: each holds the broken file, the
gold file, the oracle metadata, and the captured failure output. The JSONL is
only an index over them, so it can always be regenerated -- which makes it
immune to a miner run for one repo clobbering another repo's rows.

Idempotent. Run it after any mining pass, or any time the index looks wrong.

    python tools/rebuild_index.py
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

KIT_ROOT = Path(__file__).resolve().parent.parent
CASES_DIR = KIT_ROOT / "dataset" / "cases"
INDEX = KIT_ROOT / "dataset" / "cases.jsonl"


def row_for(case_dir: Path) -> dict | None:
    oracle_path = case_dir / "oracle.json"
    if not oracle_path.is_file():
        return None
    oracle = json.loads(oracle_path.read_text(encoding="utf-8"))
    failing = oracle.get("failing_tests") or []
    if not failing:
        return None
    failure = ""
    failure_path = case_dir / "failure.txt"
    if failure_path.is_file():
        failure = failure_path.read_text(encoding="utf-8")

    return {
        "sample_id": oracle["case_id"],
        "input": {
            "bug_report": (
                f"Test `{failing[0]}` fails in {oracle['source_repo']}. "
                f"Repair the source so it passes.\n\n{failure}"
            ),
            "code_file": oracle["target_file"],
            "repo_path": case_dir.as_posix(),
            "failing_test": failing[0],
        },
        "reference": None,
        "metadata": {
            "kind": oracle.get("kind", "MUT"),
            "source_repo": oracle["source_repo"],
            "contamination_risk": oracle.get("contamination_risk", "medium"),
            "max_changed_lines": oracle.get("max_changed_lines", 40),
            "test_file": oracle["test_file"],
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(INDEX))
    parser.add_argument(
        "--only",
        default=None,
        help="restrict to one source repo (evk, ek, arp, memoryctl)",
    )
    args = parser.parse_args()

    rows = []
    skipped = 0
    for case_dir in sorted(CASES_DIR.iterdir()):
        if not case_dir.is_dir():
            continue
        row = row_for(case_dir)
        if row is None:
            skipped += 1
            continue
        if args.only and row["metadata"]["source_repo"] != args.only:
            continue
        rows.append(row)

    out = Path(args.out)
    with out.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")

    counts = Counter(row["metadata"]["source_repo"] for row in rows)
    print(f"rebuilt {len(rows)} cases -> {out}")
    for repo, count in sorted(counts.items()):
        print(f"  {repo:<12} {count}")
    if skipped:
        print(f"  ({skipped} directories skipped: no oracle or no failing test)")
    return 0 if rows else 1


if __name__ == "__main__":
    raise SystemExit(main())
