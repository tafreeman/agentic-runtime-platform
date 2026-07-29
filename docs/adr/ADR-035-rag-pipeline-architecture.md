# ADR-035: RAG Pipeline Architecture (LanceDB + Voyage 4 Hybrid Search)

**Status:** Accepted
**Date:** 2026-06-17
**Amended:** 2026-07-28 — reconciled with the as-built code. The original text
described the pipeline as intended; several capabilities it described in the
present tense were never written. The sections below now state what exists and
name what does not. The title is unchanged because `ADR-INDEX.md` and four other
documents link this ADR by title.
**Related:** [ADR-014](ADR-014-pydantic-wire-format.md) (wire-format contract discipline), [ADR-002](ADR-001-002-003-architecture-decisions.md) (SmartModelRouter), [ADR-019](ADR-019-dag-executor-top-level-timeout.md) (DAG timeout), [ADR-023](ADR-023-executionkit-runtime-contract-relationship.md) (ExecutionKit execution kernel)

---

## Context

The runtime needs a retrieval-augmented generation (RAG) pipeline that agents
(Coder, Architect, Reviewer, Orchestrator) can invoke as a shared tool during
multi-step workflows. Without a structured retrieval layer, agents rely entirely
on their context window for domain knowledge; long document corpora exceed that
window and cannot be updated without retraining.

Several design constraints shape the choice:

- The runtime is async-first (FastAPI + asyncio). Any blocking I/O in the
  retrieval path stalls the event loop and degrades concurrent workflow
  throughput.
- Providers, embedding models, and vector stores change. The design must
  abstract these behind protocols so the runtime is not vendor-locked.
- The existing Pydantic v2 contract discipline (ADR-014) must extend to all
  RAG data boundaries — configuration, retrieval queries, and results.
- The eval framework already defines rubric-based evaluation. RAG quality
  metrics (context precision, faithfulness, answer relevancy) must integrate
  with that framework, not require a separate harness.
- The platform targets regulated environments. Every retrieval step must be
  fully traceable via OpenTelemetry.

Five local vector stores were evaluated: ChromaDB, FAISS, LanceDB, Qdrant
(embedded mode), and Milvus Lite. Five embedding providers were evaluated:
Voyage 4, OpenAI text-embedding-3-small, Nomic Embed Text v2, Voyage Code-3,
and local sentence-transformers.

---

## Decision

Adopt **LanceDB as the persistent vector store** and **LiteLLM as the embedding
abstraction layer** — Voyage, OpenAI, and a local Ollama model all reached
through one code path — with **three-stage hybrid retrieval** (dense + BM25 →
RRF fusion → cross-encoder reranking) and **Pydantic v2 typed contracts** at
every data boundary.

The pipeline is implemented as a peer module at `agentic_v2/rag/`.
`agentic_v2/rag/factory.py` is what reads the configuration: it resolves
`RAGConfig.vectorstore_type`, `EmbeddingConfig.provider`, and
`RerankerConfig.strategy` into constructed components, exposed as
`build_embedder()`, `build_vectorstore()`, `build_reranker()`, and
`build_rag_components()`.

Three details differ from the original draft of this ADR and are recorded here
rather than quietly corrected, because a reader comparing this document to the
code will hit them:

- The agent-facing bridge is `agentic_v2/rag/tools.py` (`RAGSearchTool`,
  `RAGIngestTool`), **not** `tools/rag_tool.py` — that path does not exist. The
  bridge is not auto-registered by any tool registry; a caller constructs it.
- There is **no RAG YAML configuration layer** and no `_extends` support.
  `RAGConfig` is constructed in Python and has no `from_yaml()` classmethod. No
  RAG YAML file exists in the repository.
- `RAGConfig.vectorstore_type` defaults to `"memory"`. LanceDB is opt-in and
  requires `db_path` (enforced by a `model_validator` on `RAGConfig`).

**Store selection — LanceDB over alternatives:**

