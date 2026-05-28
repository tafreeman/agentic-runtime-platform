# Pattern Catalog

**Mapping agentic AI patterns to their codebase implementations.**

This document is a navigational guide. For each pattern, it identifies the specific files, classes, and line numbers where the pattern is implemented. Use it to locate how a pattern works without reading the full codebase.

**Source:** `docs/analysis/ml-ai-patterns-review.md` Section 8 (Agentic Patterns Inventory)
**Last updated:** 2026-03-09 (**Note:** content frozen at this date. Epic 1-6 April 2026 changes may have drifted the file/line references below. Trust current code over this doc when mismatched.)

---

## Table of Contents

- [Orchestration Patterns](#orchestration-patterns)
  - [1. Tool Use](#1-tool-use)
  - [2. Task Decomposition](#2-task-decomposition)
  - [3. Capability Matching](#3-capability-matching)
  - [4. Multi-Agent Coordination](#4-multi-agent-coordination)
  - [5. Bounded Iteration](#5-bounded-iteration)
- [Prompting Patterns](#prompting-patterns)
  - [6. Chain-of-Thought Scaffolding](#6-chain-of-thought-scaffolding)
  - [7. Tree-of-Thought](#7-tree-of-thought)
  - [8. ReAct](#8-react)
  - [9. Chain-of-Verification](#9-chain-of-verification)
  - [10. Adversarial Review](#10-adversarial-review)
- [Retrieval Patterns](#retrieval-patterns)
  - [11. Hybrid Retrieval](#11-hybrid-retrieval)
  - [12. Conversational Memory](#12-conversational-memory)
- [Routing Patterns](#routing-patterns)
  - [13. Circuit Breaker](#13-circuit-breaker)
- [Evaluation Patterns](#evaluation-patterns)
  - [14. Confidence Gating](#14-confidence-gating)
  - [15. Self-Reflection](#15-self-reflection)
  - [16. Domain-Adaptive Recency](#16-domain-adaptive-recency)
- [Safety Patterns](#safety-patterns)
  - [17. Prompt Injection Defense](#17-prompt-injection-defense)

---

## Orchestration Patterns

### 1. Tool Use

**Category:** Orchestration
**Implementation:** `agentic-workflows-v2/agentic_v2/agents/base.py` -- `BaseAgent._bind_tools()`, `_handle_tool_calls()`, `_get_tool_schemas()`
**How It Works:** During initialization, `BaseAgent._bind_tools()` (line 660) iterates the global `ToolRegistry` and binds every tool whose tier is at or below the agent's configured `default_tier`. When the LLM response contains `tool_calls`, `_handle_tool_calls()` (line 696) dispatches each call to the matching bound tool, executes it, and injects the result back into conversation memory as a `"tool"` role message so the LLM can incorporate it in the next iteration.
**Code Reference:** `agentic-workflows-v2/agentic_v2/agents/base.py:660` (`_bind_tools`), `:696` (`_handle_tool_calls`)
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

### 2. Task Decomposition

**Category:** Orchestration
**Implementation:** `agentic-workflows-v2/agentic_v2/agents/orchestrator.py` -- `OrchestratorAgent._parse_output()`, `decompose_task()`
**How It Works:** The `OrchestratorAgent` sends the task description and a list of registered agents (with their capabilities) to the LLM via a system prompt requesting structured JSON decomposition (line 103). The LLM returns a JSON plan with subtasks, each declaring required `capabilities` and `dependencies`. The orchestrator parses this with `_extract_json()` (delegating to balanced-brace extraction in `json_extraction.py`) and builds `SubTask` objects with dependency edges for downstream scheduling.
**Code Reference:** `agentic-workflows-v2/agentic_v2/agents/orchestrator.py:103` (system prompt), `:275` (`_parse_output`), `:475` (`decompose_task`)
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

### 3. Capability Matching

**Category:** Orchestration
**Implementation:** `agentic-workflows-v2/agentic_v2/agents/capabilities.py` -- `CapabilitySet.score_match()`, `get_agent_capabilities()`
**How It Works:** Each agent declares capabilities via mixin classes (`CodeGenerationMixin`, `CodeReviewMixin`, etc.) that return a `CapabilitySet`. When the orchestrator needs to assign an agent to a subtask, `score_match()` (line 161) computes a 0.0-1.0 match score by averaging `min(1.0, agent_proficiency / required_proficiency)` across all required capability types. `get_agent_capabilities()` (line 352) walks the agent's MRO to aggregate capabilities from all mixin bases. The orchestrator builds a ranked candidate list sorted by score and stores fallback chains for resilience.
**Code Reference:** `agentic-workflows-v2/agentic_v2/agents/capabilities.py:161` (`score_match`), `:352` (`get_agent_capabilities`)
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

### 4. Multi-Agent Coordination

**Category:** Orchestration
**Implementation:** `agentic-workflows-v2/agentic_v2/agents/orchestrator.py` -- `OrchestratorAgent.execute_as_dag()`, `_execute_plan()`; `agentic-workflows-v2/agentic_v2/engine/dag_executor.py` -- `DAGExecutor.execute()`
**How It Works:** The orchestrator registers specialized agents, decomposes the task, assigns agents via capability scoring, and then executes the resulting plan. The preferred path is `execute_as_dag()` (line 518) which builds a `DAG` object from subtask dependencies and delegates to the `DAGExecutor`. The DAG executor implements Kahn's algorithm (line 114 of `dag_executor.py`), tracking in-degrees and scheduling steps via `asyncio.wait(FIRST_COMPLETED)` for maximum parallelism. A fallback chain tries alternative agents if the primary assignment fails (line 420 of `orchestrator.py`).
**Code Reference:** `agentic-workflows-v2/agentic_v2/agents/orchestrator.py:518` (`execute_as_dag`), `:399` (`_execute_plan` with fallback); `agentic-workflows-v2/agentic_v2/engine/dag_executor.py:49` (`DAGExecutor.execute`)
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

### 5. Bounded Iteration

**Category:** Orchestration
**Implementation:** `agentic-workflows-v2/agentic_v2/workflows/loader.py` -- `loop_max` parsing (line 513); `agentic-workflows-v2/agentic_v2/workflows/definitions/tdd_codegen_e2e.yaml` *(removed)* -- `loop_max: 2` (line 500); `agentic-workflows-v2/agentic_v2/workflows/definitions/fullstack_generation_bounded_rereview.yaml` *(removed)* -- conditional `when:` guards
**How It Works:** Workflow steps can declare a `loop_until` expression and a `loop_max` integer. The workflow loader (line 513) parses `loop_max` (default 3, minimum 1) and attaches it to the `StepDefinition`. At runtime, the step re-executes until the `loop_until` condition is satisfied or `loop_max` iterations are reached, preventing infinite agent loops. The bounded rereview workflow demonstrates a different approach: explicit conditional steps (`when:` guards) that cap review-rework cycles at 2 passes maximum.
**Code Reference:** `agentic-workflows-v2/agentic_v2/workflows/loader.py:513` (loop_max parsing); `agentic-workflows-v2/agentic_v2/workflows/definitions/tdd_codegen_e2e.yaml:500` *(removed)* (loop_max usage)
**Example:**
```yaml
# tdd_codegen_e2e.yaml -- bounded QA loop
- name: qa_rework_loop
  loop_until: >-
    ${steps.qa_rework_loop.outputs.review_report.overall_status} in ['APPROVED']
    and ${steps.qa_rework_loop.outputs.overall_test_status} in ['PASS']
  loop_max: 2
```

---

## Prompting Patterns

### 6. Chain-of-Thought Scaffolding

**Category:** Prompting
**Implementation:** All 24 persona files in `agentic-workflows-v2/agentic_v2/prompts/*.md` -- `## Reasoning Protocol` sections
**How It Works:** Every agent persona includes a `## Reasoning Protocol` section with a domain-specific 5-step cognitive workflow that instructs the LLM to reason through the task before generating output. These are not generic "think step-by-step" prompts -- each is tailored to the persona's function. For example, the coder persona uses stack-identification-first reasoning, the debugger uses trace-backward root-cause analysis, the antagonist_implementation uses FMEA failure-mode enumeration, and the task_planner uses WBS decomposition.
**Code Reference:** `agentic-workflows-v2/agentic_v2/prompts/coder.md:15` (Reasoning Protocol); `agentic-workflows-v2/agentic_v2/prompts/reasoner.md:11` *(removed)* (Reasoning Protocol)
**Example:**
```markdown
## Reasoning Protocol  (from coder.md)

Before generating your response:
1. Identify the target stack from inputs and select the matching language/framework conventions
2. Read any existing code, review findings, or rework instructions to understand what must change
3. Plan the file structure: which files to create vs. modify, and in what dependency order
4. For each file, determine imports, types, and error handling before writing implementation
5. Verify all artifacts are complete -- no TODOs, no missing imports, no placeholder logic
```

---

### 7. Tree-of-Thought

**Category:** Prompting
**Implementation:** `agentic-workflows-v2/agentic_v2/workflows/definitions/deep_research.yaml` *(removed)* -- `hypothesis_tree_tot_roundN` steps (lines 138, 237, 336, 436)
**How It Works:** In each research round, a `hypothesis_tree_tot` step instructs a `tier3_reasoner` agent to build a search plan organized as a tree of hypotheses with disconfirming paths. The agent receives the scoped research goal, prior search plans (from previous rounds), and unresolved questions, then outputs a structured `search_plan` with branching hypotheses. Each hypothesis includes both confirming and disconfirming evidence paths, forcing the LLM to explore multiple reasoning branches rather than committing to the first plausible answer. YAML anchors (`&hypothesis_step`) provide DRY template reuse across all 4 rounds.
**Code Reference:** `agentic-workflows-v2/agentic_v2/workflows/definitions/deep_research.yaml:138` *(removed)* (round 1), `:237` (round 2), `:336` (round 3), `:436` (round 4)
**Example:**
```yaml
- <<: *hypothesis_step
  name: hypothesis_tree_tot_round1
  description: Build a Tree-of-Thought search plan with hypotheses and disconfirming paths (round 1)
  depends_on: [source_policy]
  inputs:
    scoped_goal: ${steps.intake_scope.outputs.scoped_goal}
    source_policy: ${steps.source_policy.outputs.source_policy}
    objectives: ${steps.intake_scope.outputs.research_objectives}
  outputs:
    search_plan: search_plan_round1
    hypotheses: hypotheses_round1
    open_questions: open_questions_round1
```

---

### 8. ReAct

**Category:** Prompting
**Implementation:** `agentic-workflows-v2/agentic_v2/workflows/definitions/deep_research.yaml` *(removed)* -- `retrieval_react_roundN` steps (lines 151, 251, 351, 451)
**How It Works:** Each `retrieval_react` step assigns a `tier2_researcher` agent with tool access (`web_search`, `http_get`, `context_store`) to execute a Reason+Act retrieval loop. The agent receives the search plan from the Tree-of-Thought step and iteratively reasons about what evidence to gather next, acts by invoking search tools, observes the results, and decides whether to search further or stop. This implements the classic ReAct (Reason + Act) prompting pattern where the LLM alternates between thinking and tool use within a single step execution.
**Code Reference:** `agentic-workflows-v2/agentic_v2/workflows/definitions/deep_research.yaml:151` *(removed)* (round 1), `:251` (round 2)
**Example:**
```yaml
- <<: *retrieval_step
  name: retrieval_react_round1
  description: Run ReAct retrieval loop to gather evidence and source metadata (round 1)
  depends_on: [hypothesis_tree_tot_round1]
  tools: [web_search, http_get, context_store]
  inputs:
    search_plan: ${steps.hypothesis_tree_tot_round1.outputs.search_plan}
    source_policy: ${steps.source_policy.outputs.source_policy}
    recency_window_days: ${inputs.recency_window_days}
  outputs:
    sources: sources_round1
    evidence_bundle: evidence_round1
```

---

### 9. Chain-of-Verification

**Category:** Prompting
**Implementation:** `agentic-workflows-v2/agentic_v2/workflows/definitions/deep_research.yaml` *(removed)* -- `cove_verify_roundN` steps (lines 190, 290, 390, 490)
**How It Works:** After parallel AI and SWE specialist analyses in each round, a `cove_verify` step assigns a `tier3_reviewer` agent (with `web_search`, `http_get`, `context_store` tools) to independently verify claims from both analyses against fresh evidence. The step receives the AI analysis, SWE analysis, and evidence bundle, then cross-checks factual claims, identifies contradictions, produces a verification score, and surfaces unresolved questions that feed into the next round's hypothesis tree. This implements Chain-of-Verification (CoVe) by requiring independent re-verification of LLM-generated claims.
**Code Reference:** `agentic-workflows-v2/agentic_v2/workflows/definitions/deep_research.yaml:190` *(removed)* (round 1), `:290` (round 2)
**Example:**
```yaml
- <<: *cove_verify_step
  name: cove_verify_round1
  description: Perform Chain-of-Verification checks against independent evidence (round 1)
  depends_on: [analyst_ai_round1, analyst_swe_round1]
  inputs:
    ai_analysis: ${steps.analyst_ai_round1.outputs.ai_analysis}
    swe_analysis: ${steps.analyst_swe_round1.outputs.swe_analysis}
    evidence_bundle: ${steps.retrieval_react_round1.outputs.evidence_bundle}
  outputs:
    verified_claims: verified_claims_round1
    contradictions: contradictions_round1
    verification_score: verification_score_round1
    unresolved_questions: unresolved_questions_round1
```

---

### 10. Adversarial Review

**Category:** Prompting
**Implementation:** `agentic-workflows-v2/agentic_v2/prompts/antagonist_implementation.md` *(removed)* (87 lines); `agentic-workflows-v2/agentic_v2/prompts/antagonist_systemic.md` *(removed)* (115 lines)
**How It Works:** Two orthogonal antagonist personas attack plans from non-overlapping angles. The **Implementation Failure Analyst** (`antagonist_implementation.md`) applies NASA Standing Review Board / FMEA methodology -- enumerating concrete failure modes, tracing cascade chains, and calculating risk priority (Likelihood x Severity x Detection difficulty). Its boundaries strictly limit it to internal mechanical feasibility. The **Systemic Risk Analyst** (`antagonist_systemic.md`) applies Gary Klein's Pre-Mortem technique -- assuming the project has already failed 12 months from now and working backward to identify fragile assumptions, YAGNI risk, irreversibility, and second-order effects. Its boundaries strictly exclude internal code quality. Together they provide comprehensive adversarial coverage without overlap.
**Code Reference:** `agentic-workflows-v2/agentic_v2/prompts/antagonist_implementation.md:1` *(removed)* (FMEA persona); `agentic-workflows-v2/agentic_v2/prompts/antagonist_systemic.md:1` *(removed)* (Pre-Mortem persona)
**Example:**
```markdown
## Reasoning Protocol  (from antagonist_implementation.md)

1. Read the plan end-to-end and list every explicit dependency, assumption, and time estimate
2. For each task, ask: "What specific thing could go wrong here?" -- enumerate concrete failure modes
3. Trace cascade chains: if task X fails, which downstream tasks are blocked or corrupted?
4. Classify each failure: Fatal, Recoverable, or Cosmetic
5. Calculate risk priority: Likelihood x Severity x Detection difficulty
```

---

## Retrieval Patterns

### 11. Hybrid Retrieval

**Category:** Retrieval
**Implementation:** `agentic-workflows-v2/agentic_v2/rag/retrieval.py` -- `BM25Index`, `reciprocal_rank_fusion()`, `HybridRetriever`
**How It Works:** The `HybridRetriever` (line 227) combines two independent retrieval signals. Dense retrieval embeds the query via `EmbeddingProtocol` and searches a `VectorStoreProtocol` backend using cosine similarity. Keyword retrieval uses a pure-Python `BM25Index` (line 31) implementing Okapi BM25 with k1=1.5 and b=0.75, including proper IDF with Laplace smoothing. Both ranked lists are merged via `reciprocal_rank_fusion()` (line 169), which computes `score = sum(1/(k+rank))` with k=60 (per Cormack et al. 2009) and deduplicates by `chunk_id`. This dual-signal approach improves recall over either method alone.
**Code Reference:** `agentic-workflows-v2/agentic_v2/rag/retrieval.py:31` (`BM25Index`), `:169` (`reciprocal_rank_fusion`), `:227` (`HybridRetriever`), `:266` (`retrieve` method)
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

### 12. Conversational Memory

**Category:** Retrieval
**Implementation:** `agentic-workflows-v2/agentic_v2/agents/base.py` -- `ConversationMemory` class (line 131)
**How It Works:** `ConversationMemory` maintains a sliding window of messages (default 50) with a token budget (default 8000 tokens). When the window exceeds either limit, `_summarize_and_trim()` (line 274) compacts older messages into textual summaries, preserving the system prompt and most recent messages. Summaries are prepended to the LLM message list as system context (line 194). The summary budget is itself bounded (`max_summaries=5`, line 263) to prevent unbounded growth. Token counting uses a `len(text) // 4` heuristic with an optional pluggable `token_counter` callable for precise counting.
**Code Reference:** `agentic-workflows-v2/agentic_v2/agents/base.py:131` (`ConversationMemory`), `:274` (`_summarize_and_trim`), `:189` (`get_messages` with summary injection)
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

## Routing Patterns

### 13. Circuit Breaker

**Category:** Routing
**Implementation:** `agentic-workflows-v2/agentic_v2/models/model_stats.py` -- `ModelStats`, `CircuitState`; `agentic-workflows-v2/agentic_v2/models/smart_router.py` -- `SmartModelRouter`
**How It Works:** Each model has a per-model `ModelStats` instance with a `CircuitState` FSM: `CLOSED` (normal) -> `OPEN` (after 5 consecutive failures, line 242 of `model_stats.py`) -> `HALF_OPEN` (after recovery timeout, line 291). The `SmartModelRouter` layers production hardening on top: health-weighted selection scoring `success_rate x 0.6 + latency_score x 0.2 + recency_score x 0.2` (line 331 of `smart_router.py`), adaptive cooldowns with `base x 1.5^consecutive_failures` capped at 600s (line 217), per-provider bulkhead semaphores preventing cascade failures (line 119), probe lock serialization for HALF_OPEN recovery (line 132), cross-tier degradation preferring cheaper tiers first (line 236), and rate-limit header parsing (line 182). Latency is measured with `time.monotonic()` to avoid wall-clock jumps.
**Code Reference:** `agentic-workflows-v2/agentic_v2/models/model_stats.py:19` (`CircuitState`), `:49` (`ModelStats`), `:280` (`check_circuit`); `agentic-workflows-v2/agentic_v2/models/smart_router.py:63` (`SmartModelRouter`), `:528` (`call_with_fallback`)
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

## Evaluation Patterns

### 14. Confidence Gating

**Category:** Evaluation
**Implementation:** `agentic-workflows-v2/agentic_v2/workflows/definitions/deep_research.yaml` *(removed)* -- `coverage_confidence_audit_roundN` steps (lines 207, 307, 407, 507); conditional `when:` expressions on subsequent rounds
**How It Works:** At the end of each research round, a `coverage_confidence_audit` step computes a multi-dimensional confidence index (CI) from five dimensions: `coverage_score`, `source_quality_score`, `agreement_score`, `verification_score`, and `recency_score`. The step outputs a `gate_passed` boolean indicating whether the CI meets the `min_ci` threshold (default 0.8). Subsequent rounds are gated by `when: not ${steps.coverage_confidence_audit_roundN.outputs.gate_passed}` -- they only execute if the gate has not been passed. This prevents unnecessary computation when confidence is already sufficient and bounds the maximum research depth to 4 rounds.
**Code Reference:** `agentic-workflows-v2/agentic_v2/workflows/definitions/deep_research.yaml:207` *(removed)* (audit round 1), `:240` (gate condition on round 2)
**Example:**
```yaml
# Conditional execution gated on confidence score
- name: hypothesis_tree_tot_round2
  depends_on: [coverage_confidence_audit_round1]
  when: ${inputs.max_rounds} >= 2 and not ${steps.coverage_confidence_audit_round1.outputs.gate_passed}

# Audit step outputs used for gating
outputs:
  ci_score: ci_score_round1
  gate_passed: gate_passed_round1
```

---

### 15. Self-Reflection

**Category:** Evaluation
**Implementation:** `agentic-workflows-v2/agentic_v2/agents/capabilities.py` -- `SelfReflectionMixin` (line 296); `agentic-workflows-v2/agentic_v2/agents/coder.py` -- `CoderAgent.reflect()` (line 273)
**How It Works:** `SelfReflectionMixin` declares the `SELF_REFLECTION` capability type and defines an abstract `async reflect(output, criteria)` method. `CoderAgent` (line 50 of `coder.py`) inherits both `CodeGenerationMixin` and `SelfReflectionMixin`, and provides a concrete `reflect()` implementation (line 273) that sends the generated code back to the LLM with a reflection prompt requesting a JSON critique with `needs_revision`, `issues`, and optional `revised_output` fields. The reflection result is parsed via `extract_json()` for structured consumption. This enables the agent to critique its own output before returning it.
**Code Reference:** `agentic-workflows-v2/agentic_v2/agents/capabilities.py:296` (`SelfReflectionMixin`); `agentic-workflows-v2/agentic_v2/agents/coder.py:50` (class declaration), `:273` (`reflect` implementation)
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

### 16. Domain-Adaptive Recency

**Category:** Evaluation
**Implementation:** `agentic-workflows-v2/agentic_v2/workflows/definitions/deep_research.yaml` *(removed)* -- `inputs.domain` (line 72), `inputs.recency_window_days` (line 88), propagation through `retrieval_react` steps
**How It Works:** The `deep_research` workflow accepts a `domain` input with an enum of research domains (`ai_ml`, `cloud_infrastructure`, `programming_languages`, `academic_research`, `default`, `ai_software`). Each domain maps to a different implicit recency window that determines how old a source can be and still count as "recent." The `recency_window_days` input (default 183 days / ~6 months) can override the domain default. This value propagates to every `retrieval_react` step as an input, and the `coverage_confidence_audit` steps count `recent_source_count` against a `min_recent_sources` threshold. The recency score contributes to the multi-dimensional CI, ensuring fast-moving domains like AI/ML require more recent evidence than stable academic domains.
**Code Reference:** `agentic-workflows-v2/agentic_v2/workflows/definitions/deep_research.yaml:72` *(removed)* (domain enum), `:88` (recency_window_days), `:161` (recency propagation to retrieval)
**Example:**
```yaml
inputs:
  domain:
    type: string
    description: Research domain for adaptive recency window
    enum: [ai_ml, cloud_infrastructure, programming_languages, academic_research, default, ai_software]
    default: default
  recency_window_days:
    type: number
    description: Number of days considered recent (overrides domain-based default when set)
    default: 183
```

---

## Safety Patterns

### 17. Prompt Injection Defense

**Category:** Safety
**Implementation:** `agentic-workflows-v2/agentic_v2/rag/context_assembly.py` -- `frame_content()`, `TokenBudgetAssembler` with `frame_results=True`
**How It Works:** Retrieved documents may contain adversarial content designed to hijack LLM behavior (e.g., "Ignore all previous instructions..."). The `frame_content()` function (line 39) wraps each chunk in `<retrieved_context>` / `</retrieved_context>` delimiter tags, signaling to the LLM that the enclosed content is untrusted user-provided data and should not be interpreted as instructions. The `TokenBudgetAssembler` (line 66) applies this framing by default (`frame_results=True`) when assembling retrieval results, and accounts for the framing overhead in its token budget calculation. The system prompt instructs the model to treat content within these tags as data only.
**Code Reference:** `agentic-workflows-v2/agentic_v2/rag/context_assembly.py:29` (delimiter constants), `:39` (`frame_content`), `:66` (`TokenBudgetAssembler`), `:138` (framing applied during assembly)
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

## Cross-Reference: Pattern to File Index

| Pattern | Primary File(s) | Key Line(s) |
|---------|-----------------|-------------|
| Tool Use | `agents/base.py` | 660, 696 |
| Task Decomposition | `agents/orchestrator.py` | 103, 275 |
| Capability Matching | `agents/capabilities.py` | 161, 352 |
| Multi-Agent Coordination | `agents/orchestrator.py`, `engine/dag_executor.py` | 518, 399; 49 |
| Bounded Iteration | `workflows/loader.py`, YAML definitions | 513; yaml:500 |
| Chain-of-Thought Scaffolding | `prompts/*.md` (all 24) | Reasoning Protocol sections |
| Tree-of-Thought | `workflows/definitions/deep_research.yaml` *(removed)* | 138, 237, 336, 436 |
| ReAct | `workflows/definitions/deep_research.yaml` *(removed)* | 151, 251, 351, 451 |
| Chain-of-Verification | `workflows/definitions/deep_research.yaml` *(removed)* | 190, 290, 390, 490 |
| Adversarial Review | `prompts/antagonist_implementation.md` *(removed)*, `prompts/antagonist_systemic.md` *(removed)* | full files |
| Hybrid Retrieval | `rag/retrieval.py` | 31, 169, 227, 266 |
| Conversational Memory | `agents/base.py` | 131, 274, 189 |
| Circuit Breaker | `models/model_stats.py`, `models/smart_router.py` | 19, 49, 280; 63, 528 |
| Confidence Gating | `workflows/definitions/deep_research.yaml` *(removed)* | 207, 240 |
| Self-Reflection | `agents/capabilities.py`, `agents/coder.py` | 296; 50, 273 |
| Domain-Adaptive Recency | `workflows/definitions/deep_research.yaml` *(removed)* | 72, 88, 161 |
| Prompt Injection Defense | `rag/context_assembly.py` | 29, 39, 66, 138 |

All file paths above are relative to `agentic-workflows-v2/agentic_v2/`.
