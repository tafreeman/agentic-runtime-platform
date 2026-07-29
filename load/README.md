# Local load harness

This directory compares API acceptance performance with one and several
FastAPI replicas and tests the Redis circuit-breaker counter store with
concurrent writers.

It uses Docker Compose, nginx, Redis, and the `grafana/k6` image. The backend
runs with `AGENTIC_NO_LLM=1`, the native adapter, and API rate limiting
disabled.

## Evidence boundaries

The harness produces two separate results:

- k6 measures `POST /api/run` acceptance throughput and latency through nginx;
- `probe_redis_cas.py` runs a direct exact-sum experiment through the
  production Redis compare-and-swap save path.

In the currently committed capture, accepted background runs did not reach the
model client and did not create circuit-breaker keys. The direct probe, not the
HTTP workload, is the counter-consistency evidence.

## Requirements

- Docker with Compose;
- Bash;
- enough local resources for the selected replica count.

On Windows, run the script from Git Bash or WSL. No provider key or cloud
account is required.

## Run

From the repository root:

```bash
bash load/run_load.sh 3
```

The argument is the scaled replica count and defaults to `3`.

The script:

1. builds the runtime load image;
2. starts Redis, nginx, and one backend replica;
3. runs the scale scenario;
4. scales to the requested replica count and repeats the same scenario;
5. runs the CAS-pressure HTTP scenario;
6. runs the direct concurrent Redis exact-sum probe;
7. captures readiness responses;
8. removes the stack and volumes.

Set `KEEP_UP=1` to leave the stack running for diagnosis:

```bash
KEEP_UP=1 bash load/run_load.sh 3
```

Later cleanup:

```bash
docker compose -f load/docker-compose.load.yml down -v
```

The load balancer is published on host port `8088` while the stack is up.
Backend replica ports are not published.

## Results

The script writes:

| File | Contents |
| --- | --- |
| `results/scale_1replica.json` | One-replica k6 summary |
| `results/scale_<N>replica.json` | Scaled k6 summary |
| `results/redis_cas_run.json` | CAS-pressure HTTP summary |
| `results/cas_consistency.json` | Direct expected-versus-observed Redis proof |
| `results/health_ready.txt` | Readiness snapshots through nginx |

k6 threshold failure is logged but does not stop the remaining scenarios, so
inspect the summaries and command output before treating a run as valid.

## Regenerate the report

`docs/load-report.md` is generated. Do not edit it manually.

```powershell
python scripts/build_load_report.py
```

Then run the normal documentation checks and strict site build.

## Configuration

The k6 scripts accept environment values such as `BASE_URL`, `WORKFLOW`,
`ADAPTER`, `REPLICAS`, `TARGET_RUNS`, and `ARRIVAL_RATE`. The direct probe uses
`CAS_TORTURE_WORKERS`, `CAS_TORTURE_FAILURES`, and `CAS_TORTURE_MODEL`.

Change one experimental variable at a time when comparing runs. Record Docker
versions, host resources, replica count, and the exact commit with the result.

## Files

| Path | Purpose |
| --- | --- |
| `docker-compose.load.yml` | Redis, backends, nginx, and network |
| `Dockerfile.load` | Runtime image with Redis support |
| `nginx.load.conf` | Request distribution across backend replicas |
| `k6/scale_throughput.js` | One-versus-many API scenario |
| `k6/redis_cas_consistency.js` | CAS-pressure HTTP scenario |
| `probe_redis_cas.py` | Direct concurrent Redis counter test |
| `run_load.sh` | Experiment orchestration |