| Dimension | LanceDB | Qdrant | ChromaDB | FAISS | Milvus Lite |
|-----------|---------|--------|----------|-------|-------------|
| Async support | Native sync+async | Full native async | HTTP mode only | None | None |
| Type safety | Pydantic-native `LanceModel` | Pydantic throughout | Minimal | None | Dict-based |
| Hybrid search | BM25 + built-in rerankers | Sparse+dense fusion | Basic FTS only | None | BM25 sparse |
| Metadata filtering | SQL-like `WHERE` clauses | Best-in-class boolean | Basic operators | Post-hoc only | String expressions |
| Persistence | Versioned Lance format | WAL + snapshots | SQLite + segments | Manual file I/O | Single `.db` file |

LanceDB was selected for its data engineering fluency and modern Python
alignment with the existing codebase; Qdrant is the strong runner-up for
infrastructure-focused use cases.

What the shipped `LanceDBVectorStore` (`agentic_v2/rag/vectorstore.py`) actually
uses is narrower than the evaluation table suggests. It does **not** use
`LanceModel`/`Vector(768)` typed tables and does **not** use `connect_async()`;
it calls the synchronous LanceDB API and keeps the event loop free by wrapping
each call in `asyncio.to_thread`. It does not use LanceDB's built-in hybrid
search or its bundled rerankers — hybrid retrieval and reranking are implemented
in this repository (see below). Lance-format versioning on write is a property of
the storage engine and holds regardless.

`agentic_v2/rag/vectorstore.py` also defines `InMemoryVectorStore`, which is the
default and has no optional dependency. `LanceDBVectorStore` is defined only
inside an `if _LANCEDB_AVAILABLE:` block and is bound to `None` otherwise, so
importing the package never requires `lancedb`.

**Embedding selection — Voyage with a LiteLLM abstraction:**

Voyage was selected as the recommended hosted provider: it topped the RTEB
retrieval leaderboard as of early 2026 at $0.06/1M tokens, supports 32K token
context windows and Matryoshka dimensionality (256–2048), and offers a shared
embedding space across the family so documents indexed with one family member
can be queried with another without re-indexing.

The abstraction is `LiteLLMEmbedder` in `agentic_v2/rag/embeddings.py`. It
satisfies `EmbeddingProtocol` and is constructed from an `EmbeddingConfig`. Two
module-level maps are the whole routing rule, and both are assertable without a
network call:

| `EmbeddingConfig.provider` | LiteLLM model string | Credential env var |
|---|---|---|
| `voyage` | `voyage/{model_name}` | `VOYAGE_API_KEY` |
| `openai` | `openai/{model_name}` | `OPENAI_API_KEY` |
| `local` | `ollama/{model_name}` | none |
| `litellm` | `{model_name}` verbatim | none — LiteLLM resolves its own |

An unrecognised provider raises `EmbeddingError`; it never degrades to a
placeholder. `litellm` is imported lazily inside a module-level `_load_litellm()`
function, so importing `agentic_v2.rag` — or constructing a `LiteLLMEmbedder` —
never requires the `rag` extra; a missing install surfaces as an `EmbeddingError`
naming `pip install -e ".[rag]"` at the first `embed()` call.

Credentials are read with `os.getenv` at call time, never taken as a constructor
argument, never logged, and scrubbed out of provider error text before it reaches
an `EmbeddingError` message.

**Fallback order — kept, with a constraint the original text did not state.**
The documented order is Voyage → OpenAI `text-embedding-3-small` → local Nomic
Embed Text v2 via Ollama, and `FALLBACK_PROVIDER_ORDER` in
`agentic_v2/rag/factory.py` implements exactly that, with the configured provider
leading the chain. It is **opt-in** (`build_embedder(config, fallback=True)`),
not the default, for two reasons:

1. **Different providers embed into different semantic spaces.** A vector from
   `openai/text-embedding-3-small` is not comparable to one from `voyage/…`.
   Mixing them in a single index degrades retrieval without ever raising. The
   chain is therefore safe for a *fresh* index or a read-only query path, and
   unsafe against an index already populated by another provider. `FallbackEmbedder`
   refuses a mixed chain unless the caller passes
   `allow_mixed_provider_identities=True`; the factory passes it and logs a
   warning naming every model in the chain.
