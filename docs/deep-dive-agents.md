# Deep-Dive: Agents

> **Package:** `agentic-workflows-v2/agentic_v2/agents/`
> **Audience:** Engineers building new agents, workflow authors, and architects reviewing agent integration points.

**Updated:** 2026-05-02 (updated 2026-06-17)
**Key source files:** `agents/base.py`, `agents/config.py`, `agents/orchestrator.py`, `agents/orchestrator_models.py`, `agents/orchestrator_planning.py`, `agents/orchestrator_factories.py`, `agents/implementations/`

---

## 1. Agent Taxonomy

The system defines a strict hierarchy of agent types:

```
BaseAgent[TInput, TOutput]          ← abstract base
├── CoderAgent                      ← code generation
├── ReviewerAgent                   ← code review
├── ArchitectAgent                  ← system design
├── OrchestratorAgent               ← task decomposition + delegation
├── TestAgent                       ← test generation and execution
└── implementations/
    ├── ClaudeAgent                 ← Anthropic Messages API
    └── ClaudeSDKAgent              ← Anthropic Claude Code SDK
```

All agents share the `BaseAgent` lifecycle, conversation memory, tool binding, and OTEL tracing infrastructure. Concrete implementations override four abstract methods.

---

## 2. `BaseAgent[TInput, TOutput]`

Source: `agents/base.py`

`BaseAgent` is generic over `TInput` (a `TaskInput` subclass) and `TOutput` (a `TaskOutput` subclass). This provides compile-time type safety through the entire call chain.

### 2.1 Agent Configuration (`AgentConfig`)

Source: `agents/config.py`

```python
@dataclass
class AgentConfig:
    # Identity
    name: str = "agent"
    description: str = ""
    system_prompt: str = ""

    # Model selection
    default_tier: ModelTier = ModelTier.TIER_2
    max_tier: ModelTier = ModelTier.TIER_4

    # Behavior
    max_iterations: int = 10
    max_tool_calls_per_turn: int = 5
    timeout_seconds: float = 300.0

    # Memory
    max_memory_messages: int = 50
    max_memory_tokens: int = 8000

    # Streaming
    enable_streaming: bool = False
    verbose: bool = False
```

### 2.2 Agent State Machine

```
CREATED
  │
  ▼
INITIALIZING  ←── on first run() or explicit initialize()
  │
  ▼
READY
  │
  ▼
RUNNING
  ├── COMPLETED  (success)
  ├── FAILED     (exception)
  ├── CANCELLED  (asyncio.CancelledError)
  └── PAUSED → RUNNING (resume)
```

State transitions fire `AgentEvent.STATE_CHANGE` to all registered event handlers.

### 2.3 Initialization

`BaseAgent.initialize(ctx)` performs:
1. Transition to `INITIALIZING`.
2. Attach execution context.
3. Add system prompt to conversation memory (if configured).
4. Bind tools from the registry filtered by `config.default_tier.value`.
5. Call `_on_initialize()` for subclass customization.
6. Transition to `READY`.

Tool binding is tier-filtered: tools with `tier <= agent.config.default_tier.value` are bound. Higher-tier tools are unavailable to lower-tier agents.

### 2.4 Execution Loop

```python
async def run(task: TInput, ctx: ExecutionContext | None = None) -> TOutput:
    # Auto-initialize on first call
    if self._state == AgentState.CREATED:
        await self.initialize(ctx)

    task_message = self._format_task_message(task)
    self._memory.add_user(task_message)

    # Main loop with iteration limit
    while iteration < max_iterations:
        response = await self._call_model(messages, tools)
        if response.get("tool_calls"):
            await self._handle_tool_calls(response["tool_calls"])
            continue
        if await self._is_task_complete(task, content):
            return await self._parse_output(task, content)
    raise RuntimeError("Max iterations reached")
```

Every `run()` call is wrapped in an OTEL span `agent.<name>`.

### 2.5 Abstract Methods (Subclass Contract)

All four must be implemented:

| Method | Signature | Purpose |
|---|---|---|
| `_call_model` | `(messages, tools) → dict` | LLM invocation; returns `{"content": str, "tool_calls": list}` |
| `_format_task_message` | `(task: TInput) → str` | Serialize input to user message |
| `_is_task_complete` | `async (task, response) → bool` | Check termination condition |
| `_parse_output` | `async (task, response) → TOutput` | Deserialize response to output type |

