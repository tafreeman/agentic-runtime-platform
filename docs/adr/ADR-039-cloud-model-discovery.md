# ADR-039: Live Model Discovery for Keyed Cloud Providers

**Status:** Accepted
**Date:** 2026-06-23
**Related:** `agentic_v2/models/cloud_discovery.py` (new),
`agentic_v2/langchain/models.py` (`enumerate_known_models`, `_merge_cloud_models`),
`ui/src/pages/ModelFinderPage.tsx`. Completes the discovery story begun in
ADR-037 (Ollama) and ADR-038 (LM Studio + ONNX) by extending it to the hosted
providers.

---

## Context

ADR-037/038 made the model-router probe reflect what the **local** providers
(Ollama, LM Studio, ONNX) can actually run. The hosted providers the runtime
already builds backends for — OpenAI, Anthropic, Google Gemini, GitHub Models —
remained represented only by the one or two ids pinned in the static tier
chains. An operator with a valid key could invoke any model the key reaches, but
the console listed almost none of them, so the cloud groups looked nearly empty
next to the (now full) Ollama group.

## Decision

Add `agentic_v2/models/cloud_discovery.py` with one best-effort discovery
function per provider, aggregated by `discover_cloud_models()` and merged into
`enumerate_known_models()` via `_merge_cloud_models()`. Each provider is probed
**only when its key env var is set** (no key → no network call):

- **OpenAI** (`openai:`) — `GET {base}/models`, `Authorization: Bearer
  $OPENAI_API_KEY`. `OPENAI_BASE_URL` / `OPENAI_API_BASE` honored for
  proxies/Azure; `OPENAI_ORG_ID` forwarded.
- **Anthropic** (`anthropic:`) — `GET https://api.anthropic.com/v1/models`,
  `x-api-key` + `anthropic-version` headers.
- **Google Gemini** (`gemini:`) — `GET …/v1beta/models?key=…`, filtered to
  models advertising `generateContent`; the `models/` name prefix is stripped.
- **GitHub Models** (`gh:`) — `GET https://models.github.ai/catalog/models`,
  `Authorization: Bearer $GITHUB_TOKEN`. Ids keep their `publisher/model` form
  (e.g. `gh:openai/gpt-4.1`) to match the `gh:` backend's name resolution.

A shared name-heuristic filters obvious non-chat ids (embeddings, speech, image,
rerank, …); the filter is deliberately conservative (a discovery console
tolerates an over-listed model better than a silently-dropped one). Discovered
ids absent from every tier chain are appended at `tier 0`, `available: True`
(plain ids — no cloud/running metadata). The UI groups by provider prefix, so
the existing `openai` / `anthropic` / `gemini` / `gh` groups simply fill out
with **no UI change**.

### No-LLM gating

`_merge_cloud_models()` is skipped entirely when `AGENTIC_NO_LLM` is set. That
mode routes every tier to the deterministic placeholder, so a live cloud listing
would be misleading; gating there also makes the unit suite (which runs with
`AGENTIC_NO_LLM=1`) hermetic without per-test patching, and avoids needless
network/cost on the no-key CI baseline. Local discovery (localhost, free) stays
ungated; cloud discovery (internet, metered) does not.

## Consequences

- The model router now lists what **every configured key** can reach, across all
  local and cloud providers — the console reflects the operator's real surface.
- Each rescan performs up to four extra HTTPS calls (only for keyed providers),
  each bounded by an 8 s timeout and guarded so a failure (network, auth, schema
  drift) contributes nothing rather than failing the probe. Keys are sent as
  auth headers/params and never logged.
- The chat-vs-non-chat split is a name heuristic, not an authoritative
  capability check; a provider renaming conventions could mis-classify a model
  until the marker list is updated. This is cosmetic (console listing only) — it
  never blocks invoking a model by id.
- No wire-format change: the probe endpoint already returns
  `list[dict[str, Any]]` and the UI `ProbedModel` type already carries the
  optional fields, so no schema/TS regeneration is required.
