# Concept Glossary

A reference of key terms, patterns, and abstractions used throughout the `tafreeman/agentic-runtime-platform` monorepo. Each entry includes a concise definition and a pointer to the relevant source code or configuration.

---

## Core Architecture

**Adapter** -- A pluggable backend that satisfies the `ExecutionEngine` protocol and is registered with the `AdapterRegistry`. The codebase ships two built-in adapters: `native` (DAG executor) and `langchain` (LangGraph state-machine compiler). New adapters are added by implementing `ExecutionEngine` and calling `get_registry().register()`.
See `agentic_v2/adapters/registry.py`.

**AdapterRegistry** -- A thread-safe singleton that maps string names (e.g. `"native"`, `"langchain"`) to concrete `ExecutionEngine` classes. Adapters are lazily instantiated on first `get_adapter()` call; registration happens at import time and the registry never eagerly imports adapter packages.
See `agentic_v2/adapters/registry.py`.

**Additive-Only** -- Schema evolution policy for contracts: new optional fields with defaults may be added, but existing fields are never removed or renamed. This guarantees backward compatibility for downstream consumers of the contract schemas.
See `agentic_v2/contracts/`.

**Checkpoint** -- A serialized snapshot of completed workflow steps and context state, enabling resume-after-failure. The `SupportsCheckpointing` protocol defines `get_checkpoint_state()` and `resume()` methods for engines that support this capability.
See `agentic_v2/core/protocols.py`.

**Contract** -- A Pydantic v2 model defining typed data structures that flow through the workflow engine, server API, and evaluation framework. Key contracts include `TaskInput`, `TaskOutput`, `StepResult`, `WorkflowResult`, `AgentMessage`, and `ReviewReport`. Contracts follow the additive-only rule.
See `agentic_v2/contracts/`.

**ExecutionContext** -- The shared mutable state carrier for a single workflow run. Provides hierarchical scoping (child contexts inherit parent variables but write locally), JMESPath deep-nested lookups, event hooks (`STEP_START`, `STEP_END`, `VARIABLE_SET`, `CHECKPOINT_SAVE`), checkpoint/restore for fault tolerance, and a `ServiceContainer` for dependency injection. All variable mutations are guarded by `asyncio.Lock`.
See `agentic_v2/engine/context.py`.

**Protocol** -- A PEP 544 structural subtyping interface decorated with `@runtime_checkable`. Classes conform by shape (matching method signatures), not by inheritance. The codebase defines protocols for engines (`ExecutionEngine`), agents (`AgentProtocol`), tools (`ToolProtocol`), memory (`MemoryStoreProtocol`), and all RAG components (`LoaderProtocol`, `ChunkerProtocol`, `EmbeddingProtocol`, `VectorStoreProtocol`). Optional capability protocols include `SupportsStreaming` and `SupportsCheckpointing`.
See `agentic_v2/core/protocols.py`, `agentic_v2/rag/protocols.py`.

**ServiceContainer** -- A dependency injection container within `ExecutionContext` that supports singleton and factory patterns, shared across parent and child context scopes.
See `agentic_v2/engine/context.py`.

---

## Agent System

**Agent** -- An LLM-powered actor with a persona, tools, memory, and a typed execution loop. Agents process `TaskInput` and produce `TaskOutput`, optionally maintaining conversation state across invocations. Concrete agents include Coder, Architect, Reviewer, and Orchestrator.
See `agentic_v2/agents/`.

**AgentState** -- A finite-state enum representing the lifecycle of a `BaseAgent`: `CREATED -> INITIALIZING -> READY -> RUNNING -> COMPLETED | FAILED | CANCELLED`. Agents may also be `PAUSED` and later resumed.
See `agentic_v2/agents/base.py`.

**BaseAgent** -- The abstract base class that all concrete agents must subclass. Provides the iterative execution loop with typed I/O (`TInput` / `TOutput`), dynamic tool binding filtered by `ModelTier`, conversation memory with automatic summarization, and an event system for observability hooks (`STATE_CHANGE`, `TOOL_CALLED`, `STREAMING`, etc.).
See `agentic_v2/agents/base.py`.

**Capability** -- A typed skill declaration with a proficiency level (0.0--1.0) used for dynamic agent-to-task matching. Defined via `CapabilityType` enum values such as `CODE_GENERATION`, `CODE_REVIEW`, `SELF_REFLECTION`, `ORCHESTRATION`, and `TASK_DECOMPOSITION`. Agents compose capabilities through multiple-inheritance mixins (e.g. `CodeGenerationMixin`, `SelfReflectionMixin`), and the orchestrator selects the best agent for each subtask by scoring capability set matches.
See `agentic_v2/agents/capabilities.py`.

