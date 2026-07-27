# ADR-023: ExecutionKit ↔ Runtime Execution-Contract Relationship

**Status:** Accepted
**Date:** 2026-05-31

## Context

The portfolio is being positioned as a layered enterprise AI platform: ExecutionKit
as the "deterministic execution kernel" (Layer 1) that the Agentic Runtime Platform
(Layer 2) and everything above it depend on. That story is currently **aspirational,
not true in code**. Today the two layers are independent, overlapping implementations
of LLM execution that share no contracts.

Concretely, the two layers disagree at the most fundamental seam — the LLM call:

| Concern | ExecutionKit (`executionkit`) | Runtime (`agentic_v2`) |
|---|---|---|
| Real provider primitive | `LLMProvider.complete(messages: Sequence[dict], *, temperature, max_tokens, tools) -> LLMResponse` | `LLMBackend.complete_chat(model, messages, tools) -> dict` (every concrete backend); `complete(model, prompt) -> str` is a thin wrapper over it |
| Request shape | Chat message list (OpenAI format) | Chat message list via `complete_chat`; prompt string only on the wrapper |
| Response shape | Frozen `LLMResponse` (content, `tool_calls`, `finish_reason`, usage) | `dict{content, tool_calls, finish_reason, model, usage}` from `complete_chat` — structurally the same fields |
| Tool calls | First-class (`ToolCall`, `ToolCallingProvider`) | First-class on `complete_chat` (OpenAI tool format; Anthropic/Gemini converted in-backend) |
| Streaming | Not supported | Declared but **not implemented** — no concrete backend overrides `complete_stream`; the base ABC yields a single chunk from `complete()` (Ollama hardcodes `stream: False`) |
| Token counting | Derived from response usage | `count_tokens()` heuristic (`len//4`) on the base ABC, not overridden; real `usage` is returned by `complete_chat` but ignored on the routing path |
| Retry | `RetryConfig` + `with_retry` (`engine/retry.py`) | `RetryConfig`/`RetryStrategy` on `StepDefinition` + `retry_with_jitter` (`models/client.py`) |
| Budget | `TokenUsage` (llm_calls / input / output) + TOCTOU-safe `CostTracker` | `TokenBudget` (max_tokens) on `LLMClientWrapper` |
| JSON extraction | `engine/json_extraction.py` | `models`/`engine` `json_extraction.py` + `llm_output_parsing.py` |
| Routing / failover | None (single endpoint `Provider`) | `SmartModelRouter`, 8+ providers, tiers, circuit breakers, cache, sanitization |

So each layer independently reimplements provider abstraction, retry/backoff, token
budgeting, and JSON/structured extraction. Crucially, the runtime's *real* call primitive
is `complete_chat(messages, tools) -> dict` — whose payload (`content, tool_calls,
finish_reason, usage`) is structurally ExecutionKit's `LLMResponse`. The `model, prompt ->
str` form is a thin convenience wrapper, and backend-level streaming and token-counting are
non-functional fallbacks (single-chunk yield; `len//4` estimate). The two contracts are
therefore **much closer than the prompt-based path suggests** — the seam is essentially a
field map, not a redesign. Two further wrinkles compound the duplication: `LLMClientWrapper`
drives the lossy prompt path and discards `complete_chat`'s richer message/tool/usage output,
and there are two divergent `LLMBackend` definitions (a `Protocol` in `models/client.py` and
an `ABC` in `models/backends_base.py`). ExecutionKit is
the smaller, cleaner asset: published to PyPI, zero runtime dependencies, mypy --strict,
immutable value types, ~80% covered. The runtime is the larger, more differentiated
asset: routing, circuit-breaking, caching, sanitization, observability, replay, audit —
but it does not import ExecutionKit, and ExecutionKit is not a superset of what the
runtime's backend needs (no streaming, no `count_tokens`, no tier routing).

This ADR decides the relationship between the two so the platform has one coherent
execution story and stops paying for two diverging copies of the same primitives.

## Decision Drivers

- **Narrative truth:** the "kernel everything depends on" claim should match the code.
- **Duplication cost:** retry, budget, and JSON-extraction logic exist twice and drift.
- **Risk to the crown jewel:** the runtime (~36K LOC, 379+ tests) is the most valuable,
  most differentiated asset; refactoring its hot path carries regression risk.
- **ExecutionKit's value proposition:** minimal, zero-dependency, strict-typed,
  published. Anything that bloats it (streaming, routing) erodes that.
- **Speed to a credible platform story** vs. depth of true integration.

## Options Considered

### Option A — ExecutionKit becomes the execution kernel (make the vision literally true)

The runtime depends on ExecutionKit. EK's `LLMProvider` / `LLMResponse`, error
hierarchy, `TokenUsage`, and pattern set become **the** execution contract. The
runtime's `SmartModelRouter` is reframed as an EK `LLMProvider` implementation (a
routing provider that satisfies `complete(messages) -> LLMResponse`), and the step
executor delegates the inner LLM mechanics — retry, budget, structured output,
consensus/react — to EK patterns. The runtime keeps everything above the call:
DAG/Kahn execution, server, observability, replay, audit, tenancy.