### 2.6 Tool Handling

Tools use the OpenAI function-calling format. When the model returns `tool_calls`, the agent:

1. Looks up each tool name in `_bound_tools`.
2. Calls `tool.execute(**args)`.
3. Appends the tool result to conversation memory as a `tool_result` role message.
4. Emits `AgentEvent.TOOL_CALLED` and `AgentEvent.TOOL_RESULT` to handlers.
5. Loops back to call the model again with the updated conversation.

Unknown tool names return `"Unknown tool: <name>"` as the result — the agent continues rather than failing hard.

### 2.7 Conversation Memory

`ConversationMemory` is a sliding-window buffer with:
- `max_messages` (default 50): hard cap on message count.
- `max_tokens` (default 8000): soft cap with automatic summarization of evicted messages.
- Messages are stored as dicts with `role` and `content`.
- `add_system()`, `add_user()`, `add_assistant()`, `add_tool_result()` mutate the buffer.
- `get_messages()` returns the current sliding window for LLM calls.

### 2.8 Event System

```python
agent.on_event(lambda agent, event, data: logger.info("%s: %s", event, data))
```

Event handlers are synchronous callbacks. Exceptions in handlers are caught and logged at WARNING level — they never propagate to the execution loop.

| Event | When emitted | Data dict keys |
|---|---|---|
| `STATE_CHANGE` | Any state transition | `old_state`, `new_state` |
| `THINKING` | Each iteration start | `iteration` |
| `TOOL_CALLED` | Before tool execution | `tool`, `args`, `call_id` |
| `TOOL_RESULT` | After tool execution | `tool`, `result`, `call_id` |
| `STREAMING` | Each chunk (streaming mode) | `chunk` |
| `ERROR` | On exception | (varies) |

---

## 3. Concrete Implementations

### 3.1 `ClaudeAgent`

Source: `agents/implementations/claude_agent.py`

Calls the Anthropic Messages API via the `anthropic` async client. Handles format translation between the project's OpenAI-style message format and Anthropic's API.

**Translation layers:**

- `_convert_messages()` — splits the system prompt out of the message list (Anthropic requires it as a top-level parameter) and converts `"tool"` role messages to `tool_result` content blocks.
- `_convert_tools()` — maps OpenAI function schemas to Anthropic tool schemas.
- `_convert_response()` — maps Anthropic content blocks back to `{"content", "tool_calls"}`.

```python
agent = ClaudeAgent(
    model="claude-opus-4-6",
    system_prompt="You are a senior Python engineer.",
    api_key=None,          # defaults to ANTHROPIC_API_KEY env var
)
result = await agent.run(SimpleTask(prompt="Review this code: ..."))
```

Requires: `pip install 'agentic-workflows-v2[claude]'`

### 3.2 `ClaudeSDKAgent`

Source: `agents/implementations/claude_sdk_agent.py`

Uses the Anthropic Claude Code SDK (a higher-level abstraction than the raw Messages API). Intended for agents that benefit from Claude's native tool-use orchestration and multi-turn conversation management.

---

## 4. `OrchestratorAgent`

Source: `agents/orchestrator.py`

The `OrchestratorAgent` is the meta-agent responsible for task decomposition and multi-agent delegation. It does not execute domain tasks itself — it breaks complex tasks into subtasks, matches them to capable agents, and assembles final results.

### 4.1 Task Decomposition

The orchestrator calls the LLM with a structured prompt requesting JSON output:

```json
{
  "subtasks": [
    {
      "id": "t1",
      "description": "Generate a Python function",
      "capabilities": ["code_generation"],
      "dependencies": [],
      "parallel_group": 1
    }
  ]
}
```

JSON extraction from LLM responses uses `agents/json_extraction.py` which handles markdown code block wrapping and partial JSON repair.

### 4.2 Capability Matching

Source: `agents/capabilities.py`

Each agent can declare capabilities via `CapabilityMixin` subclasses:

```python
class CapabilityType(str, Enum):
    CODE_GENERATION = "code_generation"
    CODE_REVIEW = "code_review"
    TEST_GENERATION = "test_generation"
    ARCHITECTURE = "architecture"
    ORCHESTRATION = "orchestration"
    # ...
```

`get_agent_capabilities(agent)` introspects the agent's class MRO for `CapabilityMixin` subclasses and returns a `CapabilitySet`. The orchestrator uses this for automatic subtask-to-agent matching.

