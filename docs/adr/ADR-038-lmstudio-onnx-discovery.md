# ADR-038: Live Discovery for LM Studio and ONNX Local Models

**Status:** Accepted
**Date:** 2026-06-21
**Related:** `agentic_v2/models/local_discovery.py` (new),
`agentic_v2/langchain/models.py` (`enumerate_known_models`),
`agentic_v2/langchain/model_utils.py` (`PROVIDER_ENV_KEYS`),
`ui/src/pages/ModelFinderPage.tsx`. Extends ADR-037 (live Ollama discovery) to
the other two local providers the runtime already supports.

---

## Context

ADR-037 made the model router probe reflect what **Ollama** actually has (local +
cloud). The runtime also supports two other local providers that remained
invisible in the router — only their static tier-chain entries (if any) showed:

- **LM Studio** (`lmstudio:` prefix) — an OpenAI-compatible local server.
- **ONNX** (`onnx:` / `local:` prefix) — onnxruntime-genai model folders.

Operators with large local libraries (GGUF served by LM Studio; Phi-4 / Qwen
ONNX folders under the AI Dev Gallery / AI Toolkit / Foundry caches) could *run*
these models by id, but the console never listed them, so they were undiscoverable.

## Decision

Add `agentic_v2/models/local_discovery.py` with two best-effort discovery
functions, merged into `enumerate_known_models()` exactly like the Ollama source.
Both return `LocalModelInfo` records (id + optional `running` / `capabilities`)
so the console can render the same badges it draws for Ollama:

- **`discover_lmstudio_models()`** — prefers LM Studio's current **native** REST
  API `GET {host}/api/v1/models`, which lists the whole downloaded library,
  loaded instances, and capabilities. Legacy native `GET {host}/api/v0/models`
  and OpenAI-compatible `GET {host}/v1/models` are ordered fallbacks. Non-chat
  types are filtered; loaded instances set `running`, and v1 vision, tool-use,
  and reasoning metadata become capability badges. `LM_API_TOKEN` is sent as a
  bearer token when configured. The host comes from
  `resolve_lmstudio_host()`: `LMSTUDIO_HOST` wins, else `:1234` (LM Studio
  default) is probed then `:12340` (legacy ARP port), first reachable winning.
  Returns `lmstudio:<id>`.
- **`discover_onnx_models()`** — bounded-depth filesystem walk for
  `genai_config.json` under each ONNX root from `parse_onnx_roots()`:
  `ONNX_MODEL_DIR` / `AIGALLERY_CACHE` (one or more roots, `os.pathsep`-separated)
  plus the `~/.cache/aigallery` default (always appended). Returns
  `onnx:<relpath>`, where `relpath` is the model folder **relative to the root it
  was found under** — exactly what `OnnxBackend` resolves against, so every
  discovered id is runnable (**discovered == runnable**).

The **discovered == runnable** invariant is enforced by sharing resolution: the
`lmstudio` backend builds its base URL via `resolve_lmstudio_host()`, and
`OnnxBackend` resolves `onnx:` ids via `parse_onnx_roots()` (with `~` expansion),
so the backend always targets the host / searches the roots discovery scanned.

`enumerate_known_models()` enriches matching catalog entries and appends the rest
as `tier 0`, `available: True` (carrying `running` / `capabilities` when present).
`onnx` is in `PROVIDER_ENV_KEYS` (no key required) so the router marks the group
available rather than "no keys". The UI groups by provider prefix, so the
`lmstudio` and `onnx` groups appear with **no UI change**.

Both are best-effort: a down LM Studio server or an absent/*unreadable* ONNX root
contributes nothing, so the endpoint degrades to the prior catalog. Each HTTP
probe is bounded by a 4 s timeout; the filesystem walk is bounded to depth 6.

### Amendment (2026-06-23)

The first cut shipped a narrower form than the decision above: discovery hit only
`/v1/models` on a single `LMSTUDIO_HOST` (default `:12340`), and ONNX returned
nothing unless a root was explicitly configured. In practice LM Studio surfaced
just the one or two *loaded* models (vs. Ollama's full library) and ONNX stayed
dark for operators using the default aigallery cache. This amendment restores the
intended behavior and extends it: native-API preference with `/v1` fallback,
the `:1234`→`:12340` probe shared with the backend, the `~/.cache/aigallery`
default, multi-root scanning, an `expanduser()` fix in `OnnxBackend`, and richer
`LocalModelInfo` records (running / vision).

### Amendment (2026-07-14)

LM Studio's current native API is now `/api/v1/models`. Discovery probes it
first and retains `/api/v0/models` plus `/v1/models` as compatibility fallbacks.
The same `LM_API_TOKEN` used by authenticated LM Studio servers is applied to
both discovery and inference, preserving the discovered-is-runnable invariant.

## Consequences

- The model router now lists **all three** local providers (Ollama, LM Studio,
  ONNX) plus cloud — what is actually runnable, surfaced on "rescan".
- **ONNX is immediate** for models already under the default aigallery cache;
  `.aitk` / `.foundry` roots require pointing `ONNX_MODEL_DIR` at them (the
  `OnnxBackend` resolves a single root, so discovery follows it to keep
  discovered == runnable).
- **LM Studio** lights up once its server is running; with it down, the group is
  simply empty.
- GGUF files (LM Studio's library) are surfaced via the LM Studio server, not by
  scanning `~/.models` — serving them is LM Studio's job; importing them into
  Ollama (`ollama create`) is the alternative path for the Ollama group.
- The probe endpoint now also performs a local HTTP call + a bounded filesystem
  walk per rescan; both are guarded so failures never reach the caller.
