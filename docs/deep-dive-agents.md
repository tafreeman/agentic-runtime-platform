# Agents

The `agentic_v2.agents` package contains typed agent classes for code
generation, review, testing, architecture, and task delegation. Use these
classes when a workflow step needs a model-and-tool loop. Use a normal
`StepDefinition` for deterministic work that does not need one.

## Available classes

| Class | Input | Output | Purpose |
| --- | --- | --- | --- |
| `CoderAgent` | `CodeGenerationInput` | `CodeGenerationOutput` | Generate or revise code |
| `ReviewerAgent` | `CodeReviewInput` | `CodeReviewOutput` | Return structured review findings |
| `TestAgent` | `TestGenerationInput` | `TestGenerationOutput` | Generate test files |
| `ArchitectAgent` | `ArchitectureInput` | `ArchitectureOutput` | Produce a structured system design |
| `OrchestratorAgent` | `OrchestratorInput` | `OrchestratorOutput` | Decompose and delegate a task |

The package exports these classes and their public input and output models
from `agentic_v2.agents`.

## BaseAgent contract

`BaseAgent[TInput, TOutput]` owns:

- initialization and cleanup;
- state transitions and events;
- bounded model iterations;
- conversation memory;
- model routing;
- tool discovery, validation, approval, and dispatch;
- optional streaming;
- the last result and failure information.

A subclass must implement:

```python
async def _call_model(
    self,
    messages: list[dict[str, object]],
    tools: list[dict[str, object]] | None = None,
) -> dict[str, object]: ...

def _format_task_message(self, task: TInput) -> str: ...

async def _is_task_complete(self, task: TInput, response: str) -> bool: ...

async def _parse_output(self, task: TInput, response: str) -> TOutput: ...
```

`_call_model()` returns a mapping with `content` and, when applicable,
`tool_calls`. The output parser should reject invalid required data instead of
silently treating incomplete text as success.

## Configuration

`AgentConfig` has these defaults:

| Field | Default |
| --- | --- |
| `name` | `agent` |
| `default_tier` | `ModelTier.TIER_2` |
| `max_tier` | `ModelTier.TIER_4` |
| `max_iterations` | `10` |
| `max_tool_calls_per_turn` | `5` |
| `timeout_seconds` | `300.0` |
| `max_memory_messages` | `50` |
| `max_memory_tokens` | `8000` |
| `enable_streaming` | `False` |
| `verbose` | `False` |

`max_iterations` prevents an endless model/tool loop.
`max_tool_calls_per_turn` limits calls from one model response. Neither limit
replaces a timeout on the model client or tool implementation.

Constructor arguments allow injection of a model router, tool registry, and
LLM client:

```python
agent = CoderAgent(
    config=config,
    router=router,
    tools=tool_registry,
    llm_client=client,
)
```

Use dependency injection in tests so a test cannot reach a real provider by
accident.

## Lifecycle

The normal state sequence is:

```text
created -> initializing -> ready -> running
                                      |-> completed
                                      |-> failed
                                      `-> cancelled
```

`run()` initializes a newly created agent, adds the task to memory, and starts
the bounded execution loop. A model response with tool calls is dispatched,
recorded as tool-role messages, and followed by another iteration. A final
response is parsed into the declared output model.

Cancellation is re-raised after the state changes to `cancelled`. Other
exceptions set the state to `failed` and remain visible to the caller.

Call `cleanup()` when an agent instance is no longer needed. It clears memory,
bound tools, and the current execution context.

## Tools

During initialization, the base class binds registered tools whose tier is at
or below the agent's `default_tier`. You can also call `bind_tool()` or
`unbind_tool()` explicitly.

Tool calls follow the shared engine path:

1. normalize the provider's call shape;
2. resolve the bound tool;
3. apply the approval gate;
4. validate parameters;
5. execute the tool;
6. serialize and size-limit the result;
7. add the result to conversation memory.

Unknown tools, invalid parameters, and execution errors are returned to the
model as failed tool results. They are not reported as successful calls.

Tool tier is an availability filter, not an authorization boundary. Configure
approval policy and keep tool-side validation in place for operations that
read sensitive data or change state.

## Memory

`ConversationMemory` stores system, user, assistant, and tool messages. Its
message and token limits are estimates used to control context growth.
Summarization can reduce older content when the limits are exceeded.

Do not use conversation memory as an audit store. Persist workflow events or
domain records separately when the data must survive the agent process.

## Events

Register a synchronous handler with `on_event()` to observe:

- state changes;
- sent and received messages;
- tool calls and results;
- model activity;
- streaming chunks;
- errors.

Handlers are suitable for metrics and UI updates. Handler exceptions are
logged and do not stop the agent, so critical persistence should happen in
the workflow or event-storage layer instead.

## Capabilities and orchestration

Capability mixins declare what an agent is designed to do.
`get_agent_capabilities()` combines the declarations and
`CapabilitySet.score_match()` compares them with a subtask's requirements.

`OrchestratorAgent` uses those scores to assign work. Its plan includes
dependencies, which allow ready subtasks to run in parallel up to
`OrchestratorInput.max_parallel`. Fallback attempts and exhausted assignments
are recorded rather than converted into successful results.

This assignment is heuristic. Validate the plan, required capabilities, and
final output for important work.

The CLI's `agentic orchestrate` command does not currently expose this dynamic
path through the default LangGraph workflow route.

## Put an agent in a workflow

`agent_to_step()` wraps a `BaseAgent` as a `StepDefinition`:

```python
from agentic_v2.agents import AgentConfig, CoderAgent, agent_to_step

agent = CoderAgent(config=AgentConfig(name="generate_code"))
step = agent_to_step(agent)
```

The wrapper reads `task` from `ExecutionContext` and writes the agent output as
`result`. Check that this generic context contract fits the surrounding
workflow before using the wrapper.

## Anthropic implementations

`agentic_v2.agents.implementations` contains two optional integrations:

- `ClaudeAgent` extends `BaseAgent` and calls the Anthropic Messages API.
- `ClaudeSDKAgent` wraps `claude-agent-sdk` and does not extend `BaseAgent`.

Install the optional dependencies with:

```powershell
python -m pip install -e "./agentic-workflows-v2[claude]"
```

Because `ClaudeSDKAgent` has a separate lifecycle and permission model, do not
treat it as a drop-in `BaseAgent`. Its loader reads Markdown definitions with
YAML frontmatter from the bundled definitions directory or
`AGENTIC_EXTERNAL_AGENTS_DIR`.

## Adding an agent

1. Define Pydantic input and output models.
2. Subclass `BaseAgent` with those types.
3. Implement the four required methods.
4. Set finite iteration, tool-call, and timeout limits.
5. Add capability mixins only for behavior the class implements.
6. Write tests for valid output, malformed model output, tool failure,
   cancellation, and the iteration limit.
7. Add a workflow example only if the agent's context contract is clear.

Source directory:
`agentic-workflows-v2/agentic_v2/agents/`.
