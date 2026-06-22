# ADR-037: Live Ollama Model Discovery via the Raw REST API

**Status:** Accepted
**Date:** 2026-06-21
**Related:** `agentic_v2/models/ollama_discovery.py` (new),
`agentic_v2/langchain/models.py` (`enumerate_known_models`),
`agentic_v2/server/routes/models.py` (`GET /api/models/probe`),
`ui/src/pages/ModelFinderPage.tsx`, `ui/src/api/types.ts` (`ProbedModel`).
Builds on ADR-036 (OllamaBackend on the official client). Complements the
`tools/llm` discovery scan's separate `ollama_cloud` provider.

---

## Context

The console's model probe (`GET /api/models/probe` → `enumerate_known_models()`)
returned a **static** list: only the models hardcoded in `_TIER_FALLBACK_CHAINS`,
annotated with provider-level credential availability. It never asked the Ollama
server what was actually installed, so locally-pulled models did not appear and
cloud models (Ollama's hosted offering) were invisible — the "probe" probed
*credentials*, not *models*.

A first pass (same session) wired a live probe in using the official `ollama`
client's `Client.list()`. Researching the API (docs.ollama.com, OpenAPI spec)
surfaced two problems with that transport:

1. **The pinned client is lossy.** `ollama` 0.6.1's typed `ListResponse.Model`
   exposes only `model / modified_at / digest / size / details`. The wire
   `/api/tags` response also carries `capabilities` and — per the OpenAPI spec —
   `remote_model` / `remote_host`, which the typed model drops.
2. **`remote_host` is the authoritative cloud marker.** A signed-in local
   server proxies cloud models into its own `/api/tags`, stamping them with
   `remote_host` / `remote_model`. That is a far more reliable cloud signal than
   guessing from a `:cloud` / `-cloud` name suffix.

Cloud access has two documented forms: `ollama signin` (local server proxies to
ollama.com transparently) or an API key (`OLLAMA_API_KEY`, `Authorization:
Bearer`, against `https://ollama.com/api`). An Ollama Pro plan raises cloud rate
limits but does not, by itself, expose the catalog to a headless probe.

## Decision

Add a dedicated best-effort discovery module, `agentic_v2/models/ollama_discovery.py`,
that reads the **raw** Ollama REST API over `httpx` (not the typed client):

- `GET {OLLAMA_BASE_URL}/api/tags` — local models (includes proxied cloud models
  when signed in).
- `GET {OLLAMA_BASE_URL}/api/ps` — locally loaded models, to set a `running` flag.
- `GET https://ollama.com/api/tags` with a bearer token — the hosted cloud
  catalog, **only when `OLLAMA_API_KEY` is set** (no key → no network call).

It returns `OllamaModelInfo(id, name, cloud, capabilities, running, size,
remote_host)` records, de-duplicated local-first. Cloud is classified by
`remote_host` / `remote_model` first, falling back to the `:cloud` / `-cloud`
suffix; models from the hosted endpoint are always `cloud=True`.

`enumerate_known_models()` merges these records into the probe output: catalog
models that are present are marked available and enriched with
`cloud` / `capabilities` / `running`; discovered models absent from every tier
chain are appended at `tier 0`. The `ProbedModel` API/TS type gains optional
`cloud` / `capabilities` / `running`; the model-router page renders capability
chips, a cloud badge, and a running indicator, keeping everything under the one
`ollama` provider group (cloud distinguished by badge + suffix).

Discovery is **best-effort**: any probe failure (unreachable server, bad key,
`/api/ps` down) contributes no entries, so the endpoint degrades to the static
catalog instead of erroring. Timeouts are short (5s) so the on-demand probe
never hangs. The API key is never logged.

## Consequences

- The console now reflects what is *actually runnable*: real local models,
  their capabilities (`tools` / `thinking` / `vision`), whether they are loaded,
  and — with a key or signin — cloud models, all surfaced on "rescan".
- Discovery is decoupled from the lossy SDK; protocol additions (new `/api/tags`
  fields) are picked up by reading raw JSON. The `ollama` client remains the
  transport for actual inference in `OllamaBackend` (ADR-036).
- The probe endpoint now performs network I/O to the local Ollama (and cloud
  when keyed). It is an explicit on-demand probe, bounded by timeouts and
  guarded so failures never surface to the caller.
- Cloud end-to-end requires the operator to set `OLLAMA_API_KEY` (or sign in);
  Ollama Pro alone is insufficient. Documented in `MODEL_LAYER.md`.
- The `tools/llm` discovery scan keeps its own id-list contract and separate
  `ollama_cloud` provider; this ADR governs the runtime/app path only.