**Pros**
- Makes the "stack" real: one provider contract, one retry/budget/structured-output
  implementation, one source of truth. The pyramid diagram stops being marketing.
- **Defensible positioning — the OpenAI-message-format backbone.** Both layers already
  speak OpenAI chat-message format at their real primitive (`complete_chat` ⇄
  `LLMProvider.complete`), so framing EK as "the message-format execution kernel the whole
  platform runs on" is literally what the code does, not a claim retrofitted onto it. EK
  inherits the de-facto industry interchange format → drop-in, zero lock-in, instantly
  interoperable with anything that emits OpenAI-style messages.
- Standardizes on the asset that is already published, strict-typed, immutable, and
  dependency-free — a defensible foundation.
- The lab's pattern library (Layer 4) gets a real home: patterns live in EK and are
  reused by the runtime instead of reinvented.
- Clean go-to-market funnel: developers adopt the open-source kernel → upsell the
  enterprise runtime built on it. "Our runtime runs on our open kernel."
- Deletes duplicated retry/budget/json-extraction from the runtime over time.

**Cons**
- The provider-seam mismatch is smaller than first assumed (see Context): the runtime's
  real primitive `complete_chat(messages, tools) -> dict` already speaks OpenAI message
  format and returns EK's `LLMResponse` fields, and backend-level streaming/token-counting
  are non-functional fallbacks today — so EK's lack of them is not a real blocker. The
  adapter is a field map, not a redesign. **However**, if real streaming or per-provider
  token-counting is ever required, EK's minimal protocol would need extending (risking
  bloat of the "minimal kernel") or a permanent shim.
- Touches the runtime's hottest path (`LLMClientWrapper`, `smart_router`, `StepExecutor`
  LLM calls). This is weeks of work against the most valuable, best-tested code, with
  real regression risk. Routing/caching/sanitization must be preserved exactly.
- Budget models differ (`TokenUsage` calls/in/out vs `TokenBudget` max_tokens) and must
  be reconciled — a semantic, not just mechanical, merge.
- Version coupling: the runtime is now locked to EK releases; EK changes ripple upward.
- Even after the work, routing/circuit-breaking/caching/sanitization still don't belong
  in EK — so two layers remain; A only unifies the *provider seam*, not the whole story.

### Option B — Two products, one shared-contracts package (formalize the seam, decouple the implementations)

ExecutionKit and the runtime stay independent products. Extract a small, dependency-free
**contracts** package (e.g. `agentic-contracts`) holding only the shapes both already
need: the `LLMResponse` / message format, `TokenUsage`, the error hierarchy, and the
candidate cross-layer types from the platform vision (`ExecutionStep`, `AgentMessage`,
`WorkflowState`, `EvaluationResult`). Both packages depend on contracts; neither depends
on the other's implementation. Interop happens at the boundary via thin adapters: an EK
`Provider` can be wrapped as a runtime backend, and a runtime backend can emit EK's
`LLMResponse`. EK is positioned as the reference single-process library; the runtime
as the enterprise orchestration platform.

**Pros**
- Low risk, fast: extract types + publish contracts + add adapters. Days, not weeks. Does
  not touch the runtime's hot path or jeopardize the 379-test suite.
- Each product evolves at its own pace; no lock-step versioning. The runtime keeps
  routing/streaming/caching without contorting EK; EK stays minimal and zero-dep.
- Honest positioning: two complementary, interoperable products — a library and a
  platform — tied together by shared contracts.
- Still supports a platform narrative ("one contract spine across the stack") without
  overclaiming a dependency hierarchy that the code resists.

**Cons**
- The headline "ExecutionKit is the kernel every layer depends on" becomes false; you are
  choosing "interoperable peers" over a strict layered stack. Weaker single-diagram story
  for buyers/recruiters who like a clean pyramid.
- Duplication persists by default: two retry implementations, two budget models, two JSON
  extractors keep living unless you actively converge them onto the shared types.
- Adds a third versioned package with additive-only governance overhead.
- "Two products" can read as "two half-products" without a crisp tying narrative.

### Option C — Phased: B now, with an explicit option on A later (recommended sequencing)

Do Option B as the immediate, reversible step (extract contracts, add adapters, ship the
end-to-end demo across the seam). Treat Option A as a later, evidence-gated migration:
once the contract package is proven and adoption justifies the cost, migrate the runtime's
provider seam onto EK behind the already-existing adapter. B is a strict subset of the work
A requires, so nothing is wasted.

## Recommendation

**Option A, executed contract-first.** The "OpenAI-message-format backbone" framing (see
the Option A pros) tips the decision: because the runtime's real primitive already speaks
the same message format and returns EK's `LLMResponse` fields, the seam is a field map, not
a rewrite — so the deep-merge cost that made Option A look expensive is largely an
illusion. We therefore commit to A as the destination, but **sequence the work through the
Option B contract extraction as its first, fully reversible step**: extract the shared
contract, land the adapter, prove interop, then progressively retire the runtime's
duplicated primitives behind it. This captures B's low-risk early value while still
arriving at A's single coherent kernel.

