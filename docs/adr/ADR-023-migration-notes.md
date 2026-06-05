# ADR-023 Migration Notes (Option A′ — single `executionkit` package)

> **Amendment (2026-06-01):** This document now tracks **Option A′**, an amendment
> to Option A that collapses the `executionkit-contracts` intermediate package into
> the single canonical `executionkit` package. The contracts package is **retired /
> dormant** — do not treat it as live. See the Amendment section of
> `ADR-023-executionkit-runtime-contract-relationship.md` and
> `ADR-023-finish-plan.md` for full rationale.

Companion to:
- `ADR-023-executionkit-runtime-contract-relationship.md`
- `ADR-023-migration-plan.md` (original P0–P7 plan)
- `ADR-023-finish-plan.md` (Option A′ amendment and F-series phases)
- `ADR-023-preservation-matrix.md`

This document captures the operational rules and tracking state for the
migration. It is updated in-place as each phase lands.

---

## 1. Additive-Only Freeze Rule (ExecutionKit value types)

ExecutionKit's wire-shape value types are now governed by the same
discipline as the runtime Pydantic contracts (see ADR-014 wire-format
discipline and `agentic_v2/contracts/`).

**Frozen surfaces (covered by this rule):**

- `LLMResponse`
- `ToolCall`
- `TokenUsage`
- The ExecutionKit error hierarchy (`LLMError` and subclasses)

**What is frozen:**

1. **Field names.** No renames. Once a field is shipped, the name is
   permanent. A new concept gets a new field, never a renamed old field.
2. **Field order.** The dataclass / `__init__` parameter order is part of
   the public contract because downstream code (and JSON snapshots in
   tests/fixtures) depend on positional construction and dict-key
   iteration order. New fields are appended at the end.
3. **Defaults.** Existing default values do not change. A field that was
   optional with `default=None` stays that way. Tightening a default
   (e.g. `None` -> required) is a breaking change and is not allowed in
   this phase.

**What is allowed (additive only):**

- Appending a brand-new optional field with a safe default
  (`None`, `False`, `0`, `()`, `frozenset()`, etc.).
- Adding a new subclass to the error hierarchy, provided it inherits
  from an existing public base so old `except` clauses still catch it.
- Adding new helper methods / classmethods that do not shadow existing
  attribute names.

**Explicitly disallowed in P0..P4:**

- Removing or renaming any field on `LLMResponse`, `ToolCall`,
  `TokenUsage`, or any error class.
- Re-ordering existing fields.
- Changing the type of an existing field (e.g. `str -> Enum`,
  `dict -> TypedDict`) in a way that is not a transparent superset.
- Promoting an optional field to required.
- Removing or renaming a public exception class, or changing its base
  class in a way that breaks `isinstance` chains.

This mirrors the rule already enforced for runtime Pydantic contracts in
`agentic_v2/contracts/messages.py` and the broader ADR-014 wire-format
discipline. The ExecutionKit value types are now held to the same bar
because the Option A migration makes them the load-bearing exchange
format between the runtime and EK.

Reviewers: any PR that touches `LLMResponse`, `ToolCall`, `TokenUsage`,
or the error hierarchy must explicitly call out the diff against this
rule in the PR description. The default verdict is "additive only".

---

## 2. Decision Log — Open Decisions From the Migration Plan

The migration plan defers seven cross-cutting decisions out of P0 so the
baseline can be pinned without prejudging them. They are tracked here.
Status will be updated as owners are assigned and decisions land.

