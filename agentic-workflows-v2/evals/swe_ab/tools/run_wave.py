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
#:
#: Widened 2026-08-29 after wave 6 (EVIDENCE.md §2.14/§2.15): scikit-learn's
#: 15-min-1-hour bucket hit real, permanent exhaustion (0 remaining) and
#: sympy/sphinx/matplotlib were down to 3-4 instances each. scikit-learn is
#: dropped outright; sympy/sphinx/matplotlib kept at reduced weight to drain
#: naturally over the next wave or two rather than vanish abruptly. Five repos
#: added (astropy, xarray, pytest, requests, pylint), sized to their measured
#: remaining pool depth (EVIDENCE.md §2.15) -- pylint's pool is thin (4 total)
#: and included as a one-shot bonus, not a repeating bucket. django's combined
#: share drops from 40% to 27.5% of the nominal mix, which also reduces its
#: dominance in a set already flagged `contamination_risk: high`. This is a
#: deliberate, human-approved campaign change, not a wave change -- waves 1-6
#: drew from the old mix, wave 7 on draws from this one; both stay unioned in
#: EVIDENCE.md §1.3 since each paired instance is graded identically
#: regardless of which mix drew it in, but the population composition is
#: flagged at the point it changed.
#:
#: Narrowed again 2026-08-29, wave 9, in the new post-PR#282 segment
#: (EVIDENCE.md §1.7/§2.1x): sympy, sphinx-doc, matplotlib and pylint-dev all
#: hit real, permanent exhaustion at the 40-line patch cap (0 remaining each);
#: raising the cap to 250 lines was measured and rejected -- sphinx-doc and
#: pylint-dev stay at 0 regardless (no single-file patch of any size remains
#: unbuilt), and sympy/matplotlib only recover a handful (+9/+3), not enough
#: to justify changing what the patch-size cap tests. All four dropped
#: outright; their combined weight (7) folds into django, proportional to its
#: existing 6:5 split (django's remaining pool is 120+, deepest of any repo by
#: far). This re-inflates django's share of the nominal mix to 45% -- back
#: above the 40% it was reduced from before wave 7, and knowingly so
#: (human-approved 2026-08-29): the alternative buckets are themselves mostly
#: thin (astropy `<15 min fix` down to 1, xarray/pytest `15 min - 1 hour` down
#: to 4/2 against weights of 5/3) and adding new repos was explicitly declined
#: in favor of the simpler fix. This is within the new segment opened at wave
#: 8 (EVIDENCE.md's segment-boundary note) -- wave 8 alone used the pre-change
#: mix, wave 9 on uses this one; not comparable to anything in the closed
#: wave-1-7 segment either way.
#: Narrowed a third time wave 10: astropy's `15 min - 1 hour` bucket (pool
#: of 12) also hit 0 remaining -- every specialty bucket has now drained to
#: single digits (xarray 3, pytest 5, requests 2 remaining, measured) except
#: django (75 remaining across both buckets). Rather than keep re-narrowing
#: every wave or two as each thin bucket empties in turn, this consolidates
#: hard on django and keeps the rest at token weight=1-2 -- a "drain
#: naturally, drop silently once empty" bonus, not buckets sized to recur.
#: astropy is dropped outright (0 remaining, no bonus possible).
#:
#: 2026-09-02, on landing to main: the fourth field makes that bonus policy
#: real in code. Until now every slice, bonus or not, hit the ``built <
#: count`` abort below when its pool ran dry -- and psf/requests is dry
#: (2 remaining measured at wave 10, one taken by each of waves 10 and 11).
#: A ``core`` slice that comes up short still aborts the wave, because that is
#: the population pin; a ``bonus`` slice that comes up short, or empty, is
#: reported and dropped from the wave as the note above always intended.
CORE = "core"
BONUS = "bonus"
WAVE_MIX = [
    ("django/django", "15 min - 1 hour", 24, CORE),
    ("django/django", "<15 min fix", 12, CORE),
    ("pydata/xarray", "15 min - 1 hour", 1, BONUS),
    ("pytest-dev/pytest", "<15 min fix", 2, BONUS),
    ("psf/requests", "<15 min fix", 1, BONUS),
]


def run(args: list[str], *, timeout: int = 36000) -> int:
    print("+", " ".join(args[:6]), "...", flush=True)
    return subprocess.run(args, timeout=timeout).returncode


