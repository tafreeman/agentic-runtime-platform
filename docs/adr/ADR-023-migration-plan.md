# ADR-023 Option A — Phased Migration Plan
## ExecutionKit as the OpenAI-message-format Execution Kernel (contract-first, reversible)

**Verified ground truth (audit confirmed against `C:\Users\tandf\source\_audit\agentic-runtime-platform\...`):**
- Two divergent backend contracts coexist: ABC `LLMBackend` with `complete_chat` at `agentic_v2/models/backends_base.py:14-40`; lossy Protocol `LLMBackend` (no `complete_chat`) at `agentic_v2/models/client.py:45-60`.
- `AnthropicBackend.complete_chat` returns RAW `tool_use` blocks (`backends_cloud.py:314-315`) and `stop_reason` (`:320`).
- `GeminiBackend.complete_chat` hardcodes `tool_calls=None` (`backends_cloud.py:422`), returns UPPERCASE `finishReason` (`:423`), and camelCase `usageMetadata` (`:425`).
- EK canonical contracts live at `executionkit/executionkit/provider.py` (`LLMResponse` :70-110, `complete` :126-134, `_classify_http_error` :452-485) and `types.py` / `errors.py` / `retry.py` / `cost.py`.

**Guiding rule:** Contracts and adapters are built and proven in isolation FIRST. The runtime hot path (`LLMClientWrapper.complete`, step funcs) is not touched until the adapter + its test suite are green. Every phase is independently revertible.

> **Testing note:** All `pytest` / `mypy` GATEs are executed by the orchestrator, not by workflow subagents (subagents cannot run pytest). Subagents produce code + test files; the orchestrator runs the GATE and authorizes the next phase.

---

## Phase 0 — Pin baseline & freeze contracts (no code change)
**Goal:** Capture current behavior so every later phase has a regression oracle, and freeze the EK contract surface as additive-only.

**File-level changes:**
- None to source. Add `docs/adr/ADR-023-migration-notes.md` recording: the additive-only freeze of EK contract field names/order/defaults (mirrors runtime `contracts/messages.py` rule), and the decision log for the open decisions below.
- Snapshot real backend response dicts: add `tests/fixtures/backend_responses/{openai,anthropic,gemini,ollama,github}.json` captured from each backend's `complete_chat` (use recorded/mocked payloads — do NOT call live providers).

**GATE (orchestrator runs):**
- `pytest tests/ -q` baseline passes; record pass count as the floor for all later phases.
- `mypy --strict agentic_v2/models` recorded as baseline (expected to currently surface the Protocol/ABC divergence — record the error set so Phase 2 can prove it shrinks).

**Rollback:** Delete the notes doc and fixtures. Zero runtime impact.

---

## Phase 1 — Extract `executionkit-contracts` package (Option B contract extraction, fully reversible)
**Goal:** Stand up the zero-dependency `executionkit.contracts` value/protocol layer as the single seam both layers type against, WITHOUT changing any runtime or EK-engine behavior. This is the reversible foundation.

**File-level changes (new package only):**
- New dist `ek-contracts`, importable as `executionkit.contracts`. ZERO third-party runtime deps (stdlib only: `dataclasses`, `types.MappingProxyType`, `typing`, `enum`, `collections.abc`) per ADR-014.
- Move (re-export, do not delete originals yet) into `executionkit/contracts/`:
  - `protocols.py`: `LLMProvider` (runtime_checkable, `async complete(messages,*,temperature,max_tokens,tools,**kwargs)->LLMResponse`), `ToolCallingProvider` (with F-04 delegation note baked into docstring), `PatternStep`.
  - `response.py`: `LLMResponse` (frozen+slots, `content/tool_calls/finish_reason/usage:MappingProxyType/raw` + properties `input_tokens/output_tokens/total_tokens/has_tool_calls/was_truncated`), `ToolCall` (frozen+slots).
  - `usage.py`: `TokenUsage` (frozen+slots, `__add__`), `PatternResult[T]` (frozen+slots, `MappingProxyType` metadata).
  - `tools.py`: `Tool` (frozen+slots, `to_schema()` OpenAI function-tool emitter), `VotingStrategy` (StrEnum), `Evaluator` TypeAlias.
  - `errors.py`: the 9-class tree `ExecutionKitError(cost,metadata)->LLMError->{RateLimitError(retry_after),PermanentError,ProviderError}`; `ExecutionKitError->PatternError->{BudgetExhaustedError,ConsensusFailedError,MaxIterationsError}`.
  - `retry.py`: `RetryConfig` (frozen) + `DEFAULT_RETRY` (value type + policy only; `with_retry()` function stays in EK engine).
