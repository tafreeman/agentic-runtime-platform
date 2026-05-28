# ADR Index — agentic-workflows-v2

> **Last updated:** 2026-05-24
> **Total ADRs:** 19 (13 Accepted, 5 Proposed, 1 Superseded)

---

## Quick-Access Deck

| ADR | Title | Status | File |
|-----|-------|--------|------|
| **001** | Dual Execution Engine (LangGraph vs. Kahn's DAG) | Accepted | [ADR-001-002-003](ADR-001-002-003-architecture-decisions.md) |
| **002** | SmartModelRouter Circuit-Breaker Hardening | Accepted | [ADR-001-002-003](ADR-001-002-003-architecture-decisions.md) |
| **003** | Deep Research Supervisor / CI Gating | Superseded → 007 | [ADR-001-002-003](ADR-001-002-003-architecture-decisions.md) |
| **007** | Multidimensional Classification Matrix & Stop Policy | Proposed | [ADR-007](ADR-007-classification-matrix-stop-policy.md) |
| **008** | Testing Approach Overhaul (Value Taxonomy) | Accepted | [ADR-008](ADR-008-testing-approach-overhaul.md) |
| **009** | Scoring Enhancements (Exponential Decay, Lexicographic) | Accepted | [ADR-009](ADR-009-scoring-enhancements.md) |
| **010** | Commit-Driven A/B Eval Harness Methodology | Proposed | [ADR-010](ADR-010-eval-harness-methodology.md) |
| **011** | Eval Harness API & Interface Design | Proposed | [ADR-011](ADR-011-eval-harness-api-interface.md) |
| **012** | UI Evaluation Hub & A/B Comparison | Proposed | [ADR-012](ADR-012-ui-evaluation-hub.md) |
| **014** | Pydantic Discriminated Union as Execution Event Wire Format | Accepted | [ADR-014](ADR-014-pydantic-wire-format.md) |
| **015** | SLO Rolling Window Stored in Git | Accepted | [ADR-015](ADR-015-slo-in-git-rolling-window.md) |
| **016** | GitHub Models via `GITHUB_TOKEN` as Default E2E LLM Provider | Accepted | [ADR-016](ADR-016-github-token-as-default-e2e-llm.md) |
| **017** | Dataset Identifiers as Query Parameters, Not Path Segments | Accepted | [ADR-017](ADR-017-dataset-id-query-params.md) |
| **018** | API Rate Limiting and Per-IP Auth Throttle | Accepted | [ADR-018](ADR-018-api-rate-limiting-and-auth-throttle.md) |
| **019** | DAG Executor Top-Level Timeout Watchdog | Accepted | [ADR-019](ADR-019-dag-executor-top-level-timeout.md) |
| **020** | LangChain Adapter Eager Validation at FastAPI Startup | Accepted | [ADR-020](ADR-020-langchain-adapter-eager-validation.md) |
| **021** | JWT OIDC Authentication for API Routes | Accepted | [ADR-021](ADR-021-jwt-oidc-authentication.md) |
| **022** | Tenant-Scoped Run and Dataset Isolation | Accepted | [ADR-022](ADR-022-tenant-isolation.md) |
| **023** | Path-First File I/O Contracts for Multi-Step Workflows | Proposed | [ADR-023](ADR-023-path-first-workflow-io-contracts.md) |

**Note:** ADRs 004-006 and 013 were never created or were withdrawn. The numbering gaps are intentional and should not be reclaimed.

---

## Lineage Chains

```
Engine Domain:
  ADR-001 (Dual Engine) ─── standalone

Models Domain:
  ADR-002 (Circuit Breaker) ─── standalone
  ADR-016 (GitHub Models default) ─── standalone (CI policy)

Research Domain:
  ADR-003 (CI Gating) ──superseded-by──> ADR-007 (Classification Matrix)
                                              └──extended-by──> ADR-009 (Scoring Enhancements)

Testing Domain:
  ADR-008 (Test Value Taxonomy) ─── standalone

Evaluation Domain:
  ADR-010 (Harness Methodology) ──extended-by──> ADR-011 (API Interface)
                                                      └──extended-by──> ADR-012 (UI Hub)

Observability Domain:
  ADR-014 (Event Wire Format) ─── standalone
  ADR-015 (SLO Rolling Window) ─── standalone

Evaluation Surface Domain:
  ADR-017 (Dataset ID Query Params) ─── standalone (ratification)

Security / Reliability Domain (Sprint 1):
  ADR-018 (Rate Limiting + Auth Throttle) ─── standalone; cluster mode deferred to Sprint 2
  ADR-019 (DAG Top-Level Timeout) ─── standalone; composes additively with step-level timeouts
  ADR-020 (Adapter Eager Validation) ─── standalone; narrows ADR-001 startup behavior
  ADR-021 (JWT OIDC Auth) ─── extends ADR-018 auth boundary; preserves API-key fallback
  ADR-022 (Tenant Isolation) ─── extends ADR-021 identity boundary with data scoping

Workflow Authoring Domain:
  ADR-023 (Path-First File I/O Contracts) ─── extends ADR-014 wire-format discipline into step handoff artifact contracts
```

---

## Implementation Status

| ADR | Decision | Implemented | Tests | Last Audit |
|-----|:---:|:---:|:---:|---|
| 001 | Yes | ~65% | Protocol + adapter tests | 2026-03-17 |
| 002 | Yes | ~80% | Extensive router/rate-limit tests | 2026-03-17 |
| 003 | Superseded | Legacy fragments only | Legacy scoring tests | 2026-03-17 |
| 007 | Yes | ~50% | Unit + wiring tests | 2026-03-17 |
| 008 | Yes | ~90% | Phase 0-3 complete: cleanup (-23), +539 new tests | 2026-03-17 |
| 009 | Yes | ~85% | CI + multidimensional scoring tests | 2026-03-17 |
| 010 | Proposed | ~10% (primitives only) | Reused primitives only | 2026-03-17 |
| 011 | Proposed | ~15% (partial eval infra) | Adjacent route/UI helpers only | 2026-03-17 |
| 012 | Proposed | ~10% (existing evaluations table only) | None specific | 2026-03-17 |
| 014 | Yes | 100% (contracts + schema-drift gate) | test_schemas.py, golden output | 2026-04-22 |
| 015 | Yes | 100% (rolling windows, nightly gate) | slo measurement tests | 2026-04-22 |
| 016 | Yes | 100% (GITHUB_TOKEN wiring, fork-skip guards) | CI workflow invariants | 2026-04-22 |
| 017 | Yes | 100% (shape already live; ADR ratifies) | Sample-list route tests in `tests/server/` | 2026-04-22 |
| 018 | Yes | 100% (slowapi middleware + AuthThrottle) | Rate-limit + throttle unit tests | 2026-05-14 |
| 019 | Yes | 100% (asyncio.wait_for + BFS cascade) | DAG executor timeout tests | 2026-05-14 |
| 020 | Yes | 100% (validate_selected + lifespan hook) | Adapter registry startup tests | 2026-05-14 |
| 021 | Yes | 100% (OIDC JWT middleware + API-key fallback) | OIDC auth middleware tests | 2026-05-18 |
| 022 | Yes | 100% (tenant context + scoped runs/datasets) | Tenant isolation + OIDC claim tests | 2026-05-18 |
| 023 | Proposed | ~20% (pilot authored; rollout pending) | Pilot validation in workflow tests | 2026-05-24 |

---

## Supporting Documents

| Document | Description |
|----------|-------------|
| [RAG-pipeline-blueprint.md](RAG-pipeline-blueprint.md) | Companion blueprint (not a formal ADR) — LanceDB + Voyage 4 hybrid RAG design with cross-encoder reranking, async-first contracts, and provider abstraction via LiteLLM. Informs the `rag/` implementation in the main runtime. |

_Previously listed supporting audit files were removed during the 2026-04-22 docs cleanup because they had fallen out of sync with the ADRs themselves. This index is now the canonical source._
