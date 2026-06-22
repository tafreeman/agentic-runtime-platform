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
functions, merged into `enumerate_known_models()` exactly like the Ollama source:

- **`discover_lmstudio_models()`** — `GET {host}/v1/models` (OpenAI-compatible).
  Host from `LMSTUDIO_HOST` / `LM_STUDIO_HOST`; with none set, common ports
  (`1234`, then `12340`) are tried and the first reachable host wins. Returns
  `lmstudio:<id>`.
- **`discover_onnx_models()`** — bounded-depth filesystem walk for
  `genai_config.json` under the ONNX root (`ONNX_MODEL_DIR` / `AIGALLERY_CACHE`,
  default `~/.cache/aigallery`). Returns `onnx:<relpath>`, where `relpath` is the
  model folder **relative to that root** — i.e. exactly what `OnnxBackend`
  resolves against, so every discovered id is runnable (discovered == runnable).

`enumerate_known_models()` appends these as `tier 0`, `available: True` entries
(plain ids — no cloud/capabilities/running metadata, which are Ollama-specific).
`onnx` is added to `PROVIDER_ENV_KEYS` (no key required) so the router marks the
group available rather than "no keys". The UI groups by provider prefix, so new
`lmstudio` and `onnx` groups appear with **no UI change**.

Both are best-effort: a down LM Studio server or an absent/*unreadable* ONNX root
contributes nothing, so the endpoint degrades to the prior catalog. The HTTP
probe is bounded by a 4 s timeout; the filesystem walk is bounded to depth 6.

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
