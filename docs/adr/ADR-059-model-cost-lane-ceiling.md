# ADR-059: Curated Cost Lane and a Fail-Closed Failover Ceiling

**Status:** Accepted
**Date:** 2026-08-28
**Related:** `agentic_v2/models/model_registry.py` (`CostLane`, `cost_lane_for`,
`is_within_cost_lane`, `CostLaneCeilingExceededError`),
`agentic_v2/config/defaults/model_registry.yaml` (`cost_lane` per model),
`agentic_v2/langchain/models.py` (`get_model_candidates_for_tier`,
`_max_cost_lane_ceiling`), `agentic_v2/langchain/graph_wiring.py`
(`_invoke_with_failover` lane-crossing detection). Builds on ADR-040 (curated
registry) and ADR-048 (process-wide token budget); Findings F1/F2 of the
`ARP-IMPROVEMENTS-PROMPT.md` work order.

---

## Context

The SWE-fix A/B eval campaign (`agentic-workflows-v2/evals/swe_ab/`) needed a
run that provably spent nothing. It could not get one from the runtime as
configured.

`get_model_candidates_for_tier` resolves a tier's candidate list in a fixed
order: per-step `model_override`, an env override, a UI setting, the probed
tier default, then the tier's fallback chain, then (when `GITHUB_TOKEN` is
set) the GitHub backup models. The first four are prepends; the fallback
chain always follows. `_invoke_with_failover`
(`agentic_v2/langchain/graph_wiring.py`) walks that full list whenever a
response fails the step's declared output contract. Every tier's fallback
chain in `model_registry.yaml` includes paid providers — tier 1 includes
`anthropic:claude-haiku-4-5-20251001` — so pinning a free model via
`model_override` does not confine a run to free models: a contract failure on
the pinned model still fails over into the paid chain behind it. The
campaign's first probe did exactly this and reached Anthropic, returning a
billing error on a run whose entire premise was zero cost.

Two existing mechanisms look like they should help and do not. `AGENTIC_NO_LLM`
is all-or-nothing — it replaces every model call with a placeholder, which is
not a "stay free" mode, it is a "do not call a model at all" mode. ADR-048's
`ProcessWideTokenBudget` caps cumulative *tokens* on the shared client; it says
nothing about *which providers* may be called, and a single expensive call to
a paid provider is exactly the failure this needed to prevent, not something a
token-count cap catches after the fact.

The only control that worked was environmental: the eval kit's `run_ab.py`
deletes every paid credential (`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`,
`GEMINI_API_KEY`, `GITHUB_TOKEN`, `OPENROUTER_API_KEY`,
`AZURE_OPENAI_API_KEY`, `AZURE_FOUNDRY_API_KEY`, `CLAUDE_CODE_OAUTH_TOKEN`)
from the child process environment before spawning. A provider without a key
cannot be called — free by construction. That is a correct workaround and the
wrong layer: it has nothing to do with the registry ADR-040 already
established as the single source of truth for tier membership and price, and
it protects nothing for a caller who is not the eval kit.

## Decision

Add a **curated cost lane** to every registry entry, and a **ceiling** that
`get_model_candidates_for_tier` enforces by filtering, not merely reordering.

**Schema.** `RegisteredModel.cost_lane: Literal["local", "free", "paid"] | None`
in `model_registry.py`, populated per entry in `model_registry.yaml`:

- `local` — weights on this machine; no account, no network, no charge.
- `free` — no charge, a credential may still be required, rate limits often
  undocumented (Ollama Cloud's `-cloud`-suffixed models; NVIDIA NIM's curated
  free-endpoint subset).
- `paid` — metered.

This is a judgment call, not a probeable fact — exactly the ADR-040 split
("dynamic for facts, curated for judgments"): no provider's `/models` listing
exposes billing status, the same reason `price_in`/`price_out` are a
maintained table rather than derived. `cost_lane_for(model_id)` **fails
closed**: a model absent from the registry, or present with no curated
`cost_lane`, is `"paid"`. Never guessed free, mirroring `price_for`'s
never-guessed-zero contract.

Of this repository's 12 curated entries, only the two `ollama:` ids are
`local`; every cloud id — including the three `nvidia:` ids and the two `gh:`
ids — is curated `paid`. Two of those are judgment calls worth recording
because they are not obviously "paid" from the provider name alone:

- `gh:` (GitHub Models) has a nominally free tier, but the campaign already
  treated `GITHUB_TOKEN` as a must-not-reach credential alongside the metered
  providers, because its rate limits and billing tie-in are undocumented for
  this deployment. Curated `paid` to match that demonstrated risk posture, not
  because the service is definitely metered.
- The three `nvidia:` ids in the tier chains do not string-match any entry in
  this same file's curated NIM free-endpoint block (`tiers: []`,
  ARP-IMPROVEMENTS F2) — the tier-chain ids are dateless
  (`deepseek-v4-flash`) where the confirmed-free entries are dated
  (`deepseek-v4-flash-0731`). Curated `paid` until a human confirms the alias
  resolves to the same billing, per the same fail-closed principle.

Both are one-line reversals in `model_registry.yaml` once confirmed — this ADR
does not need to be revisited for that.

**Ceiling.** `AGENTIC_MAX_COST_LANE=local|free|paid` (default `paid` — every
existing deployment is unaffected until it opts in), plus a `max_cost_lane`
keyword argument on `get_model_candidates_for_tier` for a caller that wants
the same enforcement without an env var. The ceiling filters the **entire**
candidate list, pinned entries included — an explicit `model_override` cannot
bypass the ceiling it exists to enforce, closing exactly the gap the
campaign's first probe hit. If filtering would empty an otherwise non-empty
list, `get_model_candidates_for_tier` raises
`CostLaneCeilingExceededError` naming the ceiling and the tier, rather than
returning an empty list (which a caller could easily fail to check) or
falling through to the unfiltered chain (which would silently defeat the
ceiling on the one path that most needs it to hold).

**Visibility.** `_invoke_with_failover` now compares each attempted model's
cost lane to the previous attempt's; a rank increase (`local` → `free` →
`paid`, strictly more expensive) logs a WARNING and is recorded as a
`lane_crossings` entry in the step's metadata (surfaced through
`record_step_result` on both the success and failure paths, and through the
failure trace event's outputs) — `{from_model, from_lane, to_model, to_lane}`
per crossing. The default ceiling (`paid`, unset) still *permits* a crossing;
this makes it visible rather than silent, which the campaign's original
"reached Anthropic and got a billing error" surprise was not.

## Consequences

- An operator can now make "this run may not spend money" a real, enforced
  property (`AGENTIC_MAX_COST_LANE=free`), verifiable by asserting no paid
  backend is *constructed* — not merely that no charge was observed, which the
  campaign's own eval kit had no way to prove short of pulling every
  credential from the environment.
- The eval kit's credential-stripping workaround
  (`agentic-workflows-v2/evals/swe_ab/`) is not removed by this change and is
  out of scope to touch — the campaign is in flight and that path is
  independently correct defense in depth. A future eval kit revision can
  layer `AGENTIC_MAX_COST_LANE=free` on top of it once this ships, but that is
  the eval kit's decision, not this ADR's.
- Every existing deployment is unaffected: the ceiling defaults to `paid`
  (no filtering), and no `cost_lane` curation changes which candidates are
  offered under the default. The only new default-on behavior is the
  lane-crossing WARNING log and metadata event, which is additive.
- The two open curation calls above (`gh:` and the three `nvidia:` ids) are
  conservative by design: they can only ever cause a run to reach a *cheaper*
  lane than curated once corrected, never a more expensive one than assumed
  today.

## Alternatives considered

- **Env-only control, no registry field** (e.g. a hardcoded provider
  denylist keyed on `AGENTIC_MAX_COST_LANE`). Rejected: duplicates exactly the
  "three independent sources of truth" failure ADR-040 was written to close,
  this time for cost instead of tier membership.
- **Reject/degrade `model_override` under a ceiling instead of filtering it.**
  Considered filtering only the fallback chain and leaving an explicit
  `model_override` untouched (on the theory that an explicit override is
  intentional). Rejected: this is precisely how the campaign's real incident
  happened — the override was intentional, the *chain behind it* was the
  leak. A ceiling that does not also bind the pinned entry protects nothing
  new.
- **Silently return an empty candidate list when the ceiling filters
  everything.** Rejected: a caller not defensively checking for an empty list
  degrades in an unpredictable way downstream (e.g. `IndexError`, or a step
  silently never running) rather than a clear, attributable error at the
  point of the actual constraint.
- **Probe cost lane dynamically instead of curating it.** Rejected for the
  same reason ADR-040 rejected a fully dynamic model list: no provider
  `/models` endpoint exposes billing status, so "dynamic" here would mean
  "guessed," and a wrong guess in the free direction is the one failure mode
  this change exists to close.