**CapabilityMixin** -- An abstract mixin base class that concrete capability mixins extend. Each mixin declares the capabilities it provides via `get_capabilities()`. Agents gain capabilities through multiple inheritance, e.g. `class MyAgent(BaseAgent, CodeGenerationMixin, TestGenerationMixin)`. The `get_agent_capabilities()` function walks the MRO to aggregate all declared capabilities.
See `agentic_v2/agents/capabilities.py`.

**ConversationMemory** -- A sliding-window message buffer within `BaseAgent` with a configurable token budget and automatic summarization of evicted messages. Distinct from `MemoryStoreProtocol`, which handles cross-session persistent memory.
See `agentic_v2/agents/base.py`.

**MemoryStoreProtocol** -- The async interface for persistent memory backends, supporting key-value CRUD (store, retrieve, delete) and query-based search with ranked results. Implementations include `InMemoryStore` (dict-backed, for testing) and `RAGMemoryStore` (vector-backed). The deprecated alias `MemoryStore` is kept for backward compatibility.
See `agentic_v2/core/memory.py`.

**Persona** -- A markdown definition of an agent's expertise, reasoning protocol, output format, and boundaries. Located in `agentic_v2/prompts/*.md`, each persona file must define sections for Expertise, Reasoning Protocol, Boundaries, Critical Rules, and Output Format. The codebase contains 7 agent persona definitions (architect, coder, orchestrator, planner, reviewer, tester, validator) as of 2026-04-22.
See `agentic_v2/prompts/`.

**Tool** -- A callable capability available to agents during execution, satisfying `ToolProtocol` (properties: `name`, `description`; method: `execute(**kwargs)`). The codebase ships 11 built-in tool modules (code analysis, file ops, git ops, HTTP ops, memory ops, search ops, shell ops, transform, etc.). Tools are registered in a `ToolRegistry` and allowlisted per workflow step, with high-risk tools (`shell`, `git`, `file_delete`) defaulting to DENY.
See `agentic_v2/tools/`.

**ToolRegistry** -- A registry that manages available tools and provides lookup by name. Agents receive filtered tool sets based on their workflow step's allowlist and the agent's `ModelTier`.
See `agentic_v2/tools/registry.py`.

---

## RAG Pipeline

**BM25** -- Okapi BM25, a probabilistic keyword retrieval algorithm. The codebase includes a pure-Python in-memory `BM25Index` that builds an inverted index from chunks, tokenizes on whitespace with lowercasing, and computes BM25 scores with configurable `k1` (term saturation, default 1.5) and `b` (length normalization, default 0.75) parameters. Used as the sparse retrieval component in hybrid search.
See `agentic_v2/rag/retrieval.py`.

**Chunk** -- A segment of a document produced by the chunking stage. Each chunk carries its text content, a unique `chunk_id`, positional metadata (document ID, index), and arbitrary metadata for filtering. Chunks are the atomic unit that flows through embedding, indexing, and retrieval.
See `agentic_v2/rag/contracts.py`.

**Cosine Similarity** -- The distance metric used by `InMemoryVectorStore` for dense vector search. Measures the cosine of the angle between the query embedding and stored chunk embeddings to rank semantically similar content.
See `agentic_v2/rag/vectorstore.py`.

**Document** -- A loaded source file or URL represented as a structured object with content, metadata, and a document ID. Produced by loaders (`LoaderProtocol`) and consumed by chunkers.
See `agentic_v2/rag/contracts.py`.

**Embedding** -- A dense floating-point vector representation of text content, produced by an `EmbeddingProtocol` implementation. Used for semantic similarity search in the vector store. Embeddings are content-hash deduplicated to avoid redundant computation. The `InMemoryEmbedder` provides deterministic hash-based embeddings for testing.
See `agentic_v2/rag/embeddings.py`.

**Hybrid Retrieval** -- A retrieval strategy that combines dense vector search (cosine similarity) with sparse BM25 keyword search, then merges the two result sets using Reciprocal Rank Fusion (RRF). The `HybridRetriever` class orchestrates both retrieval paths and produces a unified ranked result list, combining the strengths of semantic understanding and exact keyword matching.
See `agentic_v2/rag/retrieval.py`.

