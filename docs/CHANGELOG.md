# Changelog

The canonical changelog is maintained at the repository root — see
[`CHANGELOG.md` on GitHub](https://github.com/tafreeman/agentic-runtime-platform/blob/main/CHANGELOG.md)
for the complete history of releases, epics, sprints, and security entries.
The most recent release and post-release highlights are summarized below. The
next planned release is the `0.4.0-rc.1` platform bundle
(`release-manifest.toml`); no tag newer than `v0.3.0` exists yet.

---

## Unreleased highlights

Work landed since v0.3.0 (full detail in the `Unreleased` entries of the root changelog), newest first:

- **Runtime correctness and observability** (2026-09 to 2026-10) — the DAG executor fails closed on non-terminal steps and runs the same scheduling rules as the orchestrator, modelled in Lean ([ADR-060](adr/ADR-060-scheduler-guarantees-lean.md)); the LangGraph adapter runs each step once after all its dependencies ([ADR-062](adr/ADR-062-langgraph-join-once-semantics.md)); secret masks keep JSON replies parseable ([ADR-061](adr/ADR-061-json-safe-secret-masks.md)); run records are written atomically.
- **Models and providers** (2026-07 to 2026-10) — Mistral La Plateforme provider, GitHub Models removed from the tier chains, retired NVIDIA models replaced, `onnx:<folder>` ids run in chat with weight verification, cost-lane ceiling ([ADR-059](adr/ADR-059-model-cost-lane-ceiling.md)).
- **Evaluation and workflows** — the eval gate scores through the runtime instead of `agentic-v2-eval` and rejects malformed scores; step scoring reports `unavailable` instead of an automatic 0.7 and uses the optional EvalKit 0.4.1 bridge; new `plan_tribunal` workflow and a reworked `fullstack_generation`; study telemetry and the SWE-AB ledger.
- **Dashboard** — the Evidence Ledger design system, accessibility pass and design guardrails ([ADR-054](adr/ADR-054-evidence-ledger-ui-and-model-packs.md)).
- **Curated model registry + drift detection** (2026-06-25) — single source-of-truth model registry feeding both engines, with probe-time quarantine of retired model ids ([ADR-040](adr/ADR-040-curated-model-registry.md)).
- **Epic 7 — First-Run Experience** (2026-05-21) — zero-credential onboarding, `GettingStartedCard`, `NoProviderConfiguredError` guidance, devcontainer PR gate.
- **Epic 8 — Production Readiness Pack** — OIDC JWT authentication, tenant isolation, append-only audit logging, model-weight integrity verification.
- **Sprint 1 — Production hardening** (2026-05-14) — API rate limiting + per-IP auth throttle, DAG top-level timeout, wire-format drift gate extended to six shapes (eight today), tool-safety security fixes (S1-01 – S1-07).
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
