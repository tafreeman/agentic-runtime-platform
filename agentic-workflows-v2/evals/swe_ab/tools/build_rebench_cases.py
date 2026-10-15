"""Turn SWE-rebench instances into cases the existing arms can run.

Why a second builder instead of a flag on `build_swebench_cases.py`: SWE-rebench
differs from SWE-bench Verified in four ways that all touch the loading path, and
folding them into one script would make both harder to read.

  1. `FAIL_TO_PASS` / `PASS_TO_PASS` arrive as real lists, not JSON strings.
  2. Difficulty is `meta.llm_score.difficulty_score` (an int), not a prose band.
  3. Images live under the instance's own `docker_image` field rather than a
     name templated from the instance id.
  4. `created_at` is present, which is the whole reason to use this dataset:
     contamination risk becomes *computable* per instance instead of a constant.

That last point is the motivation. Every case built by `build_swebench_cases.py`
carries `contamination_risk: "high"` as a hardcoded literal, so the field has no
variance and cannot be used as a covariate. Here it is derived from `created_at`
against `--model-cutoff`, and instances created after the cutoff are genuinely
post-training-data for that model.

**This keeps the oracle-retrieval setting, and that is still a real limitation.**
The model is told which file to fix. A number produced this way is not comparable
to any SWE-rebench leaderboard score and must never be reported as one.

    # small curated set, prebuilt images, monthly splits (recommended start)
    python tools/build_rebench_cases.py --count 40 --after 2026-01-01

    # the big corpus, streamed (never materialises the 738 GB split)
    python tools/build_rebench_cases.py --source nebius/SWE-rebench \
        --split filtered --count 40 --after 2026-01-01

Note on stratification: the leaderboard subset ships no `llm_score`, so cases
built from it carry `difficulty: "unknown"` and must be banded on `size_band`
(`band_cases.py --band-by size_band`). Cases built from the full corpus carry a
real `difficulty_score` and can be banded on that instead.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any, Iterator

KIT_ROOT = Path(__file__).resolve().parent.parent
CASES_DIR = KIT_ROOT / "dataset" / "rebench_cases"

#: The curated leaderboard subset: ~860 instances, monthly splits, prebuilt
#: images. The full `nebius/SWE-rebench` test split is 738 GB and must only ever
#: be touched with streaming=True.
DEFAULT_SOURCE = "nebius/SWE-rebench-leaderboard"
STREAM_ONLY_SOURCES = {"nebius/SWE-rebench"}

#: Roots the repo checkout may live under inside the instance image. SWE-bench
#: images use /testbed; SWE-rebench images are built by a different pipeline, so
#: the location is probed rather than assumed.
WORKDIR_CANDIDATES = ("/testbed", "/workspace", "/repo", "/app", "/src")

#: `meta.llm_score.difficulty_score` is a 0-3 integer, but it is populated only
#: in the full `nebius/SWE-rebench` corpus. The curated leaderboard subset ships
#: a reduced `meta` (commit_name, failed_lite_validators, has_test_patch,
#: is_lite, num_modified_files) with no llm_score at all — verified 2026-08-30
#: against the 2026_03 split: 0 of 110 rows carried one.
DIFFICULTY_LABELS = {
    0: "trivial",
    1: "easy",
    2: "moderate",
    3: "hard",
}

#: Fallback stratification when llm_score is absent. Gold-patch line count is a
#: size proxy, NOT a difficulty label — it is named `size_band` precisely so it
#: cannot be mistaken for one in a report. The banding script only needs a
#: stratification variable; it measures the pass rate per stratum itself.
#:
#: Thresholds are the observed quartiles of single-file gold patches of <=60
#: lines in the leaderboard subset since 2025-06 (measured 2026-08-30: min 12,
#: q25 24, median 33, q75 43, max 60). Fixed round numbers put ~85% of instances
#: in one bucket, which makes the stratification useless — recheck these against
#: `--max-patch-lines` if you raise it.
SIZE_BANDS = ((24, "size-S"), (33, "size-M"), (43, "size-L"))
SIZE_BAND_MAX = "size-XL"

#: `meta.num_modified_files` is 0 on every row of the leaderboard subset — an
#: unpopulated field, not a real count. Filtering on it silently rejected every
#: instance. The gold patch is parsed instead, which is authoritative.
UNPOPULATED_MODIFIED_FILES = 0


def docker(args: list[str], timeout: int = 1800) -> tuple[int, str]:
    proc = subprocess.run(
        ["docker", *args], capture_output=True, text=True, timeout=timeout
    )
    return proc.returncode, proc.stdout + proc.stderr


def patched_files(patch: str) -> list[str]:
    """Paths the gold patch touches, source files only."""
    found = re.findall(r"^diff --git a/(\S+) b/\S+", patch, re.MULTILINE)
    return [f for f in found if f.endswith(".py") and "/tests/" not in f]


def locate_source(image: str, path: str) -> tuple[str, str] | None:
    """Read one file out of the image, probing for the checkout root.

    Returns (workdir, contents), or None if the file was not found under any
    candidate root. Never guesses silently — the caller reports what was tried.
    """
    for root in WORKDIR_CANDIDATES:
        code, out = docker(["run", "--rm", image, "cat", f"{root}/{path}"], timeout=600)
        if code == 0 and out.strip():
            return root, out
    return None


def as_list(value: Any) -> list[str]:
    """FAIL_TO_PASS is a list here and a JSON string in SWE-bench Verified."""
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v) for v in value]
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return [value] if value else []
        return [str(v) for v in parsed] if isinstance(parsed, list) else []
    return []


def contamination_risk(created_at: str, cutoff: str) -> str:
    """Risk that the instance predates the model's training cutoff.

    The point of SWE-rebench is that this is knowable. `unknown` is returned
    rather than a guess when the date is missing or unparseable — never `low`,
    which would be the dangerous default.
    """
    if not created_at:
        return "unknown"
    date = created_at[:10]
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
        return "unknown"
    return "low" if date > cutoff else "high"


def difficulty_of(meta: dict[str, Any]) -> tuple[int | None, str]:
    """Dataset-supplied difficulty. Absent on the leaderboard subset."""
    score = ((meta or {}).get("llm_score") or {}).get("difficulty_score")
    if score is None:
        return None, "unknown"
    return int(score), DIFFICULTY_LABELS.get(int(score), f"score-{score}")


def size_band(patch: str) -> str:
    """Size proxy from gold-patch line count, used when difficulty is absent."""
    lines = (patch or "").count("\n")
    for threshold, label in SIZE_BANDS:
        if lines <= threshold:
            return label
    return SIZE_BAND_MAX


def source_file_count(patch: str) -> int:
    """Source files the gold patch touches, parsed from the patch itself.

    Authoritative, unlike `meta.num_modified_files`, which the leaderboard
    subset leaves at 0 on every row.
    """
    return len(patched_files(patch))


def load_rows(source: str, split: str, config: str | None) -> Iterator[dict[str, Any]]:
    """Stream the dataset. Streaming is mandatory for the full corpus."""
    from datasets import load_dataset

    streaming = source in STREAM_ONLY_SOURCES
    if streaming:
        print(f"streaming {source}:{split} (never materialised locally)")
    dataset = load_dataset(source, config, split=split, streaming=streaming)
    for row in dataset:
        yield dict(row)


def passes_filters(row: dict[str, Any], args: argparse.Namespace) -> str | None:
    """Return a rejection reason, or None if the row is acceptable."""
    meta = row.get("meta") or {}
    created = (row.get("created_at") or "")[:10]
    if args.after and created and created < args.after:
        return "created before --after"
    if args.before and created and created > args.before:
        return "created after --before"
    if args.require_test_patch and not meta.get("has_test_patch", True):
        return "no test patch"
    if args.lite_only and not meta.get("is_lite", False):
        return "not in lite subset"
    if not as_list(row.get("FAIL_TO_PASS")):
        return "empty FAIL_TO_PASS"
    patch = row.get("patch") or ""
    touched = source_file_count(patch)
    if touched == 0:
        return "gold patch touches no .py source file"
    if touched > args.max_source_files:
        return f"touches {touched} source files"
    if patch.count("\n") > args.max_patch_lines:
        return "patch too long"
    score, _ = difficulty_of(meta)
    if args.min_difficulty is not None and (
        score is None or score < args.min_difficulty
    ):
        return "below --min-difficulty"
    if args.max_difficulty is not None and (
        score is None or score > args.max_difficulty
    ):
        return "above --max-difficulty"
    return None


def build_case(row: dict[str, Any], args: argparse.Namespace) -> dict[str, Any] | None:
    """Materialise one case directory and return its jsonl row."""
    instance_id = row["instance_id"]
    targets = patched_files(row.get("patch") or "")
    if len(targets) != 1:
        print(f"    skip {instance_id}: gold patch touches {len(targets)} source files")
        return None
    target = targets[0]

    image = row.get("docker_image") or row.get("image_name")
    if not image:
        print(f"    skip {instance_id}: no docker_image in the record")
        return None

    print(f"  {instance_id}: pulling {image}", flush=True)
    code, out = docker(["pull", image], timeout=2400)
    if code != 0:
        tail = out.strip().splitlines()[-1][:80] if out.strip() else "?"
        print(f"    skip: pull failed ({tail})")
        return None

    found = locate_source(image, target)
    if found is None:
        print(
            f"    skip: {target} not found under any of {', '.join(WORKDIR_CANDIDATES)}"
        )
        return None
    workdir, source = found

    fail_to_pass = as_list(row.get("FAIL_TO_PASS"))
    pass_to_pass = as_list(row.get("PASS_TO_PASS"))
    meta = row.get("meta") or {}
    score, label = difficulty_of(meta)
    patch_text = row.get("patch") or ""
    band = size_band(patch_text)
    created = (row.get("created_at") or "")[:10]
    risk = contamination_risk(created, args.model_cutoff)

    case_dir = CASES_DIR / instance_id
    case_dir.mkdir(parents=True, exist_ok=True)
    (case_dir / "broken.py").write_text(source, encoding="utf-8")
    (case_dir / "gold.patch").write_text(row.get("patch") or "", encoding="utf-8")
    (case_dir / "test.patch").write_text(row.get("test_patch") or "", encoding="utf-8")

    oracle = {
        "case_id": instance_id,
        "kind": "SWEREBENCH",
        "source_repo": "swe-rebench",
        "instance_id": instance_id,
        "repo": row.get("repo"),
        "base_commit": row.get("base_commit"),
        "environment_setup_commit": row.get("environment_setup_commit"),
        "target_file": target,
        "image": image,
        "workdir": workdir,
        "fail_to_pass": fail_to_pass,
        "pass_to_pass": pass_to_pass,
        "install_config": row.get("install_config"),
        "created_at": created,
        "difficulty_score": score,
        "difficulty": label,
        "size_band": band,
        "patch_lines": patch_text.count("\n"),
        "retrieval": "oracle",
        "max_changed_lines": args.max_changed_lines,
        "contamination_risk": risk,
        "license_name": row.get("license_name"),
        "interface": row.get("interface"),
        "harbor": {
            "cpus": row.get("harbor_cpus"),
            "memory": row.get("harbor_memory"),
            "storage": row.get("harbor_storage"),
            "verifier_timeout_sec": row.get("harbor_verifier_timeout_sec"),
        },
    }
    (case_dir / "oracle.json").write_text(
        json.dumps(oracle, indent=2), encoding="utf-8"
    )

    print(
        f"    + {instance_id}  {target}  ({len(source)} chars, "
        f"difficulty={label}, {band}, contamination={risk})"
    )
    return {
        "sample_id": instance_id,
        "input": {
            "bug_report": (row.get("problem_statement") or "")[:12000],
            "code_file": target,
            "repo_path": case_dir.as_posix(),
            "failing_test": fail_to_pass[0] if fail_to_pass else "",
        },
        "reference": None,
        "metadata": {
            "kind": "SWEREBENCH",
            "source_repo": "swe-rebench",
            "instance_id": instance_id,
            "repo": row.get("repo"),
            "created_at": created,
            "contamination_risk": risk,
            "difficulty": label,
            "difficulty_score": score,
            "size_band": band,
            "source_files": source_file_count(patch_text),
            "patch_lines": patch_text.count("\n"),
            "fail_to_pass_count": len(fail_to_pass),
            "max_changed_lines": args.max_changed_lines,
            "retrieval": "oracle",
        },
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", default=DEFAULT_SOURCE)
    parser.add_argument("--split", default="test")
    parser.add_argument("--config", default=None, help="dataset config / subset name")
    parser.add_argument("--count", type=int, default=40)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--max-patch-lines", type=int, default=60)
    parser.add_argument("--max-changed-lines", type=int, default=120)
    parser.add_argument(
        "--max-source-files",
        type=int,
        default=1,
        help="max .py source files the gold patch may touch; 1 keeps the "
        "single-file oracle setting the existing arms assume",
    )
    parser.add_argument(
        "--after",
        default=None,
        help="only instances created on/after YYYY-MM-DD (contamination control)",
    )
    parser.add_argument(
        "--before", default=None, help="only instances up to YYYY-MM-DD"
    )
    parser.add_argument(
        "--model-cutoff",
        default="2025-12-31",
        help="training cutoff of the model under test; drives contamination_risk",
    )
    parser.add_argument("--min-difficulty", type=int, default=None)
    parser.add_argument("--max-difficulty", type=int, default=None)
    parser.add_argument("--lite-only", action="store_true")
    parser.add_argument("--require-test-patch", action="store_true", default=True)
    parser.add_argument("--repo", default=None, help="restrict to one owner/name")
    parser.add_argument(
        "--out", default=str(KIT_ROOT / "dataset" / "cases.rebench.jsonl")
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="report what would be built without pulling images",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    CASES_DIR.mkdir(parents=True, exist_ok=True)

    # Never rebuild an instance that already has a case directory: waves extend
    # the evidence, they do not repeat it. Same rule as the SWE-bench builder.
    already = {d.name for d in CASES_DIR.iterdir() if d.is_dir()}
    if already:
        print(f"skipping {len(already)} instances already built")

    rows: list[dict[str, Any]] = []
    rejected: dict[str, int] = {}
    seen = 0
    skipped_offset = 0

    for row in load_rows(args.source, args.split, args.config):
        if len(rows) >= args.count:
            break
        seen += 1
        if args.repo and row.get("repo") != args.repo:
            continue
        if row.get("instance_id") in already:
            continue
        reason = passes_filters(row, args)
        if reason:
            rejected[reason] = rejected.get(reason, 0) + 1
            continue
        if skipped_offset < args.offset:
            skipped_offset += 1
            continue
        if args.dry_run:
            _, label = difficulty_of(row.get("meta") or {})
            created = (row.get("created_at") or "")[:10]
            print(
                f"  would build {row['instance_id']}  difficulty={label} "
                f"{size_band(row.get('patch') or '')} created={created} "
                f"contamination={contamination_risk(created, args.model_cutoff)}"
            )
            rows.append(
                {
                    "sample_id": row["instance_id"],
                    "metadata": {
                        "contamination_risk": contamination_risk(
                            created, args.model_cutoff
                        )
                    },
                }
            )
            continue
        case = build_case(row, args)
        if case:
            rows.append(case)

    print(f"\nscanned {seen} records")
    if rejected:
        print("rejected:")
        for reason, count in sorted(rejected.items(), key=lambda kv: -kv[1]):
            print(f"  {count:5d}  {reason}")

    if args.dry_run:
        print(f"\ndry run: {len(rows)} instances would be built")
        return 0

    out_path = Path(args.out)
    with out_path.open("w", encoding="utf-8") as handle:
        for case in rows:
            handle.write(json.dumps(case) + "\n")
    print(f"\nwrote {len(rows)} cases -> {out_path}")

    risks = [c["metadata"]["contamination_risk"] for c in rows]
    if risks:
        counts = {r: risks.count(r) for r in set(risks)}
        print(f"contamination_risk distribution: {counts}")
        if len(counts) == 1:
            print(
                "  NOTE: no variance in contamination_risk — widen --after/--before "
                "if you intend to use it as a covariate."
            )
    return 0 if rows else 1


if __name__ == "__main__":
    sys.exit(main())
