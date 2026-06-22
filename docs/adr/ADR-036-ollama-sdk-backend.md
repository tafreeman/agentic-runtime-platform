# ADR-036: OllamaBackend Uses the Official `ollama` Client

**Status:** Accepted
**Date:** 2026-06-21
**Related:** `agentic_v2/models/backends_local.py` (`OllamaBackend`),
`agentic_v2/models/backends.py`, `tests/models/test_ollama_canonical.py`,
`pyproject.toml`. Supersedes the hand-rolled `httpx` transport introduced
alongside ADR-008; complements ADR-023 Phase 3 (canonical `complete_chat`
dict shape).

---

## Context

`OllamaBackend` reached the local Ollama server by hand-rolling `httpx`
requests against the native `/api/generate` and `/api/chat` endpoints,
parsing the raw JSON, and manually navigating `message.content` /
`message.thinking` / `message.tool_calls`. That bespoke parsing duplicated
work the official `ollama` Python client already does, and it had drifted
from the two *other* Ollama code paths in the repo:

- `tools/llm/provider_adapters.py::call_ollama` — a second hand-rolled
  `urllib` path that does **not** handle the reasoning `thinking` channel.
- `agentic_v2/langchain/model_builders.py::build_ollama_model` — already
  uses `langchain-ollama`, which wraps the official `ollama` client.

As a result the official `ollama` package was *already* installed in every
resolved environment (transitively via `langchain-ollama`), yet the
always-on native backend ignored it and re-implemented its wire handling —
the worst of both worlds. The native backend also ignored `OLLAMA_BASE_URL`,
which the LangChain builder and the documented model layer (`MODEL_LAYER.md`)
both honour.

A repo-wide review of Ollama usage (EK + ARP) concluded that ARP — an
application that already ships the dependency — should adopt the SDK inside
the backend, while ExecutionKit (a deliberately zero-dependency, OpenAI-wire
library) should **not**. This ADR records the ARP half. The agreed scope was
"contained": the SDK stays inside `OllamaBackend`; the `LLMBackend` interface
and the canonical return shapes do not change.

## Decision

Re-back `OllamaBackend` on `ollama.AsyncClient`:

- `complete()` calls `client.generate(...)`; `complete_chat()` calls
  `client.chat(...)`. Both pass `options={"num_predict", "temperature"}` and
  an opt-in `think` parameter.
- The canonical `complete_chat` dict (ADR-023 Phase 3) is preserved exactly:
  separate top-level `thinking`, `content` carrying only the answer text,
  `tool_calls` as a JSON-able `list[dict]` (or `None`), `finish_reason`
  `"stop"`, the requested `model` name, and `_raw_ollama`. `_raw_ollama` is
  now `ChatResponse.model_dump()` rather than the raw server JSON — a
  field-superset that still carries the full upstream message verbatim.
- SDK `Message.ToolCall` objects are normalised back to dicts via
  `model_dump()`, keeping the `{"function": {"name", "arguments"}}` shape
  downstream consumers and `ek_adapters` already expect.
- `ollama.ResponseError` is mapped to `RuntimeError`, matching the existing
  `call_ollama` convention (previously this path surfaced a raw
  `httpx.HTTPStatusError`).
- `base_url` now honours `OLLAMA_BASE_URL` (via the secrets layer), aligning
  the native backend with the LangChain builder and the documented contract.
- `ollama>=0.5.1,<1` is promoted from a transitive dependency to a direct
  core dependency, so the unconditionally-registered local backend no longer
  relies on the optional `langchain` extra being installed. `>=0.5.1` is the
  floor that guarantees the `think` parameter exists.

### Open decision: `think` policy

`think` defaults to `None`, which leaves the parameter unset and preserves
the pre-SDK behaviour (a model only emits `thinking` if it does so on its
own). `OllamaBackend._resolve_think(model_name)` is the seam for a future
per-model policy — e.g. enabling `think` only for known reasoning families
(qwen3 / deepseek-r1 / phi4-reasoning), or catching the "model does not
support thinking" error and retrying without it. Today it returns the
backend-level setting unchanged.

## Consequences

- One transport, not two-and-a-half: the bespoke `httpx` JSON parsing and the
  manual `thinking` fold-out are gone; protocol changes track the SDK.
- The reasoning `thinking` channel, structured `tool_calls`, and (via the SDK)
  `format=`-style structured outputs are now reachable without further
  wire-format work.
- Behaviour change, intentional: HTTP error responses now raise `RuntimeError`
  instead of `httpx.HTTPStatusError`, and `OLLAMA_BASE_URL` is now honoured by
  the native backend.
- `_raw_ollama` shape changed from raw server JSON to the SDK model dump. Only
  `tests/models/test_ollama_canonical.py` asserts on it; `ek_adapters`
  round-trips read the canonical fields, not `_raw_ollama`.
- `backends_local.py` remains in the coverage `omit` set (it needs a live
  server); the canonical/contract behaviour is covered by
  `tests/models/test_ollama_canonical.py` with the SDK client stubbed.
- `tools/llm/provider_adapters.py::call_ollama` is intentionally left as-is
  for this contained change; converging it onto the SDK is a follow-up.