- EK package (`executionkit/`) imports these from `executionkit.contracts` and re-exports for back-compat (no public import path breaks).
- **[Finding: was_truncated vocabulary]** Add `FinishReason` StrEnum `{STOP, LENGTH, MAX_TOKENS, TOOL_CALLS, CONTENT_FILTER}` to `executionkit/contracts/response.py`. Update `LLMResponse.was_truncated` to recognize `{LENGTH, MAX_TOKENS}` (string-compatible). This centralizes the canonical finish_reason vocabulary that adapters normalize INTO. (Resolves adversarial finding "finish_reason vocabulary incomplete".)
- **[Finding: Anthropic cache tokens dropped]** Extend `LLMResponse.input_tokens` to additively sum `cache_creation_input_tokens` + `cache_read_input_tokens` when present (keeps cache-aware cost). Additive-only; no existing key behavior changes. (Resolves medium finding.)
- **[Finding: Gemini usage not normalized]** Add a third normalization branch to `LLMResponse.input_tokens/output_tokens` recognizing `promptTokenCount`/`candidatesTokenCount` — makes EK the single source of truth for usage. (Resolves medium finding; the recommended "former" option in open_questions.)

**GATE (orchestrator runs):**
- `pytest` for EK's existing suite (consensus/refine/react/structured/pipe/cost/retry) passes UNCHANGED against the re-exported contracts (proves zero behavioral drift).
- New unit tests: `FinishReason` membership; `was_truncated` true for `length`/`max_tokens`/`MAX_TOKENS`(normalized), false for `stop`/`tool_use`; `LLMResponse` usage normalization for OpenAI + Anthropic(+cache) + Gemini camelCase yields nonzero `input_tokens/output_tokens`.
- `mypy --strict executionkit/contracts` clean. `pip install ek-contracts` in a clean venv imports with no third-party deps.

**Rollback:** Delete `executionkit/contracts/`; revert EK re-export imports. Runtime untouched, so revert is local to EK package.

---

## Phase 2 — Reconcile the runtime `LLMBackend` definitions (type-only, no behavior)
**Goal:** Eliminate the lossy Protocol so the adapter can type-check against `complete_chat`. (Resolves CRITICAL finding "two divergent LLMBackend definitions".)

**File-level changes:**
- Delete the Protocol `LLMBackend` in `agentic_v2/models/client.py:45-60`.
- `client.py` imports the ABC: `from agentic_v2.models.backends_base import LLMBackend`.
- Retype `LLMClientWrapper.backend` (currently `LLMBackend | None`, `client.py:~173`) to the ABC. No call sites change yet — `complete()` still calls `backend.complete()` (text path remains until Phase 5).

**GATE (orchestrator runs):**
- `mypy --strict agentic_v2/models` — the baseline divergence errors recorded in Phase 0 are gone; `complete_chat` is now a known method on `LLMClientWrapper.backend`.
- `pytest tests/` still at Phase-0 pass floor (pure type reconciliation, no runtime change).

**Rollback:** Restore the Protocol block and the `client.py` import; revert the type annotation. Single-file revert.

---

## Phase 3 — Make backends emit canonical OpenAI-shaped dicts (backend-layer normalization)
**Goal:** Fix the lossy/raw backend outputs at the source so the inbound adapter is lossless. This is the highest-leverage correctness phase and touches only backend `complete_chat` return construction (not the wrapper hot path). (Resolves the cluster of CRITICAL/HIGH backend findings.)