### 4.3 Execution via DAG

Once subtasks are decomposed and assigned, the orchestrator constructs a `DAG` where:

- Each subtask becomes a `StepDefinition`.
- `SubTask.dependencies` become DAG edges.
- The `DAGExecutor` runs the DAG with `max_concurrency=max_parallel` (default 3).

This gives the orchestrator the same parallelism and failure-propagation guarantees as the native engine.

### 4.4 Input / Output Types

```python
class OrchestratorInput(TaskInput):
    task: str                          # Description to orchestrate
    available_agents: list[str]        # Agent names to consider
    max_parallel: int = 3              # Concurrency limit
    require_review: bool = True

class OrchestratorOutput(TaskOutput):
    subtasks: list[dict]               # All decomposed subtasks
    agent_assignments: dict[str, str]  # subtask_id → agent_name
    final_result: Any | None           # Aggregated output
    execution_trace: list[dict]        # Step-by-step trace
```

---

## 5. Persona Definitions

Source: `agentic_v2/prompts/*.md`

Each agent has a `.md` persona definition that is loaded as the system prompt. Personas must define:

1. **Expertise** — What the agent knows.
2. **Boundaries** — What the agent should not do.
3. **Critical rules** — Hard constraints on behavior.
4. **Output format** — Expected response structure.

The 7 shipped personas are: `coder`, `reviewer`, `architect`, `orchestrator`, `tester`, `researcher`, and `skill-architect`.

---

## 6. Integrating an Agent with the Workflow Engine

### 6.1 `agent_to_step()` Adapter

```python
from agentic_v2.agents.base import agent_to_step

coder = CoderAgent()
step = agent_to_step(coder, name="generate_code")

dag = DAG("my_workflow")
dag.add(step)
```

`agent_to_step` wraps any `BaseAgent` as a `StepDefinition`. At runtime it:

1. Reads `"task"` from the `ExecutionContext`.
2. Calls `agent.run(task, ctx)`.
3. Returns `{"result": output}` to the context.

### 6.2 YAML Workflow Integration

In a YAML workflow definition, specify the agent name as the `agent:` field of a step:

```yaml
steps:
  - name: generate_code
    agent: coder
    description: Generate implementation from requirements
    depends_on: []
    inputs:
      description: ${inputs.requirements}
      language: python
    outputs:
      - code
      - explanation
```

The `agent:` field is resolved to an agent instance via `AgentLoader.load(agent_name)` which reads `config/defaults/agents.yaml` and instantiates the configured class.

---

## 7. Adding a New Agent

1. Create a file in `agents/implementations/my_agent.py`.
2. Subclass `BaseAgent[MyInput, MyOutput]` where `MyInput` and `MyOutput` are `TaskInput`/`TaskOutput` subclasses defined in `contracts/schemas.py` or locally.
3. Implement the four abstract methods: `_call_model`, `_format_task_message`, `_is_task_complete`, `_parse_output`.
4. Optionally mixin capability types from `agents/capabilities.py`.
5. Add a persona markdown file to `agentic_v2/prompts/my_agent.md`.
6. Register in `config/defaults/agents.yaml` with `name`, `description`, `tier`, and `class`.
7. Write unit tests in `tests/agents/test_my_agent.py`. Mock `_call_model` to avoid LLM calls in tests.
**Target type:** folder
**Scan mode:** exhaustive

---

## Overview

The `agents/` package defines the agent abstraction layer for the `agentic-workflows-v2` runtime. It provides `BaseAgent` (a typed lifecycle-driven protocol), concrete specialized agents (Coder, Reviewer, Architect, TestAgent, Orchestrator), supporting utilities (conversation memory, capability matching, robust JSON extraction), and pluggable backend implementations (Anthropic Messages API, `claude-agent-sdk`).

**Responsibilities:**
- Typed agent lifecycle (`base.py`)
- Conversation memory with auto-summarization (`memory.py`)
- Capability-based agent-to-task matching (`capabilities.py`)
- Robust structured-output parsing (`json_extraction.py`)
- Concrete specialists (Coder, Reviewer, Architect, TestAgent)
- Meta-agent for task decomposition and delegation (`orchestrator.py`)
- Config loading (`config.py`)
- Backend implementations (`implementations/`)

---