def existing_wave_reports(kit_root: Path, wave: int) -> list[Path]:
    """Reports already graded for *wave* -- evidence a rebuild would overwrite."""
    reports = kit_root / "reports"
    if not reports.is_dir():
        return []
    return sorted(p for p in reports.glob(f"arm-*-wave{wave}.json") if p.is_file())


#: Report basenames run_ab.py writes per arm (its ``ARMS`` table), before the
#: ``-wave{N}`` suffix. Mirrored here rather than imported so this runner does
#: not pull in run_ab.py's EvalKit imports just to name a file.
ARM_REPORT_NAMES = {"a": "arm-a-direct", "b": "arm-b-review-loop"}


def arm_report_path(kit_root: Path, wave: int, arm: str) -> Path:
    return kit_root / "reports" / f"{ARM_REPORT_NAMES[arm]}-wave{wave}.json"


def report_is_complete(path: Path, rows: list[str]) -> bool:
    """True when *path* is a parseable report covering every sample in *rows*.

    run_ab.py writes its report once, after every sample finished, so a
    report that parses and holds exactly the manifest's sample ids is that
    arm's graded result. Anything else -- unreadable, or a different sample
    set -- is not something a retry may silently replace.
    """
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    expected = {json.loads(line)["sample_id"] for line in rows}
    graded = {
        ((sample.get("sample") or {}).get("sample_id"))
        for sample in report.get("samples") or []
    }
    return bool(expected) and graded == expected


def plan_arms(
    kit_root: Path, wave: int, rows: list[str]
) -> tuple[list[str], list[Path], list[Path]]:
    """Decide which arms a rerun of *wave* may run without overwriting evidence.

    Returns ``(to_run, preserved, blocking)``: arms with no report yet, the
    complete reports a rerun keeps untouched, and reports that exist but do
    not cover the manifest -- those block the rerun rather than being
    replaced, because run_ab.py would write over them (WAVE-RUNBOOK rule 3).
    """
    to_run: list[str] = []
    preserved: list[Path] = []
    blocking: list[Path] = []
    for arm in ("a", "b"):
        path = arm_report_path(kit_root, wave, arm)
        if not path.is_file():
            to_run.append(arm)
        elif report_is_complete(path, rows):
            preserved.append(path)
        else:
            blocking.append(path)
    return to_run, preserved, blocking


def scale_mix(
    mix: list[tuple[str, str, int, str]], size: int
) -> list[tuple[str, str, int, str]]:
    """Scale *mix* to *size* proportionally, keeping every slice represented.

    A wave that dropped whole repos would sample a different population from
    its siblings and could not be unioned with them, so every slice keeps at
    least one target row.
    """
    nominal = sum(count for _, _, count, _ in mix)
    scale = size / nominal
    return [
        (repo, difficulty, max(1, round(count * scale)), kind)
        for repo, difficulty, count, kind in mix
    ]


