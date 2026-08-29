"""Run one wave of the SWE-bench A/B, so a large campaign survives across sessions.

Two hundred instances cannot run in one go here: at ~2 GB of image per instance
after layer sharing, the full set needs roughly 400 GB against 363 GB free. A
wave builds its own cases, runs both arms, and can drop its images afterwards,
so disk use stays flat no matter how many waves accumulate.

Unioning waves is only legitimate while every wave shares an arm, a model, and
a configuration -- then it combines disjoint evidence about one system rather
than averaging two. That is not a convention to remember: the settings below
are pinned here, deliberately not exposed as flags, because the two worst
errors in this campaign so far were both a mid-experiment change (an oracle
patched while a run was in flight, and arms run at different concurrency).
A wave that needs different settings is a different experiment and belongs in
a different campaign directory.

    python tools/run_wave.py --wave 1 --size 35
    python tools/run_wave.py --wave 2 --size 35 --prune-images
    # then, over every wave produced:
    uv run python analyze.py \
      --left  reports/arm-a-direct-wave1.json --left  reports/arm-a-direct-wave2.json \
      --right reports/arm-b-review-loop-wave1.json --right reports/arm-b-review-loop-wave2.json
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

KIT_ROOT = Path(__file__).resolve().parent.parent

#: Pinned campaign settings. Changing any of these starts a NEW campaign; it
#: does not extend an existing one, and its waves must not be unioned with
#: earlier ones.
CAMPAIGN = {
    "model": "ollama:deepseek-v4-flash:0731-cloud",
    "concurrency": 4,
    "timeout_a": 900,
    "timeout_b": 1200,
    "grader": "swebench",
}

#: Repos drawn from, and the difficulty mix, per wave. Kept proportional so
#: every wave is a sample of the same population rather than a different one.
WAVE_MIX = [
    ("django/django", "15 min - 1 hour", 8),
    ("sympy/sympy", "15 min - 1 hour", 6),
    ("sphinx-doc/sphinx", "<15 min fix", 5),
    ("scikit-learn/scikit-learn", "15 min - 1 hour", 5),
    ("django/django", "<15 min fix", 6),
    ("matplotlib/matplotlib", "15 min - 1 hour", 5),
]


def run(args: list[str], *, timeout: int = 36000) -> int:
    print("+", " ".join(args[:6]), "...", flush=True)
    return subprocess.run(args, timeout=timeout).returncode


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--wave", type=int, required=True)
    parser.add_argument(
        "--size",
        type=int,
        default=35,
        help="target instances for this wave. The mix is scaled proportionally "
        "rather than truncated, so a small wave samples the same population "
        "as a large one and the two can still be unioned.",
    )
    parser.add_argument(
        "--prune-images",
        action="store_true",
        help="drop this wave's instance images afterwards. They re-pull, and "
        "without this a long campaign fills the disk.",
    )
    parser.add_argument("--build-only", action="store_true")
    parser.add_argument(
        "--rebuild-cases",
        action="store_true",
        help=(
            "mine a new sample set even though this wave's case file exists. "
            "Without it a rerun reuses the existing cases, so a retry after a "
            "failed arm repeats the same experiment instead of silently "
            "sampling different instances."
        ),
    )
    args = parser.parse_args()

    wave = args.wave
    cases = KIT_ROOT / "dataset" / f"cases.swebench.wave{wave}.jsonl"
    # Each wave takes the next slice of every pool, so waves never overlap.
    offset = (wave - 1) * 8

    # Scale the mix to the requested size, keeping every repo represented:
    # a wave that dropped whole repos would sample a different population
    # from its siblings and could not be unioned with them.
    nominal = sum(count for _, _, count in WAVE_MIX)
    scale = args.size / nominal
    mix = [
        (repo, difficulty, max(1, round(count * scale)))
        for repo, difficulty, count in WAVE_MIX
    ]
    print(f"wave {wave}: targeting {args.size} -> {sum(c for _, _, c in mix)} cases", flush=True)

    # A rerun after a failed arm has to rerun *this* wave, not mine a new one.
    # build_swebench_cases.py skips instances whose case directory already
    # exists, so rebuilding here selects later instances instead: the wave
    # JSONL would be silently replaced with a different sample set, the images
    # the failure path preserved would go unused, and the retry would not
    # reproduce the experiment it was meant to repeat.
    if cases.is_file() and not args.rebuild_cases:
        existing_rows = [
            line
            for line in cases.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        print(
            f"wave {wave}: reusing the existing {len(existing_rows)} cases in "
            f"{cases.name} (pass --rebuild-cases to mine a new sample set)",
            flush=True,
        )
        if args.build_only:
            return 0 if existing_rows else 1
        return run_arms(wave, cases, existing_rows, args)

    parts: list[Path] = []
    for index, (repo, difficulty, count) in enumerate(mix):
        part = KIT_ROOT / "dataset" / f"_wave{wave}_{index}.jsonl"
        code = run(
            [
                sys.executable, str(KIT_ROOT / "tools" / "build_swebench_cases.py"),
                "--repo", repo, "--difficulty", difficulty,
                "--count", str(count), "--offset", str(offset),
                "--max-patch-lines", "40", "--out", str(part),
            ],
            timeout=7200,
        )
        # build_swebench_cases.py exits 0 as long as it produced *any* row, so
        # a drained pool or unreadable images yield a short slice rather than a
        # failure. Accepting that silently changes the wave's repo/difficulty
        # mix, which is the one thing the campaign pins -- every wave has to
        # sample the same population or the waves cannot be unioned.
        built = 0
        if code == 0 and part.is_file():
            built = sum(
                1 for line in part.read_text(encoding="utf-8").splitlines() if line.strip()
            )
            parts.append(part)
        if built < count:
            for stale in parts:
                stale.unlink(missing_ok=True)
            print(
                f"wave {wave}: slice {repo} / {difficulty} yielded {built} of the "
                f"{count} cases the mix calls for (builder exit {code}). Refusing to "
                f"run the arms on a different population than waves 1..{wave - 1} "
                f"drew from. Widen WAVE_MIX deliberately, or lower --size.",
                file=sys.stderr,
                flush=True,
            )
            return 1

    seen: set[str] = set()
    rows: list[str] = []
    for part in parts:
        for line in part.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            sample_id = json.loads(line)["sample_id"]
            if sample_id in seen:
                continue
            seen.add(sample_id)
            rows.append(line)
        part.unlink(missing_ok=True)
    cases.write_text("\n".join(rows) + "\n", encoding="utf-8")
    print(f"wave {wave}: {len(rows)} cases -> {cases}", flush=True)
    if args.build_only or not rows:
        return 0 if rows else 1

    return run_arms(wave, cases, rows, args)


def run_arms(wave: int, cases: Path, rows: list[str], args: argparse.Namespace) -> int:
    """Run both arms over *rows*, then prune images if asked.

    Split out of main so a rerun can reuse an existing wave case file and
    take exactly this path, rather than re-mining a different sample set.
    """
    for arm, timeout in (("a", CAMPAIGN["timeout_a"]), ("b", CAMPAIGN["timeout_b"])):
        code = run(
            [
                "uv", "run", "python", str(KIT_ROOT / "run_ab.py"),
                "--arm", arm, "--cases", str(cases),
                "--grader", CAMPAIGN["grader"],
                "--model", CAMPAIGN["model"],
                f"--suffix=-wave{wave}",
                "--concurrency", str(CAMPAIGN["concurrency"]),
                "--timeout", str(timeout),
            ]
        )
        # A wave is a paired experiment: half of it is not a partial result,
        # it is no result. Stop before the other arm runs, and before
        # --prune-images deletes the images a retry would need, rather than
        # exiting 0 over a missing or stale report.
        if code != 0:
            print(
                f"wave {wave}: arm {arm} exited {code}; stopping before the "
                f"remaining arm and before any image pruning",
                file=sys.stderr,
                flush=True,
            )
            return code

    if args.prune_images:
        ids = [json.loads(line)["sample_id"] for line in rows]
        for sample_id in ids:
            slug = sample_id.replace("__", "_1776_")
            subprocess.run(
                ["docker", "rmi", "-f", f"swebench/sweb.eval.x86_64.{slug}:latest"],
                capture_output=True,
            )
        print(f"pruned {len(ids)} instance images", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
