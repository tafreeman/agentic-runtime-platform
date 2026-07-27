# Pattern catalog

This document maps agentic AI patterns to their implementations in the Agentic Runtime Platform codebase. For each pattern it identifies the specific files, classes, and functions involved, so you can locate how a pattern works without reading the full codebase. Patterns whose implementations have since been removed from the repository are listed separately at the [end](#previously-implemented-removed).

---

## Table of contents

- [Orchestration patterns](#orchestration-patterns)
  - [1. Tool use](#1-tool-use)
  - [2. Task decomposition](#2-task-decomposition)
  - [3. Capability matching](#3-capability-matching)
  - [4. Multi-agent coordination](#4-multi-agent-coordination)
  - [5. Bounded iteration](#5-bounded-iteration)
- [Prompting patterns](#prompting-patterns)
  - [6. Chain-of-thought scaffolding](#6-chain-of-thought-scaffolding)
- [Retrieval patterns](#retrieval-patterns)
  - [7. Hybrid retrieval](#7-hybrid-retrieval)
  - [8. Conversational memory](#8-conversational-memory)
- [Routing patterns](#routing-patterns)
  - [9. Circuit breaker](#9-circuit-breaker)
- [Evaluation patterns](#evaluation-patterns)
  - [10. Self-reflection](#10-self-reflection)
- [Safety patterns](#safety-patterns)
  - [11. Prompt injection defense](#11-prompt-injection-defense)
- [Previously implemented (removed)](#previously-implemented-removed)

---

## Orchestration patterns

### 1. Tool use

**Category:** Orchestration
**Implementation:** `agentic-workflows-v2/agentic_v2/agents/base.py` -- `BaseAgent._bind_tools()`, `_handle_tool_calls()`, `_get_tool_schemas()`
**How It Works:** During initialization, `BaseAgent._bind_tools()` iterates the global `ToolRegistry` and binds every tool whose tier is at or below the agent's configured `default_tier`. When the LLM response contains `tool_calls`, `_handle_tool_calls()` dispatches each call to the matching bound tool, executes it, and injects the result back into conversation memory as a `"tool"` role message so the LLM can incorporate it in the next iteration.
**Code Reference:** `agentic-workflows-v2/agentic_v2/agents/base.py` (`_bind_tools`, `_handle_tool_calls`)
**Example:**
```python
# Tier-filtered binding at agent init
async def _bind_tools(self) -> None:
    max_tier = self.config.default_tier.value
    for tool in self.tools.list_tools():
        if tool.tier <= max_tier:
            self._bound_tools[tool.name] = tool
```

---

### 2. Task decomposition

**Category:** Orchestration
**Implementation:** `agentic-workflows-v2/agentic_v2/agents/orchestrator.py` -- `OrchestratorAgent._parse_output()`, `decompose_task()`
**How It Works:** The `OrchestratorAgent` sends the task description and a list of registered agents (with their capabilities) to the LLM via a system prompt requesting structured JSON decomposition. The LLM returns a JSON plan with subtasks, each declaring required `capabilities` and `dependencies`. The orchestrator parses this with `_extract_json()` (delegating to balanced-brace extraction in `json_extraction.py`) and builds `SubTask` objects with dependency edges for downstream scheduling.
**Code Reference:** `agentic-workflows-v2/agentic_v2/agents/orchestrator.py` (`decompose_task`, `_parse_output`)
**Example:**
```json
{
  "subtasks": [
    {
      "id": "generate",
      "description": "Generate the code",
      "capabilities": ["code_generation"],
      "dependencies": [],
      "parallel_group": 1
    },
    {
      "id": "review",
      "description": "Review the generated code",
      "capabilities": ["code_review"],
      "dependencies": ["generate"],
      "parallel_group": 2
    }
  ]
}
```

---

### 3. Capability matching

**Category:** Orchestration
**Implementation:** `agentic-workflows-v2/agentic_v2/agents/capabilities.py` -- `CapabilitySet.score_match()`, `get_agent_capabilities()`
**How It Works:** Each agent declares capabilities via mixin classes (`CodeGenerationMixin`, `CodeReviewMixin`, etc.) that return a `CapabilitySet`. When the orchestrator needs to assign an agent to a subtask, `score_match()` computes a 0.0-1.0 match score by averaging `min(1.0, agent_proficiency / required_proficiency)` across all required capability types. `get_agent_capabilities()` walks the agent's MRO to aggregate capabilities from all mixin bases. The orchestrator builds a ranked candidate list sorted by score and stores fallback chains for resilience.
**Code Reference:** `agentic-workflows-v2/agentic_v2/agents/capabilities.py` (`score_match`, `get_agent_capabilities`)
**Example:**
```python
# Scoring: proficiency ratio averaged across requirements
def score_match(self, required: "CapabilitySet") -> float:
    total_score = 0.0
    for cap_type, req_cap in required.capabilities.items():
        our_cap = self.capabilities.get(cap_type)
        if our_cap:
            total_score += min(1.0, our_cap.proficiency / max(0.01, req_cap.proficiency))
    return total_score / len(required.capabilities)
```

---

### 4. Multi-agent coordination

**Category:** Orchestration
**Implementation:** `agentic-workflows-v2/agentic_v2/agents/orchestrator.py` -- `OrchestratorAgent.execute_as_dag()`, `_execute_plan()`; `agentic-workflows-v2/agentic_v2/engine/dag_executor.py` -- `DAGExecutor.execute()`
**How It Works:** The orchestrator registers specialized agents, decomposes the task, assigns agents via capability scoring, and then executes the resulting plan. The preferred path is `execute_as_dag()`, which builds a `DAG` object from subtask dependencies and delegates to the `DAGExecutor`. The DAG executor implements Kahn's algorithm, tracking in-degrees and scheduling steps via `asyncio.wait(FIRST_COMPLETED)` for maximum parallelism. A fallback chain in `_execute_plan()` tries alternative agents if the primary assignment fails.
**Code Reference:** `agentic-workflows-v2/agentic_v2/agents/orchestrator.py` (`execute_as_dag`, `_execute_plan`); `agentic-workflows-v2/agentic_v2/engine/dag_executor.py` (`DAGExecutor.execute`)
**Example:**
```python
# DAG executor: Kahn's algorithm with asyncio parallelism
ready = deque([name for name, deg in in_degree.items() if deg == 0])
while len(completed) < len(dag.steps):
    while ready and len(running) < max_concurrency:
        step_name = ready.popleft()
        tasks.add(asyncio.create_task(run_step(step_name)))
    done, tasks = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
    # ... decrement downstream in-degrees, unlock ready steps
```

---

### 5. Bounded iteration

**Category:** Orchestration
**Implementation:** `agentic-workflows-v2/agentic_v2/workflows/loader.py` -- `loop_max` parsing; `agentic-workflows-v2/agentic_v2/workflows/definitions/iterative_review.yaml` -- `review_rework_loop` step (`loop_until` + `loop_max`)
**How It Works:** Workflow steps can declare a `loop_until` expression and a `loop_max` integer. The workflow loader parses `loop_max` (default 3, minimum 1) and attaches it to the `StepDefinition`. At runtime, the step re-executes until the `loop_until` condition is satisfied or `loop_max` iterations are reached, preventing infinite agent loops. The shipped `iterative_review` workflow demonstrates this: its `review_rework_loop` step reviews and reworks generated code until the review status is approved or the iteration cap trips, with a post-loop `escalation_notice` step that fires only when the loop never approved.
**Code Reference:** `agentic-workflows-v2/agentic_v2/workflows/loader.py` (`loop_max` parsing); `agentic-workflows-v2/agentic_v2/workflows/definitions/iterative_review.yaml` (`review_rework_loop`)
**Example:**
```yaml
# iterative_review.yaml -- bounded review/rework loop
- name: review_rework_loop
  agent: tier3_reviewer
  depends_on: [implement]
  loop_until: >-
    ${steps.review_rework_loop.outputs.review_status} in ['APPROVED', 'APPROVED_WITH_NOTES']
  loop_max: ${inputs.max_review_rounds}
```

---

## Prompting patterns

### 6. Chain-of-thought scaffolding

**Category:** Prompting
**Implementation:** All 7 persona files in `agentic-workflows-v2/agentic_v2/prompts/*.md` (`architect`, `coder`, `orchestrator`, `planner`, `reviewer`, `tester`, `validator`) -- `## Reasoning Protocol` sections
**How It Works:** Every agent persona includes a `## Reasoning Protocol` section with a domain-specific multi-step cognitive workflow that instructs the LLM to reason through the task before generating output. These are not generic "think step-by-step" prompts -- each is tailored to the persona's function. For example, the coder persona uses stack-identification-first reasoning, while the reviewer, tester, and validator personas each define their own review, test-design, and verification protocols.
**Code Reference:** `agentic-workflows-v2/agentic_v2/prompts/coder.md` (`## Reasoning Protocol` section; the other personas follow the same convention)
**Example:**
```markdown
## Reasoning Protocol  (from coder.md)

Before generating your response:
1. Identify the target stack from inputs and select the matching language/framework conventions
2. Read any existing code, review findings, or rework instructions to understand what must change
3. Plan the file structure: which files to create vs. modify, and in what dependency order
4. For each file, determine imports, types, and error handling before writing implementation
5. Verify all artifacts are complete — no TODOs, no missing imports, no placeholder logic
```

---

## Retrieval patterns

### 7. Hybrid retrieval

**Category:** Retrieval
**Implementation:** `agentic-workflows-v2/agentic_v2/rag/retrieval.py` -- `BM25Index`, `reciprocal_rank_fusion()`, `HybridRetriever`
**How It Works:** The `HybridRetriever` combines two independent retrieval signals. Dense retrieval embeds the query via `EmbeddingProtocol` and searches a `VectorStoreProtocol` backend using cosine similarity. Keyword retrieval uses a pure-Python `BM25Index` implementing Okapi BM25 with k1=1.5 and b=0.75, including proper IDF with Laplace smoothing. Both ranked lists are merged via `reciprocal_rank_fusion()`, which computes `score = sum(1/(k+rank))` with k=60 (per Cormack et al. 2009) and deduplicates by `chunk_id`. This dual-signal approach improves recall over either method alone.
**Code Reference:** `agentic-workflows-v2/agentic_v2/rag/retrieval.py` (`BM25Index`, `reciprocal_rank_fusion`, `HybridRetriever.retrieve`)
**Example:**
```python
# HybridRetriever.retrieve() -- dual signal + RRF fusion
async def retrieve(self, query: str, *, top_k: int = 5) -> list[RetrievalResult]:
    dense_results = await self.dense_only(query, top_k=top_k)
    bm25_results = self._bm25.search(query, top_k=top_k)
    results = reciprocal_rank_fusion(
        [dense_results, bm25_results], k=self._rrf_k, top_k=top_k,
    )
    return results
```

---

### 8. Conversational memory

**Category:** Retrieval
**Implementation:** `agentic-workflows-v2/agentic_v2/agents/memory.py` -- `ConversationMemory` class
**How It Works:** `ConversationMemory` maintains a sliding window of messages (default 50) with a token budget (default 8000 tokens). When the window exceeds either limit, `_summarize_and_trim()` compacts older messages into textual summaries, preserving the system prompt and most recent messages. Summaries are prepended to the LLM message list as system context by `get_messages()`. The summary budget is itself bounded (`max_summaries=5`) to prevent unbounded growth. Token counting uses a `len(text) // 4` heuristic with an optional pluggable `token_counter` callable for precise counting.
**Code Reference:** `agentic-workflows-v2/agentic_v2/agents/memory.py` (`ConversationMemory`, `_summarize_and_trim`, `get_messages`)
**Example:**
```python
# Automatic summarization when window overflows
def add(self, role: str, content: str, **kwargs) -> ConversationMessage:
    msg = ConversationMessage(role=role, content=content, **kwargs)
    self.messages.append(msg)
    if len(self.messages) > self.max_messages or self.total_tokens > self.max_tokens:
        self._summarize_and_trim()
    return msg
```

---

## Routing patterns

### 9. Circuit breaker

**Category:** Routing
**Implementation:** `agentic-workflows-v2/agentic_v2/models/model_stats.py` -- `ModelStats`, `CircuitState`; `agentic-workflows-v2/agentic_v2/models/smart_router.py` -- `SmartModelRouter`
**How It Works:** Each model has a per-model `ModelStats` instance with a `CircuitState` FSM: `CLOSED` (normal) -> `OPEN` (after 5 consecutive failures) -> `HALF_OPEN` (after the recovery timeout). The `SmartModelRouter` layers production hardening on top: health-weighted selection scoring `success_rate x 0.6 + latency_score x 0.2 + recency_score x 0.2`, adaptive cooldowns with `base x 1.5^consecutive_failures` capped at 600s, per-provider bulkhead semaphores preventing cascade failures, probe lock serialization for HALF_OPEN recovery, cross-tier degradation preferring cheaper tiers first, and rate-limit header parsing. Latency is measured with `time.monotonic()` to avoid wall-clock jumps.
**Code Reference:** `agentic-workflows-v2/agentic_v2/models/model_stats.py` (`CircuitState`, `ModelStats`, `check_circuit`); `agentic-workflows-v2/agentic_v2/models/smart_router.py` (`SmartModelRouter`, `call_with_fallback`)
**Example:**
```python
# Circuit state transition in ModelStats
def record_failure(self, error_type: str = "unknown") -> None:
    self._consecutive_failures += 1
    if self.circuit_state == CircuitState.HALF_OPEN:
        self.circuit_state = CircuitState.OPEN   # failed recovery probe
    elif self._consecutive_failures >= self._failure_threshold:
        self.circuit_state = CircuitState.OPEN    # trip the breaker
```

---

## Evaluation patterns

### 10. Self-reflection

**Category:** Evaluation
**Implementation:** `agentic-workflows-v2/agentic_v2/agents/capabilities.py` -- `SelfReflectionMixin`; `agentic-workflows-v2/agentic_v2/agents/coder.py` -- `CoderAgent.reflect()`
**How It Works:** `SelfReflectionMixin` declares the `SELF_REFLECTION` capability type and defines an abstract `async reflect(output, criteria)` method. `CoderAgent` inherits both `CodeGenerationMixin` and `SelfReflectionMixin`, and provides a concrete `reflect()` implementation that sends the generated code back to the LLM with a reflection prompt requesting a JSON critique with `needs_revision`, `issues`, and optional `revised_output` fields. The reflection result is parsed via `extract_json()` for structured consumption. This enables the agent to critique its own output before returning it.
**Code Reference:** `agentic-workflows-v2/agentic_v2/agents/capabilities.py` (`SelfReflectionMixin`); `agentic-workflows-v2/agentic_v2/agents/coder.py` (`CoderAgent.reflect`)
**Example:**
```python
# CoderAgent.reflect() -- self-critique via LLM
async def reflect(self, output: str, criteria: str = "correctness") -> dict[str, Any]:
    reflection_prompt = (
        f"Review the following code for {criteria} issues. "
        f"Return a JSON object with 'needs_revision' (bool), "
        f"'issues' (list of strings), and optionally 'revised_output' (str).\n\n"
        f"```\n{output}\n```"
    )
    self._memory.add_user(reflection_prompt)
    response = await self._get_model_response()
    content = response.get("content", "")
    return extract_json(content)
```

---

## Safety patterns

### 11. Prompt injection defense

**Category:** Safety
**Implementation:** `agentic-workflows-v2/agentic_v2/rag/context_assembly.py` -- `frame_content()`, `TokenBudgetAssembler` with `frame_results=True`
**How It Works:** Retrieved documents may contain adversarial content designed to hijack LLM behavior (e.g., "Ignore all previous instructions..."). The `frame_content()` function wraps each chunk in `<retrieved_context>` / `</retrieved_context>` delimiter tags, signaling to the LLM that the enclosed content is untrusted user-provided data and should not be interpreted as instructions. The `TokenBudgetAssembler` applies this framing by default (`frame_results=True`) when assembling retrieval results, and accounts for the framing overhead in its token budget calculation. The system prompt instructs the model to treat content within these tags as data only.
**Code Reference:** `agentic-workflows-v2/agentic_v2/rag/context_assembly.py` (`frame_content`, `TokenBudgetAssembler`)
**Example:**
```python
# Delimiter framing for prompt injection defense
CONTEXT_DELIMITER_START = "<retrieved_context>"
CONTEXT_DELIMITER_END = "</retrieved_context>"

def frame_content(content: str) -> str:
    return f"{CONTEXT_DELIMITER_START}\n{content}\n{CONTEXT_DELIMITER_END}"

# Applied automatically during assembly
if self._frame_results:
    framed = RetrievalResult(
        content=frame_content(result.content),
        score=result.score,
        ...
    )
```

---

## Cross-reference: pattern to file index

| Pattern | Primary file(s) | Key symbols |
|---------|-----------------|-------------|
| Tool use | `agents/base.py` | `_bind_tools`, `_handle_tool_calls` |
| Task decomposition | `agents/orchestrator.py` | `decompose_task`, `_parse_output` |
| Capability matching | `agents/capabilities.py` | `score_match`, `get_agent_capabilities` |
| Multi-agent coordination | `agents/orchestrator.py`, `engine/dag_executor.py` | `execute_as_dag`, `_execute_plan`; `DAGExecutor.execute` |
| Bounded iteration | `workflows/loader.py`, `workflows/definitions/iterative_review.yaml` | `loop_max` parsing; `review_rework_loop` |
| Chain-of-thought scaffolding | `prompts/*.md` (all 7) | `## Reasoning Protocol` sections |
| Hybrid retrieval | `rag/retrieval.py` | `BM25Index`, `reciprocal_rank_fusion`, `HybridRetriever` |
| Conversational memory | `agents/memory.py` | `ConversationMemory`, `_summarize_and_trim` |
| Circuit breaker | `models/model_stats.py`, `models/smart_router.py` | `CircuitState`, `ModelStats`; `SmartModelRouter`, `call_with_fallback` |
| Self-reflection | `agents/capabilities.py`, `agents/coder.py` | `SelfReflectionMixin`; `CoderAgent.reflect` |
| Prompt injection defense | `rag/context_assembly.py` | `frame_content`, `TokenBudgetAssembler` |

All file paths above are relative to `agentic-workflows-v2/agentic_v2/`.

---

## Previously implemented (removed)

The following patterns were implemented by files that have since been removed from the repository — principally the `deep_research.yaml` workflow and the two antagonist persona prompts. They are documented here for historical reference only; there is no current in-repo implementation to cite. Git history contains the removed files if you want to resurrect one.

- **Tree-of-thought** *(removed)* — `deep_research.yaml`'s `hypothesis_tree_tot_roundN` steps had a `tier3_reasoner` agent build a search plan as a tree of hypotheses with confirming and disconfirming evidence paths, forcing exploration of multiple reasoning branches per round.
- **ReAct** *(removed)* — `deep_research.yaml`'s `retrieval_react_roundN` steps ran a Reason+Act loop: a `tier2_researcher` agent alternated between reasoning about what evidence to gather and invoking `web_search` / `http_get` / `context_store` tools.
- **Chain-of-verification** *(removed)* — `deep_research.yaml`'s `cove_verify_roundN` steps had a `tier3_reviewer` agent independently re-verify claims from the parallel analyst steps against fresh evidence, producing a verification score and unresolved questions for the next round.
- **Adversarial review** *(removed)* — two independent antagonist personas (`antagonist_implementation.md`, FMEA-style failure-mode enumeration; `antagonist_systemic.md`, pre-mortem systemic risk analysis) attacked plans from non-overlapping angles.
- **Confidence gating** *(removed)* — `deep_research.yaml`'s `coverage_confidence_audit_roundN` steps computed a multi-dimensional confidence index and emitted a `gate_passed` boolean; later rounds ran only `when:` the gate had not yet passed. The shipped `iterative_review` and `consensus_review` workflows use related (but simpler) status- and agreement-based gates.
- **Domain-adaptive recency** *(removed)* — `deep_research.yaml` accepted a `domain` enum and a `recency_window_days` input that propagated to every retrieval step, so fast-moving domains required more recent sources than stable ones.
