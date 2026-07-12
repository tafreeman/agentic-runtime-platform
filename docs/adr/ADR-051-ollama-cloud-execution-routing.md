# ADR-051: Local-First Ollama Cloud Execution Routing and NVIDIA Registry Rungs

**Status:** Accepted
**Date:** 2026-07-12
**Related:** `agentic_v2/langchain/model_builders.py` (`build_ollama_model`,
`_ollama_served_locally`), `agentic_v2/models/ollama_discovery.py`
(`local_model_names`), `agentic_v2/config/defaults/model_registry.yaml`
(tier chains), `agentic_v2/models/model_registry.py`
(`_DEFAULT_ULTIMATE_FALLBACK`). ADR-037 (Ollama discovery), ADR-039 (cloud
discovery), ADR-040 (curated model registry), ADR-050 (chat playground /
OpenRouter precedent).

## Context

ADR-037 gave discovery two Ollama sources: the local daemon
(`OLLAMA_BASE_URL`, default `http://localhost:11434`) and — when
`OLLAMA_API_KEY` is set — the hosted **ollama.com** cloud catalog via Bearer
auth. Execution, however, had only one path: `build_ollama_model` always
targeted the local daemon, unauthenticated.

That split produced a listing-vs-execution gap observed live on 2026-07-12:
with a valid `OLLAMA_API_KEY`, `/api/models/probe` advertised ~30 hosted
models (`gpt-oss:120b`, `glm-5`, `kimi-k2.5`, …) that the local daemon could
not serve — any workflow step routed to one failed with
`model not found (status code: 404)`. A direct
`POST https://ollama.com/api/chat` with the same key succeeded, proving the
gap was ours, not the account's.

The same failed run exposed registry drift of a second kind (ADR-040 makes
tier membership a curated judgment, so retired ids linger until edited):

- `openai:gpt-4o` / `openai:gpt-4o-mini` could **never** serve in this
  deployment — `OPENAI_BASE_URL` is aliased to NVIDIA NIM
  (`integrate.api.nvidia.com/v1`, `OPENAI_API_KEY` == `NVIDIA_API_KEY`), whose
  catalog has no such ids. The boot drift check quarantined them on every
  start.
- `anthropic:claude-sonnet-4-6-20260219` was dropped from Anthropic's
  `/v1/models` listing (the undated `claude-sonnet-4-6` alias remains).
- The local tail models (`ollama:gemma3:4b` tier 1, `ollama:qwen3:8b` tier 2,
  and `special.tier_ultimate_fallback`) referenced models no longer kept
  pulled on the workstation, so the "always works offline" rung 404'd too.

## Decision

**Execution follows discovery, local-first.** `build_ollama_model` now:

1. Serves any model present in the local daemon's `/api/tags` (exact tag or
   `:latest` alias) from `OLLAMA_BASE_URL`, exactly as before.
2. Routes a model **absent locally** to `https://ollama.com` with
   `Authorization: Bearer $OLLAMA_API_KEY` on both the sync and async
   clients — but only when the key is set.
3. Without `OLLAMA_API_KEY`, behavior is byte-for-byte unchanged (no probe,
   no cloud attempt), keeping the keyless/no-LLM baseline hermetic.

The tags lookup is memoised in `ollama_discovery.local_model_names()` with a
60 s TTL so routing costs one local round-trip per window, not one per model
build; a failed probe caches an empty set (a down daemon then defers to the
cloud when a key exists, which is the best remaining option anyway).

**Registry rungs point at ids their providers actually list.** In this
deployment the `openai:` slot cannot serve OpenAI ids, so its chain rungs move
to the first-class `nvidia:` provider (live-verified completions on
2026-07-12): `nvidia:meta/llama-3.1-8b-instruct` (tier 1),
`nvidia:deepseek-ai/deepseek-v4-flash` (tiers 2–3),
`nvidia:deepseek-ai/deepseek-v4-pro` (tiers 4–5). The dated sonnet id becomes
the undated `anthropic:claude-sonnet-4-6` alias. Local tails move to models
actually pulled (`ollama:gemma4:31b` tier 1, `ollama:qwen3-coder:30b`
tiers 2–5 and `tier_ultimate_fallback`, mirrored in
`_DEFAULT_ULTIMATE_FALLBACK`). The `gh:` rungs stay: GitHub Models still
lists them; they revive when the token is rotated.

## Alternatives considered

- **`ollama signin` + pulling cloud stubs on the daemon** — zero code, but
  per-machine state the repo cannot see or test; the catalog/execution gap
  would silently reopen on any host without the signin.
- **Routing by `:cloud`/`-cloud` name suffix only** — misses the point: the
  cloud catalog serves unsuffixed names (`gpt-oss:120b`), which is exactly
  what discovery advertises and workflows route to.
- **A separate `ollama_cloud:` provider prefix** — honest but leaks into
  every chain, agent default, and UI filter; local-first fallback inside the
  existing prefix keeps ids stable while models move between local and
  hosted.
- **Dropping `openai:` rungs without replacement** — leaves tiers 2–5 with
  one cloud rung (gemini) while anthropic is credit-blocked and gh
  token-blocked; the NVIDIA rungs restore real fallback depth.

## Consequences

- Cloud-catalog ollama models advertised by the probe now execute; the
  routing decision is invisible to callers (same `ollama:` ids end-to-end).
- Prompts sent to an `ollama:` model absent locally now leave the machine
  (to ollama.com) **when the operator has set `OLLAMA_API_KEY`** — setting
  the key is the explicit opt-in for hosted execution, matching what it
  already meant for discovery.
- A model pulled locally mid-process is picked up within the 60 s TTL; until
  then it may serve one more call from the cloud. Acceptable for a fallback
  path.
- The quarantine mechanism (ADR-040) stays the drift alarm: this ADR clears
  today's standing quarantines; future retirements should get the same
  deliberate registry edit rather than permanent warn-noise.
