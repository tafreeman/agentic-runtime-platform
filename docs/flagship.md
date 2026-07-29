# Load and shared-state evidence

The repository includes a reproducible local load harness and a generated
[load report](load-report.md).

The committed report records two different experiments:

- the same API acceptance workload against one and three FastAPI replicas;
- a direct concurrent exact-sum test of the production Redis compare-and-swap
  circuit-breaker storage path.

The API workload measures `POST /api/run` acceptance throughput and latency. In
the captured run, that request path did not reach the model client, so it did
not itself create the Redis circuit-breaker writes. The separate worker
experiment is the evidence for Redis counter consistency.

The report is generated from committed JSON under `load/results/`; do not edit
its measurements by hand.

To reproduce the experiment, use the instructions in
[the load harness README](https://github.com/tafreeman/agentic-runtime-platform/blob/main/load/README.md).
It requires Docker and a Bash
environment such as Git Bash or WSL on Windows.
