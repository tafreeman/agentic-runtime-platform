# Work order — close the model-discovery and cost-control gaps in ARP

[Kit](../README.md) · [Docs](README.md) — **findings**, a work order; live until done

A self-contained prompt for an agent working in **agentic-runtime-platform**.
Nothing from the originating session is needed. The findings are grounded in a
real campaign; the evidence for each is cited so none of it has to be taken on
trust.

**Origin:** the SWE-fix A/B campaign in
`agentic-workflows-v2/evals/swe_ab/`. Running ~360 graded cases against ARP
workflows on free models exposed three platform-level gaps that the eval kit had
to work around rather than configure. Working around them is not a fix, and the
next eval will hit the same wall.

**The two headline problems, in one line each:**

1. **ARP will spend money on its own and cannot be told not to.** Failover walks
   the tier chain into paid providers when a step's output misses its contract.
   There is no flag that stops it — the only control that works is deleting the
   credentials from the process environment.
2. **ARP discovers four of seven serving paths on this machine**, and has no
   concept of which models cost money — so it cannot make a cost decision even
   in principle.

---

## Paste-ready prompt

```
You are improving agentic-runtime-platform's model discovery and cost controls.

REPO
C:/Users/tandf/source/agentic-runtime-platform

READ FIRST
- docs/adr/ADR-040-curated-model-registry.md   — the registry is human-curated
- docs/adr/ADR-048-process-wide-token-budget.md — the existing budget mechanism
- docs/NO_LLM_MODE.md                          — the existing all-or-nothing switch
- agentic-workflows-v2/evals/swe_ab/docs/MODEL-PROBE-GUIDE.md — probing procedure
- agentic-workflows-v2/evals/swe_ab/docs/BEST-PRACTICES.md §3, §4

Confirm the current branch and its relationship to origin/main before branching.
Do not assume this repo is on main.

Work the findings below in order. F1 and F2 are the ones that matter; F3-F8 are
smaller and can be folded in or deferred with a note. Report what you changed,
what you deferred, and the test results.
```

---

## F1 — Failover reaches paid providers, and nothing can stop it

**Severity: high. This is the one that costs money.**

`_invoke_with_failover` (`agentic-workflows-v2/agentic_v2/langchain/graph_wiring.py:642`)
walks `model_candidates` in order when a response fails the step's declared
output requirements. The candidate list comes from
`get_model_candidates_for_tier` (`agentic-workflows-v2/agentic_v2/langchain/models.py:728`),
whose documented resolution order is:

1. per-step `model_override`
2. env `AGENTIC_MODEL_TIER_{tier}`
3. UI settings tier override
4. probed tier default
5. **tier fallback chain**
6. **GitHub backup models when `GITHUB_TOKEN` is configured**

Steps 1–4 only **prepend**. The fallback chain still follows, and the chain
contains paid providers — `anthropic:claude-haiku-4-5-20251001` sits in tier 1
of `agentic_v2/config/defaults/model_registry.yaml` today. So pinning a free
model with `model_override` does **not** confine a run to free models.

**Observed:** the first probe of this campaign reached Anthropic and returned a
billing error, on a run whose entire premise was zero cost.

**What exists and does not solve it:** `AGENTIC_NO_LLM` is all-or-nothing (no
LLM at all). ADR-048's `TokenBudget` caps *tokens on the shared client*, not
*which providers may be reached*.

**Current workaround, in the eval kit, not in ARP:** `run_ab.py` deletes
`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`, `GITHUB_TOKEN`,
`OPENROUTER_API_KEY`, `AZURE_OPENAI_API_KEY`, `AZURE_FOUNDRY_API_KEY` and
`CLAUDE_CODE_OAUTH_TOKEN` from the child environment before spawning. A provider
without a key cannot be called at all. It works, and it is the wrong layer.

### Asked for

A **cost lane** on every registered model, and a ceiling the candidate resolver
enforces.

- Add `cost_lane` to the registry schema: `local` (weights on this machine),
  `free` (no charge, credential may still be required), `paid`. It is a curated
  human judgement in the ADR-040 sense — providers do not expose it, and
  `price_in`/`price_out` cannot substitute because they are `null` for every
  entry today.
- Add a ceiling, honoured by `get_model_candidates_for_tier`, that **filters the
  candidate list** rather than merely reordering it. Env var plus a keyword
  argument, so both an operator and a caller can set it. Suggested:
  `AGENTIC_MAX_COST_LANE=local|free|paid`, defaulting to `paid` so existing
  behaviour is unchanged.
- **Fail closed.** A model with no `cost_lane` is treated as `paid`. A ceiling
  that filters every candidate must raise a clear error naming the ceiling —
  never fall through to an unfiltered list.
- Emit a **warning-level log and a run event** whenever failover crosses from
  one lane to a more expensive one. Right now a run can silently change what it
  costs; that should be visible in the trace.

