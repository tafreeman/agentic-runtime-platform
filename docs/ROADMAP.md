# Roadmap

> **Audience:** Contributors, reviewers, and stakeholders asking "what shipped, what's next, and why is Epic 4 missing?"
> **Outcome:** After reading, you can answer "is this in scope this quarter?" without asking a human.
> **Last verified:** 2026-05-21

This is the in-repo backlog. Day-to-day sprint tracking lives in issues; this file captures the load-bearing multi-week arcs. If you are about to propose a new initiative, add a stub under **Proposed** and open a PR for review — a roadmap entry without a PR is aspiration.

---

## 1. Shipped in April 2026 (v0.3.0)

v0.3.0 bundles five epics completed between 2026-04-01 and 2026-04-22. Full change lists are in [`CHANGELOG.md`](CHANGELOG.md) under `[0.3.0]`.

| Epic | Theme | Headline |
|------|-------|----------|
| **1** | Platform Foundation | Typed protocols, consolidated settings, schema-drift CI gate, golden-output regression, OTEL parent-child trace assertion, CI ruff + 80% coverage enforcement. |
| **2** | Observable Execution | Typed event wire format, live DAG animation, StepNode B2 redesign, 5-field drill-down, Playwright streaming PR gate (5×), reconnect-replay test, time-to-first-span SLO + p95 gate, nightly 50× reliability. |
| **3** | DevEx / Windows | `scripts/setup-dev.ps1` one-command bootstrap, `port-guard`, `workspace-test-runner`, `workflow-linter`, Windows Unicode CLI fix. |
| **5** | Console UI Polish | ASCII StatusBadge, `useHotkeys`, dashboard filter, empty/error/404 states, skip-to-main link, focus ring audit, paper-theme contrast QA, `BDagMini` SVG thumbnail. |
| **6** | Evaluation & Data Depth | Additive Pydantic v2 evaluation contracts, `tokens_30d` live stat, `GET /runs/{filename}/evaluation`, dataset sample endpoints, Evaluations rubric accordion, Datasets 3-pane browser. |

Implementation history is summarized below without carrying internal planning artifacts. Epics 3, 5, and 6 did not have formal pre-implementation plans; retrospective notes are summarized in the epic entries.





### The Epic 4 question

**There is no Epic 4.** The epic numbering jumps from Epic 3 to Epic 5 intentionally — no story, plan, commit, branch, or changelog entry uses the label "Epic 4" in this repository. The number was allocated during planning but never authored.

This is a **tombstone**, not a gap: do not retroactively renumber 5/6 down to 4/5, and do not reclaim "Epic 4" for a future initiative. Future epics continue from Epic 7.

*Verification:* `git log --all --grep="epic.4" -i` returns zero matches as of 2026-04-22. A repo-wide grep of source + docs returns the same.

---

## 2. Shipped in May 2026

### Epic 8 — Production Readiness Pack
Epic 8 focused on closing the gaps to make the platform "enterprise-grade for regulated production environments."
- **E8-1**: Mandatory OIDC JWT authentication (`auth_oidc.py`).
- **E8-2**: Tenant isolation with hard boundaries for runs and datasets (`tenant.py`).
- **E8-3**: Append-only, tamper-evident audit logging for all workflow executions and config changes (`audit_log.py`).
- **E8-4**: Supply-chain provenance with hash manifest verification for local ONNX model weights (`weight_integrity.py`).
- **E8-5**: Security posture consolidation and gap report captured in the security hardening and supply-chain documentation.

---

## 3. Shipped in Sprint 1 — Engineering Stabilization (2026-05-14)

Sprint 1 ran against the post-v0.3.0 two-sprint engineering plan (T1/T2/T3 item IDs). Full change list in [`CHANGELOG.md`](CHANGELOG.md).

| Item | ID | Shipped |
|------|----|---------|
| Wire-format type generation extended to `DAGResponse`, `WorkflowInputSchemaResponse`, `WorkflowEditorStep`, `RunsSummaryResponse` | T1-1 | 2026-05-14 (Sprint 1, see CHANGELOG) |
| Rate limiting + 401 brute-force throttle added to all endpoints | T1-4 | 2026-05-14 (Sprint 1, see CHANGELOG) |
| DAG executor top-level timeout watchdog | T2-4 | 2026-05-14 (Sprint 1, see CHANGELOG) |
| Global pytest timeout = 30 s + slow-test audit (`@pytest.mark.slow`) | T3-4 | 2026-05-14 (Sprint 1, see CHANGELOG) |
| F401 baseline cleared; ruff `F401` rule re-enabled and blocking | T3-3 | 2026-05-14 (Sprint 1, see CHANGELOG) |
| Eager LangChain adapter validation at server startup | T3-2 | 2026-05-14 (Sprint 1, see CHANGELOG) |
| Dataset sample endpoint API polish | SB-1 | 2026-05-18 (Sprint B carryover, see CHANGELOG) |
| Placeholder / no-LLM CI mode | SB-2 | 2026-05-18 (Sprint B carryover, see CHANGELOG) |

Previously shipped before Sprint 1 (informational):

| Item | ID | Shipped |
|------|----|---------|
| SLO gate empty-window trivial-pass fix | T1-3 | before Sprint 1 |
| TypeScript strict mode | T2-5 | before Sprint 1 |

---

## 3a. Shipped in Sprint 2 — Operability at Scale (2026-05-18)