**File-level changes (all in `agentic_v2/models/backends_cloud.py` and `backends_local.py`):**
- **Anthropic (`backends_cloud.py:314-322`)** — normalize each `tool_use` block to OpenAI shape before returning: `{"id", "type":"function", "function":{"name", "arguments": json.dumps(block["input"])}}`. Map `stop_reason` -> OpenAI finish_reason via `{end_turn:stop, max_tokens:length, tool_use:tool_calls, stop_sequence:stop}`. Pass `usage` through (EK already reads `input_tokens`/`output_tokens` + now cache keys). (Resolves CRITICAL "Anthropic raw tool_use" + HIGH "stop_reason".)
- **Gemini (`backends_cloud.py:417-426`)** — parse `functionCall` parts from `candidates[0].content.parts` into OpenAI tool_calls `{id (synth), type:"function", function:{name, arguments: json.dumps(args)}}`. Map `finishReason` via `{STOP:stop, MAX_TOKENS:length, SAFETY:content_filter, RECITATION:content_filter}` (lowercase output). Remap `usageMetadata` -> `{prompt_tokens:promptTokenCount, completion_tokens:candidatesTokenCount}`. (Resolves CRITICAL "Gemini tool_calls None", CRITICAL "Gemini UPPERCASE finishReason", HIGH "Gemini camelCase usage".)
- **Ollama (`backends_local.py:118-123` complete_chat)** — apply the same `thinking`-field fallback as `complete()` (`:70-76`) so reasoning-model content is populated; prefix reasoning with `[THINKING]...[/THINKING]` so chain-of-thought stays distinguishable from the answer; back-fill `usage` via `count_tokens(prompt)` + `count_tokens(content)` -> `{prompt_tokens, completion_tokens}`; set a heuristic finish_reason (`length` if `num_predict` ceiling hit, else `stop`). (Resolves HIGH "Ollama zero-cost + flattened thinking".)
- **All backends** — coalesce `finish_reason or "stop"` and lowercase before returning. (Resolves MEDIUM "finish_reason None / casing".)
- **OpenAI/GitHub** — leave the OpenAI-native `{id,type:function,function:{name,arguments:<JSON string>}}` shape as-is; arguments stay JSON strings (EK `_parse_tool_calls` json.loads them). (Decoding ownership lives in the adapter, Phase 4.)

**GATE (orchestrator runs):**
- Per-backend unit tests against the Phase-0 fixtures: Anthropic tool_use -> OpenAI shape with `function.arguments` a valid JSON string; Anthropic `end_turn`->`stop`, `max_tokens`->`length`; Gemini `functionCall` parsed and present, `MAX_TOKENS`->`length`, usage `prompt_tokens`/`completion_tokens` nonzero; Ollama empty-content reasoning model populates content from `thinking`, usage nonzero, truncation heuristic fires; all backends never return `finish_reason=None` or uppercase.
- `pytest tests/` at or above Phase-0 floor (existing backend tests must still pass; update only assertions tied to the now-normalized shapes).

**Rollback:** Revert each backend's `complete_chat` return block. Backends are isolated; no wrapper/step code depends on the new shapes until Phase 5.

---

## Phase 4 — Build the inbound/outbound adapters (`ek_adapters.py`) — isolated, never wired into hot path
**Goal:** Implement `ChatDictToLLMResponse` (inbound) and `MessagesToChatDict` (outbound request) as pure functions, fully unit-tested against fixtures + the now-clean backend outputs. (Resolves CRITICAL "adapter does not exist yet".)

**File-level changes:**
- New module `agentic_v2/models/ek_adapters.py`:
  - `chat_dict_to_llm_response(dict) -> LLMResponse`: build `content`; run `tool_calls` through EK `_parse_tool_calls` semantics (json.loads arguments -> dict). **[Finding: defensive dual-shape]** Keep a defensive branch that also handles a raw `tool_use` block (`if "input" in call: ...`) so the adapter is correct even if a backend regresses — belt-and-suspenders for the Anthropic path. **[Finding: mutable-dict aliasing]** Deep-copy `usage` before `MappingProxyType` wrap: `MappingProxyType(dict(d["usage"]))` so post-return backend mutation can't leak into the frozen response. Coalesce `finish_reason or "stop"`. Stash full dict (incl. `model`) into `raw`.
  - `messages_to_chat_dict_call(...)`: forward messages verbatim; substitute wrapper-configured defaults when `temperature`/`max_tokens` are `None` (never pass literal `null` to a backend payload); pass EK `Tool.to_schema()` tools through as OpenAI function schemas.
