# Changelog

The canonical changelog is maintained at the repository root — see
[`CHANGELOG.md` on GitHub](https://github.com/tafreeman/agentic-runtime-platform/blob/main/CHANGELOG.md)
for the complete history of releases, epics, sprints, and security entries.
The most recent release and post-release highlights are summarized below.

---

## Unreleased highlights

Work landed since v0.3.0 (full detail under `[Unreleased]` in the root changelog):

- **Curated model registry + drift detection** (2026-06-25) — single source-of-truth model registry feeding both engines, with probe-time quarantine of retired model ids ([ADR-040](adr/ADR-040-curated-model-registry.md)).
- **Epic 7 — First-Run Experience** (2026-05-21) — zero-credential onboarding, `GettingStartedCard`, `NoProviderConfiguredError` guidance, devcontainer PR gate.
- **Epic 8 — Production Readiness Pack** — OIDC JWT authentication, tenant isolation, append-only audit logging, model-weight integrity verification.
- **Sprint 1 — Production hardening** (2026-05-14) — API rate limiting + per-IP auth throttle, DAG top-level timeout, wire-format drift gate extended to six shapes, tool-safety security fixes (S1-01 – S1-07).
- **Sprint 2 — Operability at scale** (2026-05-18) — Redis-backed circuit breaker, Prometheus `/metrics` endpoint, W3C `traceparent` propagation, WebSocket replay persistence, eval-package mypy strict cleanup.

## [0.3.0] — 2026-04-22

First tracked release of the platform. Bundles **Epic 1** (Platform Foundation),
**Epic 2** (Observable Execution), **Epic 3** (DevEx / Windows), **Epic 5**
(Console UI Polish), and **Epic 6** (Evaluation & Data Depth). Epic 4 was never
authored — the number was skipped during planning; it is a tombstone, not a
regression.

Per-item detail, known limitations shipped with caveats, and migration notes for
v0.3.0 live in the
[root `CHANGELOG.md`](https://github.com/tafreeman/agentic-runtime-platform/blob/main/CHANGELOG.md).
