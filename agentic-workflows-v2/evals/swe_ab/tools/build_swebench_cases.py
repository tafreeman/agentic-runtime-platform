"""Turn SWE-bench Verified instances into cases the existing arms can run.

The two workflows already take (bug_report, code_file, source_code,
failing_test) and return the corrected file, and SWE-bench maps onto that
directly: problem statement, the file the gold patch touches, that file's
contents at base_commit, and the first FAIL_TO_PASS test.

**This is the oracle-retrieval setting, and that is a real limitation.** The
model is told which file to fix. Full SWE-bench also requires *finding* the
file, which is a large part of the benchmark's difficulty. Localisation is
deliberately excluded here because the question under test is whether a review
loop improves repair, not whether it improves search — but a number produced
this way is not comparable to a SWE-bench leaderboard score, and must never be
reported as one.

File contents come out of the prebuilt instance image (`/testbed`), which holds
the repo at exactly base_commit. That is cheaper and more faithful than cloning
each repo and checking out the commit.

    python tools/build_swebench_cases.py --count 5 --repo django/django
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

import pandas as pd

KIT_ROOT = Path(__file__).resolve().parent.parent
CASES_DIR = KIT_ROOT / "dataset" / "swebench_cases"
PARQUET = (
    Path.home()
    / ".cache/huggingface/hub/datasets--princeton-nlp--SWE-bench_Verified"
    / "snapshots/c104f840cc67f8b6eec6f759ebc8b2693d585d4a/data/test-00000-of-00001.parquet"
)

#: Prebuilt evaluation images published alongside the benchmark. The instance id
#: is mangled the same way the official tooling mangles it.
IMAGE_TEMPLATE = "swebench/sweb.eval.x86_64.{slug}:latest"


def image_for(instance_id: str) -> str:
    return IMAGE_TEMPLATE.format(slug=instance_id.replace("__", "_1776_"))


def patched_files(patch: str) -> list[str]:
    """Paths the gold patch touches, source files only."""
    found = re.findall(r"^diff --git a/(\S+) b/\S+", patch, re.MULTILINE)
    return [f for f in found if f.endswith(".py") and "/tests/" not in f]


def docker(args: list[str], timeout: int = 1800) -> tuple[int, str]:
    proc = subprocess.run(
        ["docker", *args], capture_output=True, text=True, timeout=timeout
    )
    return proc.returncode, proc.stdout + proc.stderr


def read_from_image(image: str, path: str) -> str | None:
    """Read one file out of the instance image's checkout at base_commit."""
    code, out = docker(["run", "--rm", image, "cat", f"/testbed/{path}"], timeout=600)
    return out if code == 0 else None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--count", type=int, default=5)
    parser.add_argument("--repo", default="django/django")
    parser.add_argument("--max-patch-lines", type=int, default=25)
    parser.add_argument("--difficulty", default="<15 min fix")
    parser.add_argument("--out", default=str(KIT_ROOT / "dataset" / "cases.swebench.jsonl"))
    parser.add_argument("--offset", type=int, default=0)
    args = parser.parse_args()

    if not PARQUET.is_file():
        print(f"SWE-bench Verified parquet not found at {PARQUET}")
        return 1

    frame = pd.read_parquet(PARQUET)
    frame["files"] = frame["patch"].str.count("diff --git ")
    frame["plines"] = frame["patch"].str.count("\n")
    pool = frame[
        (frame.repo == args.repo)
        & (frame.files == 1)
        & (frame.plines <= args.max_patch_lines)
        & (frame.difficulty == args.difficulty)
    ]
    print(f"pool: {len(pool)} instances matching the filter")

    CASES_DIR.mkdir(parents=True, exist_ok=True)

    # Never rebuild an instance that already has a case directory. Waves are
    # supposed to extend the evidence, not repeat it, and offset arithmetic
    # alone does not guarantee that: wave 1 at offset 0 draws exactly the
    # instances the first hand-built set already used. Skipping what exists
    # makes non-overlap a property of the data on disk rather than of
    # bookkeeping nobody will maintain.
    already = {d.name for d in CASES_DIR.iterdir() if d.is_dir()} if CASES_DIR.is_dir() else set()
    if already:
        print(f"skipping {len(already)} instances already built")

    rows: list[dict] = []
    for instance in pool.iloc[args.offset :].itertuples():
        if instance.instance_id in already:
            continue
        if len(rows) >= args.count:
            break
        targets = patched_files(instance.patch)
        if len(targets) != 1:
            continue
        target = targets[0]
        image = image_for(instance.instance_id)

        print(f"  {instance.instance_id}: pulling image", flush=True)
        code, out = docker(["pull", image], timeout=2400)
        if code != 0:
            print(f"    skip: pull failed ({out.strip().splitlines()[-1][:80]})")
            continue

        source = read_from_image(image, target)
        if source is None:
            print(f"    skip: could not read /testbed/{target}")
            continue

        fail_to_pass = json.loads(instance.FAIL_TO_PASS)
        case_dir = CASES_DIR / instance.instance_id
        case_dir.mkdir(parents=True, exist_ok=True)
        (case_dir / "broken.py").write_text(source, encoding="utf-8")
        (case_dir / "gold.patch").write_text(instance.patch, encoding="utf-8")
        (case_dir / "oracle.json").write_text(
            json.dumps(
                {
                    "case_id": instance.instance_id,
                    "kind": "SWEBENCH",
                    "source_repo": "swebench",
                    "instance_id": instance.instance_id,
                    "repo": instance.repo,
                    "base_commit": instance.base_commit,
                    "target_file": target,
                    "image": image,
                    "fail_to_pass": fail_to_pass,
                    "difficulty": instance.difficulty,
                    "retrieval": "oracle",
                    "max_changed_lines": 120,
                    "contamination_risk": "high",
                },
                indent=2,
            ),
            encoding="utf-8",
        )

        rows.append(
            {
                "sample_id": instance.instance_id,
                "input": {
                    "bug_report": instance.problem_statement[:12000],
                    "code_file": target,
                    "repo_path": case_dir.as_posix(),
                    "failing_test": fail_to_pass[0] if fail_to_pass else "",
                },
                "reference": None,
                "metadata": {
                    "kind": "SWEBENCH",
                    "source_repo": "swebench",
                    "instance_id": instance.instance_id,
                    "contamination_risk": "high",
                    "difficulty": instance.difficulty,
                    "max_changed_lines": 120,
                    "retrieval": "oracle",
                },
            }
        )
        print(f"    + {instance.instance_id}  {target}  ({len(source)} chars)")

    out_path = Path(args.out)
    with out_path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")
    print(f"\nwrote {len(rows)} cases -> {out_path}")
    return 0 if rows else 1


if __name__ == "__main__":
    sys.exit(main())