## Decision

**Adopt Option A.** ExecutionKit becomes the OpenAI-message-format execution kernel; the
runtime aligns its provider seam onto EK's `LLMProvider` / `LLMResponse` contract while
retaining every orchestration, routing, caching, sanitization, observability, replay,
audit, and tenancy capability above the seam. Execution is sequenced contract-first (the
Option B contract extraction is the first, reversible phase), with explicit
functionality-preservation gates between phases — no capability in either layer may be
dropped or silently changed. The phased migration plan and the functionality-preservation
matrix live alongside this ADR (`ADR-023-migration-plan.md`,
`ADR-023-preservation-matrix.md`).

## Consequences

- A new `agentic-contracts` (name TBD) package is created, holding only shared value types
  and the error hierarchy, with zero runtime dependencies and additive-only schema rules
  (consistent with ADR-014's wire-format discipline).
- ExecutionKit and the runtime each take a dependency on contracts; a thin adapter module
  (`Provider` ⇄ `LLMBackend`) lands in the runtime so an EK provider can drive a step and
  vice versa. The runtime's hot path is otherwise untouched in this phase.
- Duplicated retry/budget/JSON-extraction logic is explicitly tracked as convergence debt
  against the shared contracts, to be retired opportunistically rather than in a big bang.
- The platform README and architecture diagram are updated to describe a shared-contract
  spine, not an unverified dependency pyramid, until/unless Option A is executed.
- This ADR is cross-repo: it should travel with the canonical runtime when it is moved out
  of `_audit/` into a top-level repo, and be cross-linked from the ExecutionKit repo.

## Alternatives Considered

- **Do nothing / keep two independent stacks.** Rejected: the duplication keeps drifting
  and the platform story stays untrue, which is the problem this ADR exists to fix.
- **Fold the runtime into ExecutionKit (one package).** Rejected: collapses a minimal,
  zero-dependency, published library into a heavyweight server/runtime, destroying EK's
  core value proposition and its standalone adoption funnel.
- **Make ExecutionKit depend on the runtime (invert the layers).** Rejected: would force
  EK to inherit the runtime's dependency surface and contradicts the kernel framing
  entirely.

---

## Amendment — Option A′ (2026-06-01)

**Decision:** Collapse to a single `executionkit` package. The intermediate
`executionkit-contracts` package introduced in Phase 1 is **retired**.

### Rationale

The contracts package was predicated on the belief that `executionkit` dragged in
httpx (a heavyweight transitive dependency) when importing only its value types.
That premise is false:

- `executionkit`'s `base dependencies = []`; httpx is an optional `[httpx]` extra.
- `executionkit.provider` probes httpx with `try/except ImportError` and falls back
  to stdlib `urllib` — the value types (`LLMResponse`, `ToolCall`, `TokenUsage`)
  never require httpx.
- `executionkit.errors` is stdlib-only.

The contracts package was therefore solving a non-problem. Worse, the build made
it a **verbatim duplicate** of EK's types — its own source files said "COPIED
VERBATIM from executionkit.provider" — while `executionkit` itself was never
refactored to import from it. The result was two parallel, identically-named class
trees:

```
adapter raises  ──▶ executionkit_contracts.errors.ProviderError  (one class)
EK retry checks ──▶ executionkit.errors.ProviderError            (a DIFFERENT class)

isinstance(contracts_error, executionkit.errors.LLMError) == False
```

This dual-tree mismatch meant EK's pattern/retry layer could not classify provider
errors raised by the runtime adapter — the root cause of B-2 (the EK-default-on
hang). The collapse eliminates the dual-tree bug by construction.

### What changed

| Aspect | Original Option A | Option A′ (this amendment) |
|---|---|---|
| Runtime dependency | `executionkit` + `executionkit-contracts` | `executionkit` only |
| Error tree | dual (contracts copy + EK original) | single (`executionkit.errors.*`) |
| Value types | dual (contracts copy + EK original) | single (`executionkit.provider.*`) |
| `cast()` boundary hacks | 2 in `ek_step_delegation.py` | deleted |
| `executionkit-contracts` package | live | **retired / dormant** |

### Implementation status (F0–F5, all landed 2026-06-01)

| Phase | Title | Status |
|-------|-------|--------|
| F0 | Environment + single dependency declaration | landed |
| F1 | Collapse imports to `executionkit` (core of A′) | landed |
| F2 | Flag-OFF green floor | landed |
| F3 | Fix B-1 (lru_cache test-isolation leak) | landed |
| F4 | Verify B-2 resolved by collapse | landed |
| F5 | Close usage-normalization drift | landed (accepted + documented) |

`AGENTIC_EK_PROVIDER` remains **opt-in** (default OFF). Default-on requires a
clean flag-ON full-suite run; ~14 flag-ON behavioral failures remain (test_agents,
test_langchain_engine, golden workflow) unrelated to the import collapse — these
are tracked as follow-on work, not blockers to the Option A′ amendment itself.
