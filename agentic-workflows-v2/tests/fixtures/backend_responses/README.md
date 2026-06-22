# Backend Response Fixtures

These JSON files are **synthetic regression oracles** for the
ADR-023 Option A migration (see `docs/adr/ADR-023-migration-notes.md`,
phase P0).

## What they are

Each file is the literal dict that the corresponding backend's
`complete_chat(...)` is documented to return for a short user prompt
("Hello!"-style). The shapes are derived directly from the existing
adapter source code:

- `agentic_v2/models/backends_cloud.py`
  - `OpenAIBackend.complete_chat` — `openai_basic.json`
  - `AnthropicBackend.complete_chat` — `anthropic_basic.json`
  - `GeminiBackend.complete_chat` — `gemini_basic.json`
- `agentic_v2/models/backends_local.py`
  - `OllamaBackend.complete_chat` (normal) — `ollama_basic.json`
  - `OllamaBackend.complete_chat` (reasoning model) — `ollama_thinking.json`

## What they are NOT

- **Not live recordings.** No live API was called to produce these.
- **Not a contract owned by an upstream vendor.** The shape is owned by
  *our* adapter return value (the dict literal at the end of each
  `complete_chat`), not by OpenAI / Anthropic / Google / Ollama
  themselves. Vendor field names are present where the adapter passes
  them through unmodified (e.g. Gemini's raw camelCase
  `usageMetadata`, Anthropic's raw `input_tokens`/`output_tokens`).
- **Not normalized.** Intentionally so. The whole point of P0 is to
  pin the *current* unnormalized shapes so Phase 4 can prove the
  adapter round-trip is loss-less.

## Per-fixture provenance

| Fixture                  | Source method                                  | Source file lines (current `main`) | Notable raw shapes preserved |
|--------------------------|------------------------------------------------|------------------------------------|------------------------------|
| `openai_basic.json`      | `OpenAIBackend.complete_chat`                  | `backends_cloud.py` ~206-212       | `usage` uses `prompt_tokens` / `completion_tokens` / `total_tokens`; `finish_reason` is `"stop"`. |
| `anthropic_basic.json`   | `AnthropicBackend.complete_chat`               | `backends_cloud.py` ~317-323       | `tool_calls` is a list of raw `tool_use` blocks (id/name/input); `finish_reason` is Anthropic's `stop_reason` (`"end_turn"`); `usage` uses `input_tokens` / `output_tokens`. |
| `gemini_basic.json`      | `GeminiBackend.complete_chat`                  | `backends_cloud.py` ~420-426       | `finish_reason` is the raw UPPERCASE `"STOP"`; `usage` is the raw camelCase `usageMetadata` (`promptTokenCount` / `candidatesTokenCount` / `totalTokenCount`). |
| `ollama_basic.json`      | `OllamaBackend.complete_chat` (chat model)     | `backends_local.py` ~118-123       | No `usage` key (Ollama chat does not return token counts in this shape); `finish_reason` hard-coded to `"stop"`. |
| `ollama_thinking.json`   | `OllamaBackend.complete_chat` (reasoning model) | `backends_local.py` (`complete_chat`) | `content` is empty; `thinking` is preserved separately. The adapter keeps `thinking` as its own top-level key and leaves `content` empty for thinking-only turns — no fold-in (open decision #6 `ollama-thinking-marker` resolved by ADR-023 Phase 3; transport now the official `ollama` client per ADR-036). |

## How they will be used

In Phase 4, the adapter conformance suite will load each fixture,
feed it through the EK adapter round-trip, and assert that:

1. The round-trip is loss-less for everything the freeze rule covers.
2. Any normalization that lands on top (e.g. Gemini camelCase ->
   `TokenUsage`) is done at the documented seam and nowhere else.
3. The reasoning-model path produces a deterministic result once the
   ollama-thinking-marker decision is accepted.

## Adding a new fixture

- Read the adapter source first; do not invent fields.
- Keep prompts short and content boring — these are oracles, not
  prose samples.
- Update the table above with file + line range.
- Tests that consume fixtures must run with `AGENTIC_NO_LLM=1` (no
  live keys, no network).
