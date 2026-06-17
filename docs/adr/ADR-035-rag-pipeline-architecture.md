# ADR-035: RAG Pipeline Architecture (LanceDB + Voyage 4 Hybrid Search)

**Status:** Accepted
**Date:** 2026-06-17
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

Adopt **LanceDB as the primary vector store** with **Voyage 4 as the default
embedding model**, connected through a **LiteLLM abstraction layer**, with
**three-stage hybrid retrieval** (dense + BM25 → RRF fusion → cross-encoder
reranking) and full **Pydantic v2 typed contracts** at every data boundary.

The pipeline is implemented as a peer module at `agentic_v2/rag/` and exposed
to agents through a thin bridge tool (`tools/rag_tool.py`). Configuration
follows the existing YAML pattern with per-workflow overrides via `_extends`.

**Store selection — LanceDB over alternatives:**

| Dimension | LanceDB | Qdrant | ChromaDB | FAISS | Milvus Lite |
|-----------|---------|--------|----------|-------|-------------|
| Async support | Native sync+async | Full native async | HTTP mode only | None | None |
| Type safety | Pydantic-native `LanceModel` | Pydantic throughout | Minimal | None | Dict-based |
| Hybrid search | BM25 + built-in rerankers | Sparse+dense fusion | Basic FTS only | None | BM25 sparse |
| Metadata filtering | SQL-like `WHERE` clauses | Best-in-class boolean | Basic operators | Post-hoc only | String expressions |
| Persistence | Versioned Lance format | WAL + snapshots | SQLite + segments | Manual file I/O | Single `.db` file |

LanceDB's decisive advantages: native `LanceModel` with `Vector(768)` type hints
(Pydantic-native, no adapter layer), `connect_async()` async API, built-in hybrid
search with integrated RRF and cross-encoder rerankers, and automatic data
versioning on every write. Qdrant is the strong runner-up for infrastructure-
focused use cases; LanceDB is selected for its data engineering fluency and
modern Python alignment with the existing codebase.

**Embedding selection — Voyage 4 with LiteLLM abstraction:**

Voyage 4 ($0.06/1M tokens) tops the RTEB retrieval leaderboard as of early 2026,
supports 32K token context windows, Matryoshka dimensionality (256–2048), and
offers a shared embedding space across the family so documents indexed with
`voyage-4-large` can be queried with `voyage-4-lite` without re-indexing. The
LiteLLM abstraction (`embedding()` unified interface) enables zero-code provider
switching. Fallback order: Voyage 4 → OpenAI text-embedding-3-small → local
Nomic Embed Text v2 via Ollama.

**Retrieval architecture — three-stage pipeline:**

1. **Hybrid retrieval.** Dense vector search (LanceDB) and BM25 sparse search
   in parallel via `asyncio.gather`. LanceDB native hybrid: `table.search("query",
   query_type="hybrid")`.
2. **RRF fusion.** Reciprocal Rank Fusion: `score(d) = Σ 1/(k + rank_i(d))`,
   k=60. Combines ranked lists from stage 1.
3. **Cross-encoder reranking.** Top 20–50 fused candidates reranked to final 3–5
   using `cross-encoder/ms-marco-MiniLM-L-12-v2`. ColBERT late-interaction is
   the upgrade path for latency-sensitive deployments.

**Document ingestion:**

- `RecursiveCharacterTextSplitter` at 400–512 tokens with 10–20% overlap as the
  default chunking strategy (69% accuracy vs. 54% for semantic chunking, per
  February 2026 Firecrawl benchmark).
- Content-hash keyed deduplication: on re-ingestion, only changed chunks are
  re-embedded.
- Required chunk metadata: `source_file`, `page_number`, `section_header`,
  `document_id`, `ingested_at`, `content_hash`, `chunk_index`.

**Typed contracts:**

Pydantic v2 models at all boundaries: `ChunkMetadata`, `RetrievalQuery` (with
`min_length` validation, bounded `top_k`), `RetrievalResult` (with `computed_field`
for `is_high_confidence`), `DocumentIngestionRequest` (with `model_validator`
ensuring overlap < chunk_size), and `EmbeddingConfig` as a discriminated union
across providers. All models use `ConfigDict(extra='forbid')` (ADR-014 additive-
only discipline).

**Resilience:**

Layered: retry with exponential backoff (tenacity, transient errors only:
`RateLimitError`, `APIError`) → circuit breaker (opens after 5 consecutive
failures, falls back to local sentence-transformers) → embedding cache (content-
hash keyed). Each layer returns a typed `EmbeddingResult` with a `source` field
("api", "local_fallback", "cache") for observability.