## Agent Taxonomy

```
BaseAgent[TInput, TOutput]               (abstract, generic protocol)
  ├─ CoderAgent         (capabilities: CodeGeneration, SelfReflection)
  ├─ ReviewerAgent      (capabilities: CodeReview)
  ├─ ArchitectAgent     (capabilities: SystemsDesign)
  ├─ TestAgent          (capabilities: TestGeneration)
  └─ OrchestratorAgent  (capabilities: TaskDecomposition, AgentMatching)

implementations/ (backend adapters, not BaseAgent subclasses)
  ├─ ClaudeAgent         → Anthropic Messages API (tool_use)
  ├─ ClaudeSDKAgent      → claude-agent-sdk (standalone, no BaseAgent)
  └─ agent_loader        → factory + registry from YAML persona files
```

**Design principle:** Composition over inheritance. Capabilities are declared via mixin-like `CapabilitySet` objects rather than deep hierarchies.

---

## Agent Lifecycle

State machine (enforced by convention in `base.py`):

```
CREATED → INITIALIZING → READY → RUNNING → COMPLETED
                                        ↘ FAILED
                                        ↘ CANCELLED
```

**Per-invocation flow:**
1. **Construct** — agent instantiated with config, capabilities, LLM client, tool registry.
2. **Initialize** — load persona prompt (`prompts/*.md`), bind tools filtered by model tier.
3. **Prepare context** — merge system prompt + conversation memory + task input; apply token budget.
4. **LLM call** — via `models.SmartModelRouter` → backend (Anthropic, OpenAI, etc.).
5. **Tool invocation loop** — if LLM emits tool_use, dispatch via `ToolRegistry`, append results, recall LLM.
6. **Parse output** — `json_extraction` for structured responses; Pydantic validation against contract.
7. **Memory update** — append user/assistant turn; auto-summarize if window exceeded.
8. **Emit events** — lifecycle events for observability.

---

## Module Inventory

### `__init__.py` — 121 LOC
- **Purpose:** Package exports and agent factory registration. Re-exports public API and registers agent classes with the implementations loader.
- **Exports:** `BaseAgent`, `CoderAgent`, `ReviewerAgent`, `ArchitectAgent`, `TestAgent`, `OrchestratorAgent`, `ConversationMemory`, `CapabilitySet`.
- **Implementation detail:** Late-binding factory registration avoids circular imports with `OrchestratorAgent`.

### `base.py` — 541 LOC
- **Purpose:** Abstract `BaseAgent[TInput, TOutput]` generic with lifecycle state machine, event emission, tool binding, and default invocation loop.
- **Key exports:**
  - `BaseAgent[TInput, TOutput]` — abstract class with `async run(input) -> TOutput`, `async _invoke_llm()`, `_bind_tools()`, `_emit_event()`.
  - `AgentState` enum (CREATED, INITIALIZING, READY, RUNNING, COMPLETED, FAILED, CANCELLED).
  - `AgentEvent` dataclass.
- **Imports:** `typing.Generic`, `..contracts`, `..models.SmartModelRouter`, `..tools.ToolRegistry`.
- **Risks:** State transitions not type-enforced — relies on convention + tests.
- **Suggested tests:** illegal transitions raise; event ordering; generic type erasure.

### `capabilities.py` — 383 LOC
- **Purpose:** Capability declaration + scoring for agent-to-task matching. Enables runtime selection of the best-fit agent for a subtask.
- **Key exports:** `Capability` enum (CodeGeneration, CodeReview, SystemsDesign, TestGeneration, TaskDecomposition, AgentMatching, SelfReflection, ...), `CapabilitySet`, `score_match(task_needs, agent_caps) -> float`.
- **Implementation:** Weighted overlap + proficiency clamp to [0.0, 1.0]; division-by-zero avoided with `max(0.01, ...)`.
- **Suggested tests:** scoring monotonicity, empty sets, ties.

### `coder.py` — 367 LOC
- **Purpose:** Concrete Coder agent specialized for code generation with optional self-reflection pass.
- **Key exports:** `CoderAgent(BaseAgent[CodeTaskInput, CodeTaskOutput])`, `CODER_SYSTEM_PROMPT`.
- **Capabilities:** CodeGeneration, SelfReflection.
- **Implementation:** Two-pass mode — initial generation → critique → revision. Controlled by `config.self_reflect`.

