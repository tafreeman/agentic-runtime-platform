# ADR-015: SLO Rolling Window Stored in Git

**Status:** Accepted
**Date:** 2026-04-22
**Implements:** commits `2e4e18a test(slo): time-to-first-span measurement and p95 gate`, `7d00ec6 ci(nightly): 50x streaming reliability + rolling flake-rate gate`, `1393b96 chore(slo): harden nightly + tighten reconnect/p95 contracts`
**Related:** Epic 2 (Observable Execution)

---

## Context

Epic 2 introduced two production-observability signals that needed CI-level enforcement:

1. **Time-to-first-span p95.** The latency from workflow start to the first span appearing downstream (Jaeger, Tempo, local OTEL collector). A regression here means users stare at a blank UI for longer on run start.

2. **Nightly streaming flake rate.** The `nightly.yml` job runs the streaming end-to-end flow 50× and measures how many runs miss events, disconnect cleanly, or hit reconnect-replay bugs. A rising flake rate is the earliest leading indicator of a WebSocket or event-loop regression.

Both are **distributional** signals — a single sample is noise. p95 over three samples is noise; p95 over 30 samples is signal. Flake rate over last night's one run is noise; flake rate over 30 nights is signal.

The obvious options for storing a rolling window were:

- **External time-series database** (Prometheus + Grafana, InfluxDB). Heavy for a single repo. Requires infrastructure we do not yet operate.
- **GitHub Actions artifacts** (retained per-run). Artifact retention is bounded (~90 days by default) and there is no cheap "give me the last 30" query — you iterate actions runs.
- **A cloud key-value store** (S3, Redis, Firebase). Requires credentials, region choices, backups — infrastructure burden disproportionate to a CI signal.
- **A separate metrics repo.** Better than the current repo; still a new repo to maintain.

None of these were justified by the scale of the signal (two numbers per nightly run).

---

## Decision

Store the rolling window **as JSON artifacts committed to this git repository**, one file per SLO signal, and compute the gate against the window.

### Shape

- `observability/slo-first-span.json` — rolling list of up to 30 recent p95 measurements, each tagged with commit SHA, timestamp, sample size.
- `observability/slo-flake-rate.json` — rolling list of the last 30 nightly runs' flake counts and totals.

Each CI run:

1. Measures the signal for the current commit.
2. Appends the result to the relevant JSON file, dropping the oldest entry when the window is full.
3. Computes the gate (`p95 of window ≤ contract threshold`, `flake rate ≤ contract threshold`).
4. Commits the updated JSON back with a `chore(slo): rolling window update` message, signed and attributed to the CI bot.
5. Fails the job if the gate fails.

### Why git works as the store

- **Durable retention** — the history is the branch history. We keep the window small (30 entries) so the files stay tiny.
- **Free review.** Every SLO update is a commit with a diff. A reviewer looking at a strange CI result can `git log observability/slo-first-span.json` and see the story.
- **Free correlation.** Each entry carries the commit SHA that produced it — regressions are attributable without a separate lookup.
- **No new infra.** Works on day one in any forked environment.
- **Works in the fork case.** Contributors do not need credentials for a metrics service to iterate.

---

## Consequences

### Positive

- Zero operational cost. No secrets, no dashboards to babysit, no retention policy to enforce.
- Every SLO number is `git blame`-able to a specific commit.
- The rolling-window file is itself diffable — a reviewer can see the whole story in the PR that breaks the gate.
- The signal travels with the repo — a forked repo picks up the same SLO behavior immediately.

### Negative

- **Gate passes trivially on an empty window.** A fresh branch, a window reset, or a file deletion leaves the gate in a "nothing measured, therefore passing" state. See [`KNOWN_LIMITATIONS.md`](../KNOWN_LIMITATIONS.md) §1.2. Sprint B will require ≥ N samples before the gate can declare pass.
- **No cross-branch aggregation.** The window is per-branch. Feature branches build their own history; main's is authoritative.
- **Commit noise on main.** Each nightly run produces a commit. We accept that; commits are prefixed `chore(slo):` and are trivially filterable from `git log --invert-grep`.
- **Not a substitute for real observability.** This stores two numbers. Production deployment of the platform will still need Prometheus/Grafana or equivalent — this ADR is about *CI signals*, not runtime observability.
- **Race on concurrent writes.** Two nightly runs landing seconds apart could conflict on the JSON file. We serialize by running SLO updates only on `main` and on scheduled cron, not on every PR.

### Alternatives revisited

- **Prometheus.** Will become the right answer when we deploy the platform. Not yet justified for CI signals.
- **GitHub Actions matrix + artifacts with a custom aggregator.** Considered. Rejected because it shifts the burden to a GH API crawler that breaks if GH changes retention semantics.
- **Cloud KV.** Revisit if we ever need cross-repo or cross-branch aggregation.

---

## Implementation references

- Measurement job: `.github/workflows/nightly.yml`
- Gate script: invoked from nightly job; computes p95 and flake rate
- Current contracts (thresholds): documented in [`docs/KNOWN_LIMITATIONS.md`](../KNOWN_LIMITATIONS.md) §1.2
- Landing commits: `2e4e18a`, `7d00ec6`, `1393b96`

---

## Review cadence

Re-evaluate when either:

- The set of SLO signals grows beyond three — at that point a proper metrics store becomes cheaper than maintaining one JSON file per signal.
- We deploy the platform to a production target that already has Prometheus / Grafana — at that point dual-storing CI signals there is free.
- The empty-window trivial-pass issue produces a miss in the wild.

---

## Pattern name

This is a specific application of a broader pattern occasionally called "git-as-time-series" or "measurement-as-commit". The pattern is worth naming because it composes well with other CI signals and is cheap enough to adopt incrementally.