Sprint 2 completed the two-sprint engineering stabilization plan. Full change list in [`CHANGELOG.md`](CHANGELOG.md).

| Item | ID | Shipped |
|------|----|---------|
| Redis-backed circuit breaker (Lua CAS, shared state across processes) | T1-2 | 2026-05-18 (Sprint 2, see CHANGELOG) |
| OTEL Metrics API + `/metrics` Prometheus scrape endpoint | T2-1 | 2026-05-18 (Sprint 2, see CHANGELOG) |
| W3C `traceparent` propagation (HTTP + WebSocket + browser SDK) | T2-2 | 2026-05-18 (Sprint 2, see CHANGELOG) |
| WebSocket replay buffer persistence (Redis / SQLite / InMemory backends) | T2-3 | 2026-05-18 (Sprint 2, see CHANGELOG) |
| `agentic-v2-eval` mypy strict mode cleanup + re-enable | T1-5 | 2026-05-18 (Sprint 2, see CHANGELOG) |
| JSON structured logs via `LOG_FORMAT=json` | T3-1 | 2026-05-18 (Sprint 2, see CHANGELOG) |
| CI doc-drift checks (protocol drift + workflow schema validation) | T3-5 | 2026-05-18 (Sprint 2, see CHANGELOG) |

### Sprint B backlog (portfolio stabilization — carried forward)

Sprint B targeted 2026-04-29 → 2026-05-10 and focused on stabilization for v0.3.1.

| Item | Owner | Status |
|------|-------|--------|
| **Unmask 35 mypy findings in `agentic-v2-eval/`** | unassigned | ✅ Shipped in Sprint 2 (T1-5) |
| **Fix SLO p95 empty-window trivial-pass** | unassigned | ✅ Shipped before Sprint 1 (T1-3) |
| **Automate Python ↔ TypeScript wire-format drift detection** | unassigned | ✅ Partially: T1-1 (Sprint 1) + T3-5 (Sprint 2). Remaining endpoints hand-mirrored. |

None of these block v0.3.0 release; all are honest accounting of debt taken on to ship.

---

## 3b. Shipped in May 2026 — Epic 7: First-Run Experience (2026-05-21)

Epic 7 closed the contributor onboarding gap: from `git clone` to a running workflow in under 10 minutes, with no LLM provider key required. Full change list in [`CHANGELOG.md`](CHANGELOG.md).

| Ticket | Headline | Shipped |
|--------|----------|---------|
| **E7-1** | Docs + setup hardening: surfaced `test_deterministic` as zero-credential first run in `docs/ONBOARDING.md`, `README.md`, `agentic-workflows-v2/README.md`, and `setup-dev.ps1`; fixed all `--input` inline-JSON examples to file-based form; added `just` installation instructions. | 2026-05-21 |
| **E7-2** | `GettingStartedCard` React component displayed to new users with no prior runs; dismissible and localStorage-persisted; wired into `DashboardPage.tsx`. | 2026-05-21 |
| **E7-3** | `NoProviderConfiguredError` added to `core/errors.py`; CLI renders a Rich panel with actionable guidance instead of a traceback; server returns HTTP 503 with JSON guidance; 7 new tests. | 2026-05-21 |
| **E7-4** | `.github/workflows/devcontainer-validate.yml` PR gate: builds the devcontainer and runs a smoke test on relevant file changes. | 2026-05-21 |
| **E7-5** | QA audit of onboarding docs: timing confirmed < 10 minutes, all commands verified copy-pasteable. | 2026-05-21 |

---

## 4. Proposed

### Epic 9 — Multi-Run Comparison (candidate)

**Problem statement:** Today the UI shows one run at a time. A frequent workflow during evaluation is comparing two or three runs side by side — same workflow, different prompts or adapters — to spot regressions. Some primitives exist (`agentic compare`, ADR-012 UI Evaluation Hub proposed), but the full comparison UX has not been built.

**Status:** Partially proposed in [ADR-012](adr/ADR-012-ui-evaluation-hub.md). Consolidate into an epic if prioritized.

---

## 5. Out of scope for v0.3.x

Flagged here so nobody quietly adds them to a sprint:

- **Presentation / deck system** - extracted to a separate repository on 2026-04-22. See [`MIGRATIONS.md`](MIGRATIONS.md). Not returning to this repo.
- **Cross-language agent workers** — this runtime is Python. Polyglot agents are intentionally deferred.
- **Multi-tenant billing / quotas** — Epic 8 shipped tenant isolation; billing/quota enforcement is deferred beyond v0.3.x.

---

## 6. How to propose new work

1. Open a PR that adds a subsection under §4 (Proposed). Include: problem statement, definition of done, rough sizing (story-weeks), open questions.
2. If the work crosses an architectural boundary — new engine, new contract, new security surface — write an ADR under [`adr/`](https://github.com/tafreeman/agentic-runtime-platform/tree/main/docs/adr) at the same time (see [`CONTRIBUTING.md`](https://github.com/tafreeman/agentic-runtime-platform/blob/main/CONTRIBUTING.md#6-when-to-write-an-adr)).
3. Once an epic is accepted for sprint, add a short implementation note to the epic entry before execution begins.
4. When the epic ships, add a new dated shipped section following the §N / §Na / §Nb naming pattern and link the final CHANGELOG entry.

An accepted roadmap entry is a promise to a reviewer, not to a user — shipping dates slip, scope narrows. Update the entry when reality changes.