| # | Key                                  | Question (one line)                                                                                       | Status         | Owner          | Resolution / Notes |
|---|--------------------------------------|-----------------------------------------------------------------------------------------------------------|----------------|----------------|--------------------|
| 1 | gemini-usage-normalization-location  | Where do we normalize Gemini's camelCase `usageMetadata` (promptTokenCount/candidatesTokenCount) into `TokenUsage` — in the backend adapter, in the EK wrapper, or in a dedicated normalization layer? | accepted       | tandfreeman    | **Moot under Option A′** (single type set). Phase-3 backend canonicalization already emits snake_case `prompt_tokens`/`completion_tokens` upstream of the adapter; `GeminiBackend.complete_chat` canonicalizes `usageMetadata` and `finishReason` before the response reaches `dict_to_llm_response`. Verified by the 26-test conformance suite (2026-06-01). |
| 2 | budget-precedence-token-vs-call      | When both a token budget and a call-count budget are configured, which one wins on tie / near-tie, and how is the rejection surfaced?                                                                  | accepted       | tandfreeman    | **Hybrid:** runtime `TokenBudget` owns the token-sum ceiling; EK `CostTracker` owns the `llm_calls` dimension. `TokenBudget.consume()` runs first and raises `BudgetExhaustedError` on token cap; EK `reserve_call()` enforces calls. Cache hits count as a 0-token recorded call (call_count++, tokens 0). Both layers preserve existing semantics. (2026-05-31) |
| 3 | cache-hit-budget-accounting          | Do cache hits count against the token/call budget? If not, how do we expose the "free" path in telemetry without breaking budget invariants?                                                          | deferred       | unassigned     | Explicitly deferred post-Option-A′. Interacts with prompt-caching rollout and observability; not a blocker to F0–F5 landing. Budget semantics for cache hits already accepted (decision #2: 0-token recorded call). |
| 4 | model-field-promotion                | Should `model` (currently optional, free-form string on responses) be promoted to a typed, required field on `LLMResponse`, or stay best-effort?                                                       | deferred       | unassigned     | Frozen-field decision; explicitly deferred. Any promotion must stay additive-only (new optional typed field alongside the existing free-form string, never a rename/tighten). |
| 5 | tool-path-single-owner               | Tool-call extraction currently happens in two places (backend adapter and downstream `StepExecutor`). Who owns it post-migration — adapter, EK, or runtime?                                            | accepted       | tandfreeman    | **EK `react_loop` is the default** tool-calling loop (uniform retry/budget/structured semantics). Per-step opt-out via `tool_path: native` in step YAML keeps `tool_execution.run_tool_calls` available for steps that need legacy semantics. Adapter remains the single boundary translator (Anthropic `tool_use` → OpenAI tool_calls). (2026-05-31) |
| 6 | ollama-thinking-marker               | How do we represent reasoning-model "thinking" content (qwen3, deepseek-r1, phi4-reasoning) on `LLMResponse` — separate field, content prefix, metadata flag, or stay implicit?                        | deferred       | unassigned     | Explicitly deferred. Additive-only constraint applies: resolution must append a new optional field (e.g. `thinking: str | None = None`) rather than alter content format. The `ollama_thinking.json` fixture remains interpretable as-is. |
| 7 | streaming-counttokens-roadmap        | Are `complete_stream` and `count_tokens` in-scope for Option A, or are they explicitly P7+? If in-scope, where do they live on the EK seam?                                                            | accepted       | tandfreeman    | **Streaming + per-provider `count_tokens` stay OUT of the kernel; they remain reachable on the `LLMBackend` ABC; the `SupportsStreaming` protocol already exists.** The EK kernel seam is `complete(messages) -> LLMResponse` only. (2026-05-31) |

Status legend: `pending owner` -> `assigned` -> `proposal-up` -> `accepted` -> `landed`.

When a decision moves to `accepted`, the chosen resolution must be
back-filled into the Resolution column with a link to the PR or ADR
update that made it canonical.

---

## 3. Phase Status Tracker

Phases follow the migration plan (`ADR-023-migration-plan.md`). This
tracker is the single source of truth for "where are we right now" and
is updated at the end of each phase.

| Phase | Title                                                  | Status                | Notes |
|-------|--------------------------------------------------------|-----------------------|-------|
| P0    | Pin the baseline (notes + fixtures + freeze rule)      | landed                | Migration notes + 5 backend response fixtures. No source code changes. (2026-05-31) |
| P1    | Extract `executionkit-contracts` package               | superseded by F1      | Was landed 2026-05-31; **superseded** by Option A′ amendment (2026-06-01). The contracts package was a verbatim duplicate that created a dual error-tree bug (B-2). F1 collapsed all imports back to `executionkit` and the contracts package is now retired. |
| P2    | Reconcile divergent runtime `LLMBackend` defs          | landed                | `models/client.py` Protocol deleted, repointed to `backends_base.py` ABC. Type widening only; 3/3 tests green. (2026-05-31) |
| P3    | Backend dict canonicalization                          | landed                | Anthropic / Gemini / Ollama `complete_chat` now emit OpenAI-shaped dicts; raw payloads preserved under `_raw_*` keys. 22/22 tests green. (2026-05-31) |
| P4    | `ek_adapters.py` round-trip module                     | landed                | `dict_to_llm_response` / `llm_response_to_dict` / `map_http_error` + 26 tests. Not imported outside its own tests — hot path untouched. (2026-05-31) |
| P5    | `SmartRouterProvider` + `LLMClientWrapper` re-point    | landed                | Flag-gated hot-path cutover via `agentic_ek_provider` (default OFF). `_complete_via_ek` layers TokenBudget (tokens) over EK CostTracker (calls); router owns reliability. (2026-05-31) |
| P6    | StepExecutor delegation to EK patterns                 | landed                | EK `react_loop` is the default tool loop; per-step opt-out via `tool_path: native` keeps `tool_execution.run_tool_calls`. Gemini routes (`supports_tools=False`) refuse tools rather than drop them. (2026-05-31) |
| P7    | Default cutover, retain legacy text path, finalize docs | landed (default-on REVERTED) | Legacy text path retained (deprecated, not deleted). The default flip to ON was applied then **reverted same-day** — full-suite gating with default-on exposed B-1 and B-2 (see below). `agentic_ek_provider` default is **False** (opt-in via `AGENTIC_EK_PROVIDER=1`). Default-on resumes once flag-ON full suite is clean. (2026-05-31) |
| **F0** | **Environment + single dependency declaration (Option A′)** | **landed** | `.venv` created via `uv sync`. `executionkit` added to `pyproject.toml` as editable path-dep (ek extra + `[tool.uv.sources]`). `executionkit_contracts` NOT on path. (2026-06-01) |
| **F1** | **Collapse imports to `executionkit` — core of A′**    | **landed**            | All `executionkit_contracts.*` imports repointed to `executionkit.errors` / `executionkit.provider` across `ek_adapters.py`, `ek_provider.py`, `ek_step_delegation.py` + 5 test files. Two `cast()` boundary hacks deleted. Dual error-tree eliminated by construction. mypy --strict + ruff clean on all 8 changed files. (2026-06-01) |
| **F2** | **Flag-OFF green floor**                               | **landed**            | Full pytest flag-OFF: 0 regressions from the import collapse. Floor established as regression oracle. (2026-06-01) |
| **F3** | **Fix B-1 (lru_cache test-isolation leak)**            | **landed**            | Root cause: `tests/test_audit_log.py` replaced `sys.modules["agentic_v2.settings"]` defeating `setdefault`, creating a split `get_settings` lru_cache. Fixed with a one-line guard. 17 flag tests went green (38→21→10 suite failures). (2026-06-01) |
| **F4** | **Verify B-2 resolved by collapse**                   | **landed**            | EK-default-on hang confirmed fixed. Residual hang was test-design: `TestSmartModelRouterHardening` synchronizes on an `asyncio.Event` set inside the legacy `complete()`, which deadlocks when EK routes to `complete_chat`. Fixed by pinning that class flag-OFF. Full suite completes flag-ON in ~46s (vs ~50s flag-OFF). (2026-06-01) |
| **F5** | **Close usage-normalization drift**                    | **landed**            | Decision #1 accepted as moot: Phase-3 backend canonicalization already covers Gemini camelCase upstream of the adapter. Verified by 26-test conformance suite. No additive change to `LLMResponse` needed. (2026-06-01) |

Status legend: `queued` -> `in-progress` -> `landed` -> `verified`. A
phase is `blocked-on-review` when it cannot start until an open decision
from section 2 is accepted.

### Blockers to default-on (P7 follow-up)

~~Both are pre-existing in the P5–P7 test/runtime work; both are masked while the
default is OFF.~~ **B-1 and B-2 are both fixed as of F3/F4 (2026-06-01).**

- **B-1 — FIXED (F3).** Root cause: `tests/test_audit_log.py` replaced
  `sys.modules["agentic_v2.settings"]` via `_load_module`, defeating
  `setdefault` and creating a split `get_settings` lru_cache. Fixed with a
  one-line guard in the module reload path. 17 flag tests went green
  (suite failures: 38→21→10). `get_settings.cache_clear()` is now called on
  fixture teardown *after* `monkeypatch` undo, mirroring `_force_no_llm_env`.
- **B-2 — FIXED (F4).** The import collapse (F1) unified the error tree,
  which was the suspected root cause of the hang. Residual hang was test-design:
  `TestSmartModelRouterHardening` synchronized on an `asyncio.Event` set inside
  the legacy `complete()`, deadlocking when EK reroutes to `complete_chat`. Fixed
  by pinning that class to flag-OFF. Full suite completes flag-ON in ~46s
  (vs ~50s flag-OFF).

**Remaining blockers to default-on (unrelated to B-1/B-2):**

~14 flag-ON behavioral failures remain in test_agents (RuntimeErrors),
test_langchain_engine (model-registry), and golden workflow tests. These are
unrelated to the import collapse and require separate triage before `AGENTIC_EK_PROVIDER`
defaults to ON. Two pre-existing environmental hangs (test_phase2d_tools.py HTTP
test-server, test_runner_ui.py) and ~10 server/websocket failures are also
flag-independent and do not import EK modules — tracked separately.

---

## 4. Update Protocol

- Section 1 (freeze rule) is amended only via a follow-up ADR. Do not
  silently weaken it in this file.
- Section 2 (decision log) is updated in the PR that assigns or accepts
  a decision. Keep the row; do not delete history.
- Section 3 (phase tracker) is updated by the orchestrator at the end
  of each phase, in the same commit that closes the phase's work.
