# Deep-dive: agents

> **Package:** `agentic-workflows-v2/agentic_v2/agents/`
> **Audience:** Engineers building new agents, workflow authors, and architects reviewing agent integration points.

**Generated:** 2026-05-02 (updated 2026-07-05)
**Key source files:** `agents/base.py`, `agents/config.py`, `agents/orchestrator.py`, `agents/orchestrator_models.py`, `agents/orchestrator_planning.py`, `agents/orchestrator_factories.py`, `agents/implementations/`

---

## Overview

The `agents/` package defines the agent abstraction layer for the `agentic-workflows-v2` runtime. It provides `BaseAgent` (a typed lifecycle-driven abstract class), concrete specialized agents (Coder, Reviewer, Architect, TestAgent, Orchestrator), supporting utilities (conversation memory, capability matching, JSON extraction), and backend implementations (Anthropic Messages API, `claude-agent-sdk`).

**Responsibilities:**

- Typed agent lifecycle (`base.py`)
- Agent configuration, state, and event enums (`config.py`)
- Conversation memory with auto-summarization (`memory.py`)
- Capability-based agent-to-task matching (`capabilities.py`)
- Structured-output parsing (`json_extraction.py`)
- Concrete specialists (Coder, Reviewer, Architect, TestAgent)
- Meta-agent for task decomposition and delegation (`orchestrator.py`)
- Backend implementations (`implementations/`)

---

## 1. Agent taxonomy

```
BaseAgent[TInput, TOutput]               (abstract, generic)
  ├─ CoderAgent          (mixins: CodeGeneration, SelfReflection)
  ├─ ReviewerAgent       (mixin: CodeReview)
  ├─ ArchitectAgent      (system design)
  ├─ TestAgent           (test generation)
  ├─ OrchestratorAgent   (mixin: Orchestration — decomposition + delegation)
  └─ implementations/ClaudeAgent   (Anthropic Messages API backend)

implementations/ClaudeSDKAgent     (standalone — wraps claude-agent-sdk;
                                    does NOT inherit BaseAgent)
```

`ClaudeAgent` is a `BaseAgent[SimpleTask, SimpleOutput]` subclass that translates between the project's OpenAI-style message format and the Anthropic API. `ClaudeSDKAgent` sits outside the taxonomy: it delegates lifecycle, tools, and conversation management to the `claude-agent-sdk` package, so callers must branch on agent type.

**Design principle:** composition over inheritance. Capabilities are declared via `CapabilityMixin` subclasses (`capabilities.py`) rather than deep hierarchies.

**Agent classes vs personas:** the Python classes above are distinct from the seven persona prompt files in `agentic_v2/prompts/` (`architect`, `coder`, `orchestrator`, `planner`, `reviewer`, `tester`, `validator`). Personas are markdown system prompts and do not map one-to-one onto classes — `planner` and `validator`, for example, have no dedicated agent class.

---

## 2. `BaseAgent[TInput, TOutput]`

Source: `agents/base.py`

`BaseAgent` is generic over `TInput` (a `TaskInput` subclass) and `TOutput` (a `TaskOutput` subclass). This provides compile-time type safety through the entire call chain.

### 2.1 Agent configuration (`AgentConfig`)

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

### 2.2 Agent state machine

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

State transitions fire `AgentEvent.STATE_CHANGE` to all registered event handlers. `AgentState` and `AgentEvent` are defined in `agents/config.py`.

### 2.3 Initialization

`BaseAgent.initialize(ctx)` performs:

1. Transition to `INITIALIZING`.
2. Attach execution context.
3. Add system prompt to conversation memory (if configured).
4. Bind tools from the registry filtered by `config.default_tier.value`.
5. Call `_on_initialize()` for subclass customization.
6. Transition to `READY`.

Tool binding is tier-filtered: tools with `tier <= agent.config.default_tier.value` are bound. Higher-tier tools are unavailable to lower-tier agents.

### 2.4 Execution loop

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

### 2.5 Abstract methods (subclass contract)

All four must be implemented:

| Method | Signature | Purpose |
|---|---|---|
| `_call_model` | `(messages, tools) → dict` | LLM invocation; returns `{"content": str, "tool_calls": list}` |
| `_format_task_message` | `(task: TInput) → str` | Serialize input to user message |
| `_is_task_complete` | `async (task, response) → bool` | Check termination condition |
| `_parse_output` | `async (task, response) → TOutput` | Deserialize response to output type |