- **[Finding: kwargs collision]** Adapter/wrapper signature normalizes `temperature`/`max_tokens` as explicit params extracted from `**kwargs` before forwarding, so they reach the keyword-only EK seam rather than leaking into backend `**kwargs`.

**GATE (orchestrator runs):**
- Round-trip tests: each fixture (OpenAI/Anthropic/Gemini/Ollama/GitHub) `complete_chat` dict -> `LLMResponse` preserves `content`, `tool_calls` (typed `ToolCall` tuple with dict args), normalized `finish_reason`, nonzero token counts (where provider reports them), `was_truncated` correct.
- Aliasing test: mutate source dict after adapter returns; assert `LLMResponse.usage` unchanged.
- Anthropic-regression test: feed a raw `tool_use` block directly; assert defensive branch still yields populated `ToolCall.arguments`.
- `mypy --strict agentic_v2/models/ek_adapters.py` clean.

**Rollback:** Delete `ek_adapters.py`. Nothing imports it yet.

---

## Phase 5 — `SmartRouterProvider` + wrapper re-point (the hot-path change, gated behind a flag)
**Goal:** Expose routing as an EK `LLMProvider` and re-point `LLMClientWrapper.complete()` onto the message/`complete_chat` path through the adapter — preserving caching, sanitization, budget, and ALL router reliability behavior. (Resolves CRITICAL "complete() bypasses complete_chat" + HIGH "SmartRouterProvider not implemented".)

