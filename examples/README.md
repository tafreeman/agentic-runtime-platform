# Python examples

These scripts show the runtime's Python APIs in small, independent programs.
Examples 01 through 06, plus the default resume and tool-choice paths, do not
need provider credentials.

Run each command from the repository root.

## Setup

The standard setup installs the runtime, evaluation package, and development
dependencies:

```text
just setup
```

The repository `justfile` currently requires PowerShell. For a Python-only
setup or another operating system:

```text
python -m pip install -e ".[dev]"
python -m pip install -e "./agentic-workflows-v2[dev,server,langchain]"
python -m pip install -e "./agentic-v2-eval[dev]"
```

Install the runtime's `claude` extra before using the Claude Agent SDK example
or a live Claude tool-choice run.

## Example index

| File | What it shows | Provider call |
|---|---|---|
| [01_hello_workflow.py](01_hello_workflow.py) | Build and execute a three-step pipeline | No |
| [03_custom_agent.py](03_custom_agent.py) | Implement a typed `BaseAgent` with lifecycle events | No; uses a mock call |
| [04_model_routing.py](04_model_routing.py) | Configure fallback chains, scoped overrides, and provider health | No |
| [05_evaluation.py](05_evaluation.py) | Score results with inline and bundled rubrics | No |
| [06_adapter_switching.py](06_adapter_switching.py) | Compare sequential pipeline and dependency-based DAG execution | No |
| [resume_and_fork.py](resume_and_fork.py) | Resume a checkpoint and fork it into a new session | No |
| [forced_tool_choice.py](forced_tool_choice.py) | Compare forced, required, and automatic tool selection | Only with `--live` |
| [sdk_task_orchestrator.py](sdk_task_orchestrator.py) | Delegate tasks through the Claude Agent SDK `Task` tool | Yes |

## Run the local examples

```text
python examples/01_hello_workflow.py
python examples/03_custom_agent.py
python examples/04_model_routing.py
python examples/05_evaluation.py
python examples/06_adapter_switching.py
python examples/resume_and_fork.py demo
python examples/forced_tool_choice.py
```

Resume or fork a saved checkpoint:

```text
python examples/resume_and_fork.py --resume my_checkpoint
python examples/resume_and_fork.py --fork my_checkpoint
```

## Run provider-backed examples

In PowerShell:

```powershell
$env:ANTHROPIC_API_KEY = "<your-key>"
python examples/sdk_task_orchestrator.py "Review the orchestrator for risks"
python examples/forced_tool_choice.py --live
```

In Bash:

```bash
export ANTHROPIC_API_KEY="<your-key>"
python examples/sdk_task_orchestrator.py "Review the orchestrator for risks"
python examples/forced_tool_choice.py --live
```

Do not put credentials in source files, command history, test output, or
commits. The provider-backed examples print a clear message and stop if the
required key or SDK is unavailable.

## Main APIs used

| Package | APIs demonstrated |
|---|---|
| `agentic_v2.engine` | Pipelines, DAGs, step definitions, and execution context |
| `agentic_v2.agents` | Base agent, configuration, events, and state |
| `agentic_v2.models` | Tier routing, fallback chains, and health tracking |
| `agentic_v2.adapters` | Engine discovery |
| `agentic_v2.contracts` | Typed task and workflow results |
| `agentic_v2_eval` | Rubrics and weighted scores |

For design background on the advanced examples, see
[ADR-025](../docs/adr/ADR-025-sdk-task-orchestration.md),
[ADR-026](../docs/adr/ADR-026-resume-vs-summary-session.md), and
[ADR-027](../docs/adr/ADR-027-forced-tool-choice.md).