### 2.6 Tool handling

Tools use the OpenAI function-calling format. When the model returns `tool_calls`, the agent:

1. Looks up each tool name in `_bound_tools`.
2. Calls `tool.execute(**args)`.
3. Appends the tool result to conversation memory as a `tool_result` role message.
4. Emits `AgentEvent.TOOL_CALLED` and `AgentEvent.TOOL_RESULT` to handlers.
5. Loops back to call the model again with the updated conversation.

Unknown tool names return `"Unknown tool: <name>"` as the result — the agent continues rather than failing hard.

### 2.7 Conversation memory

`ConversationMemory` (`agents/memory.py`) is a sliding-window buffer with:

- `max_messages` (default 50): hard cap on message count.
- `max_tokens` (default 8000): soft cap with automatic summarization of evicted messages.
- Messages are stored with `role` and `content`.
- `add_system()`, `add_user()`, `add_assistant()`, `add_tool_result()` mutate the buffer.
- `get_messages()` returns the current sliding window for LLM calls.

### 2.8 Event system

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

## 3. Concrete implementations

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

Uses the Anthropic Claude Code SDK (`claude-agent-sdk`, a higher-level abstraction than the raw Messages API). Standalone — it does not inherit `BaseAgent`; it relies on the SDK's own lifecycle and built-in file, web, and terminal tools. Intended for agents that benefit from Claude's native tool-use orchestration and multi-turn conversation management.

---

## 4. `OrchestratorAgent`

Source: `agents/orchestrator.py`

The `OrchestratorAgent` is the meta-agent responsible for task decomposition and multi-agent delegation. It does not execute domain tasks itself — it breaks complex tasks into subtasks, matches them to capable agents, and assembles final results.

### 4.1 Task decomposition

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

### 4.2 Capability matching

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

`get_agent_capabilities(agent)` introspects the agent's class MRO for `CapabilityMixin` subclasses and returns a `CapabilitySet`. The orchestrator uses this (via `CapabilitySet.score_match()`) for automatic subtask-to-agent matching.

### 4.3 Execution via DAG

Once subtasks are decomposed and assigned, the orchestrator constructs a `DAG` where:

- Each subtask becomes a `StepDefinition`.
- `SubTask.dependencies` become DAG edges.
- The `DAGExecutor` runs the DAG with `max_concurrency=max_parallel` (default 3).

This gives the orchestrator the same parallelism and failure-propagation guarantees as the native engine.

### 4.4 Input / output types

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

## 5. Persona definitions

Source: `agentic_v2/prompts/*.md`

Each persona is a `.md` file that is loaded as a system prompt. Personas must define:

1. **Expertise** — What the agent knows.
2. **Boundaries** — What the agent should not do.
3. **Critical rules** — Hard constraints on behavior.
4. **Output format** — Expected response structure.

The shipped personas are kept in sync with the named constants in
`agentic-workflows-v2/agentic_v2/prompts/__init__.py` (call `list_prompts()` for the live list):
`architect`, `coder`, `orchestrator`, `planner`, `reviewer`, `tester`, and
`validator`.

Personas are prompt assets, not classes — see the taxonomy note in section 1 for how they relate to the `BaseAgent` subclasses.

---

## 6. Integrating an agent with the workflow engine

### 6.1 `agent_to_step()` adapter

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

### 6.2 YAML workflow integration

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

The `agent:` field is resolved by `resolve_agent()` in `engine/agent_resolver.py`, which maps agent names (including `tier{N}_{role}` forms) to executor functions when the workflow is loaded. Separately, `config/defaults/agents.yaml` provides the agent metadata served by `GET /api/agents`.

---

## 7. Adding a new agent

1. Create a file in `agents/implementations/my_agent.py`.
2. Subclass `BaseAgent[MyInput, MyOutput]` where `MyInput` and `MyOutput` are `TaskInput`/`TaskOutput` subclasses defined in `contracts/schemas.py` or locally.
3. Implement the four abstract methods: `_call_model`, `_format_task_message`, `_is_task_complete`, `_parse_output`.
4. Optionally mix in capability types from `agents/capabilities.py`.
5. Add a persona markdown file to `agentic_v2/prompts/my_agent.md`.
6. Register in `config/defaults/agents.yaml` with `name`, `description`, `tier`, and `class`.
7. Write unit tests (see `tests/test_agents.py`, `tests/test_new_agents.py` for patterns). Mock `_call_model` to avoid LLM calls in tests.