**IngestionPipeline** -- The orchestrator for the load-then-chunk stages of the RAG pipeline. Takes a `LoaderProtocol` and `ChunkerProtocol` and provides a single `ingest(source)` method that produces chunks ready for embedding and indexing.
See `agentic_v2/rag/ingestion.py`.

**RAG (Retrieval-Augmented Generation)** -- A pattern of retrieving relevant documents from a knowledge base to augment LLM context before generation. The codebase implements a full 13-module, protocol-backed RAG pipeline: load, recursive chunk, embed (content-hash dedup), index (cosine similarity vector store + BM25 keyword index), hybrid retrieve (RRF fusion), token-budget assemble, and OTEL trace.
See `agentic_v2/rag/`.

**RecursiveChunker** -- The default chunking implementation that splits documents using hierarchical separators (`\n\n` paragraph, `\n` line, `. ` sentence, ` ` word, `` `` character), recursively splitting oversized segments until all chunks fit within the configured `chunk_size`. Satisfies `ChunkerProtocol`.
See `agentic_v2/rag/chunking.py`.

**RRF (Reciprocal Rank Fusion)** -- A score fusion algorithm that combines ranked lists from multiple retrieval methods. For each document, the fused score is `sum(1 / (k + rank))` across all retrieval methods, where `k` is a smoothing constant (typically 60). Produces a single merged ranking from dense and BM25 results without requiring score normalization.
See `agentic_v2/rag/retrieval.py`.

**Token Budget** -- The maximum token allocation for assembled RAG context. The `TokenBudgetAssembler` greedily adds retrieval results in descending score order until the budget is exhausted, using a `len(text) // 4` heuristic for token estimation. When framing is enabled, each chunk is wrapped in `<retrieved_context>` delimiters for prompt injection defense, and the framing overhead is deducted from the budget.
See `agentic_v2/rag/context_assembly.py`.

**VectorStore** -- A backend for storing and searching embedding vectors. The `VectorStoreProtocol` defines the interface (`add`, `search`, `delete`). Implementations include `InMemoryVectorStore` (pure-Python cosine similarity, for testing/dev) and `LanceDBVectorStore` (persistent, requires optional `lancedb` dependency).
See `agentic_v2/rag/vectorstore.py`.

---

## Agentic Patterns

**Antagonist Review** -- An adversarial review methodology implemented at the prompt level through two orthogonal antagonist personas: one performing FMEA (Failure Mode and Effects Analysis) murder-board review, and another conducting systemic pre-mortem analysis. Designed to surface failure modes before deployment.
See `agentic_v2/prompts/`.

**Chain-of-Thought (CoT)** -- A prompting technique where the model reasons step-by-step before answering. All 12 agent personas include a `## Reasoning Protocol` section that scaffolds structured thinking. CoT improves accuracy on complex tasks by making the reasoning process explicit and auditable.
See `agentic_v2/prompts/*.md`.

**Chain-of-Verification (CoVe)** -- A pattern where claims generated by the model are independently verified after generation. Dedicated verification steps re-check factual claims against source material, flagging unsupported assertions. Verification steps have access to web search and HTTP tools for independent source confirmation.
See `agentic_v2/workflows/lib/ci_calculator.py`.

**Confidence Gating** -- Conditional execution based on multi-dimensional confidence interval scores. Research workflows produce a confidence index (CI); iteration continues until `CI >= min_ci` (default 0.80) or `max_rounds` is reached. The CI is computed from coverage score, source quality score, and recency metrics.
See `agentic_v2/workflows/lib/ci_calculator.py`, `agentic_v2/config/defaults/evaluation.yaml`.

**ReAct (Reason + Act)** -- An agentic pattern where the agent reasons about the next action, executes it via a tool, observes the result, and repeats. In the codebase, ReAct manifests in retrieval steps where agents decide which searches to perform, execute them via `web_search` / `http_get` tools, and incorporate results into the next reasoning cycle.
See `agentic_v2/agents/base.py`.

**Tree-of-Thought (ToT)** -- A reasoning pattern that generates multiple reasoning paths (hypotheses) and evaluates them to select the most promising. Agent personas include ToT scaffolding for hypothesis generation and evaluation across multiple reasoning paths.
See `agentic_v2/prompts/*.md`.

---

## LLM Routing

