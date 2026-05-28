# Blueprint for a portfolio-grade RAG retrieval pipeline

**LanceDB with Voyage 4 embeddings, hybrid search with cross-encoder reranking, and full Pydantic v2 typed contracts form the strongest foundation for a RAG pipeline that will impress senior technical reviewers at top AI companies.** This architecture demonstrates async-first design, provider abstraction via LiteLLM, multi-stage retrieval (dense + BM25 → RRF fusion → reranking), and production resilience patterns — the exact signals that distinguish senior engineering from tutorial-grade work. The research below covers every layer of implementation, from vector store selection to CI/CD regression testing, calibrated to the existing monorepo's LangChain/LangGraph engine, Pydantic contracts, YAML configuration style, and eval framework.

---

## LanceDB emerges as the clear vector store choice

Among the five local vector stores evaluated — ChromaDB, FAISS, LanceDB, Qdrant (embedded mode), and Milvus Lite — **LanceDB** stands out for a portfolio project demanding engineering sophistication. The decisive advantages are its native Pydantic integration via `LanceModel` with `Vector(768)` type hints, native async/await support through `connect_async()`, and built-in hybrid search with integrated rerankers (linear combination, RRF, cross-encoder, ColBERT). The Lance columnar format provides **automatic data versioning** on every write — a feature that signals awareness of data engineering best practices that reviewers will notice.

LanceDB's SQL-like filter syntax (`.where("date > '2025-01-01' AND category = 'architecture'")`) is far more expressive than ChromaDB's dict-based operators, while its schema-driven embedding registry (`get_registry().get("openai").create()`) eliminates boilerplate. The Lance SDK hit v1.0.0 in December 2025, and LanceDB Cloud launched mid-2025, demonstrating active development velocity. Performance is strong for disk-based workloads using IVF-PQ indexing, with production deployments handling **700M+ vectors**.

Qdrant in local mode is the strong runner-up, offering the best metadata filtering of any option (filterable HNSW with boolean `must/should/must_not` clauses), full Pydantic types throughout its API, and FastEmbed integration for ONNX-based local embeddings. Reddit selected Qdrant over alternatives in 2025 after extensive evaluation, which gives it real-world credibility. Choose Qdrant if the portfolio emphasizes infrastructure engineering; choose LanceDB if it emphasizes data engineering fluency and modern Python patterns.