---

## Module inventory

### `__init__.py`
- **Purpose:** Package exports and agent factory registration. Re-exports the public API (`BaseAgent`, concrete agents, `ConversationMemory`, `CapabilitySet`).
- **Implementation detail:** late-binding factory registration avoids circular imports with `OrchestratorAgent`.

### `base.py`
- **Purpose:** Abstract `BaseAgent[TInput, TOutput]` generic with lifecycle state machine, event emission, tool binding, and default invocation loop.
- **Key exports:** `BaseAgent[TInput, TOutput]` (with `async run(task, ctx) -> TOutput`), `agent_to_step()` adapter. The `AgentState`/`AgentEvent` enums it drives live in `config.py`.
- **Risks:** state transitions not type-enforced — relies on convention + tests.
- **Suggested tests:** illegal transitions raise; event ordering; generic type erasure.

### `capabilities.py`
- **Purpose:** Capability declaration + scoring for agent-to-task matching. Enables runtime selection of the best-fit agent for a subtask.
- **Key exports:** `CapabilityType` enum, `Capability`, `CapabilitySet` (with `score_match(required) -> float`), `CapabilityMixin` and concrete mixins (`CodeGenerationMixin`, `CodeReviewMixin`, `TestGenerationMixin`, `OrchestrationMixin`, `SelfReflectionMixin`), `requires_capabilities()`, `get_agent_capabilities()`.
- **Suggested tests:** scoring monotonicity, empty sets, ties.

### `config.py`
- **Purpose:** Agent lifecycle enums and configuration — `AgentState`, `AgentEvent`, and the `AgentConfig` dataclass (identity, tier bounds, iteration/tool-call limits, memory bounds, streaming flags).

### `coder.py`
- **Purpose:** Concrete Coder agent specialized for code generation with optional self-reflection pass.
- **Key exports:** `CoderAgent(BaseAgent[CodeGenerationInput, CodeGenerationOutput], CodeGenerationMixin, SelfReflectionMixin)`.
- **Implementation:** two-pass mode — initial generation → critique → revision.

### `reviewer.py`
- **Purpose:** Code-review agent producing structured findings (severity, file, line, category, recommendation).
- **Key exports:** `ReviewerAgent(BaseAgent[CodeReviewInput, CodeReviewOutput], CodeReviewMixin)`.
- **Implementation:** uses `json_extraction` to parse findings list.

### `architect.py`
- **Purpose:** Architecture-design agent producing component design, tech-stack choices, and decision rationale.
- **Key exports:** `ArchitectAgent(BaseAgent[ArchitectureInput, ArchitectureOutput])`.

### `test_agent.py`
- **Purpose:** Test-generation agent producing test scaffolds with fixtures.
- **Key exports:** `TestAgent(BaseAgent[TestGenerationInput, TestGenerationOutput])`, `TestType`, `TestFile`.

### `orchestrator.py`
- **Purpose:** Meta-agent that decomposes a high-level task into subtasks, scores candidate agents via capability matching, dispatches, and aggregates results. Supports fallback chains and DAG execution.
- **Key exports:** `OrchestratorAgent(BaseAgent[OrchestratorInput, OrchestratorOutput], OrchestrationMixin)`.
- **Imports:** `..engine.dag`, capabilities, sibling modules `orchestrator_models`, `orchestrator_planning`, `orchestrator_factories`.
- **Risks:** silent fallback chain — logs warnings but returns best-effort output if all agents fail.
- **Suggested tests:** all-agents-fail scenario surfaces error; DAG cycle detection; capability tie-breaking.

### `orchestrator_models.py`
- **Purpose:** Value objects and prompts decomposed from `orchestrator.py` — `SubTask`, `OrchestratorInput`, `OrchestratorOutput`, system prompts, capability constants. Dependencies restricted to `..contracts` and `.capabilities` — no engine imports.
- **Design rationale:** isolating these value objects allows them to be imported by unit tests and by the evaluation harness without pulling in orchestration logic.

### `orchestrator_planning.py`
- **Purpose:** Deterministic, stateless planning utilities: `_intent_decomposition` (capability-tagged plan from task text for no-LLM mode), `_extract_file_tokens`, `_latest_user_text`, `_has_extractable_json`, `_per_file_task_id`.
- **Design rationale:** pure functions with no orchestrator state — directly unit-testable without mocking the LLM. Backs the `AGENTIC_NO_LLM` decomposition path.

