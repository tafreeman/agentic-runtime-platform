# Lab-vs-Canonical Divergence Audit — Final Report

## Verdict: STALE FORK (with one genuine un-upstreamed lab contribution)

The lab `agentic_v2` tree is a **pre-ADR-023-Phase-4 snapshot, roughly six months behind canonical**. It is *not* a healthy parallel branch: across six audited subsystems, the directionality is overwhelmingly **canonical-ahead**, with bidirectional divergence confined to a single research-tier feature (the Confidence-Index calculator) and ADR-013 deprecation scaffolding. The lab has also *actively diverged in a contract-breaking direction* (Pydantic `extra='forbid'`, `str`-typed `tier`, dropped `ErrorEvent`), which makes a symmetric merge unsafe.

### Mechanical baseline
- 630 canonical files / 531 lab files
- 313 identical, 209 content-divergent, **108 canonical-only**, **9 lab-only**
- The 108 canonical-only files cluster in security, observability, reliability, and ExecutionKit bridging. The 9 lab-only files are the CI calculator module + tests + runtime artifacts.

This 108-to-9 asymmetry is the headline: canonical added ~60KB+ of enterprise infrastructure the lab never received, while the lab accrued one library and four test files.

---

## Methodology

Per-subsystem analyses were each cross-examined by a 3-lens adversarial panel:
- **Reality lens** — is the claimed divergence real or an artifact of partial reads?
- **Directionality lens** — who is actually ahead, and did the analysis miss lab-ahead work?
- **Risk lens** — what breaks if both copies coexist?

This report **weights adversarially-confirmed findings and discards overturned ones**.

### Overturned (discarded) claims
- "Lab has hardened fail-closed sanitization middleware" — **REVERSED**: canonical holds the `_SANITIZER_NOT_CONFIGURED` sentinel + HTTP 503; lab passes through on `None` (lab is *less* hardened).
- `integrations/base.py` `Dict` import, `langchain.py` 508B delta — cosmetic.
- `rag/tracing.py` `perf_counter_ns` vs `monotonic` — functionally equivalent elapsed_ms.
- `contracts/sanitization.py` & `verification.py` docstring deltas — byte-identical files (false positives).
- `src/`, `feature_package/`, `final_feature_package/` — AI-generated codegen output staging, not platform capability (null-valued scaffolding).
- README/CONTRIBUTING title differences, `.gitignore` line — naming/noise.
- protocols.py TYPE_CHECKING — real but low functional impact (runtime behavior equivalent).

---

## Directionality by subsystem

| Subsystem | Net call | Why |
|---|---|---|
| server + integrations | **canonical-ahead** | 5 missing files (audit_log, replay_store, 2 middleware, metrics), stripped app factory |
| models | **canonical-ahead** | 4 missing files (weight_integrity, redis_state, ek_provider, ek_adapters); 43–57% smaller router/tracker |
| engine + adapters + core | **bidirectional → canonical** | timeout/cleanup/sort guardrails canonical; CI calculator lab |
| contracts + workflows + langchain | **bidirectional → canonical** | ADR-014 wire-format breaks canonical-ahead; CI calc + ADR-013 lab |
| middleware + rag + cli + settings | **canonical-ahead** | settings 6 config blocks, logging_config, RAG provider validation |
| tests | **bidirectional → canonical** | ~44 canonical-only test files; 4 lab-only Sprint 9 / ADR-013 tests |
| packaging + docs | **canonical-ahead** | newer deps + extras; lab has minor coverage tuning |

---

## What the lab is ahead on (un-upstreamed — would be LOST on discard)

1. **`agentic_v2/workflows/lib/ci_calculator.py`** (~182 lines, production code). Multidimensional research Confidence Index: 5 dimensions (coverage, source_quality, agreement, verification, recency); arithmetic + geometric aggregation; non-compensatory `check_gate()`; exponential `recency_decay()` with domain half-lives (ai_ml=90d, cloud=180d, languages=365d, academic=730d); frozen `GateResult` + `MappingProxyType` configs. Canonical explicitly removed/never had this. **Survived all three lenses in four separate subsystem panels.**
2. **`agentic_v2/workflows/lib/__init__.py`** — package marker.
3. **`tests/test_ci_calculator.py`** (~20KB, 80+ cases).
4. **`tests/test_multidimensional_scoring_wiring.py`** — Sprint 9 Task 9.2 delegation/backward-compat.
5. **`tests/test_json_extraction.py`** — JSON-extraction edge cases (fences, escapes, brace masking) absent in canonical.
6. **`tests/test_langchain_deprecation.py`** + 4 `@pytest.mark.skip(ADR-013)` markers — an EOL decision canonical has not yet adopted.
7. **Coverage rigor**: `precision=2` in pyproject (minor).

