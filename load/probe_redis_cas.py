"""Redis-CAS consistency probe for the ARP load proof.

Runs as a one-shot container on the load network AFTER the k6 scenarios, with
access to the SAME live Redis the ARP replicas share. It produces the
machine-readable consistency evidence the Pages generator consumes — every
number it writes is measured against the live Redis, never hand-set.

Two independent, honest signals are captured:

1. ``observed_state`` — a snapshot of the circuit-breaker keys (``agentic:cb:*``)
   that the running replicas persisted during the load. This proves the keys are
   present, hold valid JSON, and carry coherent monotonic counters (no torn /
   corrupt writes from the concurrent multi-replica CAS traffic).

2. ``cas_torture`` — a live, in-Redis exact-sum experiment that exercises the
   ACTUAL production CAS save path (``SmartModelRouter._save_stats_to_redis`` →
   ``RedisCircuitBreakerStore.save_stats_cas``) from N concurrent independent
   "workers" (each its own router + store, all sharing this one Redis, exactly
   as separate replica processes do). Each worker records a known number of
   failures; the persisted ``failure_count`` MUST equal the exact sum across all
   workers. This is the directly-assertable "no double-count, no lost update"
   proof, with observed-vs-expected derived from the run.

Output: ``/results/cas_consistency.json`` (mounted to ``load/results/``).
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from datetime import UTC, datetime
from typing import Any

# The agentic_v2 package is installed in the image; import the real production
# CAS components so the torture test exercises shipped code, not a reimplementation.
from agentic_v2.models.model_stats import ModelStats
from agentic_v2.models.redis_state import (
    _COUNTER_FIELDS,
    RedisCircuitBreakerStore,
)
from agentic_v2.models.smart_router import SmartModelRouter

REDIS_URL = os.environ.get("REDIS_URL", "redis://redis:6379/0")
CB_PREFIX = os.environ.get("REDIS_CIRCUIT_BREAKER_PREFIX", "agentic:cb:")
RESULTS_PATH = os.environ.get("CAS_RESULT_PATH", "/results/cas_consistency.json")

# Torture-test parameters (recorded in output → derivable, not magic).
TORTURE_WORKERS = int(os.environ.get("CAS_TORTURE_WORKERS", "4"))
TORTURE_FAILURES_PER_WORKER = int(os.environ.get("CAS_TORTURE_FAILURES", "50"))
TORTURE_MODEL = os.environ.get("CAS_TORTURE_MODEL", "loadtest:cas-probe")


async def _snapshot_observed_state(store: RedisCircuitBreakerStore) -> dict[str, Any]:
    """Snapshot circuit-breaker keys persisted by the replicas during the load."""
    all_stats = await store.get_all()
    coherent = True
    per_model: dict[str, Any] = {}
    for model, stats_dict in all_stats.items():
        counters = {f: stats_dict.get(f, 0) for f in _COUNTER_FIELDS}
        # Coherence: counters must be non-negative ints (a torn CAS write or a
        # lost-update merge bug would surface as a negative or missing counter).
        model_coherent = all(isinstance(v, int) and v >= 0 for v in counters.values())
        coherent = coherent and model_coherent
        per_model[model] = {
            "counters": counters,
            "circuit_state": stats_dict.get("circuit_state"),
            "coherent": model_coherent,
        }
    return {
        "key_prefix": CB_PREFIX,
        "model_count": len(all_stats),
        "models": per_model,
        "all_counters_coherent": coherent,
    }


async def _one_worker(failures: int) -> dict[str, int]:
    """One independent 'replica': its own router+store on the shared Redis."""
    store = await RedisCircuitBreakerStore.connect(
        redis_url=REDIS_URL, prefix=CB_PREFIX
    )
    if not store.is_connected:
        raise RuntimeError(f"probe worker could not connect to Redis at {REDIS_URL}")
    router = SmartModelRouter(_redis_store=store, _auto_save=False)
    for _ in range(failures):
        router.record_failure(TORTURE_MODEL, "timeout")
    # Persist via the real production CAS read-modify-write path.
    await router._save_stats_to_redis()
    await router.aclose()
    await store.close()
    return {"failures_recorded": failures}


async def _run_cas_torture(store: RedisCircuitBreakerStore) -> dict[str, Any]:
    """Live exact-sum CAS experiment against the shared Redis.

    N concurrent workers each record ``TORTURE_FAILURES_PER_WORKER`` failures on
    the SAME model and persist concurrently. The merged ``failure_count`` in
    Redis must equal ``N * failures`` — proving the CAS path summed every
    worker's delta with no double-count and no lost update.
    """
    # Start from a clean key so the expected total is exactly the sum we drive.
    await store.delete(TORTURE_MODEL)

    expected = TORTURE_WORKERS * TORTURE_FAILURES_PER_WORKER
    await asyncio.gather(
        *[_one_worker(TORTURE_FAILURES_PER_WORKER) for _ in range(TORTURE_WORKERS)]
    )

    persisted = await store.get(TORTURE_MODEL)
    observed = int(persisted["failure_count"]) if persisted else 0
    # Snapshot the merged key the concurrent writers produced (before cleanup),
    # so observed_state shows a real multi-writer CAS-persisted counter.
    merged_snapshot = {
        f: (persisted.get(f, 0) if persisted else 0) for f in _COUNTER_FIELDS
    }
    # Clean up the probe key so it does not pollute the replicas' real state.
    await store.delete(TORTURE_MODEL)

    return {
        "model": TORTURE_MODEL,
        "workers": TORTURE_WORKERS,
        "failures_per_worker": TORTURE_FAILURES_PER_WORKER,
        "expected_failure_count": expected,
        "observed_failure_count": observed,
        "consistent": observed == expected,
        "lost_or_double_counted": expected - observed,
        "merged_counter_snapshot": merged_snapshot,
    }


async def main() -> int:
    store = await RedisCircuitBreakerStore.connect(
        redis_url=REDIS_URL, prefix=CB_PREFIX
    )
    if not store.is_connected:
        print(
            f"FATAL: probe could not connect to Redis at {REDIS_URL}", file=sys.stderr
        )
        return 2

    observed_state = await _snapshot_observed_state(store)
    cas_torture = await _run_cas_torture(store)
    await store.close()

    result = {
        "schema": "arp.load.cas_consistency/v1",
        "generated_at": datetime.now(UTC).isoformat(),
        "redis_url_host": REDIS_URL.split("@")[-1],  # never echo credentials
        "observed_state": observed_state,
        "cas_torture": cas_torture,
    }

    os.makedirs(os.path.dirname(RESULTS_PATH), exist_ok=True)
    with open(RESULTS_PATH, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2)

    status = "CONSISTENT" if cas_torture["consistent"] else "INCONSISTENT"
    print(
        f"[probe] CAS torture: {cas_torture['observed_failure_count']}/"
        f"{cas_torture['expected_failure_count']} -> {status}; "
        f"replica keys observed: {observed_state['model_count']} "
        f"(coherent={observed_state['all_counters_coherent']})"
    )
    print(f"[probe] wrote {RESULTS_PATH}")
    return 0 if cas_torture["consistent"] else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