### `orchestrator_factories.py`
- **Purpose:** Maps subtask descriptions to concrete `TaskInput` subclasses per managed agent type. E.g., reviewer subtasks → `CodeReviewInput`, coder subtasks → `CodeGenerationInput`.
- **Design rationale:** deferred imports at call time (not module load) keep this module free of import-time coupling to the contracts layer and concrete agents.

### `memory.py`
- **Purpose:** `ConversationMemory` with sliding-window summarization. Keeps up to 50 messages and ~8000 tokens; auto-summarizes older turns when the window is exceeded. First system message always preserved.
- **Key exports:** `ConversationMemory`, `ConversationMessage`, `reduce_tool_result()`.
- **Implementation:** 4-char-per-token heuristic; summarization delegates to the LLM client if configured, else naive concatenation.
- **Suggested tests:** window overflow triggers summarize; system message never evicted; token-count accuracy.

### `json_extraction.py`
- **Purpose:** JSON extraction from LLM freeform responses. Strategies in order: fenced ` ```json ` block, fenced ` ``` ` (any), balanced-brace scan (handles strings with escapes).
- **Key exports:** `extract_json(text)` — overloaded to return a plain dict or validate against a supplied Pydantic model.
- **Implementation:** balanced-brace scan tracks string state (`"`, `\"`) to avoid false matches.
- **Suggested tests:** malformed responses, nested braces in strings, truncated JSON, multiple JSON blocks.

### `implementations/__init__.py`
- **Purpose:** Exposes backend implementations. `ClaudeAgent` (plus `SimpleTask`/`SimpleOutput`) is always importable; `ClaudeSDKAgent`, `load_agents`, `AGENTS`, and `BUILTIN_TOOLS` are guarded behind the optional `[claude]` extra.

### `implementations/agent_loader.py`
- **Purpose:** Loads `.md` agent definition files (YAML frontmatter + system-prompt body) from the bundled definitions directory plus an optional external pack, returning a dict of `claude_agent_sdk.AgentDefinition` instances.
- **Key exports:** `load_agents(directory=None)`, `agents` (loaded registry).

### `implementations/claude_agent.py`
- **Purpose:** Backend adapter using the Anthropic Messages API directly. Handles tool_use, streaming, and content-block parsing.
- **Key exports:** `ClaudeAgent` (inherits `BaseAgent`), `SimpleTask`, `SimpleOutput`.
- **Imports:** `anthropic` SDK.

