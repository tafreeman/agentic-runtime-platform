# Reference IaC — NOT deployed, $0

This Bicep is **prod-readiness evidence**, not a running deployment. The ARP
flagship's *live* proof is the local k6 run + the GitHub Pages report
(`load/`, `scripts/build_load_report.py`, `docs/load-report.md`). This template
is authored, `az bicep build`/`lint`-clean, and secret-free — but it is **never
deployed**. No `az login`, no `az deployment`, no paid resource is ever stood up
from this repo's automation.

## What it maps

It expresses the local load topology as managed Azure services, 1:1:

| Local load proof | Azure (this template) |
|---|---|
| nginx round-robin + N replicas | Container Apps, HTTP-concurrency autoscale, `minReplicas..maxReplicas` |
| local Redis (shared CAS store) | Azure Cache for Redis (Standard, TLS-only) |
| OTel collector + Jaeger | Log Analytics + Application Insights |
| local `docker build` | Azure Container Registry (admin user **off**) |
| no static keys | user-assigned managed identity + `AcrPull` |

`minReplicas` defaults to **2**, mirroring the multi-replica Redis-CAS proof
(at least two replicas sharing one Redis under concurrent load).

## Secret-free by construction

- No secrets are committed. Redis keys, the App Insights connection string, and
  ACR pull are all resolved **at deploy time** inside the template via
  `listKeys()` / managed identity — never as committed parameters or literals.
- `main.bicepparam.example` is the committed, secret-free parameter template.
  Copy it to `main.bicepparam` (gitignored) and fill real values before any
  deploy.
- The deploy workflow (`.github/workflows/infra-deploy.yml`) uses **OIDC**
  federation (`id-token: write`) — no stored client secret.

## Validate locally (no cloud, no cost)

```bash
az bicep install          # one-time
az bicep build --file infra/azure/main.bicep   # compile + lint -> main.json
az bicep lint  --file infra/azure/main.bicep   # lint only
```

## Why it is never run

The deploy workflow is `workflow_dispatch`-only (no push/PR/schedule trigger)
and additionally gated behind a typed `DEPLOY` confirmation plus an
`az deployment ... what-if` preview. It exists to demonstrate the production
shape of the system, not to spend money. Triggering it is an explicit,
out-of-band decision.