2. **`FallbackEmbedder` requires one shared dimensionality**, so every chain
   member inherits `EmbeddingConfig.dimensions`. `LiteLLMEmbedder` does not
   forward a `dimensions=` request parameter to LiteLLM, so a provider whose
   native width differs from the configured value fails the width check and the
   chain advances. At the `EmbeddingConfig` default of 1536 that means the
   Voyage and Nomic members cannot succeed. Failing loudly is the right
   behaviour — a silently truncated or padded vector would corrupt the index —
   but it makes the chain usable in practice only when every provider natively
   emits the configured width.

`InMemoryEmbedder` (also in `embeddings.py`) remains what it always was: a
deterministic SHA-256 hash expansion, for tests and offline development. No
factory path returns it for a production provider string.

**Retrieval architecture — three-stage pipeline:**

1. **Hybrid retrieval.** Dense vector search and BM25 sparse search in parallel
   via `asyncio.gather`. Implemented in this repository — `BM25Index` and
   `HybridRetriever` in `agentic_v2/rag/retrieval.py` — and therefore identical
   for the in-memory and LanceDB stores. LanceDB's own `query_type="hybrid"` is
   **not** used.
2. **RRF fusion.** Reciprocal Rank Fusion: `score(d) = Σ 1/(k + rank_i(d))`,
   k=60. `reciprocal_rank_fusion()` in `agentic_v2/rag/retrieval.py`.
3. **Cross-encoder reranking.** Fused candidates reranked by
   `CrossEncoderReranker` in `agentic_v2/rag/reranking.py`, which defaults to
   `cross-encoder/ms-marco-MiniLM-L-6-v2` — not the `…-L-12-v2` this ADR
   originally named. `RerankerConfig.model_name` can supply the L-12 model; the
   out-of-the-box default is L-6. `LLMReranker` (LLM-as-judge) and
   `NoOpReranker` are the other two strategies; `"none"` is the default.
   **ColBERT late-interaction is not implemented** and appears nowhere in the
   codebase — it remains an upgrade path, not a shipped option.

**Document ingestion:**

- Recursive character splitting at 400–512 tokens with 10–20% overlap as the
  default chunking strategy (69% accuracy vs. 54% for semantic chunking, per
  February 2026 Firecrawl benchmark). Shipped as `RecursiveChunker` in
  `agentic_v2/rag/chunking.py`. **`SemanticChunker` is not implemented** —
  `ChunkingConfig.strategy` accepts `"semantic"` as a `Literal` value, but only
  the recursive chunker exists.
- Content-hash keying: `Chunk.content_hash` is a `computed_field` (SHA-256 of
  the content) on the contract. The **deduplication logic that would use it is
  not implemented** — `IngestionPipeline.ingest()` loads and chunks, and does not
  compare hashes against an existing index or skip unchanged chunks. Incremental
  re-ingestion is a property of the contract, not yet of the pipeline.
- Chunk fields carried today: `chunk_id`, `document_id`, `chunk_index`,
  `content`, `content_hash`, and a free-form `metadata` dict. The named metadata
  keys (`source_file`, `page_number`, `section_header`, `ingested_at`) are a
  convention within that dict, not typed fields.

**Typed contracts:**

Pydantic v2 models at all boundaries. `agentic_v2/rag/contracts.py` defines
`Document`, `Chunk`, `RetrievalResult` (with a `computed_field` for
`is_high_confidence`), and `RAGResponse`. `agentic_v2/rag/config.py` defines
`ChunkingConfig` (with the `model_validator` ensuring overlap < chunk_size),
`EmbeddingConfig`, `RerankerConfig`, and `RAGConfig` (whose `model_validator`
requires `db_path` when `vectorstore_type` is `"lancedb"`). Every one is
`frozen=True` with `ConfigDict(extra='forbid')` (ADR-014 additive-only
discipline).