### `reviewer.py` — 370 LOC
- **Purpose:** Code-review agent producing structured findings (severity, file, line, category, recommendation).
- **Key exports:** `ReviewerAgent(BaseAgent[ReviewInput, ReviewOutput])`.
- **Implementation:** Uses `json_extraction` to parse findings list; supports per-category gating.

### `architect.py` — 361 LOC
- **Purpose:** Architecture-design agent producing component diagrams, data flow, and decision rationale.
- **Key exports:** `ArchitectAgent(BaseAgent[DesignInput, DesignOutput])`.

### `test_agent.py` — 544 LOC
- **Purpose:** Test-generation agent producing pytest/Jest test scaffolds with fixtures.
- **Key exports:** `TestAgent(BaseAgent[TestInput, TestOutput])`.

### `orchestrator.py`
- **Purpose:** Meta-agent that decomposes a high-level task into subtasks, scores candidate agents via `capabilities.score_match`, dispatches, and aggregates results. Supports fallback chains and DAG execution.
- **Key exports:** `OrchestratorAgent(BaseAgent[OrchestratorInput, OrchestratorOutput])`, `decompose_task()`, `select_agent()`.
- **Imports:** `..engine.dag`, capabilities, all concrete agents (via factory registry), plus sibling modules `orchestrator_models`, `orchestrator_planning`, `orchestrator_factories`.
- **Risks:** Silent fallback chain — logs warnings but returns best-effort output if all agents fail.
- **Suggested tests:** all-agents-fail scenario surfaces error; DAG cycle detection; capability tie-breaking.

### `orchestrator_models.py` — value objects and prompts (decomposed from `orchestrator.py`)
- **Purpose:** Holds `SubTask`, `OrchestratorInput`, `OrchestratorOutput`, system prompts, and capability constants. Dependencies restricted to `..contracts` and `.capabilities` — no engine imports.
- **Key exports:** `SubTask`, `OrchestratorInput`, `OrchestratorOutput`.
- **Design rationale:** Isolating these value objects allows them to be imported by unit tests and by the evaluation harness without pulling in orchestration logic.

### `orchestrator_planning.py` — pure planning helpers (decomposed from `orchestrator.py`)
- **Purpose:** Deterministic, stateless planning utilities: `_intent_decomposition` (capability-tagged plan from task text for no-LLM mode), `_extract_file_tokens`, `_latest_user_text`, `_has_extractable_json`, `_per_file_task_id`.
- **Key exports:** `_intent_decomposition()`, `_extract_file_tokens()`, `_latest_user_text()`, `_per_file_task_id()`.
- **Design rationale:** Pure functions with no orchestrator state — directly unit-testable without mocking the LLM. Backs the `AGENTIC_NO_LLM` decomposition path.

### `orchestrator_factories.py` — task-input factories (decomposed from `orchestrator.py`)
- **Purpose:** Maps subtask descriptions to concrete `TaskInput` subclasses per managed agent type. E.g., reviewer subtasks → `CodeReviewInput`, coder subtasks → `CodeGenerationInput`. All cross-module imports are deferred to call time to avoid circular imports.
- **Key exports:** `_reviewer_input_factory()`, `_coder_input_factory()`, `register_default_factories()`.
- **Design rationale:** Deferred imports at call time (not module load) keeps this module free of import-time coupling to the contracts layer and concrete agents.

### `memory.py` — 266 LOC
- **Purpose:** `ConversationMemory` with sliding-window summarization. Keeps up to 50 messages and ~8000 tokens; auto-summarizes older turns when window exceeded. First system message always preserved.
- **Key exports:** `ConversationMemory`, `Message`, `summarize_window()`.
- **Implementation:** 4-char-per-token heuristic; summarization delegates to LLM client if configured, else naive concat.
- **Suggested tests:** window overflow triggers summarize; system message never evicted; token-count accuracy.

### `config.py` — 139 LOC
- **Purpose:** Agent configuration loader from YAML persona files (`prompts/*.md`) + runtime overrides.
- **Key exports:** `AgentConfig`, `load_agent_config(name)`, `AgentProfile`.