Avoid ChromaDB (too prototype-oriented, sync-only in embedded mode, minimal type safety), FAISS (zero metadata awareness — it's a library, not a database), and Milvus Lite (FLAT-index only, sync-only, dict-based API).

| Dimension | LanceDB | Qdrant | ChromaDB | FAISS | Milvus Lite |
|-----------|---------|--------|----------|-------|-------------|
| Async support | Native sync+async | Full native async | HTTP mode only | None | None |
| Type safety | Pydantic-native LanceModel | Pydantic throughout | Minimal | None | Dict-based |
| Hybrid search | BM25 + built-in rerankers | Sparse+dense fusion | Basic FTS only | None | BM25 sparse |
| Metadata filtering | SQL-like WHERE clauses | Best-in-class boolean | Basic operators | Post-hoc only | String expressions |
| Persistence | Versioned Lance format | WAL + snapshots | SQLite + segments | Manual file I/O | Single .db file |

---

## Embedding model selection and provider abstraction

**Voyage 4** ($0.06/1M tokens) delivers the best price-to-performance ratio among API embedding models as of early 2026. Its MoE architecture tops the RTEB retrieval leaderboard, supports Matryoshka dimensionality (256–2048), handles **32K token** context windows, and offers 200M free tokens per model for prototyping. The Voyage 4 family's shared embedding space is a unique advantage: documents indexed with `voyage-4-large` can be queried with the cheaper `voyage-4-lite` without re-indexing.

For a fallback, **OpenAI text-embedding-3-small** ($0.02/1M tokens) provides the widest ecosystem support and is instantly recognizable to any reviewer. For fully local/offline operation, **Nomic Embed Text v2 MoE** runs via Ollama with zero setup, is Apache 2.0 licensed, supports 100+ languages, and provides Matryoshka dimensionality at 768 dimensions. For code-heavy retrieval, **Voyage Code-3** outperforms OpenAI's best model by 13.8% across 238 code retrieval datasets.

The provider abstraction layer should use **LiteLLM**, which provides a unified `embedding()` function across 100+ providers with identical response formats. This enables single-config model switching and demonstrates production-level engineering:

```python
from litellm import embedding
# Swap providers with zero code changes
response = embedding(model="voyage/voyage-4", input=["query text"])
response = embedding(model="text-embedding-3-small", input=["query text"])
```

For the custom abstraction within the repo, define a `Protocol`-based `EmbeddingProvider` with `embed_batch` and `aembed_batch` methods, then implement concrete providers (OpenAI, Voyage, Local) that wrap LiteLLM or direct SDK calls. Use a discriminated union in Pydantic v2 (`Field(discriminator='provider')`) for the embedding configuration, so YAML config parsing is zero-ambiguity and self-documenting.

---

## Multi-stage retrieval architecture with LangGraph integration

The RAG pipeline should implement a **three-stage retrieval architecture**: parallel dense + sparse retrieval, reciprocal rank fusion, then cross-encoder reranking. This pattern, validated by Anthropic's contextual retrieval research showing a **67% reduction in retrieval failures** when combining contextual embeddings with BM25 and reranking, represents the current state of the art.

**Stage 1 — Hybrid retrieval.** Run dense vector search (via LanceDB) and BM25 sparse search in parallel using `asyncio.gather`. LanceDB's native hybrid search makes this a single call: `table.search("query", query_type="hybrid")`. The critical insight from IBM's research is that three-way retrieval (BM25 + dense + sparse vectors) outperforms any single method. Fix recall first — if recall@50 is below 90%, adding a reranker won't help.

**Stage 2 — Fusion via Reciprocal Rank Fusion.** RRF combines ranked lists with the formula `score(d) = Σ 1/(k + rank_i(d))` where k=60. LanceDB includes built-in `LinearCombinationReranker` and RRF, or use LangChain's `EnsembleRetriever` with configurable weights for explicit control.

**Stage 3 — Cross-encoder reranking.** Rerank the top 20–50 fused candidates down to the final 3–5 using a cross-encoder (e.g., `cross-encoder/ms-marco-MiniLM-L-12-v2`) or ColBERTv2 for better latency. ColBERT's late-interaction architecture provides near-cross-encoder accuracy at **100x the speed** by pre-computing document token embeddings and using MaxSim scoring. Jina ColBERT v2 supports 89 languages and 8192 tokens.

**Wiring RAG as a LangGraph tool** follows the official agentic RAG pattern: wrap the retrieval pipeline as a `@tool`-decorated function, bind it to agent LLMs via `.bind_tools([retriever_tool])`, and use LangGraph's `ToolNode` with `tools_condition` for routing. The state graph should include a `grade_documents` node using a Pydantic `GradeDocuments` model (with binary relevance scoring) as a conditional edge — if retrieved documents are irrelevant, the graph routes to a `rewrite_question` node that reformulates the query before retrying. This self-corrective loop is the signature pattern of production-grade agentic RAG.

For the multi-agent system, register the RAG retriever as a shared tool that all agents (Coder, Architect, Reviewer) can invoke alongside their specialty tools. Each agent autonomously decides when to invoke RAG based on its system prompt. The Orchestrator routes queries to the appropriate specialist, and per-agent retrieval configuration (different collections, different `top_k`) is supported through the YAML config system.

### Query transformation and context management

For complex queries, implement **multi-query retrieval** as the default query transformation: the LLM generates 3–5 alternative phrasings, each retrieves independently, and results are deduplicated. LangChain's `MultiQueryRetriever` handles this out of the box. Reserve HyDE (Hypothetical Document Embedding) for vague or domain-specific queries where the semantic gap between question and document is large, but test carefully — if the LLM lacks domain knowledge, the hypothetical document can mislead retrieval.

Context window budgeting for multi-agent calls should allocate **3,000–8,000 tokens** for retrieved context within a typical 8K–16K total budget per agent invocation. Place the most relevant chunks at the beginning and end of the context window to mitigate the lost-in-the-middle effect, which causes **>30% performance degradation** when relevant information sits in middle positions. Use LangChain's `ContextualCompressionRetriever` to extract only query-relevant sentences from each chunk, and implement a parent-child chunk strategy where small child chunks (256 tokens) are used for precise retrieval but the parent chunks (1024 tokens) are injected into context for richer information.

### Document ingestion pipeline

Use **RecursiveCharacterTextSplitter at 400–512 tokens with 10–20% overlap** as the default chunking strategy. A February 2026 Firecrawl benchmark across 50 academic papers found recursive 512-token splitting scored **69% accuracy** versus only 54% for semantic chunking (which produced fragments averaging 43 tokens). For code, use code-aware separators that split at class/function boundaries first.

Each chunk must carry structured metadata: `source_file`, `page_number`, `section_header` (extracted from document structure), `document_id`, `ingested_at`, `content_hash`, and `chunk_index`. The `content_hash` enables incremental updates: on re-ingestion, compare hashes and only re-embed changed documents, using the vector store's delete-by-metadata plus re-insert pattern to avoid full re-indexing.

---

## Engineering patterns that signal senior-level craft

The gap between tutorial-grade and portfolio-grade RAG lies in five areas: typed contracts, async design, resilience, observability, and testing. Each deserves deliberate implementation.

### Typed contracts with Pydantic v2

Define explicit Pydantic models for every data boundary. The essential models are `ChunkMetadata` (source, page, headings, content hash), `RetrievalQuery` (text with `min_length` validation, `top_k` with bounds, `score_threshold`, metadata filters), `RetrievalResult` (content, score, metadata, `computed_field` for `is_high_confidence`), `DocumentIngestionRequest` (with `model_validator` ensuring overlap < chunk_size), and `EmbeddingConfig` as a discriminated union across providers. Use `ConfigDict(extra='forbid')` on all models to reject unknown fields at load time — catching config typos immediately rather than silently ignoring them. Leverage Pydantic v2's `computed_field` for derived values that appear in serialization, and discriminated unions (`Field(discriminator='provider')`) for zero-ambiguity configuration parsing backed by Rust-speed validation.

### Async-first with controlled concurrency

RAG pipelines are heavily I/O-bound. The embedding service should use `asyncio.Semaphore` for rate limiting concurrent API calls, `asyncio.gather` for parallel hybrid retrieval (dense + BM25 simultaneously), and `asyncio.to_thread` for offloading blocking operations like cross-encoder inference. LanceDB's `AsyncConnection` and `AsyncTable` provide native async vector store operations. The anti-pattern to avoid: synchronous `requests.get()` blocking the event loop, or sequential embedding calls for 1,000 documents.

### Layered resilience: retry → circuit breaker → fallback → cache

Use **tenacity** for retry with exponential backoff (1s, 2s, 4s, 8s, 16s) on transient errors only (`RateLimitError`, `APIError`) — never retry auth or validation errors. Layer a circuit breaker (via `circuitbreaker` or `pybreaker`) that opens after 5 consecutive failures and falls back to local sentence-transformers embedding. The final fallback layer checks an embedding cache. Each layer returns a typed `EmbeddingResult` with a `source` field ("api", "local_fallback", "cache") for observability. This layered approach — resilience as a strategy, not an afterthought — is a signature senior engineering pattern.

### OpenTelemetry-based observability

Instrument every pipeline stage as a span in a trace tree: `rag.query` (root) → `rag.embed_query` → `rag.vector_search` → `rag.rerank` → `rag.assemble_context` → `rag.llm_inference`. Record key attributes on each span: embedding latency, model name, result count, top/min scores, token counts, and estimated cost. Export traces to LangSmith (set `LANGSMITH_OTEL_ENABLED=true` with langsmith ≥ 0.4.25) or Langfuse (OTLP endpoint at `/api/public/otel`). The critical metrics to dashboard are **embedding latency** (histogram), **retrieval score distribution** (gauge), **context token utilization** (histogram), and **end-to-end query latency at p50/p95/p99**.

### Testing at three levels

**Unit tests** validate chunking logic (respects max size, preserves heading hierarchy, overlap works correctly), Pydantic model validation (rejects empty queries, clamps `top_k`), and query transformation outputs. **Integration tests** use deterministic fixtures: seed a vector store with fixed embeddings (`np.random.seed(42)`), verify result count, score ordering, and metadata filtering. **Eval tests** using DeepEval's pytest integration run against a golden dataset of 20–50 curated (question, expected_answer, expected_contexts) triples, asserting thresholds on `ContextualPrecisionMetric(threshold=0.7)`, `FaithfulnessMetric(threshold=0.8)`, and `AnswerRelevancyMetric(threshold=0.7)`. Wire these into GitHub Actions with a CI gate that fails if any metric drops >5% from baseline.

---

## RAG evaluation integrated with the existing YAML rubric framework

The eval framework should combine **RAGAS** for metric calculation with **DeepEval** for pytest-style CI/CD integration and **Promptfoo-style YAML rubrics** for defining evaluation criteria declaratively. RAGAS provides reference-free evaluation using the LLM-as-judge pattern across retrieval metrics (context precision, context recall) and generation metrics (faithfulness, answer relevancy, factual correctness). As of December 2025, RAGAS also supports agent-specific metrics (tool call accuracy, agent goal accuracy) and custom rubrics-based scoring — both directly relevant to the multi-agent architecture.

To integrate with the existing YAML-rubric eval system, define RAG evaluation suites in YAML that match the existing configuration style:

```yaml
eval_suite:
  name: "rag_regression_v1"
  metrics:
    retrieval:
      - name: context_precision
        type: ragas
        threshold: 0.7
      - name: context_recall  
        type: ragas
        threshold: 0.8
    generation:
      - name: faithfulness
        type: ragas
        threshold: 0.85
    custom:
      - name: domain_accuracy
        type: llm-rubric
        prompt: "Is the response grounded in retrieved context? Score pass/fail."
  dataset:
    source: "eval/datasets/golden_rag_v1.jsonl"
```

Build the golden dataset incrementally: start with 20–50 manually curated examples from domain experts, augment with production query sampling (5–10% of live queries scored asynchronously by LLM-as-judge), and expand synthetically using RAGAS's `TestsetGenerator`. Version-control the dataset alongside code and link evaluation results to specific dataset versions.

For regression detection, track Precision@k, Recall@k, MRR, and NDCG trends across merges. Implement NDCG@10 as the primary ranking quality metric since it captures both relevance and position weighting. Use LLM-based relevance labels (which agree with human annotators >80% of the time per MT-Bench research) when ground-truth annotations are unavailable.

---

## File structure and module organization

The RAG pipeline should live as a **peer module** to `agents/`, `workflows/`, `tools/`, and `eval/` — not nested inside any of them. This maintains the monorepo's existing separation of concerns while making RAG capabilities independently testable and configurable.

```
project-root/
├── agents/                     # Existing agents
├── workflows/                  # Existing YAML workflow definitions
├── tools/
│   ├── registry.py             # Existing tool registry
│   └── rag_tool.py             # Thin bridge: wraps rag/ as a discoverable tool
├── rag/                        # NEW: RAG pipeline module
│   ├── __init__.py             # Public API exports
│   ├── config.py               # Pydantic settings with from_yaml() classmethod
│   ├── models.py               # All typed contracts (ChunkMetadata, RetrievalQuery, etc.)
│   ├── ingestion/
│   │   ├── loader.py           # Document loaders (PDF, Markdown, HTML)
│   │   ├── chunker.py          # Strategy pattern: RecursiveChunker, SemanticChunker
│   │   ├── metadata.py         # Metadata extraction and enrichment
│   │   └── pipeline.py         # IngestionPipeline orchestrator
│   ├── embedding/
│   │   ├── provider.py         # Abstract base + LiteLLM-backed factory
│   │   ├── batch.py            # Async batch embedding with semaphore rate limiting
│   │   └── cache.py            # Embedding cache (content-hash keyed)
│   ├── indexing/
│   │   ├── store.py            # VectorStore protocol + factory
│   │   ├── lifecycle.py        # Index create/update/rebuild/delete operations
│   │   └── adapters/
│   │       ├── lancedb.py      # LanceDB adapter (primary)
│   │       └── qdrant.py       # Qdrant adapter (secondary)
│   ├── retrieval/
│   │   ├── retriever.py        # Base retriever with hybrid search strategy
│   │   ├── reranker.py         # Cross-encoder and ColBERT reranking
│   │   ├── query_transform.py  # Multi-query, HyDE, step-back prompting
│   │   └── postprocessor.py    # Context compression, dedup, token budgeting
│   └── resilience/
│       └── decorators.py       # Circuit breaker, retry, fallback decorators
├── eval/
│   ├── metrics/
│   │   ├── rag_metrics.py      # RAGAS/DeepEval metric wrappers
│   │   └── rubrics/
│   │       └── rag_quality.yaml
│   └── datasets/
│       └── golden_rag_v1.jsonl
├── configs/
│   └── rag/
│       ├── default.yaml        # Default RAG config
│       └── workflows/          # Per-workflow RAG overrides
├── tests/
│   └── test_rag/
│       ├── test_ingestion.py
│       ├── test_retrieval.py
│       ├── test_rag_eval.py    # Golden dataset regression tests
│       └── conftest.py         # Seeded vector store fixtures
└── docs/
    └── decisions/
        └── adr-001-vector-store-selection.md
```

The `tools/rag_tool.py` bridge is deliberately thin — it wraps the `rag/` module's retriever as a LangChain `@tool` with a clear docstring that tells agents when to invoke it. Tool discovery uses the existing registry's auto-import pattern (`pkgutil.iter_modules`), checking for `BaseTool` instances in each module. The RAG config follows the same YAML pattern as existing workflow definitions, with per-workflow overrides using an `_extends` key for config inheritance.

---

## Conclusion

The implementation path is clear: start with LanceDB + Voyage 4 embeddings behind a LiteLLM abstraction, wire hybrid search (dense + BM25 → RRF → cross-encoder reranking) as a LangGraph `ToolNode` with self-corrective document grading, and wrap everything in Pydantic v2 typed contracts with async-first execution. The three patterns that will most impress reviewers are the **discriminated union configuration model** (showing Pydantic v2 mastery), the **layered resilience strategy** (retry → circuit breaker → local fallback → cache), and the **integrated evaluation pipeline** with YAML-defined rubrics and NDCG regression gates in CI. Each of these signals that the builder understands not just how RAG works, but how production ML systems are engineered. The module structure keeps RAG as an independent, testable subsystem that plugs cleanly into the existing agent/workflow/tool architecture through a single bridge file.