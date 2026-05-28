# Examples

Self-contained scripts demonstrating the core APIs of the agentic-workflows-v2 platform.  Every example is runnable without API keys unless noted otherwise, and includes comments explaining key concepts.

## Prerequisites

Install the main runtime and evaluation packages in development mode from the repository root:

```bash
# From agentic-workflows-v2/
pip install -e ".[dev,server]"

# From agentic-v2-eval/
pip install -e ".[dev]"
```

## Index

| # | File | What it demonstrates |
|---|------|----------------------|
| 01 | [01_hello_workflow.py](01_hello_workflow.py) | Define steps with `StepDefinition`, build a `Pipeline` with `PipelineBuilder`, execute it with `PipelineExecutor`, and inspect results via `ExecutionContext`. |
| 02 | [02_rag_pipeline.py](02_rag_pipeline.py) | Full RAG pipeline: create a `Document`, chunk with `RecursiveChunker`, embed with `InMemoryEmbedder`, store in `InMemoryVectorStore`, retrieve via `HybridRetriever` (dense + BM25 with RRF fusion), and assemble context with `TokenBudgetAssembler`. |
| 03 | [03_custom_agent.py](03_custom_agent.py) | Subclass `BaseAgent` with typed I/O (`TaskInput`/`TaskOutput`), implement the four abstract methods, configure with `AgentConfig`, register event handlers, and run the agent lifecycle. Uses a mock LLM call. |
| 04 | [04_model_routing.py](04_model_routing.py) | `ModelRouter` default chains, custom `FallbackChain` via fluent DSL, `ScopedRouter` temporary overrides, `SmartModelRouter` with health tracking / circuit breakers / adaptive cooldowns, and `call_with_fallback` automatic failover. |
| 05 | [05_evaluation.py](05_evaluation.py) | `Scorer` with inline rubric dicts, `ScoringResult` inspection, handling missing criteria, discovering built-in rubrics with `list_rubrics`/`load_rubric`, and comparing two workflow runs. |
| 06 | [06_adapter_switching.py](06_adapter_switching.py) | `AdapterRegistry` engine discovery, `DAG` with dependency-driven parallelism via `DAGExecutor` (Kahn's algorithm), `Pipeline` with sequential stages via `PipelineExecutor`, and comparing execution semantics. |

## Running

```bash
python examples/01_hello_workflow.py
python examples/02_rag_pipeline.py
python examples/03_custom_agent.py
python examples/04_model_routing.py
python examples/05_evaluation.py
python examples/06_adapter_switching.py
```

## Key Packages Used

- **agentic_v2.engine** -- `Pipeline`, `PipelineBuilder`, `DAG`, `DAGExecutor`, `StepDefinition`, `ExecutionContext`
- **agentic_v2.rag** -- `Document`, `RecursiveChunker`, `InMemoryEmbedder`, `InMemoryVectorStore`, `HybridRetriever`, `TokenBudgetAssembler`
- **agentic_v2.agents** -- `BaseAgent`, `AgentConfig`, `AgentEvent`, `AgentState`
- **agentic_v2.models** -- `ModelRouter`, `SmartModelRouter`, `ModelTier`, `FallbackChain`
- **agentic_v2.adapters** -- `AdapterRegistry`, `get_registry`
- **agentic_v2.contracts** -- `TaskInput`, `TaskOutput`, `StepResult`, `WorkflowResult`
- **agentic_v2_eval** -- `Scorer`, `ScoringResult`, `load_rubric`, `list_rubrics`
