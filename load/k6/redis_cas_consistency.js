// Redis-CAS shared-counter consistency scenario.
//
// Goal: drive a FIXED, known number of orchestration requests concurrently
// across >=2 replicas that all share one Redis, so the circuit-breaker counter
// deltas each replica produces are merged via the CAS read-modify-write path
// (agentic_v2/models/redis_state.py::save_stats_cas). The consistency claim is:
//
//   the counter persisted in Redis == the exact sum of every replica's deltas
//   (no double-count from the fire-and-forget save race, no lost update from
//    last-writer-wins).
//
// k6 itself cannot read Redis, so this script's job is ONLY to generate the
// concurrent multi-replica write pressure and emit a JSON summary recording the
// EXACT number of orchestration requests it successfully issued. The companion
// probe (load/probe_redis_cas.py, run by the runner right after this scenario)
// snapshots the merged Redis counters into load/results/cas_consistency.json.
// The generator then cross-checks the two: requests-issued (k6 JSON) vs
// counter-persisted (probe JSON), observed-vs-expected, derived — never typed.
//
// We use a constant-arrival-rate executor with a fixed total so the "expected"
// number is deterministic and recorded in the summary, not assumed.

import http from "k6/http";
import { check } from "k6";
import { Counter } from "k6/metrics";

const BASE_URL = __ENV.BASE_URL || "http://lb:80";
const WORKFLOW = __ENV.WORKFLOW || "code_review";
const ADAPTER = __ENV.ADAPTER || "native";
const REPLICAS = __ENV.REPLICAS || "unknown";

// Total orchestration requests this run intends to issue. Fixed + recorded so
// "expected" is a measured input, not a magic number on the page.
const TARGET_RUNS = parseInt(__ENV.TARGET_RUNS || "600", 10);
const ARRIVAL_RATE = parseInt(__ENV.ARRIVAL_RATE || "60", 10); // runs/sec
const DURATION_S = Math.ceil(TARGET_RUNS / ARRIVAL_RATE);

// Explicit, derivable counters in the JSON summary.
const runsIssued = new Counter("arp_cas_runs_issued");
const runsAccepted = new Counter("arp_cas_runs_accepted");
const runsRejected = new Counter("arp_cas_runs_rejected");

export const options = {
  scenarios: {
    cas_pressure: {
      executor: "constant-arrival-rate",
      rate: ARRIVAL_RATE,
      timeUnit: "1s",
      duration: `${DURATION_S}s`,
      preAllocatedVUs: 50,
      maxVUs: 100,
    },
  },
  thresholds: {
    http_req_failed: ["rate<0.05"],
    // Acceptance must be near-total for the consistency claim to be meaningful;
    // any rejected request reduces the "expected" delta the probe verifies.
    arp_cas_runs_accepted: ["count>0"],
  },
  tags: { replicas: REPLICAS, scenario: "redis_cas" },
};

const runPayload = JSON.stringify({
  workflow: WORKFLOW,
  adapter: ADAPTER,
  input_data: {
    code_file: "examples/sample.py",
    review_depth: "quick",
  },
});

const jsonHeaders = { "Content-Type": "application/json" };

export default function () {
  const res = http.post(`${BASE_URL}/api/run`, runPayload, {
    headers: jsonHeaders,
    tags: { endpoint: "run" },
  });
  runsIssued.add(1);
  const ok = check(res, { "run accepted (200)": (r) => r.status === 200 });
  if (ok) {
    runsAccepted.add(1);
  } else {
    runsRejected.add(1);
  }
}
