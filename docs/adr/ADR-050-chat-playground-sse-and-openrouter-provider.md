# ADR-050: SSE Chat Playground Endpoint and a First-Class OpenRouter Provider

**Status:** Accepted
**Date:** 2026-07-12
**Related:** `agentic_v2/contracts/chat.py` (new — `ChatRequest`,
`ChatStreamEvent`), `agentic_v2/server/routes/chat.py` (new — `POST
/api/chat`), `agentic_v2/langchain/model_builders.py`
(`build_openrouter_model`), `agentic_v2/models/backends_cloud.py`
(`OpenRouterBackend`), `agentic_v2/models/cloud_discovery.py` (OpenRouter
discovery), `ui/src/pages/ModelFinderPage.tsx` (playground tab). ADR-014
(wire-format drift gate), ADR-039 (cloud model discovery), ADR-040 (curated
model registry).

## Context

The model probe (ADR-037/038/039) and curated registry (ADR-040) say what
models exist and which providers look configured, but neither exercises a
real call. `is_provider_available()` (`agentic_v2/langchain/model_utils.py`,
gated by `PROVIDER_ENV_KEYS`) is env-presence detection only — a provider
reads "available" when its key env var is non-empty, and every local
provider (`ollama`/`local`/`onnx`/`lmstudio`/`local_api`) maps to an empty
key list and is hard-coded `True` regardless of whether its server is
actually up. Nothing confirms a key authenticates or an id is invocable
short of wiring it into a full workflow run and watching it fail. Every
invocation path also runs through `SmartModelRouter` tier selection or a
workflow step — no direct "send this model this message" surface existed.

Separately, the runtime had no OpenRouter provider at all — not in
`PROVIDER_ENV_KEYS`, cloud discovery, or the native backends — despite it
being a widely held single-key aggregator in front of several hundred
models. A chat playground closes both gaps at once: a real, model-exact
call path doubles as the liveness check `is_provider_available` cannot be,
and building it against OpenRouter gives it real breadth from day one.

## Decision

- **Wire contract.** Add `POST /api/chat` backed by
  `agentic_v2/contracts/chat.py`: `ChatRequest {model: <full prefixed id>,
  messages: [{role, content}], temperature=0.2}` and a streamed
  discriminated-union `ChatStreamEvent`: `token {delta}` | `done {model}`
  | `error {message, category}`. Both join the ADR-014 drift pipeline as
  a fourth generated pair — `scripts/generate_ts_types.py` and
  `ui/scripts/generate-ts-types.mjs` gain `chat_request` /
  `chat_stream_event` schema+TS generation, and the `wire-format-drift`
  CI file list grows to match.
- **Transport: SSE via `StreamingResponse`, not `/ws`.** Chat is a
  single request-scoped, unidirectional stream — the shape the runs
  endpoint (`GET /api/runs/{id}/stream`) already serves over SSE, riding
  standard HTTP auth (`Depends(get_tenant_context)`) rather than the
  bespoke `_reject_websocket_connection` path (`server/websocket.py`,
  ~90 lines of origin/query-token/throttle/API-key checks needed because
  `WebSocket.accept()` predates FastAPI dependency auth). Unlike the
  runs stream, which fans one run out to every subscribed viewer via
  `ConnectionManager`'s listener registry and replay buffer, a chat call
  has one consumer and no reconnect/replay need, so a plain async
  generator over the provider's token stream suffices — no
  `ConnectionManager` coupling. The reserved `TokenDeltaEvent` in
  `contracts/events.py` stays untouched: it is run/step-scoped by
  contract, and chat events are a separate union, not a repurposing of
  `run_id`.
- **Errors are in-stream, never a non-200 status.** The endpoint always
  returns HTTP 200; provider failures (401, 429, connection refused,
  unknown prefix, missing key) surface as `error` events with `category`
  from the existing `core.errors.classify_error()` and a scrubbed
  `message` (Bearer/API-key patterns redacted, length-capped).
- **Direct-model requests bypass tier selection by design.** The original
  handler builds the exact picked model via `get_chat_model(full_id)` and
  calls it directly, preserving the Playground's "does this one id work?"
  behavior.
- **2026-07-14 amendment — tier overload.** `ChatRequest` now exposes two
  strict constructors: `{model, messages, temperature?}` and
  `{tier, messages, temperature?}`. The tier form resolves the existing
  ordered candidate chain and emits `route {requested_tier, model}` before
  output tokens. Both/neither selectors are invalid. Direct-model behavior is
  unchanged, while HTTP clients can delegate provider/model selection without
  duplicating router policy.
