# Runtime pattern catalog

This page points to concrete implementations in `agentic-workflows-v2`. It is
an implementation map, not a list of AI design ideas.

Patterns in the library are not automatically active in every workflow. Check
the selected adapter and workflow definition before assuming that a pattern is
part of an execution path.

## Workflow execution

### Dependency-driven execution

Use a directed acyclic graph (DAG) when steps have explicit dependencies and
independent steps may run at the same time.

- Graph model: `agentic_v2/engine/dag.py`
- Scheduler: `agentic_v2/engine/dag_executor.py`
- Adapter entry point: `agentic_v2/adapters/native/engine.py`

The scheduler runs ready nodes up to the configured concurrency limit. A
dependency failure is propagated instead of reporting the downstream node as
successful.

### Ordered pipelines

Use a pipeline when the order is more important than maximum concurrency.

- Pipeline types and builder: `agentic_v2/engine/pipeline.py`
- Unified dispatch: `agentic_v2/engine/executor.py`

Pipelines support sequential steps, explicit parallel groups, and conditional
branches. They do not infer dependencies between arbitrary steps.

### Conditional steps

Workflow `when` expressions decide whether a step runs.

- Native evaluator: `agentic_v2/engine/expressions.py`
- LangGraph evaluator: `agentic_v2/langchain/expressions.py`
- Authoring rules: [Workflow authoring](WORKFLOW_AUTHORING.md)

Expressions are evaluated by the runtime's restricted expression parser. They
are not Python `eval` expressions.

### Bounded review loops

`loop_until` repeats a step until its condition passes. `loop_max` sets a hard
limit.

- YAML parsing: `agentic_v2/workflows/loader.py`
- Native execution: `agentic_v2/engine/step.py`
- LangGraph wiring: `agentic_v2/langchain/graph_wiring.py`
- Shipped example:
  `agentic_v2/workflows/definitions/iterative_review.yaml`

Always set a useful completion condition and a small upper bound. Repetition
alone does not guarantee a better result.

## Agents and tools

### Typed agent lifecycle

`BaseAgent[TInput, TOutput]` defines initialization, execution, cancellation,
events, tool calls, and output parsing.

- Base lifecycle: `agentic_v2/agents/base.py`
- Configuration and state: `agentic_v2/agents/config.py`
- Concrete agents: `agentic_v2/agents/coder.py`,
  `reviewer.py`, `architect.py`, and `test_agent.py`

See [Agents](deep-dive-agents.md) for the extension contract.

### Tool binding and calls

`BaseAgent._bind_tools()` selects registered tools allowed by the agent's
configured tier. `_handle_tool_calls()` dispatches requested calls and adds
their results to conversation memory.

- Agent integration: `agentic_v2/agents/base.py`
- Registry and tool metadata: `agentic_v2/tools/`

Registration makes a tool available; it does not make every call safe. Tool
implementations still need input validation, timeouts, and clear failure
results.

### Capability-based assignment

Agents declare capabilities such as code generation, review, testing, and
orchestration. The orchestrator can score those capabilities against a
subtask.

- Capability types and scoring: `agentic_v2/agents/capabilities.py`
- Assignment and fallback handling: `agentic_v2/agents/orchestrator.py`

The score is a routing input, not proof that an agent can complete the task.

### Task decomposition and delegation

`OrchestratorAgent` can request a structured subtask plan, validate it, select
agents, and run dependency-ready work with bounded parallelism.

- Public orchestrator: `agentic_v2/agents/orchestrator.py`
- Plan models and prompt: `agentic_v2/agents/orchestrator_models.py`
- Deterministic planning helpers:
  `agentic_v2/agents/orchestrator_planning.py`
- Input factories: `agentic_v2/agents/orchestrator_factories.py`

The `agentic orchestrate` CLI command currently reports that dynamic
orchestration is not exposed through the default LangGraph workflow path. Use
the Python API when testing this implementation.

### Conversation memory

`ConversationMemory` stores messages within configurable message and token
limits and can summarize older content.

- Implementation: `agentic_v2/agents/memory.py`

This is per-agent conversation state. It is separate from persisted workflow
checkpoints.

## Models and reliability

### Model routing and circuit state

`SmartModelRouter` combines model availability and recorded statistics when it
selects a model. `ModelStats` tracks circuit states so repeatedly failing
models can be skipped temporarily.

- Routing: `agentic_v2/models/smart_router.py`
- Statistics and circuit state: `agentic_v2/models/model_stats.py`

Routing decisions depend on the statistics available to that process or
configured store. They are not a provider service-level guarantee.

### Consensus

The engine provides majority voting and repeated-sample consistency helpers.

- Implementation: `agentic_v2/engine/consensus.py`
- Shipped workflow:
  `agentic_v2/workflows/definitions/consensus_review.yaml`

Agreement can reduce isolated variation, but several models can agree on the
same error. Keep evidence-based checks outside the vote.

## Evaluation and review

### Agent self-review

`CoderAgent.reflect()` implements an optional review pass through the
`SelfReflectionMixin` contract.

- Contract: `agentic_v2/agents/capabilities.py`
- Coder implementation: `agentic_v2/agents/coder.py`

Self-review is generated by a model and may repeat the original mistake. Treat
it as another signal, not independent verification.

### Workflow and output evaluation

The runtime and `agentic-v2-eval` package provide different evaluation paths.

- Runtime scoring: `agentic_v2/scoring/`
- Evaluation package: `agentic-v2-eval/src/agentic_v2_eval/`
- User guide: [Evaluation framework](architecture-eval.md)

Choose one path explicitly and record its rubric, model, run count, and input
set with the result.

## Historical patterns

Earlier versions included a `deep_research.yaml` workflow and antagonist
personas that are no longer in the repository. Tree search,
chain-of-verification, adversarial review, confidence gating, and
domain-specific recency rules described in old ADRs or changelog entries are
historical unless a current file above implements them.

Do not copy a historical pattern into a new workflow without rechecking its
data contract, stopping conditions, provider calls, and tests.