### `json_extraction.py` — 155 LOC
- **Purpose:** Robust JSON extraction from LLM freeform responses. Three strategies in order: fenced ` ```json `, fenced ` ``` ` (any), balanced-brace scan (handles strings with escapes).
- **Key exports:** `extract_json(text) -> dict | list | None`, `ExtractionStrategy`.
- **Implementation:** Balanced-brace scan tracks string state (`"`, `\"`) to avoid false matches.
- **Strengths:** Avoids greedy regex pitfalls; handles nested objects and embedded strings.
- **Suggested tests:** malformed responses, nested braces in strings, truncated JSON, multiple JSON blocks.

### `implementations/__init__.py` — 36 LOC
- **Purpose:** Exposes backend implementations and the agent loader.
- **Exports:** `ClaudeAgent`, `ClaudeSDKAgent`, `load_agent(name)`.

### `implementations/agent_loader.py` — 130 LOC
- **Purpose:** Factory registry for agent classes. Maps agent name → factory function. Populated by `agents/__init__.py` during import.
- **Key exports:** `register_agent(name, factory)`, `load_agent(name, config) -> BaseAgent`, `AGENT_REGISTRY`.

### `implementations/claude_agent.py` — 228 LOC
- **Purpose:** Backend adapter using Anthropic Messages API directly. Handles tool_use, streaming, and content-block parsing.
- **Key exports:** `ClaudeAgent` (inherits `BaseAgent`), `invoke_claude()`.
- **Imports:** `anthropic` SDK.