**Acceptance:** with `AGENTIC_MAX_COST_LANE=free`, a step whose output fails its
contract on every free candidate raises rather than calling a paid provider —
proven by a test that asserts no paid backend was constructed, not merely that
no charge was observed.

---

## F2 — Discovery covers four of seven serving paths, and knows no prices

ARP discovers:

| module | covers |
|---|---|
| `agentic_v2/models/cloud_discovery.py` | OpenAI, Anthropic, Gemini, GitHub Models, **NVIDIA NIM**, OpenRouter |
| `agentic_v2/models/ollama_discovery.py` | Ollama (`:11434`), local and `-cloud` ids |
| `agentic_v2/models/local_discovery.py` | LM Studio (`:1234`), ONNX |

**Not discovered at all, and running on this machine:**

| runtime | endpoint | list models |
|---|---|---|
| Lemonade (Ryzen AI hybrid NPU path) | `:13305` | `GET /api/v1/models` |
| Docker Model Runner | `:12434` | `GET /engines/v1/models` |
| Foundry Local | `:60160` | `foundry model ls` |

> **Naming trap:** `agentic_v2/models/backends.py` already handles **Azure AI
> Foundry** (`azure-foundry:`, `AZURE_FOUNDRY_API_KEY`) — a paid cloud service.
> **Foundry Local** is an unrelated on-device ONNX runtime. Grepping "foundry"
> finds the wrong one. Pick a distinct provider prefix, e.g. `foundry-local:`.

At the 2026-08-27 probe these three held the richest local catalogue on the
machine, including the only NPU-quantised coding models
(`qwen2.5-coder-7b` on NPU via Foundry Local, `CodeLlama-7b-Instruct-hf-Hybrid`
via Lemonade's `ryzenai-llm` recipe). Full snapshot:
[MODEL-INVENTORY-2026-08-27.md](MODEL-INVENTORY-2026-08-27.md).

**NIM specifically:** `discover_nvidia_models` sees the catalogue — 76 models
visible at the last probe — but has **no notion of which 14 are on free
endpoints**. The NIM API exposes no free-tier field; the authority is a "Free
Endpoint" label on the model card at <https://build.nvidia.com>. That list must
therefore be curated in the registry, not derived at runtime. This is exactly
the ADR-040 split: dynamic for facts the runtime can verify (availability,
health), curated for judgements a human owns (tier, capability, **price**).

### Asked for

- Three new discovery modules for Lemonade, Docker Model Runner and Foundry
  Local, following the shape of the existing ones.
- A single façade — `discover_all_models()` — returning one uniform record per
  model: `id`, `provider`, `endpoint`, `cost_lane`, `reachable`,
  `verified_by` (`listing` vs `completion`), `latency_ms`, `probed_at`.
  Today a caller has to know which of five functions to call and reconcile three
  differently-shaped records.
- `cost_lane` populated for every provider, with NIM's free-endpoint list
  carried as curated registry data.

**Constraint:** ADR-040 stands. Discovery **warns and quarantines**; it never
auto-promotes a newly discovered id into a tier chain. Adding a model to a chain
stays a deliberate human edit to `model_registry.yaml`.

---

## F3 — A model that lists is not a model that answers

Discovery treats presence in a `/models` listing as availability. Three failure
modes on this machine defeat that:

- **Lists but cannot load.** `muse-glimmer` appears in Docker Model Runner and
  fails at load with `unknown model architecture: 'muse-glimmer'` — the bundled
  llama.cpp does not know it.
- **Answers with nothing.** Reasoning models spend a small token budget entirely
  on internal reasoning and return empty content with `done_reason: length`.
  **Four NIM models looked dead for this reason and were not.** A health check
  that marks them unavailable is wrong; one that marks them available without
  reading the content is also wrong.
- **Cold-start timeouts** read as absence. Five NIM models timed out at 60 s on a
  cold call and were fine subsequently.

### Asked for

- A `verify=True` mode on discovery that completes one real chat call —
  `"Reply with exactly: OK"` — and records `verified_by: completion`.
- Reasoning-model normalisation in that probe: send `think: false` where the
  provider supports it (Ollama does), otherwise a token budget large enough that
  reasoning cannot consume all of it. Empty content must be reported as
  `empty_response`, distinct from both `ok` and `unreachable`.
- Distinguish `timeout` from `unavailable` in the recorded status.

---

## F4 — Every price in the registry is `null`

`model_registry.yaml` declares `price_in` / `price_out` per model, USD per
Mtok, and its own header says: *"null = unknown (spend is reported as None for
that model, never guessed). Populating real numbers is a follow-up; provider
/models endpoints do not expose pricing."* Every entry is still `null`.