**Circuit Breaker** -- A fault tolerance pattern implemented in `SmartModelRouter` with three states: `CLOSED` (normal operation), `OPEN` (model is failing, reject requests and skip to next in chain), and `HALF_OPEN` (testing recovery with serialized probe requests). Transitions are driven by consecutive failure counts and adaptive cooldown timers.
See `agentic_v2/models/model_stats.py`, `agentic_v2/models/smart_router.py`.

**CooldownConfig** -- Configuration for adaptive cooldown scaling in the smart router. Base cooldowns are multiplied by `1.5^consecutive_failures`, capped at 600 seconds. Separate base durations exist for general failures (30s), rate limits (120s), and timeouts (60s). Rate-limit cooldowns parse `Retry-After` headers from provider responses.
See `agentic_v2/models/smart_router.py`.

**FallbackChain** -- An immutable ordered sequence of model identifiers to try in priority order within a tier. Built via a fluent `ChainBuilder` DSL. Default chains are ordered free-tier-first (Gemini, GitHub Models) then paid (OpenAI, Anthropic). Model identifiers use a `provider:model_name` format, e.g. `"gemini:gemini-2.0-flash"` or `"gh:openai/gpt-4o-mini"`.
See `agentic_v2/models/router.py`.

**ModelRouter** -- The foundational routing layer for LLM model selection. Routes requests to the first available model in a tier's `FallbackChain`. Supports lazy model discovery, parallel health checks, and `ScopedRouter` context-manager overrides.
See `agentic_v2/models/router.py`.

**Per-Provider Bulkhead** -- An `asyncio.Semaphore` per LLM provider (e.g. OpenAI: 50, Ollama: 10) that prevents cascade failures when one provider is slow. Limits concurrent requests to any single provider independently of other providers.
See `agentic_v2/models/smart_router.py`.

**SmartModelRouter** -- A production-hardened extension of `ModelRouter` with runtime intelligence: health-weighted model selection (`success_rate * 0.6 + latency_score * 0.2 + recency_score * 0.2`), circuit breaker logic, adaptive cooldowns with exponential backoff, per-provider bulkhead semaphores, rate-limit header parsing, optional cost-aware routing, and atomic JSON stats persistence for cross-restart continuity.
See `agentic_v2/models/smart_router.py`.

**Tier** -- An LLM routing level from `TIER_0` (deterministic tools, no LLM) through `TIER_5` (premium cloud models like GPT-4-turbo, Claude-3-opus). Each tier has a pre-configured `FallbackChain` of models ordered by cost and capability. `TIER_1` = small models (1-3B params), `TIER_2` = medium (7-14B), `TIER_3` = large (32B+), `TIER_4` = cloud (GPT-4, Claude), `TIER_5` = premium cloud.
See `agentic_v2/models/router.py`.

---

## Evaluation

**Evaluator** -- A component that scores agent or workflow output against a rubric. The framework provides multiple evaluator types: base, LLM-based (uses an LLM as judge), pattern-based (regex/structural matching), quality, and standard evaluators. All evaluators produce numeric scores and structured feedback.
See `agentic-v2-eval/src/agentic_v2_eval/evaluators/`.

**LLM Judge** -- An evaluation method where an LLM scores output on a 0.0--10.0 scale against rubric-defined criteria. Used for automated quality assessment when human evaluation is impractical.
See `tools/agents/benchmarks/llm_evaluator.py`.

**Reporter** -- A component that formats evaluation results into human-readable output. Supports multiple output formats including HTML reports. Reporters consume scored results from runners and produce presentation-ready summaries.
See `agentic-v2-eval/src/agentic_v2_eval/reporters/`.

**Rubric** -- A YAML-defined set of evaluation criteria with weighted dimensions and scoring thresholds. Each rubric specifies named criteria (e.g. Accuracy, Completeness, Efficiency) with weights that sum to 1.0 and description strings. The framework includes 8 rubric definitions: `default`, `agent`, `code`, `coding_standards`, `pattern`, `prompt_pattern`, `prompt_standard`, and `quality`.
See `agentic-v2-eval/src/agentic_v2_eval/rubrics/`.

**Runner** -- The execution harness for evaluation: loads datasets, invokes evaluators against rubrics, and collects scored results. Implementations include `BatchRunner` (synchronous batch), `StreamingRunner` (progressive output), and `AsyncStreamingRunner` (async progressive output).
See `agentic-v2-eval/src/agentic_v2_eval/runners/`.

---

## Workflow Engine

