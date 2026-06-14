# Flagship: proven Redis-CAS + horizontal scale

ARP's reliability story is not just described — it is **measured**. A free,
local k6 load proof hammers a multi-replica `docker compose` stack (Redis +
N ARP FastAPI replicas, `AGENTIC_NO_LLM=1`) and publishes the real numbers to
GitHub Pages.

➡️ **[Load proof: Redis-CAS + horizontal scale](load-report.md)** — auto-generated
from the committed k6 JSON; no metric is hand-typed.

What it demonstrates:

- **Horizontal scale delta** — the same ramping-VU k6 profile run at 1 replica
  and at N replicas, so the throughput/latency improvement is attributable to
  scale.
- **Redis-CAS shared-counter consistency** — concurrent multi-replica load
  exercising the Compare-And-Swap circuit-breaker store, with an observed-vs-
  expected exact-sum proof that the shared counter never double-counts or loses
  an update.

The load **run** is local and $0; CI only renders the committed
`load/results/*.json`, so GitHub Pages stays free and deterministic. Reproduce
with `bash load/run_load.sh` then `python scripts/build_load_report.py`.

> Orchestrator note: link this page (and `load-report.md`) from `README.md` and
> the mkdocs nav. The generator owns `docs/load-report.md`; this pointer file is
> safe to edit by hand.
