"""Select the case band that maximises McNemar power, from measured pass rates.

The A/B campaign's power does not come from n. It comes from the number of
**discordant pairs** — cases where one arm succeeds and the other fails. A case
both arms pass, or both arms fail, contributes exactly nothing to the test.

Discordance is bounded by `2p(1-p)`, which peaks at a pass rate of 0.50 and
collapses at both ends. That single fact explains two things the campaign has
already hit:

  * the mutation set ceilinged at ~95% and "could not separate two competent
    orchestrations" (EVIDENCE.md §1.2) — at p=0.95 the ceiling is 9.5%;
  * moving to a much *harder* set would fail the same way from below. At p=0.05
    the ceiling is also 9.5%.

So "pick a harder benchmark" is not the move. "Pick the band where the arm under
test sits near 50%" is. This script measures that band instead of guessing it.

Two modes, used in order:

    # 1. no measurements yet — emit a stratified calibration probe
    python tools/band_cases.py --cases dataset/cases.rebench.jsonl \
        --emit-probe 60 --out dataset/cases.rebench.probe.jsonl

    # ... run that probe through Arm A only, then:

    # 2. select the wave from the measured pass rates
    python tools/band_cases.py --cases dataset/cases.rebench.jsonl \
        --probe-report reports/arm-a-rebench-probe.json \
        --target-n 350 --out dataset/cases.rebench.wave1.jsonl

`--kappa` is the fraction of the theoretical discordance ceiling the two arms
actually use. It defaults to 0.49, calibrated from this campaign's own n=47 union
(11 discordant pairs at an arm pass rate of ~0.60, against a 48.0% ceiling). It is
a property of how *similar* the arms are, and it is the one input here that is
borrowed rather than measured per-band — re-derive it once a paired run exists.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

KIT_ROOT = Path(__file__).resolve().parent.parent

#: Discordance efficiency observed in EVIDENCE.md §1.3: 11/47 discordant at an
#: arm pass rate of ~0.60, against a 2p(1-p) ceiling of 0.480.
DEFAULT_KAPPA = 0.49

#: Below this many probe samples a band's pass rate is noise. Selecting on it
#: would repeat the mistake this whole exercise exists to avoid.
DEFAULT_MIN_PROBE_N = 15

Z95 = 1.96
Z80 = 0.84


def wilson(k: int, n: int, z: float = Z95) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def discordant_pairs_needed(split: float) -> float:
    """Discordant pairs for 80% power at alpha=0.05, given the true split.

    `split` is the fraction of discordant pairs favouring the better arm; 0.5 is
    the null. A 65/35 split is a moderate effect, 75/25 a large one.
    """
    if abs(split - 0.5) < 1e-9:
        return float("inf")
    numerator = Z95 * 0.5 + Z80 * math.sqrt(split * (1 - split))
    return (numerator / (split - 0.5)) ** 2


def expected_discordance(p: float, kappa: float) -> float:
    return kappa * 2 * p * (1 - p)


def load_cases(path: Path) -> list[dict[str, Any]]:
    rows = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def band_of(meta: dict[str, Any], band_by: str) -> Any:
    """Band key for a case. Numeric scores band directly; labels pass through."""
    value = (meta or {}).get(band_by)
    return "unknown" if value is None else value


def case_band(case: dict[str, Any], band_by: str) -> Any:
    return band_of(case.get("metadata"), band_by)


def group_by_band(
    cases: list[dict[str, Any]], band_by: str
) -> dict[Any, list[dict[str, Any]]]:
    grouped: dict[Any, list[dict[str, Any]]] = defaultdict(list)
    for case in cases:
        grouped[case_band(case, band_by)].append(case)
    return grouped


def load_probe(path: Path, band_by: str) -> dict[Any, tuple[int, int]]:
    """Read an eval report -> {band: (passes, total)}.

    Accepts the report shape this kit already writes: a top-level `samples` list
    whose entries carry `grade.status` and `sample.metadata`.
    """
    report = json.loads(path.read_text(encoding="utf-8"))
    samples = report.get("samples")
    if not isinstance(samples, list):
        raise SystemExit(f"{path}: no `samples` list — is this an eval report?")

    tally: dict[Any, list[int]] = defaultdict(lambda: [0, 0])
    skipped = 0
    for sample in samples:
        status = str((sample.get("grade") or {}).get("status") or "").lower()
        if status not in {"pass", "fail"}:
            skipped += 1  # errors/timeouts are operational, not task outcomes
            continue
        meta = (sample.get("sample") or {}).get("metadata") or {}
        key = band_of(meta, band_by)
        tally[key][1] += 1
        if status == "pass":
            tally[key][0] += 1
    if skipped:
        print(
            f"note: excluded {skipped} non-pass/fail samples (errors, timeouts) "
            "from the pass-rate estimate — they are operational, not task, outcomes"
        )
    return {k: (v[0], v[1]) for k, v in tally.items()}


def summarise(
    tally: dict[Any, tuple[int, int]], kappa: float, min_n: int
) -> list[dict[str, Any]]:
    """Per-band pass rate, expected discordance, and power cost."""
    out = []
    for key, (passes, total) in tally.items():
        p = passes / total if total else 0.0
        lo, hi = wilson(passes, total)
        disc = expected_discordance(p, kappa)
        # Worst case across the CI: the pass rate furthest from 0.5 gives the
        # least discordance, so plan against that rather than the point estimate.
        worst_p = min((lo, hi), key=lambda x: expected_discordance(x, kappa))
        out.append(
            {
                "band": key,
                "n": total,
                "passes": passes,
                "pass_rate": p,
                "ci": (lo, hi),
                "discordance": disc,
                "discordance_worst": expected_discordance(worst_p, kappa),
                "reliable": total >= min_n,
            }
        )
    out.sort(key=lambda r: -r["discordance"])
    return out


def cases_needed(disc: float, split: float) -> float:
    if disc <= 0:
        return float("inf")
    return discordant_pairs_needed(split) / disc


def print_table(rows: list[dict[str, Any]], kappa: float) -> None:
    print(f"\nBand analysis (kappa={kappa:.2f})")
    print(
        f"{'band':>10} {'n':>4} {'pass':>7} {'95% CI':>16} "
        f"{'E[disc]':>8} {'n for 65/35':>12} {'n for 75/25':>12}  flag"
    )
    for r in rows:
        lo, hi = r["ci"]
        n65 = cases_needed(r["discordance"], 0.65)
        n75 = cases_needed(r["discordance"], 0.75)
        flag = "" if r["reliable"] else "UNRELIABLE (probe n too small)"
        print(
            f"{r['band']!s:>10} {r['n']:>4} {100 * r['pass_rate']:>6.1f}% "
            f"[{100 * lo:>5.1f},{100 * hi:>5.1f}] {100 * r['discordance']:>7.1f}% "
            f"{n65:>12.0f} {n75:>12.0f}  {flag}"
        )


def select(
    cases: list[dict[str, Any]],
    rows: list[dict[str, Any]],
    band_by: str,
    target_n: int,
    exclude: set[str],
) -> tuple[list[dict[str, Any]], list[Any]]:
    """Greedily fill target_n from the highest-discordance reliable bands."""
    available = [c for c in cases if c.get("sample_id") not in exclude]
    by_band = group_by_band(available, band_by)

    chosen: list[dict[str, Any]] = []
    used: list[Any] = []
    for r in rows:
        if len(chosen) >= target_n:
            break
        if not r["reliable"]:
            continue
        pool = by_band.get(r["band"], [])
        if not pool:
            continue
        take = pool[: target_n - len(chosen)]
        chosen.extend(take)
        used.append((r["band"], len(take), r["pass_rate"], r["discordance"]))
    return chosen, used


def emit_probe(cases: list[dict[str, Any]], band_by: str, count: int, out: Path) -> int:
    """Stratified sample across bands, for the calibration run."""
    by_band = group_by_band(cases, band_by)
    bands = sorted(by_band, key=lambda b: str(b))
    per = max(1, count // max(1, len(bands)))

    picked: list[dict[str, Any]] = []
    for band in bands:
        picked.extend(by_band[band][:per])
    for band in bands:  # top up round-robin if integer division left room
        for case in by_band[band][per:]:
            if len(picked) >= count:
                break
            picked.append(case)

    picked = picked[:count]
    write_jsonl(out, picked)
    print(f"\nstratified probe: {len(picked)} cases across {len(bands)} bands")
    per_band = Counter(case_band(c, band_by) for c in picked)
    for band in bands:
        print(f"  {band!s:>10}: {per_band[band]}")
    print(f"wrote -> {out}")
    print(
        "\nRun this through ONE arm, then re-run with --probe-report to select "
        "the wave. A probe of 60 buys the band estimate; it is not itself a result."
    )
    return 0


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row) + "\n")


def measured_sample_ids(report_path: Path) -> set[str]:
    """Sample ids already measured in a probe report."""
    report = json.loads(report_path.read_text(encoding="utf-8"))
    ids = (
        (sample.get("execution") or {}).get("sample_id")
        for sample in report.get("samples", [])
    )
    return {sid for sid in ids if sid}


def print_power_verdict(n_chosen: int, used: list[Any]) -> None:
    """Report expected discordant pairs and whether each effect size is powered."""
    blended = sum(take * disc for _, take, _, disc in used) / max(1, n_chosen)
    exp_pairs = blended * n_chosen
    print(f"\nExpected discordant pairs at n={n_chosen}: {exp_pairs:.0f}")
    for split, label in ((0.65, "moderate 65/35"), (0.75, "large 75/25")):
        need = discordant_pairs_needed(split)
        if exp_pairs >= need:
            outcome = "POWERED"
        else:
            outcome = f"UNDERPOWERED (need ~{cases_needed(blended, split):.0f} cases)"
        print(f"  {label}: needs {need:.0f} discordant pairs -> {outcome}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", required=True, help="candidate cases jsonl")
    parser.add_argument("--probe-report", default=None, help="single-arm eval report")
    parser.add_argument("--emit-probe", type=int, default=0)
    parser.add_argument("--target-n", type=int, default=350)
    parser.add_argument("--band-by", default="difficulty_score")
    parser.add_argument("--kappa", type=float, default=DEFAULT_KAPPA)
    parser.add_argument("--min-probe-n", type=int, default=DEFAULT_MIN_PROBE_N)
    parser.add_argument(
        "--reuse-probe-cases",
        action="store_true",
        help="allow probe instances into the wave (they are already measured, "
        "so including them biases the wave toward the calibration sample)",
    )
    parser.add_argument("--out", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    cases = load_cases(Path(args.cases))
    print(f"loaded {len(cases)} candidate cases from {args.cases}")

    if args.emit_probe:
        return emit_probe(cases, args.band_by, args.emit_probe, Path(args.out))

    if not args.probe_report:
        raise SystemExit("need either --emit-probe N or --probe-report PATH")

    tally = load_probe(Path(args.probe_report), args.band_by)
    if not tally:
        raise SystemExit("probe report yielded no pass/fail samples")

    rows = summarise(tally, args.kappa, args.min_probe_n)
    print_table(rows, args.kappa)

    unreliable = [r for r in rows if not r["reliable"]]
    if unreliable:
        print(
            f"\n{len(unreliable)} band(s) below --min-probe-n={args.min_probe_n} "
            "are excluded from selection. Widen the probe rather than trusting them."
        )

    exclude: set[str] = set()
    if not args.reuse_probe_cases:
        exclude = measured_sample_ids(Path(args.probe_report))
        print(f"excluding {len(exclude)} already-measured probe instances")

    chosen, used = select(cases, rows, args.band_by, args.target_n, exclude)
    if not chosen:
        raise SystemExit(
            "no cases selected — every reliable band is exhausted. Build more "
            "cases with build_rebench_cases.py, or lower --min-probe-n."
        )

    write_jsonl(Path(args.out), chosen)
    print(f"\nselected {len(chosen)} cases -> {args.out}")
    for band, take, p, disc in used:
        print(
            f"  band {band}: {take} cases  (measured pass {100 * p:.1f}%, "
            f"E[discordance] {100 * disc:.1f}%)"
        )

    print_power_verdict(len(chosen), used)
    if len(chosen) < args.target_n:
        print(
            f"\nNOTE: asked for {args.target_n}, got {len(chosen)}. The reliable "
            "bands ran out of unused cases — build more before running the wave."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
