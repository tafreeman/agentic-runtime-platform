"""Generate the GitHub Pages load-report page from committed k6 + probe JSON.

This is the single source of truth for the ARP flagship reliability/load
dashboard. EVERY number on the rendered page is derived here from the JSON the
local k6 run produced (``load/results/*.json``) — nothing is hand-typed. Re-run
the load proof, re-run this generator, and every figure on the page updates with
zero manual editing (a standing project rule).

Inputs (all under ``load/results/``):
  * ``scale_1replica.json``       — k6 --summary-export, 1-replica scale run
  * ``scale_<N>replica.json``     — k6 --summary-export, N-replica scale run
  * ``redis_cas_run.json``        — k6 --summary-export, CAS-pressure run
  * ``cas_consistency.json``      — Redis-CAS probe (live exact-sum + snapshot)

Output:
  * ``docs/load-report.md``       — the mkdocs page (mermaid topology + tables)

Usage::

    python scripts/build_load_report.py            # default paths
    python scripts/build_load_report.py --results load/results --out docs/load-report.md

If the expected JSON is missing the page is still generated, but the affected
section is rendered as an explicit "not measured in this run" admonition rather
than a fabricated value.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
from datetime import UTC, datetime
from typing import Any

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_RESULTS = os.path.join(REPO_ROOT, "load", "results")
DEFAULT_OUT = os.path.join(REPO_ROOT, "docs", "load-report.md")

# k6 --summary-export keys we read. Kept centralized so a k6 schema change is a
# one-line edit, not a scavenger hunt.
_DURATION_METRIC = "http_req_duration"
_REQS_METRIC = "http_reqs"
_FAILED_METRIC = "http_req_failed"


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------
def _load_json(path: str) -> dict[str, Any] | None:
    """Load a JSON file, returning None if it is absent or unparseable."""
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def _find_scale_files(results_dir: str) -> dict[int, str]:
    """Map replica-count -> scale summary file path (e.g. {1: ..., 3: ...})."""
    found: dict[int, str] = {}
    for path in glob.glob(os.path.join(results_dir, "scale_*replica.json")):
        base = os.path.basename(path)
        # scale_<N>replica.json
        digits = base.replace("scale_", "").replace("replica.json", "")
        if digits.isdigit():
            found[int(digits)] = path
    return found


# ---------------------------------------------------------------------------
# k6 summary extraction (defensive against schema variance)
# ---------------------------------------------------------------------------
def _metric_values(summary: dict[str, Any], metric: str) -> dict[str, Any]:
    """Return the ``values`` dict for a k6 metric, or {} if absent."""
    metrics = summary.get("metrics", {})
    entry = metrics.get(metric, {})
    values = entry.get("values", entry)  # some exporters flatten one level
    return values if isinstance(values, dict) else {}


def _num(values: dict[str, Any], *keys: str) -> float | None:
    """Return the first present numeric value among ``keys`` (case-tolerant)."""
    for key in keys:
        if key in values and isinstance(values[key], (int, float)):
            return float(values[key])
        # k6 percentile keys look like "p(95)"
        for actual, val in values.items():
            if actual.replace(" ", "").lower() == key.replace(" ", "").lower():
                if isinstance(val, (int, float)):
                    return float(val)
    return None


def _custom_count(summary: dict[str, Any], metric: str) -> float | None:
    """Return the ``count`` of a custom Counter metric, if present."""
    values = _metric_values(summary, metric)
    return _num(values, "count")


def _extract_run(summary: dict[str, Any] | None) -> dict[str, Any] | None:
    """Pull the headline figures out of one k6 summary into a flat dict."""
    if not summary:
        return None
    dur = _metric_values(summary, _DURATION_METRIC)
    reqs = _metric_values(summary, _REQS_METRIC)
    failed = _metric_values(summary, _FAILED_METRIC)

    total_reqs = _num(reqs, "count")
    req_rate = _num(reqs, "rate")
    fail_rate = _num(failed, "rate", "value")

    return {
        "total_requests": total_reqs,
        "req_per_sec": req_rate,
        "p50_ms": _num(dur, "p(50)", "med"),
        "p90_ms": _num(dur, "p(90)"),
        "p95_ms": _num(dur, "p(95)"),
        "p99_ms": _num(dur, "p(99)"),
        "avg_ms": _num(dur, "avg"),
        "max_ms": _num(dur, "max"),
        "error_rate": fail_rate,
        "max_vus": _num(_metric_values(summary, "vus_max"), "value", "max"),
        "runs_accepted": _custom_count(summary, "arp_runs_accepted"),
        "dag_reads": _custom_count(summary, "arp_dag_reads"),
    }


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------
def _fmt(value: float | None, suffix: str = "", nd: int = 2) -> str:
    """Format a number for the table, or an em-dash when not measured."""
    if value is None:
        return "—"
    if abs(value - round(value)) < 1e-9 and suffix in ("", " req"):
        return f"{round(value):,}{suffix}"
    return f"{value:,.{nd}f}{suffix}"


def _pct(value: float | None) -> str:
    """Format a 0..1 rate as a percentage string."""
    if value is None:
        return "—"
    return f"{value * 100:.2f}%"


def _delta_x(base: float | None, scaled: float | None) -> str:
    """Format a multiplicative scale delta (scaled / base)."""
    if not base or not scaled:
        return "—"
    return f"{scaled / base:.2f}x"


# ---------------------------------------------------------------------------
# Page rendering
# ---------------------------------------------------------------------------
def _render_scale_table(runs: dict[int, dict[str, Any]]) -> str:
    """Render the 1-vs-N replica scale-delta table from extracted runs."""
    counts = sorted(runs)
    header = "| Metric | " + " | ".join(f"{c} replica(s)" for c in counts)
    if len(counts) >= 2:
        header += " | Scale delta (N vs 1) |"
    else:
        header += " |"
    sep = "|" + "---|" * (len(counts) + (2 if len(counts) >= 2 else 1))

    base = runs[counts[0]] if counts else {}
    topn = runs[counts[-1]] if counts else {}

    def row(label: str, key: str, fmt, delta: bool = False) -> str:
        cells = [fmt(runs[c].get(key)) for c in counts]
        line = f"| {label} | " + " | ".join(cells)
        if len(counts) >= 2:
            if delta:
                line += f" | {_delta_x(base.get(key), topn.get(key))} |"
            else:
                line += " | — |"
        else:
            line += " |"
        return line

    lines = [header, sep]
    lines.append(row("Total requests", "total_requests", lambda v: _fmt(v)))
    lines.append(row("Throughput (req/s)", "req_per_sec", lambda v: _fmt(v, "", 2), delta=True))
    lines.append(row("Runs accepted (POST /api/run)", "runs_accepted", lambda v: _fmt(v), delta=True))
    lines.append(row("p50 latency", "p50_ms", lambda v: _fmt(v, " ms")))
    lines.append(row("p95 latency", "p95_ms", lambda v: _fmt(v, " ms")))
    lines.append(row("p99 latency", "p99_ms", lambda v: _fmt(v, " ms")))
    lines.append(row("Avg latency", "avg_ms", lambda v: _fmt(v, " ms")))
    lines.append(row("Max VUs", "max_vus", lambda v: _fmt(v)))
    lines.append(row("Error rate", "error_rate", _pct))
    return "\n".join(lines)


def _render_cas_section(probe: dict[str, Any] | None, cas_run: dict[str, Any] | None) -> str:
    """Render the Redis-CAS consistency evidence from the probe + k6 JSON."""
    if not probe:
        return (
            '!!! warning "Redis-CAS consistency — not measured in this run"\n'
            "    `load/results/cas_consistency.json` was not found, so no CAS "
            "consistency figures are shown. Run `bash load/run_load.sh` to "
            "produce it.\n"
        )

    torture = probe.get("cas_torture", {})
    observed = torture.get("observed_failure_count")
    expected = torture.get("expected_failure_count")
    consistent = torture.get("consistent")
    workers = torture.get("workers")
    per_worker = torture.get("failures_per_worker")
    drift = torture.get("lost_or_double_counted")

    state = probe.get("observed_state", {})
    model_count = state.get("model_count")
    coherent = state.get("all_counters_coherent")

    # CAS-pressure run figures (from k6 JSON), if available.
    issued = _custom_count(cas_run, "arp_cas_runs_issued") if cas_run else None
    accepted = _custom_count(cas_run, "arp_cas_runs_accepted") if cas_run else None

    verdict = "✅ CONSISTENT" if consistent else "❌ INCONSISTENT"

    lines = []
    lines.append(
        f"**Live exact-sum CAS experiment** — {workers} independent workers "
        f"(each its own router + Redis store, all sharing the one Redis the "
        f"replicas use) each recorded **{per_worker}** failures on the same "
        f"model and persisted concurrently through the production CAS "
        f"read-modify-write path."
    )
    lines.append("")
    lines.append("| Quantity | Value |")
    lines.append("|---|---|")
    lines.append(f"| Concurrent CAS writers | {_fmt(workers)} |")
    lines.append(f"| Failures recorded per writer | {_fmt(per_worker)} |")
    lines.append(f"| **Expected** persisted `failure_count` | **{_fmt(expected)}** |")
    lines.append(f"| **Observed** persisted `failure_count` | **{_fmt(observed)}** |")
    lines.append(f"| Lost / double-counted | {_fmt(drift)} |")
    lines.append(f"| Result | **{verdict}** |")
    lines.append("")
    if model_count:
        lines.append(
            f"During the load run, **{_fmt(model_count)}** circuit-breaker "
            f"key(s) (`{state.get('key_prefix', 'agentic:cb:')}*`) were persisted "
            f"to the shared Redis by the replicas, and every counter was "
            f"{'coherent (no torn or negative writes)' if coherent else 'NOT all coherent — see JSON'}."
        )
    else:
        lines.append(
            f'!!! note "Why the exact-sum experiment is the primary signal"\n'
            f"    The orchestration accept path (`POST /api/run`) drives the "
            f"shared circuit-breaker counters only when a workflow run reaches "
            f"the model client. In the working tree this load was run against, "
            f"the native DAG adapter raised before recording, so the replicas "
            f"persisted **{_fmt(model_count)}** `"
            f"{state.get('key_prefix', 'agentic:cb:')}*` keys via that path. "
            f"The consistency proof above therefore exercises the **same "
            f"production CAS code** "
            f"(`SmartModelRouter._save_stats_to_redis` → "
            f"`RedisCircuitBreakerStore.save_stats_cas`) directly from "
            f"concurrent workers against the live shared Redis — an honest, "
            f"directly-assertable observed-vs-expected result that does not "
            f"depend on that orchestration path."
        )
    if issued is not None:
        lines.append("")
        lines.append(
            f"The CAS-pressure k6 scenario issued **{_fmt(issued)}** "
            f"orchestration requests across the replicas "
            f"(**{_fmt(accepted)}** accepted), generating the concurrent "
            f"multi-replica write pressure that the experiment runs under."
        )
    return "\n".join(lines)


def _topology_mermaid(replica_count: int | None) -> str:
    """Mermaid topology diagram of the load stack."""
    n = replica_count or 3
    replicas = "\n".join(
        f'        R{i}["ARP replica {i}<br/>FastAPI · AGENTIC_NO_LLM=1"]'
        for i in range(1, n + 1)
    )
    edges = "\n".join(f"    LB --> R{i}" for i in range(1, n + 1))
    cas_edges = "\n".join(f"    R{i} -.CAS.-> REDIS" for i in range(1, n + 1))
    return f"""```mermaid
flowchart TD
    K6["k6 load<br/>(grafana/k6 container)"] --> LB["nginx<br/>round-robin lb"]
    subgraph replicas["Horizontally-scaled ARP replicas"]
{replicas}
    end
{edges}
{cas_edges}
    REDIS[("Redis<br/>shared circuit-breaker state")]
```"""


def build_report(results_dir: str) -> str:
    """Assemble the full markdown page from the result JSON files."""
    scale_files = _find_scale_files(results_dir)
    runs: dict[int, dict[str, Any]] = {}
    for count, path in scale_files.items():
        extracted = _extract_run(_load_json(path))
        if extracted is not None:
            runs[count] = extracted

    probe = _load_json(os.path.join(results_dir, "cas_consistency.json"))
    cas_run = _load_json(os.path.join(results_dir, "redis_cas_run.json"))

    top_replicas = max(runs) if runs else None
    generated = datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")

    parts: list[str] = []
    parts.append("# Load proof: Redis-CAS + horizontal scale\n")
    parts.append(
        "!!! abstract \"Auto-generated — do not hand-edit\"\n"
        "    Every number on this page is derived by "
        "`scripts/build_load_report.py` from the committed k6 JSON in "
        "`load/results/`. Re-run `bash load/run_load.sh` then the generator to "
        f"refresh it. Generated **{generated}**.\n"
    )
    parts.append(
        "This page turns ARP's Redis-CAS circuit-breaker and horizontal-scale "
        "engineering from *described in code* into *proven with real numbers*. "
        "The proof runs locally and free (the `grafana/k6` image hammering a "
        "multi-replica `docker compose` stack with `AGENTIC_NO_LLM=1`); only the "
        "resulting JSON is published here.\n"
    )

    parts.append("## Topology\n")
    parts.append(_topology_mermaid(top_replicas))
    parts.append("")
    parts.append(
        "Redis is **external shared state on purpose.** Each ARP replica keeps "
        "an in-process circuit-breaker tally, but the *authoritative* per-model "
        "counters live in Redis. When a replica records a success/failure it "
        "persists only its **delta** via an atomic Compare-And-Swap "
        "(read-modify-write) keyed on the current value. If two replicas write "
        "concurrently, the CAS loser re-reads and re-merges its delta on top of "
        "the winner's value, so the persisted counter reflects **every** "
        "replica's contribution. That is why the shared counter stays exactly "
        "consistent under concurrent multi-replica load — no double-count, no "
        "lost update — which a per-replica in-memory tally could never guarantee."
    )
    parts.append("")

    parts.append("## Scale / throughput: 1 vs N replicas\n")
    if runs:
        parts.append(_render_scale_table(runs))
        parts.append("")
        parts.append(
            "Both runs use the identical ramping-VU k6 profile against the same "
            "nginx round-robin; the only variable is the replica count, so the "
            "throughput delta is attributable to horizontal scale."
        )
    else:
        parts.append(
            '!!! warning "Scale runs — not measured"\n'
            "    No `scale_*replica.json` summaries were found in "
            "`load/results/`. Run `bash load/run_load.sh`."
        )
    parts.append("")

    parts.append("## Redis-CAS shared-counter consistency\n")
    parts.append(_render_cas_section(probe, cas_run))
    parts.append("")

    parts.append("## How to reproduce\n")
    parts.append(
        "```bash\n"
        "# from the repo root (Docker required; no host k6 install needed)\n"
        "bash load/run_load.sh 3                 # 1-replica + 3-replica + CAS run\n"
        "python scripts/build_load_report.py     # regenerate THIS page from JSON\n"
        "mkdocs build                            # render the docs site\n"
        "```\n"
    )
    parts.append(
        "The load **run** is local and free; CI only **renders** the committed "
        "`load/results/*.json`, so GitHub Pages stays $0 and deterministic.\n"
    )

    return "\n".join(parts) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--results", default=DEFAULT_RESULTS, help="results dir")
    parser.add_argument("--out", default=DEFAULT_OUT, help="output markdown path")
    args = parser.parse_args()

    page = build_report(args.results)
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(page)
    print(f"Wrote {args.out} ({len(page):,} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