**File-level changes:**
- New `agentic_v2/models/ek_provider.py` — `SmartRouterProvider` implementing EK `LLMProvider`/`ToolCallingProvider`:
  - `complete(messages,*,temperature=None,max_tokens=None,tools=None,**kwargs)->LLMResponse`: resolve `model = router.get_model_for_tier(self.tier)` (raise EK `ProviderError` if None); call `backend.complete_chat` inside `async with router.execute_with_bulkhead(model):` (NOT `_execute_call`, which is text-only and would collapse the rich dict — Resolves "router _execute_call is text-only" finding); time the call; on success `router.record_success(model, latency_ms)`; on exception `router._classify_and_record_error(model, exc)` then translate `httpx.HTTPStatusError` 429->`RateLimitError(retry_after)`, {401,403,404}->`PermanentError`, else->`ProviderError` (mirrors `provider.py:452-485`) so EK `RetryConfig.should_retry` recognizes them (Resolves "error-type translation gap"). Loop over fallback candidates (like `complete_chat_with_fallback`, max 6) so failover/circuit-breaking happen INSIDE one EK `complete()`. Pass returned dict through `chat_dict_to_llm_response`.
  - `supports_tools`: delegating `@property` reading inner backend/route capability (False for Gemini routes that can't do tools) — honors F-04, NOT hardcoded `Literal[True]`. (Resolves "Gemini tool-blind silent loss".)
- `LLMClientWrapper` (`client.py`) re-point, behind env flag `AGENTIC_EK_PROVIDER=1` (default off in this phase):
  - When flag on: `complete()` builds `messages=[{role:"user",content:effective_prompt}]` (or accepts a messages list), calls `SmartRouterProvider.complete(messages)`, returns `(response.content, model_used, response.total_tokens)`.
  - Ordering preserved: cache lookup -> pre-send sanitization -> `provider.complete(messages)` (routing/failover/circuit-break inside EK+router) -> post-receive sanitization -> `TokenBudget.consume(response.total_tokens)` -> cache store.
  - **[Finding: double-retry/double-cost]** Retire the wrapper's `retry_with_jitter` ON THE EK PATH only; `record_success`/`_classify_and_record_error` fire exactly once per physical HTTP call (inside `SmartRouterProvider`, not also in the wrapper). The wrapper's `retry_with_jitter` decorator stays available for non-EK/non-LLM call sites. (Resolves "double retry / double cost amplification".)

**GATE (orchestrator runs):**
- Flag-off regression: `pytest tests/` at Phase-0 floor with `AGENTIC_EK_PROVIDER` unset (proves the legacy path is untouched).
- Flag-on suite: tool_calls + finish_reason + real usage survive end-to-end through the wrapper (asserts the prior text-only loss is fixed); `SmartRouterProvider` reliability tests — (1) repeated 429 opens circuit breaker + fires `is_degraded`/`on_degraded_selection` hook, (2) cross-tier fallback skips sick model and escalates tier, (3) per-provider bulkhead semaphore caps concurrency, (4) rate-limit headers parsed into cooldown, (5) Redis CAS shared-state path when available + in-memory fallback when not, (6) `httpx` 429/401/5xx -> correct EK error class, (7) `supports_tools` False for Gemini route causes `react_loop` to refuse rather than silently drop tools.
- `mypy --strict agentic_v2/models`.

**Rollback:** Unset `AGENTIC_EK_PROVIDER` (instant runtime revert to legacy text path). Code-level revert: delete `ek_provider.py`, revert the `complete()` branch — wrapper returns to pre-Phase-5 behavior.

---

## Phase 6 — Delegate inner step LLM mechanics to EK patterns (step-by-step, DAG lifecycle untouched)
**Goal:** Route the INNER LLM mechanics of step funcs through EK patterns while StepExecutor keeps all DAG-level lifecycle. (Resolves HIGH "StepExecutor lifecycle regression" + MEDIUM "two tool-execution paths".)

**File-level changes (incremental, one delegation per sub-step, each independently gated):**
- 6a plain completion -> EK `checked_complete()`/`_TrackedProvider` over `SmartRouterProvider` (budget-checked, retry-wrapped, truncation-tracked, shared `CostTracker`).
- 6b tool-use loop -> EK `react_loop(provider, prompt, tools, max_rounds=8)` replacing bespoke `run_tool_calls`; runtime Tools wrapped as EK `Tool` value types. **[Finding: two tool paths diverge]** Per call path choose exactly ONE owner: a step is either EK-`react_loop` OR runtime-`tool_execution`, never both mid-thread. Document the chosen owner per step; if coexistence is required they must share one message thread + tool-call tracking state. Until a step is migrated, it keeps `run_tool_calls` (`MAX_TOOL_ROUNDS=8`, `MAX_TOOL_CALLS_PER_ROUND=12`, 12000-char truncation) unchanged.
- 6c JSON/structured -> EK `structured()` (extract_json 3-strategy); runtime `ReviewStatus.normalize` still runs at the DAG/gating layer.
- 6d multi-sample -> EK `consensus()`; 6e prompt-level self-correction -> EK `refine_loop()` (distinct from StepExecutor.loop_until).
- **[Finding: EK error bypasses VerificationGate/hooks]** Wrap all step execution (incl. EK pattern calls) inside the `VerificationGate` context; catch `ExecutionKitError`, pass to `error_hooks` before retry decision, and map to `StepResult.error` preserving `cost`/`metadata`. Make the budget-pct floor visible to the inner pattern (share `TokenBudget` or check `token_budget_pct` before the pattern proceeds) so a spent step-budget stops the pattern before it wastes tokens. (Resolves HIGH "step lifecycle".)
- **[Finding: budget precedence]** Establish explicit precedence: on each recorded `LLMResponse` the adapter calls `TokenBudget.consume(response.total_tokens)` FIRST; if False raise `BudgetExhaustedError` before `CostTracker` recording continues. `CostTracker` owns the call-count + input/output split; `TokenBudget` owns the scalar token-sum ceiling; `VerificationPolicy.token_budget_pct` is the higher-layer step-retry guard. Document layering, not merging. Preserve EK `reserve_call()`/`record_without_call()` two-phase ordering. (Resolves MEDIUM "two budget systems".)

**GATE (orchestrator runs):**
- Per sub-step: the migrated step's tests pass AND DAG-lifecycle tests (should_run, when/unless, retry/backoff, verification gate escalation, loop_until, hooks, output_mapping, `_meta` model/token extraction) still pass.
- Budget-precedence test: a step whose EK pattern would exceed budget raises `BudgetExhaustedError`, fires `error_hooks`, and `loop_until`/verify both behave; no double-counting (TokenBudget total == sum of recorded responses).
- Concurrency test: N parallel `checked_complete` gate correctly at the budget limit (no over-admission), `CancelledError` propagates unretried.
- `pytest tests/` full suite at or above Phase-0 floor after each sub-step.

**Rollback:** Each sub-step is a discrete revert (the step func reverts to `get_client().complete(...)` / `run_tool_calls`). Because sub-steps land one at a time, a regression rolls back only that step.

---

## Phase 7 — Cut over default, remove dead text-only path, finalize docs
**Goal:** Flip `AGENTIC_EK_PROVIDER=1` to default-on, retire the legacy text-only wrapper branch, and lock the contract.

**File-level changes:**
- Default `AGENTIC_EK_PROVIDER` on; after a bake-in window, delete the legacy text-only `complete()` branch and the wrapper-level `retry_with_jitter` use on the LLM seam.
- Update `docs/adr/ADR-023-migration-notes.md` and `docs/ARCHITECTURE.md`: one runtime `LLMBackend` (ABC), one EK `LLMProvider` (Protocol), adapter as the sole bridge; budget/retry/tool-path ownership tables.

**GATE (orchestrator runs):**
- Full `pytest tests/` + `mypy --strict` green; flag-off path removal does not reduce the pass floor.
- Confirm `complete_stream` and `count_tokens` remain reachable on the underlying ABC (kernel seam stays minimal; streaming/token-counting explicitly OUT per open decision).

**Rollback:** Re-introduce the flag default-off and restore the legacy branch from the Phase-5 revert point (kept in git history through the bake-in window).

---

## Accepted risks (explicit, not mitigated by code)
- **Gemini history tool-blindness pre-Phase-3:** any Gemini tool call made before Phase 3 lands is unrecoverable (backend never parsed it). Accepted — no historical replay; forward-fixed in Phase 3.
- **Ollama truncation is heuristic, not authoritative:** Ollama reports no native finish_reason; the `length` heuristic (Phase 3) may misclassify edge cases. Accepted as best-effort for local models.
- **Streaming + per-provider `count_tokens` stay OUT of the kernel contract** (roadmap, separate optional protocols — `SupportsStreaming` already exists in `core/protocols.py`). Accepted: kernel seam stays `complete(messages)->LLMResponse` only.

---

## Done when (final checklist)
- [ ] `executionkit.contracts` package exists, stdlib-only, additive-only frozen; EK suite passes against it unchanged. (P1)
- [ ] `FinishReason` enum + `was_truncated` recognize length/max_tokens across OpenAI/Anthropic/Gemini. (P1)
- [ ] `LLMResponse` usage normalization covers OpenAI + Anthropic(+cache) + Gemini camelCase; nonzero token tests pass. (P1)
- [ ] Single runtime `LLMBackend` ABC; lossy `client.py` Protocol deleted; `mypy --strict` clean and `complete_chat` reachable on wrapper backend. (P2)
- [ ] Anthropic tool_use -> OpenAI shape; stop_reason mapped. (P3)
- [ ] Gemini functionCall parsed, finishReason lowercased/mapped, usageMetadata remapped. (P3)
- [ ] Ollama thinking fallback in `complete_chat`, usage back-filled, reasoning marked, truncation heuristic. (P3)
- [ ] No backend returns `None`/uppercase finish_reason. (P3)
- [ ] `ek_adapters.py` round-trips all 5 backends losslessly; usage deep-copied (no aliasing); defensive Anthropic branch; mypy clean. (P4)
- [ ] `SmartRouterProvider` preserves circuit breaker / bulkhead / rate-limit parsing / cross-tier fallback / Redis CAS / `supports_tools` delegation; httpx->EK error translation verified. (P5)
- [ ] Wrapper drives the message/`complete_chat` path; tool_calls + finish_reason + real usage survive end-to-end; no double-retry/double-cost. (P5)
- [ ] Step inner mechanics on EK patterns; DAG lifecycle + VerificationGate + hooks intact; one owner per tool path; budget precedence documented + tested. (P6)
- [ ] Default cutover; legacy text-only path removed; docs updated; `complete_stream`/`count_tokens` still reachable. (P7)
- [ ] Every preservation-matrix capability has a passing verifying test (orchestrator-run).
- [ ] All 19 adversarial findings closed as fixed-task or explicitly-accepted risk.