**Observability:**

Full OTEL span tree per query: `rag.query` (root) → `rag.embed_query` →
`rag.vector_search` → `rag.rerank` → `rag.assemble_context` → `rag.llm_inference`.
Key span attributes: embedding latency, model name, result count, top/min scores,
token counts, estimated cost. Exports to LangSmith or Langfuse via OTLP.

**Module layout:**

```
agentic_v2/rag/           # peer to agents/, workflows/, tools/
    __init__.py            # public API exports
    config.py              # Pydantic settings with from_yaml() classmethod
    contracts.py           # all typed contracts (ChunkMetadata, RetrievalQuery, etc.)
    ingestion.py           # IngestionPipeline orchestrator
    loaders.py             # document loaders (PDF, Markdown, HTML)
    chunking.py            # strategy pattern: RecursiveChunker, SemanticChunker
    embeddings.py          # EmbeddingProvider protocol + LiteLLM-backed factory
    vectorstore.py         # VectorStore protocol + factory (LanceDB primary)
    retrieval.py           # base retriever with hybrid search strategy
    reranking.py           # cross-encoder and ColBERT reranking
    memory.py              # MemoryStore integration (InMemoryStore / RAGMemoryStore)
    protocols.py           # EmbeddingProvider, VectorStore protocols
    errors.py              # RAG-specific error hierarchy
    tracing.py             # OTEL span helpers
    tools.py               # thin bridge: wraps rag/ as a discoverable tool
    context_assembly.py    # token-budget-aware context assembler
```

---

## Consequences

### Positive

- Agents gain access to document corpora that exceed their context window without
  any per-agent integration work — RAG is registered once as a shared tool.
- Native async throughout the pipeline eliminates event-loop blocking under
  concurrent workflow load.
- LiteLLM abstraction makes provider switches zero-code; only config YAML changes.
- Content-hash deduplication keeps ingestion incremental; large corpora do not
  require full re-indexing on updates.
- Three-stage retrieval (dense + BM25 → RRF → reranking) achieves up to 67%
  reduction in retrieval failures over single-stage dense search (per Anthropic
  contextual retrieval research).
- Pydantic v2 contracts at every boundary catch config typos at load time rather
  than silently at inference time.
- RAGAS + DeepEval integration brings RAG quality metrics into the existing YAML
  rubric eval framework — no second harness required.

### Negative

- LanceDB is an optional dependency (`pip install -e ".[rag]"`); RAG features
  are unavailable without it. The runtime starts cleanly without the extra.
- Voyage 4 is a paid API; the local Ollama fallback degrades embedding quality.
- Cross-encoder reranking runs synchronously via `asyncio.to_thread`; it adds
  latency on the retrieval hot path for large candidate sets.
- Parent-child chunking (small child for retrieval, large parent for context)
  requires two LanceDB tables per collection, increasing storage overhead.

---

## Alternatives Considered

| Alternative | Disposition |
|------------|-------------|
| ChromaDB | Rejected — sync-only in embedded mode, minimal type safety, prototype-oriented. |
| FAISS | Rejected — zero metadata awareness; a library, not a database. |
| Milvus Lite | Rejected — FLAT index only, sync-only, dict-based API. |
| Qdrant embedded | Viable runner-up; select if infrastructure engineering is the emphasis over data engineering fluency. |
| OpenAI text-embedding-3-small as default | Retained as first fallback; not the primary because Voyage 4 outperforms it on RTEB at comparable cost. |
| Single-stage dense retrieval only | Rejected — three-way retrieval (BM25 + dense) consistently outperforms; IBM research confirms this at scale. |
| Synchronous pipeline | Rejected — async-first is a hard requirement per the runtime's concurrency model. |

---

## Implementation

The pipeline is live in `agentic-workflows-v2/agentic_v2/rag/` (thirteen modules).
The thin tool bridge at `tools/rag_tool.py` registers it under the existing tool
registry auto-import pattern. RAG configuration follows the same YAML style as
existing workflow definitions, with per-workflow overrides using `_extends`.

Evaluation integration: RAG eval suites are defined in YAML matching the existing
rubric config style. NDCG@10 is the primary ranking quality metric; CI gates
Precision@k, Recall@k, MRR, and NDCG trends across merges.

See [`adr/RAG-pipeline-blueprint.md`](RAG-pipeline-blueprint.md) for the full
research backing and implementation rationale that informed this decision.
