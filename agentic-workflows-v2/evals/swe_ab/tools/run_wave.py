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
        if code == 0 and part.is_file():
            parts.append(part)

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

    for arm, timeout in (("a", CAMPAIGN["timeout_a"]), ("b", CAMPAIGN["timeout_b"])):
        run(
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