def shortfall_is_fatal(kind: str) -> bool:
    """Only a core slice that comes up short changes the pinned population."""
    return kind == CORE


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
            "sampling different instances. Refused once any report exists for "
            "this wave: run_ab.py writes to the same report paths and would "
            "overwrite graded evidence."
        ),
    )
    args = parser.parse_args()

    wave = args.wave
    cases = KIT_ROOT / "dataset" / f"cases.swebench.wave{wave}.jsonl"

    # A graded wave is evidence. Re-mining its cases would replace the tracked
    # manifest and then run_ab.py would write new results over the same
    # reports/*-wave{N}.json paths, silently destroying the provenance of what
    # was landed (WAVE-RUNBOOK rule 3). The next experiment gets the next number.
    graded = existing_wave_reports(KIT_ROOT, wave)
    if args.rebuild_cases and graded:
        print(
            f"wave {wave}: refusing --rebuild-cases: "
            f"{', '.join(p.name for p in graded)} already hold this wave's graded "
            f"evidence and run_ab.py would overwrite them (WAVE-RUNBOOK rule 3). "
            f"Use the next unused wave number instead.",
            file=sys.stderr,
            flush=True,
        )
        return 1
    if graded and not cases.is_file():
        # Mining a fresh sample set here would then write over these reports.
        print(
            f"wave {wave}: refusing to mine cases: {', '.join(p.name for p in graded)} "
            f"exist but {cases.name} is missing. Restore the manifest to retry the "
            f"wave, or use the next unused wave number.",
            file=sys.stderr,
            flush=True,
        )
        return 1

    # Always scan each pool from the start. Non-overlap comes from
    # build_swebench_cases.py skipping instance ids that already have a case
    # directory (EVIDENCE.md §2.10) or that any tracked wave manifest or report
    # has already drawn (tools/drawn_instances.py -- so a fresh checkout without
    # the gitignored case trees cannot re-draw graded instances), not from this
    # offset — a growing offset was found to permanently strand real, unbuilt
    # instances in any pool smaller than the offset (EVIDENCE.md §2.13).
    offset = 0

    mix = scale_mix(WAVE_MIX, args.size)
    print(
        f"wave {wave}: targeting {args.size} -> {sum(c for _, _, c, _ in mix)} cases",
        flush=True,
    )

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
        # A retry runs only what is missing. run_ab.py writes each arm's report
        # to the same deterministic path, so re-running an arm that already
        # has a complete report would overwrite graded evidence.
        to_run, preserved, blocking = plan_arms(KIT_ROOT, wave, existing_rows)
        for path in preserved:
            print(
                f"wave {wave}: keeping {path.name}, already complete for these cases",
                flush=True,
            )
        if blocking:
            print(
                f"wave {wave}: refusing to rerun: {', '.join(p.name for p in blocking)} "
                f"exist but do not cover {cases.name}'s sample set. A rerun would "
                f"overwrite them; move them aside by hand (never delete a report, "
                f"WAVE-RUNBOOK rule 3) or use the next unused wave number.",
                file=sys.stderr,
                flush=True,
            )
            return 1
        if not to_run:
            print(
                f"wave {wave}: both arms are already graded for these cases; nothing "
                f"to run. Use the next unused wave number for a new experiment.",
                file=sys.stderr,
                flush=True,
            )
            return 1
        return run_arms(wave, cases, existing_rows, args, arms=tuple(to_run))

    parts: list[Path] = []
    for index, (repo, difficulty, count, kind) in enumerate(mix):
        part = KIT_ROOT / "dataset" / f"_wave{wave}_{index}.jsonl"
        code = run(
            [
                sys.executable,
                str(KIT_ROOT / "tools" / "build_swebench_cases.py"),
                "--repo",
                repo,
                "--difficulty",
                difficulty,
                "--count",
                str(count),
                "--offset",
                str(offset),
                "--max-patch-lines",
                "40",
                "--out",
                str(part),
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
                1
                for line in part.read_text(encoding="utf-8").splitlines()
                if line.strip()
            )
            parts.append(part)
        else:
            part.unlink(missing_ok=True)
        if built < count and not shortfall_is_fatal(kind):
            # A bonus slice drains naturally and drops silently once empty;
            # its rows were never part of the population pin (WAVE_MIX note).
            print(
                f"wave {wave}: bonus slice {repo} / {difficulty} yielded {built} of "
                f"{count} (builder exit {code}); its pool is draining, dropping the "
                f"shortfall from this wave as WAVE_MIX intends",
                flush=True,
            )
            continue
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


def run_arms(
    wave: int,
    cases: Path,
    rows: list[str],
    args: argparse.Namespace,
    arms: tuple[str, ...] = ("a", "b"),
) -> int:
    """Run *arms* over *rows*, then prune images if asked.

    Split out of main so a rerun can reuse an existing wave case file and
    take exactly this path, rather than re-mining a different sample set.
    A rerun passes only the arms that still lack a complete report.
    """
    timeouts = {"a": CAMPAIGN["timeout_a"], "b": CAMPAIGN["timeout_b"]}
    for arm, timeout in ((arm, timeouts[arm]) for arm in arms):
        code = run(
            [
                "uv",
                "run",
                "python",
                str(KIT_ROOT / "run_ab.py"),
                "--arm",
                arm,
                "--cases",
                str(cases),
                "--grader",
                CAMPAIGN["grader"],
                "--model",
                CAMPAIGN["model"],
                f"--suffix=-wave{wave}",
                "--concurrency",
                str(CAMPAIGN["concurrency"]),
                "--timeout",
                str(timeout),
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
