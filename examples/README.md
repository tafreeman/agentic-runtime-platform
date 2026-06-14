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
| 07 | [sdk_task_orchestrator.py](sdk_task_orchestrator.py) | **SDK-native** `Task`-tool coordinator using the real Claude Agent SDK (`AgentDefinition`, `allowed_tools=["Task", ...]`, dynamic subagent selection, explicit per-spawn context, and parallel `Task` calls in one turn). The SDK-native counterpart to `OrchestratorAgent` — see [ADR-025](../docs/adr/ADR-025-sdk-task-orchestration.md). **Requires `ANTHROPIC_API_KEY`** (no-ops with a clear message when unset). |
| 08 | [resume_and_fork.py](resume_and_fork.py) | `ExecutionContext` checkpoint **`--resume <name>`** rehydration, **`fork_session(name)`** branching a divergent run off a shared baseline via `context.child()`, and on-resume changed-file detection that surfaces a "these files changed" notice for the caller to prepend to a resumed prompt. See [ADR-026](../docs/adr/ADR-026-resume-vs-summary-session.md). |
| 09 | [forced_tool_choice.py](forced_tool_choice.py) | **Forced / `any` / `auto` `tool_choice`** threaded through `build_tool_contracts` and the cloud backends so a step can force a specific tool (`{"type":"tool","name":...}`) or require *some* tool, plus the tier-0 cross-role **`verify_fact`** shared tool. Deterministic walkthrough needs no key; `--live` drives a real forced-tool step. See [ADR-027](../docs/adr/ADR-027-forced-tool-choice.md). |

## Running

```bash
python examples/01_hello_workflow.py
python examples/02_rag_pipeline.py
python examples/03_custom_agent.py
python examples/04_model_routing.py
python examples/05_evaluation.py
python examples/06_adapter_switching.py

# Claude Agent SDK Task-tool coordinator (needs ANTHROPIC_API_KEY)
python examples/sdk_task_orchestrator.py "Audit the orchestrator for risks"

# Checkpoint resume / fork-session demo (no API key required)
python examples/resume_and_fork.py demo
python examples/resume_and_fork.py --resume my_checkpoint
python examples/resume_and_fork.py --fork my_checkpoint   # resume, then fork it

# Forced/any/auto tool_choice + cross-role verify_fact (no API key required)
python examples/forced_tool_choice.py
ANTHROPIC_API_KEY=sk-ant-... python examples/forced_tool_choice.py --live
```

## Key Packages Used

- **agentic_v2.engine** -- `Pipeline`, `PipelineBuilder`, `DAG`, `DAGExecutor`, `StepDefinition`, `ExecutionContext`
- **agentic_v2.rag** -- `Document`, `RecursiveChunker`, `InMemoryEmbedder`, `InMemoryVectorStore`, `HybridRetriever`, `TokenBudgetAssembler`
- **agentic_v2.agents** -- `BaseAgent`, `AgentConfig`, `AgentEvent`, `AgentState`
- **agentic_v2.models** -- `ModelRouter`, `SmartModelRouter`, `ModelTier`, `FallbackChain`
- **agentic_v2.adapters** -- `AdapterRegistry`, `get_registry`
- **agentic_v2.contracts** -- `TaskInput`, `TaskOutput`, `StepResult`, `WorkflowResult`
- **agentic_v2_eval** -- `Scorer`, `ScoringResult`, `load_rubric`, `list_rubrics`