Two names this ADR originally listed do not exist: `ChunkMetadata` (chunk
metadata is a `dict[str, Any]` on `Chunk`) and `DocumentIngestionRequest` (the
overlap validator lives on `ChunkingConfig` instead). `RetrievalQuery` also does
not exist as a model; `HybridRetriever.retrieve()` takes a plain query string and
`top_k`. And `EmbeddingConfig` is **not** a discriminated union — `provider` is a
flat `Literal["openai", "voyage", "local", "litellm"]`, which is sufficient
because `LiteLLMEmbedder` takes the same constructor arguments for every
provider.

**Resilience:**

One layer is implemented, not four. `FallbackEmbedder`
(`agentic_v2/rag/embeddings.py`) tries each provider in order and advances to the
next **only** on `EmbeddingError` — any other exception propagates, because a
`TypeError` from a provider is a bug, not a transient fault. When every provider
fails it raises a single `EmbeddingError` naming all of them.

Explicitly **not implemented**, and named here so the gap is not rediscovered by
reading the old text as fact:

- No retry and no exponential backoff. `tenacity` is not a dependency of this
  package. LiteLLM's own `num_retries` is not set, so a 429 surfaces as an
  `EmbeddingError` and advances the fallback chain instead of retrying.
- No circuit breaker. Nothing counts consecutive failures; the runtime's
  `SmartModelRouter` breakers cover chat completions, not this path.
- No embedding cache.
- No `EmbeddingResult` type and no `source` field. `embed()` returns
  `list[list[float]]` per `EmbeddingProtocol`, so a caller cannot tell which
  chain member produced a vector.
- `asyncio.gather` over batches runs without `return_exceptions=True`: the first
  batch failure propagates immediately, but sibling in-flight batches are not
  cancelled, so a failed `embed()` can still consume provider quota (bounded by
  `EmbeddingConfig.max_concurrent`).

**Observability:**

`agentic_v2/rag/tracing.py` defines `RAGTracer`, which emits **string-named
events through an injected `TraceAdapter` callback** — it does not import
`opentelemetry` and does not open spans. The events are `rag.query_start`,
`rag.embed`, `rag.search`, `rag.assemble`, `rag.query_complete`,
`rag.ingest_start`, and `rag.ingest_complete`, carrying latency, result counts,
and token counts. `query_span()` and `ingest_span()` are context managers over
that event pair, not OTEL spans.

The OTEL span tree described in the original draft (`rag.embed_query` →
`rag.vector_search` → `rag.rerank` → `rag.assemble_context` →
`rag.llm_inference`), the cost attributes, and OTLP export to LangSmith or
Langfuse are **not implemented**. Wiring `RAGTracer`'s adapter to the platform's
existing OTEL exporter is the path to closing that gap; nothing does so today.

**Module layout:**

Seventeen modules as built (the original draft listed sixteen and named several
that do not exist):

```
agentic_v2/rag/           # peer to agents/, workflows/, tools/
    __init__.py            # flat public API re-exports
    config.py              # frozen Pydantic settings (no from_yaml())
    contracts.py           # Document, Chunk, RetrievalResult, RAGResponse
    protocols.py           # LoaderProtocol, ChunkerProtocol, EmbeddingProtocol,
                           #   RerankerProtocol, VectorStoreProtocol
    errors.py              # RAG error hierarchy (RAGError and five subclasses)
    loaders.py             # document loaders (plain text, Markdown)
    chunking.py            # RecursiveChunker (only)
    ingestion.py           # IngestionPipeline: load + chunk
    embeddings.py          # InMemoryEmbedder, FallbackEmbedder, LiteLLMEmbedder
    vectorstore.py         # InMemoryVectorStore, LanceDBVectorStore (guarded)
    factory.py             # config → components; reads vectorstore_type,
                           #   embedding.provider, reranker.strategy
    retrieval.py           # BM25Index, reciprocal_rank_fusion, HybridRetriever
    reranking.py           # NoOpReranker, CrossEncoderReranker, LLMReranker
    context_assembly.py    # token-budget-aware context assembler
    memory.py              # RAGMemoryStore
    tracing.py             # RAGTracer: callback events (not OTEL spans)
    tools.py               # RAGSearchTool / RAGIngestTool bridge
```

