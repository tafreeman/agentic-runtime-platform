# ARP local k6 load proof ($0, no cloud)

A free, local proof of ARP's **Redis-CAS circuit-breaker** + **horizontal-scale**
story. A multi-replica `docker compose` stack (Redis + N ARP FastAPI replicas,
all `AGENTIC_NO_LLM=1`) is hammered by the dockerized `grafana/k6` image; every
resulting number is published to GitHub Pages by `scripts/build_load_report.py`
— nothing is hand-typed.

GitHub Pages is static hosting: it cannot run Python/Redis/multiple replicas, so
the proof inherently needs live containers. **Run the proof locally (free),
publish the results.**

## Prerequisites

- Docker + Compose (the `grafana/k6` image is pulled automatically — **no host
  k6 install**).
- No API keys, no cloud account, no secrets. `AGENTIC_NO_LLM=1` makes every
  agent deterministic and token-free, so the load exercises the
  orchestration / scheduling / circuit-breaker / Redis-CAS paths, not a model.

## Reproduce (one command)

```bash
# from the repo root
bash load/run_load.sh 3        # 1 replica + 3 replicas + Redis-CAS run + probe
```

`run_load.sh`:

1. builds the load image (the shipped `backend-dev` stage **plus** the `redis`
   extra — that extra is what turns the Redis-CAS shared-state path on);
2. brings up **Redis + 1 replica**, runs the scale/throughput scenario;
3. scales to **N replicas**, re-runs the SAME scenario (captures the scale delta);
4. runs the **Redis-CAS consistency** scenario at N replicas;
5. runs the **CAS probe** (a live exact-sum experiment against the shared Redis,
   plus a snapshot of the circuit-breaker keys the replicas persisted);
6. snapshots each replica's `/api/health/ready` (shared-Redis evidence);
7. tears the stack down (`KEEP_UP=1` to leave it running for debugging).

Then regenerate the Pages report and render the docs:

```bash
python scripts/build_load_report.py     # writes docs/load-report.md from the JSON
mkdocs build                             # renders the docs site
```

## What lands in `load/results/`

| File | Produced by | Used for |
|---|---|---|
| `scale_1replica.json` | k6 `--summary-export` | 1-replica throughput/latency |
| `scale_<N>replica.json` | k6 `--summary-export` | N-replica throughput/latency, scale delta |
| `redis_cas_run.json` | k6 `--summary-export` | CAS-pressure request counts |
| `cas_consistency.json` | `probe_redis_cas.py` | observed-vs-expected CAS exact-sum proof + key snapshot |
| `health_ready.txt` | `/api/health/ready` snapshot | shared-Redis evidence |

These JSON files are the **only** data source for the Pages report. Re-running
the load proof + the generator updates every number with zero hand-editing.

## Files

| Path | Purpose |
|---|---|
| `docker-compose.load.yml` | Redis + scalable ARP `backend` + nginx round-robin `lb` |
| `Dockerfile.load` | shipped `backend-dev` image + the `redis` extra |
| `nginx.load.conf` | per-request DNS round-robin across replicas |
| `k6/scale_throughput.js` | ramping-VU scale/throughput scenario (1 vs N) |
| `k6/redis_cas_consistency.js` | constant-arrival CAS-pressure scenario |
| `probe_redis_cas.py` | live exact-sum CAS proof + Redis key snapshot |
| `run_load.sh` | end-to-end orchestrator |

## Tuning

`run_load.sh [N_REPLICAS]` sets the scaled replica count (default 3). The k6
scripts accept env overrides via `-e` (see each script header): `BASE_URL`,
`WORKFLOW`, `ADAPTER`, `REPLICAS`, `TARGET_RUNS`, `ARRIVAL_RATE`. The probe
accepts `CAS_TORTURE_WORKERS` / `CAS_TORTURE_FAILURES`.

## Honesty notes

- The load targets the **native** DAG adapter (`AGENTIC_DEFAULT_ADAPTER=native`)
  because the shipped `backend-dev` image does not install the `[langchain]`
  extra and the LangChain default would abort startup.
- `POST /api/run` enqueues a background workflow run and returns `PENDING`
  immediately, so the scale scenario measures the **orchestration accept path**
  throughput; the background runs drive the router + Redis-CAS saves.
- The CAS exact-sum proof in `probe_redis_cas.py` exercises the **real**
  production CAS path (`SmartModelRouter._save_stats_to_redis` →
  `RedisCircuitBreakerStore.save_stats_cas`) from concurrent independent workers
  against the live shared Redis, so the observed-vs-expected number is real.