Reporting `None` rather than guessing is right. The consequence is that ARP
cannot estimate the cost of a run, so a cost-aware routing decision is not
possible even in principle, and an eval cannot report cost alongside accuracy —
which [BEST-PRACTICES.md §8](BEST-PRACTICES.md#8-report-the-number-with-its-caveats-bound-to-it)
argues is half the result.

### Asked for

Populate `price_in` / `price_out` for the paid providers actually in the tier
chains, from published price lists, with a `price_source` and `price_asof` date
per entry so staleness is visible. Leave `null` where genuinely unknown. `local`
and `free` lanes are `0.0`, not `null` — that is a known price, not an unknown
one.

---

## F5 — `model_override` promises more than it delivers

A caller reading `model_override` reasonably expects "run this step on this
model". What it does is "try this model first". For an A/B where the whole
premise is *same model in both arms*, silent failover to a different model
destroys the comparison — and it is not visible in the report unless
`attempted_models` is inspected.

### Asked for

Either a `model_pin=True` variant that **truncates** the candidate list to the
pinned model (fail rather than substitute), or — cheaper — surface the substitution
loudly: warn on every failover away from an overridden model and make the
substitution a first-class field on the step result. `attempted_models` already
carries the data; nothing reads it.

---

## F6 — Progress within a long run is not observable

Not an ARP defect; recorded here so it is not lost. `run_ab.py` prints only at
the end, so a 50-minute wave is opaque and the current workaround is counting
spilled artifact files. `EvalRunner.run(event_sink=…)` exists
(`agentic-evalkit/src/agentic_evalkit/runner.py:220`) and the EvalKit CLI
already uses it. **Fix belongs in the eval kit**, not in ARP.

---

## F7 — Consistent probing and model usage across the portfolio

The reason to do F1–F4 properly rather than locally: **every app currently
decides for itself what a model is, whether it is reachable, and whether it
costs money.** ARP has three discovery modules with three record shapes; the
eval kit hand-rolled probes for the three runtimes ARP misses; EvalKit's
execution targets carry their own model plumbing. The same wrong assumption
("Lemonade is on :8000") was made twice because there was no shared answer.

### Asked for — a shared vocabulary first, shared code second

**One vocabulary, adopted everywhere:**

| term | meaning |
|---|---|
| `local` | weights on this machine; no account, no network, no charge |
| `free` | no charge, credential may still be required; rate limits often undocumented |
| `paid` | metered |
| `verified_by: listing` | the endpoint listed it |
| `verified_by: completion` | it answered a real request |

**ARP owns discovery** — it is the only repo with a curated registry and a
router. EvalKit must **not** import `agentic_v2` (that anti-dependency is
contract-enforced by AST scan on both sides), so sharing is by **data, not
imports**: ARP emits a probe snapshot in a documented JSON shape; anything that
needs it reads the file.

**Deliverables:** `discover_all_models(verify=…)` writing a versioned snapshot;
the field vocabulary documented in ARP's docs; the eval kit's hand-rolled probes
retired in favour of reading that snapshot.

---

## Constraints — do not break these

- **ADR-040 stands.** Discovery warns and quarantines; a human edits the registry
  to promote a model into a tier chain.
- **ADR-051.** In this deployment `OPENAI_BASE_URL` is aliased to NVIDIA NIM, so
  plain `openai:` ids can never be served and are permanently quarantined. The
  NIM catalogue is declared under the `nvidia:` provider. Do not "fix" that.
- **Do not weaken the anti-dependency.** `agentic-evalkit` must never import
  `agentic_v2`, `tools`, or `executionkit`, and all ARP↔EvalKit adaptation lives
  on the ARP side.
- **Default behaviour is unchanged** unless the new ceiling is set. `paid` is the
  default lane ceiling; nobody's existing run changes.
- **A campaign is in flight** in `agentic-workflows-v2/evals/swe_ab/`. Do not
  change workflows, graders, oracles, reports or dataset files under that path —
  a mid-campaign change invalidates every banked wave. Documentation there is
  read-only for this work order.

## Definition of done

- [ ] `cost_lane` on every registry entry; unknown ⇒ treated as `paid`.
- [ ] `AGENTIC_MAX_COST_LANE` filters candidates in `get_model_candidates_for_tier`,
      with a test proving no paid backend is constructed under `free`.
- [ ] Lane-crossing failover logs a warning and emits a run event.
- [ ] Lemonade, Docker Model Runner and Foundry Local discovered, under a
      provider prefix that does not collide with Azure AI Foundry.
- [ ] `discover_all_models()` returns one uniform record shape across every path.
- [ ] `verify=True` completes a real call; `empty_response`, `timeout` and
      `unavailable` are distinguishable.
- [ ] NIM free-endpoint list curated in the registry.
- [ ] Prices populated for paid tier-chain models, with source and as-of date.
- [ ] An ADR for the cost lane — derive the next free number from `docs/adr/`
      (ADR-057 was the highest at the time of writing) and follow the repo's
      `ADR-NNN-` filename convention and heading template.
- [ ] Lint, typecheck and the full suite green before and after; report
      pass/fail counts for both.

## Report on completion or blocker

What changed, which findings were deferred and why, test pass/fail counts, and
anything that turned out to be wrong in this work order — several claims here
are grounded in a 2026-08-27 probe of one machine and may have drifted.
