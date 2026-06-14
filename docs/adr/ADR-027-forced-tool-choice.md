# ADR-027: Forced / `any` / `auto` `tool_choice` and the cross-role `verify_fact` tool

**Status:** Accepted
**Date:** 2026-06-13
**Related:** [ADR-023](ADR-023-executionkit-runtime-contract-relationship.md) (EK step delegation / canonical `complete_chat` dict), [ADR-001](ADR-001-002-003-architecture-decisions.md) (native engine / tool loop)

---

## Context

The provider tool-use APIs (OpenAI, Anthropic, Azure) all expose a
`tool_choice` control that decides *whether and which* tool the model may call:

- `auto` — the model decides (call a tool or answer directly).
- `any` / `required` — the model must call *some* tool.
- a named tool — the model must call *that specific* tool.

ARP modeled only `auto`: every cloud backend hardcoded `tool_choice = "auto"`
whenever tools were present, and `build_tool_contracts` returned just
`(tool_schemas, bound_tools)` with no way for a step to express intent. That
left two SDK/provider primitives unmodeled:

1. **Forcing a tool** — e.g. "verify the claim *before* you reason about it",
   which is most reliable when the first turn is *required* to call the verifier
   rather than left to the model's discretion.
2. **A shared, cross-role tool** — the exam's pattern where one verification
   primitive is available to every role/tier instead of each role re-deriving it.

---

## Decision

### 1. Thread a normalized `tool_choice` through the contract + backends

`build_tool_contracts(tier, requested_tools, tool_choice="auto")` now also
returns the **validated, normalized** choice as a third tuple element. A
single `normalize_tool_choice` helper accepts every input shape — bare strings
(`auto`/`any`/`required`/`none`), a tool name, an OpenAI
`{"type":"function","function":{"name":...}}` dict, or an Anthropic
`{"type":"tool","name":...}` dict — and canonicalizes to the OpenAI wire form.
Forcing a tool **not** in the resolved set raises `ValueError` (fail-fast on a
typo) — the choice is validated against the same allowlist/tier filter that
built the contracts, so a forced tool is always one the model actually has.

The four cloud backend call sites (`GitHubModelsBackend`, `OpenAIBackend`,
`AzureOpenAIBackend`, `AzureFoundryBackend`) take an explicit
`tool_choice="auto"` parameter instead of the hardcoded literal.
`AnthropicBackend` — which previously sent no `tool_choice` at all — maps the
OpenAI-normalized choice to Anthropic's shape (`{"type":"any"}` /
`{"type":"none"}` / `{"type":"tool","name":...}`) and **omits** the key for
plain `auto`, preserving its prior payload byte-for-byte in the default case.

### 2. Forced on turn 1, `auto` thereafter

In the native tool loop a forced/`required` choice applies **only to the first
turn**; subsequent turns revert to `auto`. Otherwise a forced choice would make
every turn emit another tool call and the loop would never terminate. This is
the standard "force the opening move, then let the model conclude" pattern.

The opt-in EK completion path does not thread `tool_choice`; when a non-`auto`
choice is requested while `AGENTIC_EK_PROVIDER` is on, the engine **logs a
warning** and proceeds with model-decided selection rather than silently
dropping the request.

### 3. `verify_fact` — a tier-0 cross-role shared tool

`verify_fact` deterministically checks whether a `claim` is grounded in supplied
`evidence` (substring / exact / numeric modes), returning a
`supported`/`unsupported` verdict and the matched span. It is registered at
**tier 0**, and because `build_tool_contracts` includes a tool when
`tool.tier <= step_tier`, a tier-0 tool is selectable by **every** tier — and
therefore by every role. That single fact is the mechanism that makes it a
genuine cross-role shared tool rather than a tier-locked one. Being
deterministic (no model call) makes it cheap, reproducible, and safe to *force*
at the start of a step.

---

## Consequences

- **Positive:** Steps can now force a specific tool, require *some* tool, or keep
  `auto` — across OpenAI-, Azure-, and Anthropic-shaped backends. Step metadata
  carries `tool_choice` end-to-end into the native loop.
- **Positive:** Forcing is validated against the resolved tool set, so a typo'd
  or out-of-tier forced tool fails fast instead of reaching a provider.
- **Positive:** `verify_fact` gives every role one shared verification primitive;
  the "verify before reasoning" pattern is expressible by forcing it on turn 1.
- **Neutral:** Default behavior is unchanged — `tool_choice` defaults to `auto`,
  Anthropic still sends no `tool_choice` key in the default path, and the EK path
  is untouched.
- **Negative:** Forced selection is honored only on the native (default) loop;
  the EK path warns and falls back. Threading it through the EK provider stack is
  deferred until that path is no longer opt-in.