Protocol names are `EmbeddingProtocol` and `VectorStoreProtocol` — not
`EmbeddingProvider` / `VectorStore` as the original draft wrote them.

---

## Consequences

### Positive

- Agents can reach document corpora that exceed their context window through
  `RAGSearchTool` / `RAGIngestTool` without per-agent integration work.
- Async throughout the pipeline: LanceDB's synchronous calls are offloaded with
  `asyncio.to_thread` and LiteLLM's synchronous `embedding` entrypoint is
  offloaded to the default executor when the installed version exposes no
  `aembedding`, so no retrieval path blocks the event loop.
- Provider switches are a one-line config change — `EmbeddingConfig.provider`
  plus `model_name` — with no new code, because `LiteLLMEmbedder` and
  `build_embedder()` handle all four provider strings identically. (There is no
  YAML layer, so "config" here means the Pydantic model, not a file.)
- Three-stage retrieval (dense + BM25 → RRF → reranking) achieves up to 67%
  reduction in retrieval failures over single-stage dense search (per Anthropic
  contextual retrieval research).
- Pydantic v2 contracts at every boundary catch config typos at construction time
  rather than silently at inference time; `extra='forbid'` rejects unknown keys.
- Optional backends stay optional. `import agentic_v2.rag` succeeds with neither
  `litellm` nor `lancedb` installed, and requesting a backend that is missing
  raises a typed error naming `pip install -e ".[rag]"` rather than an
  `ImportError` or a `TypeError` from calling `None`.

### Negative

- `lancedb` and `litellm` are optional (`pip install -e ".[rag]"`); the
  persistent store and every hosted embedding provider are unavailable without
  the extra. The runtime starts cleanly without it, falling back to
  `InMemoryVectorStore`.
- **No CI job installs the `rag` extra.** `ci.yml` installs
  `[dev,server,mcp,langchain,tracing]` (plus `ek` in one job) and
  `windows-workflows-ci.yml` runs `uv sync --frozen --extra dev --extra server
  --extra langchain`. `litellm` and `lancedb` are therefore absent everywhere in
  CI, so `LiteLLMEmbedder` and `LanceDBVectorStore` are exercised **only against
  fakes**. No automated test anywhere makes a live embedding call. See
  [`KNOWN_LIMITATIONS.md` §4.6](../KNOWN_LIMITATIONS.md).
- Voyage is a paid API; the local Ollama fallback degrades embedding quality, and
  its endpoint is not configurable — `EmbeddingConfig` is frozen with
  `extra='forbid'` and carries no `api_base`, so `local` always resolves to
  LiteLLM's own Ollama default.
- The fallback chain is opt-in and narrow: it pins every member to one
  dimensionality, cannot request a provider-side dimension, and mixes semantic
  spaces. See the Embedding selection section above and
  [`KNOWN_LIMITATIONS.md` §4.7](../KNOWN_LIMITATIONS.md).
- Cross-encoder reranking runs synchronously via `asyncio.to_thread`; it adds
  latency on the retrieval hot path for large candidate sets. It also depends on
  `sentence-transformers`, which **no extra in `pyproject.toml` declares** — a
  fully installed `.[rag]` machine still raises `ImportError` unless the caller
  passes `predict_fn=` to `build_reranker()`. The `"llm"` strategy has no default
  scorer at all. `build_rag_components(config)` is therefore fully config-driven
  only for `strategy="none"`.
- `RerankerConfig.top_k` is inert at construction: no reranker takes it as a
  constructor argument, so a caller must thread it into the `rerank()` call
  themselves or silently get the library default of 5.
- Two implementations do not structurally match their protocol.
  `NoOpReranker.rerank` names its first parameter `_query` where
  `RerankerProtocol` declares `query`, so keyword calls fail for the default
  strategy; `LanceDBVectorStore.search` names its third `_metadata_filter` and
  absorbs `metadata_filter=` into `**kwargs`, returning **unfiltered** results
  rather than erroring. Both are recorded in `factory.py`'s docstrings.