Everything else attributed to the lab was either overturned or is a stale subset of canonical.

---

## What canonical is ahead on (lab is missing/regressed)

- **Compliance/audit**: `audit_log.py` (SHA-256 hash chain) + auth audit events. SOC2/FedRAMP/HIPAA critical.
- **Supply-chain**: `weight_integrity.py` + `trusted_model_hashes.yaml` + schema. No tamper detection in lab.
- **Session durability**: `replay_store.py` (Redis/SQLite/in-memory). Lab loses state on restart.
- **Observability**: `integrations/metrics.py` (Prometheus), `middleware/metrics.py`, `middleware/tracing.py` (W3C traceparent), `logging_config.py`, settings `agentic_metrics` + 6 config blocks.
- **Distributed state**: `models/redis_state.py` + smart_router Redis/metrics/degraded callbacks.
- **Auth**: `auth_oidc.py` (OIDC JWT), `AuthThrottle` per-IP lockout, slowapi rate limiting.
- **ExecutionKit (ADR-023 Phase 4/5a)**: `ek_provider.py`, `ek_adapters.py`.
- **Reliability guardrails**: DAG wall-clock timeout + spans, NativeEngine checkpoint cleanup, deterministic `MemoryEntry` sort, `registry.validate_selected()`.
- **Provider compat**: rate_limit_tracker Gemini/GitHub/Azure/OpenAI-duration parsers.
- **Wire-format (ADR-014)**: `ErrorEvent`, `StepStartEvent.input`, int-typed `tier`, `TaskInput extra='ignore'`, `StepConfig dict[str,Any]` + `loop_max_expr`.
- **Multi-tenancy**: tenant isolation + tests.
- **Deps**: langchain-core 1.4 (vs 0.3), langgraph 1.2 (vs 0.2), cachetools<8, python-json-logger; `[mcp]/[redis]/[sqlite]/[postgres]/[devex]` extras.
- **DX**: `NoProviderConfiguredError`, README "Your First Run", setup-dev.ps1 helpers, `schemas/workflow.schema.json`.
- **Test coverage**: ~44 canonical-only test files mirroring all of the above.

---

## Risk if unreconciled

**HIGH and compounding.** Lab deployment loses audit trails, OIDC, throttling, and weight verification (compliance + attack surface). ADR-014 wire-format diverges — `ErrorEvent`/`tier`/`TaskInput` mismatches silently break any canonical↔lab event flow. No durable replay (session loss on restart), no DAG timeout (runaway-workflow DoS), no Redis CB coordination (thundering herd), checkpoint task leaks (FD/lock exhaustion). Observability blind. Stale `langchain-core 0.3` carries unpatched/incompatible APIs. Governance: 209 divergent + 108 canonical-only files guarantee wrong-tree edits, non-propagating security fixes, and an ever-widening gap. The lab is safe only as a sandboxed dev environment, never a production baseline.

---

## Reconciliation (ADR-023 compliant)

ADR-023: canonical is the single source of truth; the lab must **consume** the canonical runtime, not vendor a forked copy.

0. **Freeze** the lab's vendored `agentic_v2/` (read-only).
1. **Upstream lab-only work to canonical FIRST** (before any deletion): port `ci_calculator.py` + `lib/__init__.py` + the four lab-only tests; adopt the ADR-013 deprecation decision; optionally adopt `precision=2`. Land via reviewed PR with tests green.
2. **Re-base the lab as a dependency**: publish canonical `agentic_v2` as a versioned wheel (preferred) or pin via git-subtree/submodule; switch the lab's pyproject to depend on the canonical runtime; delete the lab's entire vendored `agentic_v2/` source tree. Keep only true lab-layer code that *imports* the runtime.
3. **Delete** stale lab pins and tracked runtime artifacts (`.agentic_memory.json`, `.coverage`, `ui/tsconfig.tsbuildinfo`).
4. **Guardrail**: CI check that fails on re-vendoring canonical source + an automated divergence detector.

