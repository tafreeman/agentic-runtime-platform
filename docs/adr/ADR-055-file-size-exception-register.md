# ADR-055: File-Size Exception Register

**Status:** Accepted
**Date:** 2026-07-17
**Related:** [`docs/CODING_STANDARDS.md`](../CODING_STANDARDS.md) (Design
rules: "Files under 800 lines"), [ADR-032](ADR-032-extract-scoring-package.md)
(documented-exception precedent for `evaluation_scoring.py`), the thirteen
files listed in the register below (all under `agentic-workflows-v2/agentic_v2/`)

## Context

`docs/CODING_STANDARDS.md` states the rule plainly: "Files under 800 lines —
split before a module grows past this." That rule and the codebase have been
out of sync for a while. Thirteen Python files under
`agentic-workflows-v2/agentic_v2/` exceed 800 physical lines today, and until
this ADR only one of them — `scoring/evaluation_scoring.py` — had a documented
exception. ADR-032 recorded it explicitly: the scoring-package extraction was
a "move + rewire only" change, and it said outright that
"`evaluation_scoring.py` stays over the 800-line guide; splitting it is
deferred."

The obvious fix — split the other twelve files to bring the codebase back
under the rule — was already tried. A 2026-07-01 mechanical-split attempt
(tracked as ARP-7, part of that day's remediation wave) split files purely
to satisfy the line-count cap and caused regressions; it was reverted rather
than merged. PR #145's merged summary is the durable record: "Deferred:
ARP-7 (800-line file caps) — an attempted split introduced behavior
regressions and was reverted; flagged for a careful test-guarded pass."
Splitting a module along a line-count boundary
instead of a cohesion boundary produces exactly this outcome: the cut doesn't
track a real seam in responsibility, so it either fractures state that needs
to stay together or scatters one concern across files that now have to be
read side by side anyway.

A 2026-07-01 career-signal audit flagged the resulting gap as "own-rule
consistency" debt: a standards doc that states a hard limit while a growing
set of real files sit above it, with no record of why, reads as either an
unenforced rule or an unreviewed codebase — neither is true, but nothing said
so. ADR-032 already established the right answer for one file: an explicit,
dated, ADR-recorded exception beats a silent violation or a regression-prone
forced split. This ADR extends that precedent into a standing register that
covers every file currently over the guide, so the rule and the repository
stop contradicting each other.

## Decision

Maintain a dated register of every file currently over the 800-line guide,
with an honest cohesion rationale and a stated bar for when a split would be
justified. `scoring/evaluation_scoring.py` is not re-registered here — it
stays covered by ADR-032, which already recorded the same kind of exception
for it.

Line counts below are a dated measurement, current as of 2026-07-17. Recording
a count in a dated ADR is fine — it is a record of that day, not a live
claim — but `docs/CODING_STANDARDS.md` itself must stay number-free and
point here instead of listing files or counts inline.

| File | Lines (2026-07-17) | Why it coheres | What would justify a split |
|---|---|---|---|
| `agentic_v2/langchain/graph_wiring.py` | 1319 | Single LangGraph wiring surface: tier-0 step implementations, the LLM-node factory with multi-model failover, the skip-check wrapper, and every `add_*`/`wire_*`/`build_*` edge-assembly helper that turns one `WorkflowConfig` into one populated `StateGraph`. `build_graph` is the sole entry point; splitting would scatter one graph definition's node factories and edge wiring across files that still have to be read together to trace a single compile. | Node-factory logic (tier-0 steps, the LLM node, failover) growing independently testable from edge/graph-assembly logic (the `add_*`/`wire_*` helpers) would justify separating "how a node runs" from "how nodes connect." |
| `agentic_v2/models/smart_router.py` | 1063 | Almost entirely one class, `SmartModelRouter` (~870 of 1063 lines): the circuit-breaker state machine (three states, adaptive cooldowns), bulkhead concurrency limits, and health-weighted selection all read and mutate the same per-model state. Splitting the state machine from the selection policy would require passing that shared state across a module boundary for no behavioral gain. | If bulkhead/circuit-breaker mechanics grow complex enough to be unit-tested in isolation from the selection algorithm that consumes circuit state, split the breaker/cooldown state machine out of the selection logic that reads it. |
| `agentic_v2/models/client.py` | 1055 | The module docstring names the design intent directly: `LLMClientWrapper` is "the primary interface for making LLM calls," deliberately combining smart routing, response caching, token-budget enforcement, streaming, and retry-with-jitter behind one facade so callers (the native engine, `agents/base.py`) have a single object to hold. Budget and cache already have their own modules (`cache_budget.py`); what's left in `client.py` is the wrapper that wires them together per-call. | If a capability currently wired into `complete()`/`complete_chat()`/`complete_stream()` (e.g. streaming) grows enough call-path-specific logic to be independently tested and reused without the rest of the wrapper, extract that call path into its own module the way `cache_budget.py` was already extracted. |
| `agentic_v2/server/models.py` | 955 | Pure Pydantic schema module — 36 `BaseModel` classes with no business logic — defining the entire JSON wire contract between the FastAPI backend and the UI (workflow run/result, DAG visualization, evaluation, dataset sampling). These are exactly the shapes the ADR-014 wire-format-drift gate and the TypeScript generator (`generate_ts_types` / `npm run generate:types`) scan as one surface; fragmenting it would fragment that generation step too. | If one sub-domain (e.g. the evaluation/scoring response models, roughly `EvaluationCriterionDetail` through `DatasetSampleDetailResponse`) grows large enough to warrant its own wire-format module, split it out — but only alongside an update to the type-generation scripts so drift detection still covers every fragment. |
| `agentic_v2/langchain/runner.py` | 891 | One end-to-end lifecycle: `WorkflowRunner` loads a YAML config, validates inputs, compiles it via `graph.py`, executes (invoke/stream), and resolves outputs. The private checkpointer-resolution and `ExecutionContext`-sync helpers exist only to support that one class's lifecycle and aren't meaningfully reusable outside it. | If checkpointer construction/URL-parsing or the state-sync helpers grow enough independent branching (new checkpoint backends, new sync policies) to need their own test surface, extract them from the `WorkflowRunner` class they currently support inline. |
| `agentic_v2/models/backends_cloud.py` | 865 | Already the product of a prior split — `backends.py` was previously divided into `backends_base.py` (the shared ABC), `backends_local.py`, and this file, grouping every cloud-hosted provider (GitHub Models, OpenAI, NVIDIA NIM, OpenRouter, Anthropic, Gemini, Azure OpenAI, Azure Foundry) behind the shared `LLMBackend` interface and a few genuinely shared helpers (`_to_anthropic_tool_choice`, the JSON content-type constant). The grouping boundary is "cloud-hosted," already narrower than "all backends." | If any single provider (e.g. Azure Foundry, which already carries its own retry/streaming variants) grows complex enough to need dedicated tests and maintenance independent of the other cloud backends, give it its own file the same way local vs. cloud was already split out of `backends.py`. |
| `agentic_v2/server/routes/model_finder.py` | 849 | One FastAPI feature end to end: hardware profiling (CPU/RAM/accelerator detection with a gitignored override file), a curated open-model catalog, the scoring function that ranks the catalog against the detected profile, and the route handlers that expose all of it under one `/model-finder` router. The Pydantic models (`SystemProfile`, `ModelCandidate`, `CatalogItem`, etc.) exist only to serve this one page. | If hardware-profiling/probing (the `_cpu_name`/`_ram_gb`/`_accelerators` family) or catalog scoring (`score_model`/`sorted_candidates`) grow enough independent logic to be tested without spinning up the route layer, split profiling and scoring out of the route handlers that currently sit in the same file. |
| `agentic_v2/langchain/models.py` | 823 | The provider/tier registry: fallback-chain construction, tier-default resolution, availability probing, registry-drift detection, and the merge logic that reconciles Ollama/local/cloud model listings into `enumerate_known_models`. The module docstring is explicit that builder functions live in `model_builders.py` and provider-detection utilities live in `model_utils.py` — this file is deliberately the routing/tier-resolution core those modules feed, not a catch-all. | If the discovery-merge logic (`_merge_ollama_models`/`_merge_local_models`/`_merge_cloud_models`/`detect_registry_drift`) grows independently of the tier-fallback/registry-config logic it feeds, split live-discovery merging from static tier-chain configuration. |
| `agentic_v2/engine/step.py` | 823 (2026-07-18) | One native step-execution lifecycle: the `StepDefinition` contract with its builder API, the `RetryConfig` policy it embeds, and the `StepExecutor` state machine that runs a single step — attempt loop, timeout/cancel/exception handling, verification, and loop continuation (including expression-valued `loop_max` resolution added 2026-07-18 to mirror the LangGraph adapter, which pushed the file over the guide). These read and mutate the same per-attempt state; splitting the continuation check from the executor that owns the iteration state would scatter one loop's semantics across files read together anyway. | If loop/refinement continuation semantics (expression resolution, iteration bookkeeping) grow independently testable from single-attempt execution (retry/timeout/verification), extract loop control into its own module; likewise if `StepDefinition`'s builder surface grows into a standalone DSL. |
| `agentic_v2/langchain/model_builders.py` | 822 | One `build_*` factory function per supported provider (eleven: GitHub Models, OpenAI, NVIDIA, OpenRouter, Anthropic, Gemini, NotebookLM alias, Ollama, LM Studio, local API, local ONNX), each importing its provider-specific LangChain package lazily so installing one provider's dependency doesn't require installing all of them. The file is a single dispatch surface reached from one call site (`_build_model_by_prefix` in `models.py`). | If the provider count keeps growing, split along the same cloud/local seam already used for backend implementations (`backends_cloud.py` vs. `backends_local.py`): cloud-hosted builders in one file, self-hosted/local builders (Ollama, LM Studio, local API, local ONNX) in another. |
| `agentic_v2/engine/context.py` | 820 | Almost entirely one class, `ExecutionContext` (~670 of 820 lines), whose own docstring lists five interdependent responsibilities — hierarchical scoping, JMESPath queries, event hooks, checkpoint/restore, and a DI `ServiceContainer` — all guarded by the same `asyncio.Lock` over the same variable dict. Splitting the class would mean passing that lock and the underlying state across a module boundary for capabilities that only make sense in terms of each other. | If the `ServiceContainer` DI mechanism or checkpoint/restore serialization grow enough independent surface area to be tested without a live `ExecutionContext` instance, extract them as standalone collaborators the context composes rather than inline members. |
| `agentic_v2/server/replay_store.py` | 814 | Three interchangeable implementations (`RedisReplayStore`, `SqliteReplayStore`, `InMemoryReplayStore`) of one `ReplayStore` Protocol, selected at runtime by `Settings.replay_store_backend`, plus the factory functions that build whichever one is configured. Keeping the Protocol and all three strategies in one file makes the tradeoffs comparable at a glance — durability, multi-worker support, dependency count — which is the whole point of documenting them as alternatives. | If any one backend (most likely Redis, given TTL/LTRIM/multi-worker concerns) accumulates enough backend-specific configuration or retry logic to need its own test file independent of the others, split that backend out while keeping the shared `ReplayStore` Protocol as the common contract. |
| `agentic_v2/server/datasets.py` | 806 | One dataset-access facade across three sources — repository datasets (HuggingFace/GitHub via `tools.agents.benchmarks`), local JSON fixtures, and `evaluation.yaml`-defined eval sets — re-exported by `server/evaluation.py` for backward compatibility. Sample-extraction helpers (`_extract_sample`, `_sample_from_list`) are shared across the repository and local loaders, which is why they still live together. | If repository-dataset loading (network/HF/GitHub fetch logic) grows enough independent complexity (retries, pagination, caching) to diverge from local-file discovery, split repository loading from local/eval-set discovery — keeping the shared sample-extraction helpers with whichever side uses them more, and re-exporting from the other. |

Policy going forward:

- A file may exceed the 800-line guide **only** while it is listed in this
  register.
- A new entry requires an ADR update to this register (or a new ADR that
  supersedes it) with the same two things every row above has: an honest
  cohesion rationale and a stated bar for when a split would be justified.
  "It's just large" is not sufficient on its own.
- An entry is removed when its file is split below the guide or shrinks under
  it through unrelated changes. Removal does not require a new ADR; updating
  this table to drop the row is enough, since the row's absence is itself the
  record.
- This register does not grandfather *future* growth of a listed file. A file
  already on the register that grows further is still expected to be
  reconsidered against its own "what would justify a split" bar, not treated
  as permanently exempt.

### What I decided vs. what the assistant proposed

The route itself — a documented exception register instead of another
mechanical split — was decided in the 2026-07-02 remediation work order,
directly in response to the reverted 2026-07-01 split attempt: forcing files
under a line count without a matching cohesion seam had just caused
regressions, and ADR-032 had already shown that a recorded exception is a
legitimate, lower-risk alternative to splitting on a deadline. That decision,
and the policy rules above (exceed-only-while-listed, ADR-gated additions,
no grandfathered future growth), are mine.

The assistant measured the twelve files' current line counts, read each
file's module docstring and class/function structure, and drafted the
per-file cohesion rationale and split-trigger language in the table — grounded
in what each file actually contains, not templated.

## Consequences

- `docs/CODING_STANDARDS.md`'s 800-line rule and the actual state of
  `agentic-workflows-v2/agentic_v2/` are consistent again: every file above
  the guide is either covered by ADR-032 or listed here, and the standards
  doc points to this register instead of silently tolerating the gap.
- Growth is visible and dated. The next time this register is touched, the
  2026-07-17 counts make it obvious which files grew, by how much, and
  whether their "why it coheres" rationale still holds.
- Nothing here forecloses splitting any of these files later — several rows
  above already name the seam a future split would follow. That work can
  still happen file-by-file, on its own merits, without being forced by a
  line-count deadline.
- The 800-line guide keeps its teeth for **new** files: nothing in this ADR
  raises the limit or exempts code that doesn't yet exist. A new file over
  800 lines is a standards violation, not an automatic register candidate.