- Parent-child chunking is not implemented; only `RecursiveChunker` exists. If
  added, it would need two LanceDB tables per collection.

---

## Alternatives Considered

| Alternative | Disposition |
|------------|-------------|
| ChromaDB | Rejected — sync-only in embedded mode, minimal type safety, prototype-oriented. |
| FAISS | Rejected — zero metadata awareness; a library, not a database. |
| Milvus Lite | Rejected — FLAT index only, sync-only, dict-based API. |
| Qdrant embedded | Viable runner-up; select if infrastructure engineering is the emphasis over data engineering fluency. |
| OpenAI text-embedding-3-small as default | Retained as the first fallback after the configured provider (`FALLBACK_PROVIDER_ORDER`); not the recommended primary because Voyage outperforms it on RTEB at comparable cost. It is, however, the value `EmbeddingConfig.provider` and `model_name` default to, so an unconfigured pipeline uses OpenAI. |
| Single-stage dense retrieval only | Rejected — three-way retrieval (BM25 + dense) consistently outperforms; IBM research confirms this at scale. |
| Synchronous pipeline | Rejected — async-first is a hard requirement per the runtime's concurrency model. |

---

## Implementation

The pipeline lives in `agentic-workflows-v2/agentic_v2/rag/` (seventeen modules,
listed above). The tool bridge is `agentic_v2/rag/tools.py`; it is constructed by
a caller, not auto-registered by the tool registry. There is no RAG YAML
configuration layer.

**Implemented and covered by tests**

- `LiteLLMEmbedder` — `voyage`, `openai`, `local` (Ollama), and `litellm`
  passthrough, with lazy import, per-provider credential env vars, credential
  scrubbing, batching, bounded concurrency, order-preserving results, and ten
  distinct `EmbeddingError` conditions. Tests:
  `agentic-workflows-v2/tests/test_rag_embeddings_litellm.py`.
- `factory.py` — `build_embedder`, `build_vectorstore`, `build_reranker`,
  `build_rag_components`. Tests: `agentic-workflows-v2/tests/test_rag_factory.py`.
- Hybrid retrieval, RRF, in-memory and LanceDB stores, all three rerankers,
  chunking, ingestion, context assembly, memory store, tracing — the pre-existing
  suites under `agentic-workflows-v2/tests/test_rag_*.py`.

Both new suites are written so they pass **with the `rag` extra absent**, and
neither uses `pytest.importorskip` — that would skip silently in CI and leave the
code unproven while the run stayed green. They inject a fake `litellm` instead,
by monkeypatching the `_load_litellm()` seam or by setting `sys.modules["litellm"]`
directly; the factory suite additionally monkeypatches
`vectorstore.LanceDBVectorStore` to `None` to exercise the missing-extra error
path regardless of what is installed locally.

The consequence is the one stated in the Negative list: **no automated test makes
a live embedding call or exercises a real LanceDB table in CI.** The one suite
that does need a real LanceDB, `tests/test_vectorstore_lancedb.py`, uses
`pytest.importorskip("lancedb")` and is skipped there.

**Not implemented** — carried as open work, not as shipped capability: retry /
backoff / circuit breaker / embedding cache; the OTEL span tree and OTLP export;
`SemanticChunker`; ingestion-time content-hash deduplication; parent-child
chunking; ColBERT reranking; a YAML config layer; and RAG evaluation. There is no
RAGAS or DeepEval integration, no NDCG@10 metric, and no CI gate on Precision@k,
Recall@k, or MRR — those strings appear nowhere in the repository. The
[`KNOWN_LIMITATIONS.md`](../KNOWN_LIMITATIONS.md) entries §4.6–§4.10 track the
operational consequences.

See [`adr/RAG-pipeline-blueprint.md`](RAG-pipeline-blueprint.md) for the research
backing that informed this decision. That document is a pre-implementation
research artifact and describes several capabilities listed above as
unimplemented; read it as rationale, not as a description of the code.