### `implementations/claude_sdk_agent.py` — 155 LOC
- **Purpose:** Backend using `claude-agent-sdk` package. Standalone — does not inherit `BaseAgent` (uses SDK's own lifecycle).
- **Key exports:** `ClaudeSDKAgent`, `run_claude_sdk()`.
- **Gotcha:** Not part of `BaseAgent` taxonomy — callers must branch on agent type.

---

## Dependency Graph (within `agents/`)

```
base.py
  ↑
  ├─ coder.py              → json_extraction.py, memory.py, capabilities.py
  ├─ reviewer.py           → json_extraction.py, memory.py, capabilities.py
  ├─ architect.py          → json_extraction.py, memory.py, capabilities.py
  ├─ test_agent.py         → json_extraction.py, memory.py, capabilities.py
  └─ orchestrator.py       → capabilities.py, (factory registry from __init__)
       ├─ orchestrator_models.py      → ..contracts, .capabilities (no engine)
       ├─ orchestrator_planning.py    → .capabilities, .json_extraction (pure functions)
       └─ orchestrator_factories.py   → (deferred imports at call time)

implementations/
  ├─ agent_loader.py  (registry populated by __init__.py)
  ├─ claude_agent.py  → base.py
  └─ claude_sdk_agent.py  (standalone)
```

No circular imports — `OrchestratorAgent` uses late-binding factory lookup to avoid importing concrete agents at module load.

---

## Capabilities & Config

- **`capabilities.py`**: declarative enum of skills an agent provides; `CapabilitySet` composes them. `score_match(task_needs, agent_caps)` returns weighted float for runtime routing.
- **`config.py`**: loads YAML persona (system prompt, expertise, boundaries, output format) and merges with runtime overrides (temperature, model tier, tool allowlist).

**Flow:**
1. Workflow YAML step declares required capabilities + agent name.
2. `agent_loader.load_agent(name, config)` constructs agent with `AgentConfig`.
3. `OrchestratorAgent` uses `capabilities.score_match` when subtasks need dynamic agent selection.

---

## Memory Integration

`memory.ConversationMemory` is self-contained and does NOT use `core.memory.MemoryStoreProtocol` — that protocol is for cross-run persistence (e.g., RAG-backed long-term memory). `ConversationMemory` is per-invocation context window management only.

For long-term memory, agents delegate to `core.memory.RAGMemoryStore` via `rag/` — retrieved chunks are injected into the prompt by the agent's `_prepare_context()`.

---

## JSON Extraction

Three strategies, applied in order until one succeeds:

1. **Fenced `json`** — ` ```json\n{...}\n``` `
2. **Fenced any** — ` ```\n{...}\n``` `
3. **Balanced-brace scan** — walks text tracking `{` / `}` depth; respects string literals and escape sequences.

**Why not regex:** greedy regex on nested braces fails silently; the balanced-brace scanner is correct by construction.

**Edge cases handled:** embedded `"}"`, escaped quotes `\"`, newlines inside strings, multiple JSON blocks (returns first valid).

---

## Integration Points

- **`..contracts`**: `TaskInput`/`TaskOutput` Pydantic models per agent.
- **`..models`**: `ModelTier`, `SmartModelRouter`, `get_client()` for LLM dispatch.
- **`..tools`**: `BaseTool`, `ToolRegistry` for function-calling.
- **`..engine`**: `DAG`, `StepDefinition` (orchestrator only).
- **`..prompts/*.md`**: persona definitions loaded by `config.py`.
- **`..rag`**: optional long-term memory via `RAGMemoryStore`.
- **External**: `anthropic` SDK, `claude-agent-sdk`.

**Used by:**
- `server/execution.py` (workflow runner invokes agents).
- `server/routes/agents.py` (enumeration via `load_agent_config`).
- `langchain/` adapter (wraps agents as LangGraph nodes).
- `engine/` native executor (invokes agents as DAG step handlers).
- Tests: `tests/test_agents/*.py`.

---

## Risks & Gotchas

1. **JSON extraction ambiguity** — if LLM emits multiple JSON blocks, only first is returned.
2. **Memory summarization loss** — 4-char/token heuristic is approximate; real token count may differ ±15%.
3. **Capability scoring** — no type-level enforcement that `Capability` enums align across declarations.
4. **Tool tier binding** — requires consistent `ModelTier` numbering in `..models`; drift breaks filtering silently.
5. **Orchestrator silent fallback** — logs warnings per failure but may return partial output; callers must check `OrchestratorOutput.status`.
6. **Mock backend fallback** — when `llm_client.backend is None`, agents return mock responses (dev mode). Must not leak to prod.
7. **State machine by convention** — illegal transitions not raised at type level; only caught by tests.
8. **Circular deps** — `OrchestratorAgent` uses late-binding factory registry; direct imports would break.
9. **`ClaudeSDKAgent` outside taxonomy** — does not inherit `BaseAgent`; callers need type narrowing.
10. **Agent config merging** — YAML + runtime overrides; unclear precedence in edge cases (nested dicts).

---

## Verification Steps

Before shipping agent changes:

1. `pip install -e ".[dev,claude]"` from `agentic-workflows-v2/`.
2. `python -m pytest tests/test_agents -v` — full agent suite green.
3. `python -m pytest tests/test_agents/test_json_extraction.py` — structured-output robustness.
4. `python -m pytest tests/test_agents/test_memory.py` — window overflow + summarization.
5. `agentic list agents` — all agents discoverable.
6. Run a minimal workflow using each concrete agent via `POST /api/run`.
7. `pre-commit run --all-files` — mypy strict passes with generics.

---

## Suggested Tests

- **BaseAgent**: state-machine legal/illegal transitions; event ordering; generic type preservation.
- **ConversationMemory**: window overflow triggers summarize; system message eviction prevention; token-count accuracy vs actual tokenizer.
- **CapabilitySet**: scoring monotonicity, empty intersections, ties, proficiency clamps.
- **JSON extraction**: malformed LLM responses (truncated, multiple blocks, nested braces in strings, escape sequences).
- **OrchestratorAgent**: all-agents-fail raises rather than silently returning; DAG cycle detection; capability tie-breaking.
- **ClaudeAgent**: tool_use round-trip; streaming content blocks; rate-limit retry.
- **ClaudeSDKAgent**: session lifecycle; standalone invocation path.
- **agent_loader**: unknown agent raises; registry population after late-binding.
- **Config**: YAML parse errors; override precedence; missing persona file.
- **Mock backend**: dev-mode path produces deterministic output; never fires in production config.

---

## Related Code & Reuse Opportunities

- **`json_extraction.py`** could be extracted as a standalone library — it's generally useful and better than greedy regex approaches.
- **`ConversationMemory`** could generalize to non-agent contexts (e.g., chat UI) — move to `core/memory.py`.
- **`CapabilitySet.score_match`** is a public-utility-caliber function; could be exposed for external orchestrators.
- **Agent event system** parallels `server/websocket.py` hub — consider unifying into `core/events.py`.
- **System prompts** currently in `prompts/*.md`; consider externalizing into versioned YAML for experimentation.
- **Backend adapters** (`ClaudeAgent`, `ClaudeSDKAgent`) could use the existing `AdapterRegistry` pattern from `adapters/` for symmetry.
- **Mock backend** pattern should be promoted to a shared `tools.llm.mock_client` for cross-package reuse.