- **OpenRouter joins as a supported provider.**
  `PROVIDER_ENV_KEYS["openrouter"] = ["OPENROUTER_API_KEY"]`;
  `build_openrouter_model` is a `ChatOpenAI` base-URL swap
  (`https://openrouter.ai/api/v1`, `X-Title` header, model id passed
  verbatim) — safe under `provider_prefix`'s first-colon-only split
  (`model_id.split(":")[0]`) even though ids are `publisher/model` with
  an optional trailing `:free`. The native engine gets parity via
  `OpenRouterBackend(OpenAIBackend)`. No `model_registry.yaml`
  tier-chain entry is added — mirrors the NVIDIA precedent (keyed, also
  absent from curated chains): reachable via explicit id or override,
  probe-visible via discovery, while chain membership stays curated per
  ADR-040.
- **Discovery deviations, scoped to OpenRouter only.** ADR-039's
  providers stay uncached by design; OpenRouter uses a 300s TTL around
  `GET /models` because its catalog is large and near-static. The public
  endpoint is queried with `output_modalities=all`, with optional bearer
  auth when `OPENROUTER_API_KEY` exists, and every text-output chat model
  is retained. A small static list is used only when the live request
  fails or returns no compatible models. This required an honesty fix:
  `_merge_cloud_models`
  (`langchain/models.py`) now derives `available` from
  `is_provider_available(provider)` per model instead of hard-coding
  `True` — unchanged in practice for the four ADR-039 providers, but now
  correct for OpenRouter's no-key fallback. Discovered ids keep `tier 0`.
- **UI: a tab inside `ModelFinderPage`, not a new route.** Smallest
  diff — a new route would also touch `App.tsx` (route table),
  `Sidebar` (nav entry), and `useGoNav` (route registry). The TS side
  gets hand-maintained mirror/narrowing code in `ui/src/api/types.ts`,
  consistent with the pattern ADR-014 already sets for discriminated-
  union event consumption. The tab's enabled state reads the probe's
  `no_llm_mode` (env-read at probe time), not `/api/health`'s
  `effective_no_llm_mode()` (the constructed client's actual backend) —
  the two can diverge, and the playground is a probe-adjacent surface.

## Consequences

- Operators get a real per-model, per-key liveness check for the first
  time: a call that either streams tokens back or reports a classified,
  scrubbed failure, independent of workflow wiring.
- OpenRouter becomes invokable by id (`openrouter:<publisher>/<model>`)
  everywhere `get_chat_model` is reachable, and shows up in the probe
  like any other keyed provider.
- Two more hand-maintained blocks land in each TS-generation script and
  in the `wire-format-drift` CI file list — the same cost every prior
  contract addition has paid.
- SSE frames are uncompressed JSON-per-token; fine at chat scale, not a
  transport to reuse for a bulk/batch streaming need.
- The full OpenRouter chat catalog can be large; the provider-card summary,
  collapsed detail groups, and catalog search keep it navigable.
- Always-200-with-in-stream-errors means HTTP-status-based monitoring
  will not see chat provider failures — legible only to a consumer
  reading the event stream, the usual tradeoff of an in-band error
  channel.

## Alternatives considered

- **WebSocket transport, reusing `/ws/execution`.** Rejected: chat has
  none of the fan-out/reconnect-replay needs that justify
  `ConnectionManager` and `_reject_websocket_connection` — ~90 lines of
  bespoke auth for a stream SSE already serves more simply.
- **Route chat through `SmartModelRouter`/tier selection.** Rejected:
  the playground tests one exact id a caller picked, not router
  fallback behavior — already covered ground (ADR-002, ADR-040).
- **Formalize OpenRouter into the curated registry** — a
  `model_registry.yaml` tier-chain entry, or a price-derived 1-5 tier
  for discovered ids. Rejected on both counts: tier is a
  chain-membership signal here (ADR-040), not a price band, and an
  unvetted rotating catalog doesn't belong in reviewed chain
  membership — the exact drift ADR-040 exists to stop. `tier_overrides`
  remains the sanctioned way to promote a specific id.
- **Dump OpenRouter's full catalog into the probe.** Initially rejected, then
  superseded on 2026-07-14: the UI now provides provider summary cards,
  collapsed details, and search, so the full compatible catalog is both useful
  and navigable.
- **New top-level `/chat` route.** Rejected in favor of a
  `ModelFinderPage` tab: the nav/routing surface (`App.tsx`, `Sidebar`,
  `useGoNav`) is a larger diff for a feature that is conceptually "do
  something with a model I just found."
