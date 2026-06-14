// Scale / throughput scenario for the ARP no-LLM load proof.
//
// Drives the orchestration accept path (`POST /api/run`) plus a workflow-DAG
// read (`GET /api/workflows/{name}/dag`) under a ramping-VU profile, with
// thresholds on p95/p99 latency and error rate. The SAME script is run at
// 1 replica and at N replicas (the replica count is injected via the BASE_URL
// target + an env tag) so the generator can compute the scale delta from two
// real k6 JSON summaries.
//
// Every request goes through the nginx round-robin (`lb`), so at N replicas the
// load provably fans out across all replicas sharing one Redis. Under
// AGENTIC_NO_LLM=1 the orchestration/scheduling/circuit-breaker/Redis-CAS paths
// run deterministically with zero tokens — we measure the platform, not a model.

import http from "k6/http";
import { check } from "k6";
import { Counter, Rate } from "k6/metrics";

const BASE_URL = __ENV.BASE_URL || "http://lb:80";
const WORKFLOW = __ENV.WORKFLOW || "code_review";
const ADAPTER = __ENV.ADAPTER || "native";
const REPLICAS = __ENV.REPLICAS || "unknown";

// Custom metrics so the JSON summary carries explicit, derivable signals.
const runsAccepted = new Counter("arp_runs_accepted");
const dagReads = new Counter("arp_dag_reads");
const appErrors = new Rate("arp_app_errors");

export const options = {
  // Ramping-VU profile: warm up, sustain, ramp down. Short by design so the
  // whole 1-replica + N-replica sweep finishes in a couple of minutes locally.
  scenarios: {
    ramping: {
      executor: "ramping-vus",
      startVUs: 0,
      stages: [
        { duration: "10s", target: 10 },
        { duration: "20s", target: 25 },
        { duration: "20s", target: 25 },
        { duration: "10s", target: 0 },
      ],
      gracefulStop: "5s",
    },
  },
  thresholds: {
    // Latency + error budgets. These are asserted by k6 (pass/fail in the
    // summary) and ALSO surfaced verbatim on the Pages report.
    http_req_failed: ["rate<0.05"], // <5% transport-level failures
    http_req_duration: ["p(95)<1500", "p(99)<3000"],
    arp_app_errors: ["rate<0.05"], // <5% app-level (non-2xx) responses
  },
  // Tag every metric sample with the replica count so the run is self-describing.
  tags: { replicas: REPLICAS },
  summaryTrendStats: ["avg", "min", "med", "max", "p(50)", "p(90)", "p(95)", "p(99)"],
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
  // 1. Orchestration accept path — enqueues a no-LLM workflow run. Returns 200
  //    with status=PENDING; the background run drives the router + Redis CAS.
  const runRes = http.post(`${BASE_URL}/api/run`, runPayload, {
    headers: jsonHeaders,
    tags: { endpoint: "run" },
  });
  const runOk = check(runRes, {
    "run: status 200": (r) => r.status === 200,
  });
  if (runOk) runsAccepted.add(1);
  appErrors.add(!runOk);

  // 2. Orchestration read path — DAG topology for the same workflow. Exercises
  //    config loading + serialization on the request thread (synchronous work).
  const dagRes = http.get(`${BASE_URL}/api/workflows/${WORKFLOW}/dag`, {
    tags: { endpoint: "dag" },
  });
  const dagOk = check(dagRes, {
    "dag: status 200": (r) => r.status === 200,
    "dag: has nodes": (r) => {
      try {
        return Array.isArray(r.json("nodes"));
      } catch (_e) {
        return false;
      }
    },
  });
  if (dagOk) dagReads.add(1);
  appErrors.add(!dagOk);
}
