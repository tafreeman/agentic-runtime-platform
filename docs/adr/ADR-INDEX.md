# ADR index — Agentic Runtime Platform

Architecture Decision Records capture the load-bearing choices behind the
Agentic Runtime Platform — what was decided, what alternatives were rejected,
and what it costs. Every decision is enumerated in the deck below, each with its
own status (004–006 and 013 are intentionally unused number gaps). If you read
only five:

- **[ADR-001](ADR-001-002-003-architecture-decisions.md)** — the dual execution engine (LangGraph adapter alongside the native Kahn's-DAG executor).
- **[ADR-002](ADR-001-002-003-architecture-decisions.md)** — SmartModelRouter circuit-breaker hardening (three-state breaker, adaptive cooldowns, bulkheads).
- **[ADR-014](ADR-014-pydantic-wire-format.md)** — the Pydantic discriminated-union wire format that every event contract and the drift CI gate build on.
- **[ADR-023](ADR-023-executionkit-runtime-contract-relationship.md)** — how the runtime relates to the external ExecutionKit kernel (single `executionkit` package).
- **[ADR-042](ADR-042-agentic-evalkit-adoption.md)** — the in-flight sliced migration from in-tree `agentic-v2-eval` to the external `agentic-evalkit` framework.

---

## Quick-access deck

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
| **023** | ExecutionKit ↔ Runtime Execution-Contract Relationship (Option A′: single `executionkit` package) | Accepted | [ADR-023](ADR-023-executionkit-runtime-contract-relationship.md) · [working notes](drafts/README.md) |
| **024** | Expression Evaluation via AST Interpreter (eliminate `eval()`) | Accepted | [ADR-024](ADR-024-expression-evaluator-ast-sandbox.md) |
| **025** | SDK `Task`-Tool Orchestration (counterpart to the asyncio orchestrator) | Accepted | [ADR-025](ADR-025-sdk-task-orchestration.md) |
| **026** | `--resume` / `fork_session` and the summary-seeded-session tradeoff | Accepted | [ADR-026](ADR-026-resume-vs-summary-session.md) |
| **027** | Forced / `any` / `auto` `tool_choice` and cross-role `verify_fact` | Accepted | [ADR-027](ADR-027-forced-tool-choice.md) |
| **028** | Tool descriptions are the primary tool-selection mechanism | Accepted | [ADR-028](ADR-028-tool-descriptions-as-selection-mechanism.md) |
| **029** | Adaptive decomposition (investigate → per-file → cross-file) | Accepted | [ADR-029](ADR-029-adaptive-decomposition.md) |
| **030** | SSRF guard pins the connection target in both modes (opt-out too) | Accepted | [ADR-030](ADR-030-unconditional-connection-pinning.md) |
| **031** | Native DAG as Single Supported Execution Engine (salvaged from `agentic-systems-lab`; single-engine proposal NOT adopted — the LangGraph adapter is retained) | Superseded | [ADR-031](ADR-031-native-dag-single-engine.md) |
| **032** | Extract Scoring/Judge Domain into `agentic_v2.scoring` (break the server "god package", fix dependency direction) | Accepted | [ADR-032](ADR-032-extract-scoring-package.md) |
| **033** | Defensive Import-Time Project-Root Resolution in Scoring Eval-Config Loader | Accepted | [ADR-033](ADR-033-eval-config-project-root-resolution.md) |
| **034** | Path-First File I/O Contracts for Multi-Step Workflows | Proposed | [ADR-034](ADR-034-path-first-workflow-io-contracts.md) |
| **035** | RAG Pipeline Architecture (LanceDB + Voyage 4 Hybrid Search) | Accepted | [ADR-035](ADR-035-rag-pipeline-architecture.md) |
| **036** | `OllamaBackend` uses the official `ollama` client (contained SDK swap) | Accepted | [ADR-036](ADR-036-ollama-sdk-backend.md) |
| **037** | Live Ollama model discovery via the raw REST API (`/api/tags`+`/api/ps`, cloud via `remote_host`) | Accepted | [ADR-037](ADR-037-live-ollama-model-discovery.md) |
| **038** | Live discovery for LM Studio (native `/api/v0/models`, multi-port) and ONNX (multi-root `genai_config.json`) local models | Accepted | [ADR-038](ADR-038-lmstudio-onnx-discovery.md) |
| **039** | Live model discovery for keyed cloud providers (OpenAI / Anthropic / Gemini / GitHub Models) | Accepted | [ADR-039](ADR-039-cloud-model-discovery.md) |
| **040** | Curated single-source model registry (one YAML + loader feeds both engines; reconciles divergent tier chains) | Accepted | [ADR-040](ADR-040-curated-model-registry.md) |
| **041** | Bounded human-approval gate timeout — a hung ApprovalProvider fails closed (DENIED) within a configurable bound (default 30 min) instead of blocking the gated tool indefinitely | Accepted | [ADR-041](ADR-041-approval-gate-timeout.md) |
| **042** | Adopt `agentic-evalkit` as ARP's evaluation framework, superseding in-tree `agentic-v2-eval`, via a sliced migration (A: dependency, B: bridge module, C: cut over step_scoring, D: deprecate+delete agentic-v2-eval, E: CI cutover); evalkit stays optional until it has a public remote | Proposed | [ADR-042](ADR-042-agentic-evalkit-adoption.md) |
| **043** | Configurable workflow UI: per-step node config (model params / persona / observers) in the YAML schema, a JSON UI-settings store for provider endpoints + tier reranks (below env-var pins in routing precedence), self-describing DAG edges, and replay-based run comparison (`POST /api/eval/compare`) | Accepted | [ADR-043](ADR-043-configurable-workflow-ui.md) |
| **044** | Evaluation scoring visibility (issue #172): loader-side `golden_output_path` resolution inlined as `golden_output_text`, loud+typed judge skips (`judge_skipped`/`judge_skip_reason`/`judge_skip_code`, `expected_text_present`, opt-in `judge_required` → `JudgeRequiredError` scoped to the evaluation), replay sample rehydration with task_id verification, and a config-backed efficiency SLO band | Accepted | [ADR-044](ADR-044-evaluation-scoring-visibility.md) |
| **045** | `BuildAppTool` requires human approval — the `build_app` install/build/test shell tool joins the fail-closed HITL gate (it was ungated, contradicting the shell-approval claim) | Accepted | [ADR-045](ADR-045-build-app-approval-gate.md) |
| **046** | Response-path masking of high-entropy-only secrets — an opaque token matching no named pattern is now masked + classified REDACTED outbound (was CLEAN + unmasked); measured FP surface keeps structured hex/UUIDs below threshold | Accepted | [ADR-046](ADR-046-response-entropy-masking.md) |
| **047** | Tool approval gate enforced structurally in `BaseTool.execute` via `__init_subclass__` (was per-dispatch-site convention, bypassable by a direct `.execute()`/`__call__`/registry call); 4 pre-gates removed for a single gate; the separate LangChain `@tool` system keeps its manual gate | Accepted | [ADR-047](ADR-047-structural-tool-approval-gate.md) |
| **048** | Process-wide token budget on the shared LLM client — `AGENTIC_TOKEN_BUDGET` now arms `LLMClientWrapper.set_budget()` on `get_client()`'s singleton (previously a dead setter with zero production callers); cumulative across the process, not per-run; skipped under `AGENTIC_NO_LLM` | Accepted | [ADR-048](ADR-048-process-wide-token-budget.md) |
| **050** | SSE chat playground endpoint (`POST /api/chat`, discriminated-union `ChatStreamEvent`) and OpenRouter as a first-class provider — joins the ADR-014 drift pipeline; rides `StreamingResponse` not `/ws`; always HTTP 200 with in-stream classified errors; bypasses `SmartModelRouter`/tier selection by design; OpenRouter gets cached (300s TTL) + curated discovery with no `model_registry.yaml` tier-chain entry (mirrors the NVIDIA precedent) | Accepted | [ADR-050](ADR-050-chat-playground-sse-and-openrouter-provider.md) |
| **051** | Local-first Ollama cloud execution routing — `build_ollama_model` serves models present in the local daemon's `/api/tags` from `OLLAMA_BASE_URL` and routes models absent locally to `ollama.com` with Bearer `OLLAMA_API_KEY` (no key → unchanged local-only), closing ADR-037's listing-vs-execution gap; registry rungs repointed at ids providers actually list (`openai:gpt-4o*` → `nvidia:*` since `OPENAI_BASE_URL` is NIM-aliased in this deployment; dated sonnet → undated alias; local tails → models actually pulled) | Accepted | [ADR-051](ADR-051-ollama-cloud-execution-routing.md) |
| **052** | `memoryctl` deterministic maintenance core for agent memory (`agentic_v2/memoryctl/`, Typer CLI + `memoryctl` script) — zero LLM calls; harvest-then-regenerate `MEMORY.md` (one harvest file per run, never blind-overwrite because Claude Code auto-memory writes without the advisory lock); doc staleness takes the *older* of git date and mtime so import commits can't launder stale content; `verify:` frontmatter commands run `shell=True` (hook-equivalent trust domain); run rotation refuses to archive episode data not yet reduced into `registry/stats.json` | Accepted | [ADR-052](ADR-052-memoryctl-deterministic-maintenance-core.md) |

**Note:** ADRs 004-006 and 013 were never created or were withdrawn; those numbering gaps are intentional and should not be reclaimed. (The decision once numbered ADR-013 in the `agentic-systems-lab` fork was salvaged into this repo as **ADR-031**, not as 013.) ADR-023 working notes (migration plan, phase tracker, finish plan, divergence audit, preservation matrix) were moved to [`drafts/`](drafts/README.md) on 2026-06-17 to resolve a naming collision; the canonical decision record remains at ADR-023.

---

## Lineage chains

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
  ADR-024 (AST Expression Interpreter) ─── standalone; eliminates eval() in the engine condition evaluator

Execution Kernel Domain:
  ADR-023 (EK as OpenAI-message-format kernel, Option A′) ─── builds on ADR-002 (router) + ADR-014 (additive-only wire format); single `executionkit` package; `executionkit-contracts` retired; aligns runtime LLMBackend onto EK LLMProvider via ek_adapters bridge

Workflow I/O Domain:
  ADR-034 (Path-First I/O Contracts) ─── extends ADR-014 wire-format discipline to file artifact handoffs

RAG / Retrieval Domain:
  ADR-035 (RAG Pipeline Architecture) ─── builds on ADR-014 (Pydantic contracts) + ADR-002 (SmartModelRouter) + ADR-019 (DAG timeout); promoted from RAG-pipeline-blueprint.md

Eval / Scoring Domain:
  ADR-032 (Extract Scoring Package) ─── standalone; removes server "god package" coupling
  ADR-033 (Eval-Config Project-Root Resolution) ─── extends ADR-032; import-time path fix
  ADR-042 (Adopt agentic-evalkit, sliced migration) ─── supersedes agentic-v2-eval;
    builds on ADR-032's scoring package as the landing site for the new bridge module;
    follows the external-package precedent set by ADR-023 (ExecutionKit)
```

---

## Implementation status

> **Scope note:** This table covers the ADRs that have received a formal
> implementation audit: 001–024, 032–038, and 042. ADRs 025–031 and 039–041
> have not yet been audited and are intentionally absent — their absence is
> not a statement about implementation state.

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
| 019 | Yes | 100% (asyncio.timeout + BFS cascade) | DAG executor timeout tests | 2026-05-14 |
| 020 | Yes | 100% (validate_selected + lifespan hook) | Adapter registry startup tests | 2026-05-14 |
| 021 | Yes | 100% (OIDC JWT middleware + API-key fallback) | OIDC auth middleware tests | 2026-05-18 |
| 022 | Yes | 100% (tenant context + scoped runs/datasets) | Tenant isolation + OIDC claim tests | 2026-05-18 |
| 023 | Yes | F0–F5 landed (Option A′: single `executionkit` package; `executionkit-contracts` retired; B-1/B-2 fixed; `AGENTIC_EK_PROVIDER` opt-in) | 81 EK bridge tests green; flag-OFF floor held | 2026-06-01 |
| 024 | Yes | 100% (AST interpreter replaces eval() in the engine condition evaluator) | test_expressions.py (128 cases incl. dunder/DoS vectors) | 2026-06-13 |
| 032 | Yes | 100% (`agentic_v2/scoring/` package live) | scoring unit tests | 2026-06-17 |
| 033 | Yes | 100% (import-time root resolution in eval_config.py) | scoring eval-config tests | 2026-06-17 |
| 034 | Proposed | 0% (pilot on fullstack_generation workflow pending) | — | 2026-06-17 |
| 035 | Yes | 100% (`agentic_v2/rag/` thirteen modules live) | rag/ unit + retrieval tests | 2026-06-17 |
| 036 | Yes | 100% (`OllamaBackend` on `ollama.AsyncClient`; `ollama` promoted to core dep) | test_ollama_canonical.py (SDK-stubbed) | 2026-06-21 |
| 037 | Yes | 100% (`models/ollama_discovery.py` raw probe; merged into `enumerate_known_models`; UI badges) | test_ollama_discovery.py, test_langchain_models_unit.py, ModelFinderPage.test.tsx | 2026-06-21 |
| 038 | Yes | 100% (`models/local_discovery.py` LM Studio `/v1/models` + ONNX `genai_config.json`; merged into `enumerate_known_models`) | test_local_discovery.py, test_langchain_models_unit.py | 2026-06-21 |
| 042 | Partial | Slice B only: `agentic_v2/scoring/evalkit_bridge.py` (additive, not wired into `step_scoring.py`) | test_evalkit_bridge.py (skips without evalkit installed) | 2026-07-03 |

---

## Supporting documents

| Document | Description |
|----------|-------------|
| [RAG-pipeline-blueprint.md](RAG-pipeline-blueprint.md) | Research blueprint and full implementation rationale for ADR-035. Retained alongside the formal ADR for deep reference. |
| [drafts/](drafts/README.md) | Superseded ADR-023 working notes (migration plan, phase tracker, finish plan, divergence audit, preservation matrix). Not formal ADRs; retained for historical reference. |

_Previously listed supporting audit files were removed during the 2026-04-22 docs cleanup because they had fallen out of sync with the ADRs themselves. This index is now the canonical source._
