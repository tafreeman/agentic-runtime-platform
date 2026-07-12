"""Performance regression gate for ARP load results.

Reads a k6 --summary-export JSON and a baseline file, then exits non-zero
if any of the following breach conditions are true:

- p99 latency > P99_LATENCY_BREACH_MULTIPLIER x baseline.p99_latency_ms
- throughput  < THROUGHPUT_BREACH_MULTIPLIER    x baseline.throughput_rps

Usage
-----
    python load/compare_to_baseline.py <summary.json> [--baseline load/baseline.json]

Exit codes
----------
    0  All metrics within acceptable range.
    1  One or more metrics breached the threshold.
    2  Bad arguments or unreadable/malformed input files.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Threshold constants — documented here so they are easy to find and change.
#
# P99_LATENCY_BREACH_MULTIPLIER: the measured p99 latency must be BELOW this
# many times the baseline value. 2.0 means we tolerate up to 2x degradation
# before failing CI.
P99_LATENCY_BREACH_MULTIPLIER: float = 2.0

# THROUGHPUT_BREACH_MULTIPLIER: the measured throughput (iterations/sec) must
# stay ABOVE this fraction of the baseline. 0.5 means we fail if throughput
# drops below half of the baseline rate.
THROUGHPUT_BREACH_MULTIPLIER: float = 0.5
# ---------------------------------------------------------------------------

_DEFAULT_BASELINE = Path(__file__).parent / "baseline.json"


def _load_json(path: Path, label: str) -> Any:
    """Read and parse a JSON file, exiting with code 2 on any error."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        print(f"ERROR: {label} not found: {path}", file=sys.stderr)
        sys.exit(2)
    except json.JSONDecodeError as exc:
        print(f"ERROR: {label} is not valid JSON: {exc}", file=sys.stderr)
        sys.exit(2)


def _extract_p99(summary: Any) -> float:
    """Pull p99 latency (ms) from a k6 --summary-export JSON.

    k6 stores the value at metrics.http_req_duration["p(99)"]. Returns
    the float value or exits with code 2 if the key is absent.
    """
    try:
        p99: float = float(summary["metrics"]["http_req_duration"]["p(99)"])
        return p99
    except (KeyError, TypeError, ValueError) as exc:
        print(
            f'ERROR: Cannot read metrics.http_req_duration["p(99)"] from summary: {exc}',
            file=sys.stderr,
        )
        sys.exit(2)


def _extract_throughput(summary: Any) -> float:
    """Pull throughput (iterations/sec) from a k6 --summary-export JSON.

    k6 stores the iteration rate at metrics.iterations.rate. Returns the
    float value or exits with code 2 if the key is absent.
    """
    try:
        rate: float = float(summary["metrics"]["iterations"]["rate"])
        return rate
    except (KeyError, TypeError, ValueError) as exc:
        print(
            f"ERROR: Cannot read metrics.iterations.rate from summary: {exc}",
            file=sys.stderr,
        )
        sys.exit(2)


def _extract_baseline_value(baseline: Any, key: str) -> float:
    """Read a numeric key from the baseline dict, exiting on missing/invalid."""
    try:
        return float(baseline[key])
    except (KeyError, TypeError, ValueError) as exc:
        print(
            f"ERROR: baseline.{key} is missing or not numeric: {exc}", file=sys.stderr
        )
        sys.exit(2)


def compare(summary_path: Path, baseline_path: Path) -> int:
    """Compare summary metrics to baseline.

    Returns 0 if all metrics are within acceptable range, 1 if any
    breach.
    """
    summary = _load_json(summary_path, "k6 summary")
    baseline = _load_json(baseline_path, "baseline")

    baseline_p99: float = _extract_baseline_value(baseline, "p99_latency_ms")
    baseline_rps: float = _extract_baseline_value(baseline, "throughput_rps")

    measured_p99: float = _extract_p99(summary)
    measured_rps: float = _extract_throughput(summary)

    ceiling_p99: float = P99_LATENCY_BREACH_MULTIPLIER * baseline_p99
    floor_rps: float = THROUGHPUT_BREACH_MULTIPLIER * baseline_rps

    breached = False

    print(f"Baseline p99 latency : {baseline_p99:.2f} ms")
    print(
        f"Measured p99 latency : {measured_p99:.2f} ms"
        f"  (ceiling: {ceiling_p99:.2f} ms = {P99_LATENCY_BREACH_MULTIPLIER}x baseline)"
    )
    if measured_p99 > ceiling_p99:
        print(
            f"BREACH: p99 latency {measured_p99:.2f} ms exceeds "
            f"{P99_LATENCY_BREACH_MULTIPLIER}x baseline ({ceiling_p99:.2f} ms)",
            file=sys.stderr,
        )
        breached = True
    else:
        print("  -> p99 latency OK")

    print(f"Baseline throughput  : {baseline_rps:.2f} req/s")
    print(
        f"Measured throughput  : {measured_rps:.2f} req/s"
        f"  (floor: {floor_rps:.2f} req/s = {THROUGHPUT_BREACH_MULTIPLIER}x baseline)"
    )
    if measured_rps < floor_rps:
        print(
            f"BREACH: throughput {measured_rps:.2f} req/s is below "
            f"{THROUGHPUT_BREACH_MULTIPLIER}x baseline ({floor_rps:.2f} req/s)",
            file=sys.stderr,
        )
        breached = True
    else:
        print("  -> throughput OK")

    return 1 if breached else 0


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare a k6 summary JSON to the ARP load baseline.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "summary",
        type=Path,
        help="Path to the k6 --summary-export JSON file to evaluate.",
    )
    parser.add_argument(
        "--baseline",
        type=Path,
        default=_DEFAULT_BASELINE,
        help=f"Path to the baseline JSON (default: {_DEFAULT_BASELINE}).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    sys.exit(compare(args.summary, args.baseline))


if __name__ == "__main__":
    main()