Do **not** attempt a symmetric merge — it would re-introduce the lab's contract-breaking edits. The flow is strictly one-directional: upstream the CI calculator, then make the lab a consumer.

## Directionality

| Subsystem | Canonical-ahead | Lab-ahead | Bidirectional | Noise (overturned) | Net call |
|---|---|---|---|---|---|
| server + integrations (observability/audit/metrics/replay) | audit_log.py, replay_store.py, middleware/metrics.py, middleware/tracing.py, integrations/metrics.py, OIDC+rate-limit+metrics app factory, decoupled otel.py, step scoring | — (CI calculator lives elsewhere) | — | base.py `Dict` import, langchain.py 508B delta | **canonical-ahead** (lab is missing ~60KB enterprise infra; the "hardened sanitization" claim was REVERSED — canonical has the fail-closed sentinel, not lab) |
| models (routing/backends) | weight_integrity.py, redis_state.py, ek_provider.py, ek_adapters.py, rate_limit_tracker (Gemini/GitHub/Azure parsers), smart_router (Redis+metrics+degraded callbacks), LLMBackend ABC unification, backends canonicalization | — | — | none material | **canonical-ahead** (mid-ADR-023 migration; lab is a pre-Phase-4 snapshot) |
| engine + adapters + core | DAG timeout+span, ConditionalBranch/ParallelGroup, CancelledError propagation, registry.validate_selected(), NativeEngine checkpoint cleanup, MemoryEntry deterministic sort, NoProviderConfiguredError | ci_calculator.py + 3 test suites (research evaluation tier) | yes (core canonical-ahead; research lab-ahead) | protocols.py TYPE_CHECKING (functionally low-impact), Mapping import | **bidirectional, net canonical-ahead** (lab carries genuine un-upstreamed CI calculator) |
| contracts + workflows + langchain | ErrorEvent export+class, StepStartEvent.input, tier int-typing, TaskInput extra='ignore', loop_max_expr, dict[str,Any] inputs, feature_spec required, runner checkpoint helpers | ci_calculator lib + tests, ADR-013 deprecation tests | yes | sanitization.py & verification.py docstrings (identical files) | **bidirectional, net canonical-ahead** (wire-format breaks per ADR-014 are acute; lab also actively diverged via extra='forbid') |
| middleware + rag + tools + cli + settings | settings.py (6 config blocks: OTEL/OIDC/audit/Redis/replay/checkpointing), logging_config.py, RAG embedding provider validation, CLI test-patch hooks, error dedup | ci_calculator module | — | rag/tracing.py timing (perf_counter_ns vs monotonic — functionally equivalent) | **canonical-ahead** |
| tests (behavioral drift signal) | ~44 canonical-only test files: audit_log, weight_integrity, redis_circuit_breaker, auth_oidc, auth_throttle×2, otel_metrics, json_logging, replay_store, traceparent, tenant_isolation, model canonicalization, ek_adapters | test_ci_calculator, test_multidimensional_scoring_wiring, test_json_extraction, test_langchain_deprecation; ADR-013 skips; WorkflowState import | yes | none | **bidirectional, net canonical-ahead** (lab ~6mo behind on security/observability; carries Sprint 9 + ADR-013 work) |
| packaging + docs + top-level | pyproject deps (langchain-core 1.4 vs 0.3, langgraph 1.2 vs 0.2, cachetools<8, python-json-logger) + extras (mcp/redis/sqlite/postgres/devex), NoProviderConfiguredError, agentic_metrics, setup-dev.ps1 helpers, schemas/*.json | ci_calculator lib, coverage precision=2, lab-specific coverage omits | yes (minor) | src/, feature_package/, final_feature_package/ (generated codegen artifacts — overturned as low-materiality), .gitignore line, README/CONTRIBUTING titles | **canonical-ahead** (lab's lib + coverage tuning are minor) |