### `implementations/claude_sdk_agent.py`
- **Purpose:** Backend using the `claude-agent-sdk` package. Standalone — does not inherit `BaseAgent` (uses the SDK's own lifecycle).
- **Key exports:** `ClaudeSDKAgent`, `BUILTIN_TOOLS`.
- **Gotcha:** not part of the `BaseAgent` taxonomy — callers must branch on agent type.

---

## Dependency graph (within `agents/`)

```
base.py  (+ config.py enums)
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
  ├─ agent_loader.py  (loads .md agent definitions for the SDK backend)
  ├─ claude_agent.py  → base.py
  └─ claude_sdk_agent.py  (standalone)
```

No circular imports — `OrchestratorAgent` uses late-binding factory lookup to avoid importing concrete agents at module load.

---

## Memory integration

`memory.ConversationMemory` is self-contained and does NOT use `core.memory.MemoryStoreProtocol` — that protocol is for cross-run persistence (e.g., RAG-backed long-term memory). `ConversationMemory` is per-invocation context window management only.

For long-term memory, agents delegate to `rag.memory.RAGMemoryStore` (a `MemoryStoreProtocol` implementation) — retrieved chunks are injected into the prompt by the agent's `_prepare_context()`.

---

## JSON extraction

Strategies, applied in order until one succeeds:

1. **Fenced `json`** — ` ```json\n{...}\n``` `
2. **Fenced any** — ` ```\n{...}\n``` `
3. **Balanced-brace scan** — walks text tracking `{` / `}` depth; respects string literals and escape sequences.

**Why not regex:** greedy regex on nested braces fails silently; the balanced-brace scanner is correct by construction.

**Edge cases handled:** embedded `"}"`, escaped quotes `\"`, newlines inside strings, multiple JSON blocks (returns first valid).

---

## Integration points

- **`..contracts`**: `TaskInput`/`TaskOutput` Pydantic models per agent.
- **`..models`**: `ModelTier`, `SmartModelRouter`, `get_client()` for LLM dispatch.
- **`..tools`**: `BaseTool`, `ToolRegistry` for function-calling.
- **`..engine`**: `DAG`, `StepDefinition` (orchestrator only); `engine/agent_resolver.py` resolves YAML `agent:` names.
- **`..prompts/*.md`**: persona definitions loaded as system prompts.
- **`..rag`**: optional long-term memory via `RAGMemoryStore`.
- **External**: `anthropic` SDK, `claude-agent-sdk`.

**Used by:**

- `server/execution.py` (workflow runner invokes agents).
- `server/routes/agents.py` (enumeration from `config/defaults/agents.yaml`).
- `langchain/` adapter (wraps agents as LangGraph nodes).
- `engine/` native executor (invokes agents as DAG step handlers).
- Tests: `tests/test_agents*.py`, `tests/test_new_agents.py`.

---

## Risks and gotchas

1. **JSON extraction ambiguity** — if the LLM emits multiple JSON blocks, only the first is returned.
2. **Memory summarization loss** — 4-char/token heuristic is approximate; real token count may differ ±15%.
3. **Capability scoring** — no type-level enforcement that `CapabilityType` enums align across declarations.
4. **Tool tier binding** — requires consistent `ModelTier` numbering in `..models`; drift breaks filtering silently.
5. **Orchestrator silent fallback** — logs warnings per failure but may return partial output; callers must check the output status.
6. **Mock backend fallback** — when `llm_client.backend is None`, agents return placeholder responses (dev mode). Must not leak to prod.
7. **State machine by convention** — illegal transitions not raised at type level; only caught by tests.
8. **Circular deps** — `OrchestratorAgent` uses late-binding factory registry; direct imports would break.
9. **`ClaudeSDKAgent` outside taxonomy** — does not inherit `BaseAgent`; callers need type narrowing.
10. **Agent config merging** — YAML + runtime overrides; unclear precedence in edge cases (nested dicts).

---

## Verification steps

Before shipping agent changes:

1. `pip install -e ".[dev,claude]"` from `agentic-workflows-v2/`.
2. `python -m pytest tests/ -k agent -q` — agent suites green.
3. `python -m pytest tests/ -k json_extraction -q` — structured-output parsing.
4. `python -m pytest tests/ -k memory -q` — window overflow + summarization.
5. `curl http://127.0.0.1:8010/api/agents` — all agents discoverable.
6. Run a minimal workflow using each concrete agent via `POST /api/run`.
7. `pre-commit run --all-files` — mypy strict passes with generics.

---

## Suggested tests

- **BaseAgent**: state-machine legal/illegal transitions; event ordering; generic type preservation.
- **ConversationMemory**: window overflow triggers summarize; system message eviction prevention; token-count accuracy vs actual tokenizer.
- **CapabilitySet**: scoring monotonicity, empty intersections, ties, proficiency clamps.
- **JSON extraction**: malformed LLM responses (truncated, multiple blocks, nested braces in strings, escape sequences).
- **OrchestratorAgent**: all-agents-fail raises rather than silently returning; DAG cycle detection; capability tie-breaking.
- **ClaudeAgent**: tool_use round-trip; streaming content blocks; rate-limit retry.
- **ClaudeSDKAgent**: session lifecycle; standalone invocation path.
- **agent_loader**: unknown/missing definition directory handling; frontmatter parse errors.
- **Config**: override precedence; missing persona file.
- **Mock backend**: dev-mode path produces deterministic output; never fires in production config.

---

## Related code and reuse opportunities

- **`json_extraction.py`** could be extracted as a standalone library — it's generally useful and better than greedy regex approaches.
- **`ConversationMemory`** could generalize to non-agent contexts (e.g., chat UI) — move to `core/memory.py`.
- **`CapabilitySet.score_match`** is a public-utility-caliber function; could be exposed for external orchestrators.
- **Agent event system** parallels the `server/websocket.py` hub — consider unifying into `core/events.py`.
- **System prompts** currently in `prompts/*.md`; consider externalizing into versioned YAML for experimentation.
- **Backend adapters** (`ClaudeAgent`, `ClaudeSDKAgent`) could use the existing `AdapterRegistry` pattern from `adapters/` for symmetry.
- **Mock backend** pattern should be promoted to a shared mock client for cross-package reuse.
