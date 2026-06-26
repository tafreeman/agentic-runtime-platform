# ADR-040: Curated Single-Source Model Registry

**Status:** Accepted
**Date:** 2026-06-25
**Related:** `agentic_v2/config/defaults/model_registry.yaml` (new),
`agentic_v2/models/model_registry.py` (new), `agentic_v2/models/router.py`
(`DEFAULT_CHAINS`), `agentic_v2/langchain/models.py` (`_TIER_FALLBACK_CHAINS`,
`_TIER_DEFAULTS`), `agentic_v2/scoring/judge.py`,
`agentic_v2/langchain/model_builders.py`. Builds on the discovery story of
ADR-037/038/039; sets up the probe-time drift detection planned as a follow-up.

---

## Context

Model identifiers were declared independently in three places that drifted apart:

1. `models/router.py` — `DEFAULT_CHAINS` (native engine, per `ModelTier`).
2. `langchain/models.py` — `_TIER_FALLBACK_CHAINS` / `_TIER_DEFAULTS` (LangChain
   engine).
3. `config/defaults/agents.yaml` — per-agent `default_model` / `fallback_models`.

This triplication caused a production incident: the retired `gemini-2.0-flash`
and `gemini-2.0-flash-lite` ids began returning 404 ("model no longer
available"). The fix (PR #126) had to edit all three files by hand, and nothing
flagged that the ids were retired — it surfaced only as runtime 404s.

The three sources had also **silently diverged** on more than the retired ids:

- `router.py` pinned `anthropic:claude-sonnet-4-5-20250929` while
  `langchain/models.py` pinned `anthropic:claude-sonnet-4-6-20260219` for the
  same logical tier.
- The two engines encoded different routing *philosophies*: the native router
  **escalated** high tiers (`gemini-2.5-pro`, `claude-opus-4-6`); the LangChain
  engine stayed on `gemini-2.5-flash` / `claude-sonnet` for tiers 3–5 and added
  a local Ollama tail. Neither divergence was a deliberate, recorded decision.

## Decision

Introduce one curated registry — a YAML data file
(`config/defaults/model_registry.yaml`) plus a typed loader
(`models/model_registry.py`) — as the single source of truth for tier fallback
chains, the special-purpose model ids, and a per-token price table. Both engines
and the judge/NotebookLM call sites read from it.

**Guiding principle — dynamic for facts, curated for judgments:**

- *Dynamic* (verified at runtime): availability, health/circuit state,
  rate-limit headroom. These already come from the discovery probes
  (ADR-037/038/039), `rate_limit_tracker`, and `model_stats`.
- *Curated* (human-owned, reviewed): which models belong in which tier,
  capability classification, and per-token price. A machine cannot safely decide
  these, so they live in the registry and change only by a reviewed edit.

### Chain reconciliation

The two divergent chain sets are unified into one canonical chain per tier:
cloud-capability-first with a local Ollama tail, **escalating tiers 4–5** to
`gemini-2.5-pro` / `claude-opus-4-6`. The `sonnet-4-5` vs `sonnet-4-6`
divergence is reconciled to `claude-sonnet-4-6-20260219`. Net effect: the native
router gains the richer chains (anthropic + local tail); the LangChain engine
gains capability escalation at tiers 4–5. This is a deliberate choice favoring
capability over cost at the top tiers; it is a one-line-per-tier data edit to
revert to cost-saving flash/sonnet if desired.

### Pricing

`price_in` / `price_out` (USD per Mtok) and `context_window` live in the
registry, seeded `null`. Cost-per-token **cannot** be probed — provider
`/models` endpoints return ids only (ADR-039; `CloudModelInfo` carries only
`id`) — so price is necessarily a maintained table. `compute_spend()` turns
observed token usage into a dollar figure, or `None` when a price is uncurated
(never a guessed zero). Populating real prices and wiring `compute_spend` into
spend tracking are follow-ups.

### Scope boundaries (what the registry does NOT own)

- **`GH_BACKUP_MODELS`** stays in `langchain/model_utils.py` next to the provider
  gate (`PROVIDER_ENV_KEYS`) it belongs to. Pulling it into the registry would
  create a `model_utils` ↔ `model_registry` import cycle for a two-id fallback
  whose ids are already declared in the registry catalog.
- **Named-agent model fields** (`agents.yaml` `default_model` /
  `fallback_models`) are *not* migrated. An audit found them vestigial: agent
  model selection flows through the agent's **tier** (now registry-sourced), and
  the only reader of those fields (`/api/agents`) surfaces just
  `name`/`description`/`tier`. Adding an agents block to the registry would be
  dead, misleading data.

### Validation & provider authority

The loader validates that every id referenced by a tier chain or special slot
has a `models:` entry (catches dangling references), and that every model's
`provider` is in `PROVIDER_ENV_KEYS` — the authoritative routable-provider set,
**not** `_KNOWN_PREFIXES` (a display superset that includes keyless namespaces
like `azure:` / `windows-ai:`). Env-var precedence is preserved unchanged:
per-step `model_override` → `AGENTIC_MODEL_TIER_{n}` → probed default → registry
chain → `GH_BACKUP_MODELS`.

## Consequences

- A retired or mis-typed id is now a one-file edit, and a dangling reference
  fails loudly at load time (a unit test loads the production file and asserts no
  dangling references).
- Behavior change: both engines now use the reconciled chains; tiers 4–5 escalate
  to `gemini-2.5-pro` / `claude-opus-4-6` (a cost/capability shift for the
  LangChain engine's high tiers).
- The registry is the foundation for **probe-time drift detection** (planned
  follow-up): diff the curated catalog against the live `discover_cloud_models()`
  listings on probe and *warn + quarantine* a pinned id the provider no longer
  lists — automatically catching the next `gemini-2.0-flash`. The probe will
  **warn and filter, never auto-promote** a newly discovered id into a chain.

## Alternatives considered

- **Keep the three hand-maintained sources** — rejected; this is exactly what
  caused the incident and the silent divergence.
- **Fully dynamic model list** (discover everything at runtime, no curated file)
  — rejected: pricing is not discoverable, tier/capability assignment is a human
  judgment, and unattended auto-routing to a newly discovered, unvetted model is
  unsafe.