**DAG (Directed Acyclic Graph)** -- The data structure representing step dependencies in a workflow. Steps are nodes and `depends_on` declarations are directed edges. The DAG ensures no circular dependencies and enables parallel scheduling of independent steps.
See `agentic_v2/engine/dag.py`.

**DAGExecutor** -- The native execution engine that schedules workflow steps using Kahn's algorithm for maximum parallelism. Steps execute as soon as their upstream dependencies are satisfied, using `asyncio.wait(FIRST_COMPLETED)` to unblock downstream steps instantly. Includes cascade-skip via BFS on failure and deadlock detection.
See `agentic_v2/engine/dag_executor.py`.

**Expression Language** -- A safe DSL embedded in YAML workflow definitions for dynamic value resolution. Syntax includes `${inputs.topic}` for workflow inputs, `${steps.step1.outputs.result}` for step output references, `${coalesce(a, b)}` for null-safe fallback, and `${ctx.count > 5}` for conditional expressions. Evaluated via AST-safe parsing with `_NullSafe` sentinel for missing values, preventing `AttributeError` on optional step outputs.
See `agentic_v2/engine/expressions.py`.

**Kahn's Algorithm** -- A topological sorting algorithm used by the `DAGExecutor` for runtime step scheduling. Tracks in-degree counts (number of unsatisfied upstream dependencies) per step; steps with in-degree 0 are immediately eligible for execution. When a step completes, all downstream in-degrees are decremented, potentially releasing new steps for parallel execution.
See `agentic_v2/engine/dag_executor.py`.

**Loop-Until** -- A bounded re-execution mechanism for workflow steps. A step with a `loop_until` expression is re-executed until the expression evaluates to `True` or `loop_max` iterations are reached. Used for iterative refinement patterns like bounded re-review, where a reviewer step re-runs until the output meets quality criteria.
See `agentic_v2/engine/step.py`.

**RetryConfig** -- Configuration for step-level retry behavior, supporting four backoff strategies: `NONE`, `FIXED`, `LINEAR`, and `EXPONENTIAL` (with jitter). Each step can specify `max_retries` and strategy parameters independently.
See `agentic_v2/engine/step.py`.

**StepDefinition** -- A declarative specification of what a single workflow step does: its async function, model tier, conditional execution (`when` / `unless`), input/output mappings, lifecycle hooks, retry configuration, and optional `loop_until` expression. Constructed via a fluent builder API or the `@step` decorator.
See `agentic_v2/engine/step.py`.

**StepExecutor** -- The runtime delegate that handles single-step execution within the DAG. Manages the full step lifecycle: input mapping from `ExecutionContext`, timeout enforcement, retry with backoff, pre/post hooks, output capture, loop-until re-execution, and review-report normalization.
See `agentic_v2/engine/step.py`.

**StepState** -- The lifecycle state of an individual step during execution: `PENDING -> READY -> RUNNING -> SUCCESS | FAILED | SKIPPED`. Managed by `StepStateManager`, which enforces valid state transitions and emits events for observability.
See `agentic_v2/engine/step_state.py`.

**Workflow** -- A declarative YAML definition of a multi-step, multi-agent execution plan. Each workflow specifies a name, description, version, input/output schemas, and an ordered list of steps. Each step declares its agent, tools, dependencies (`depends_on`), input/output mappings using expression language, and optional conditions. The codebase includes 6 workflow definitions covering code review, bug resolution, fullstack generation, iterative review, and conditional branching.
See `agentic_v2/workflows/definitions/`.

---

## Cross-Cutting Concerns

**OTEL Tracing** -- OpenTelemetry-based distributed tracing integrated into the RAG pipeline for observability. Traces span the full retrieval lifecycle (embed, search, assemble) to support debugging and performance analysis.
See `agentic_v2/rag/tracing.py`.

**Research Gating** -- Quality thresholds applied to research outputs: `coverage_score >= 0.80` and `source_quality_score >= 0.80`. Research that does not meet these thresholds is flagged for additional iteration or manual review.
See `agentic_v2/config/defaults/evaluation.yaml`.

**Source Tier** -- A classification system for research source quality. **Tier A** (always acceptable): official docs, peer-reviewed papers, arXiv from known groups. **Tier B** (conditional): high-quality engineering blogs, high-vote Stack Overflow answers. **Tier C** (blocked): unverified blogs, marketing materials. Critical architectural claims require at least 2 independent Tier A sources.
See `docs/OWASP_LLM_THREAT_MODEL.md` and `docs/AI_RISK_MANAGEMENT.md`.
