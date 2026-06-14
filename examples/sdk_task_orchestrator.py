"""SDK-native ``Task``-tool coordinator — the Claude Agent SDK counterpart to
:class:`~agentic_v2.agents.orchestrator.OrchestratorAgent`.

This example contrasts ARP's in-house asyncio orchestrator (which scores agents
against a capability set and fans subtasks out with ``asyncio.gather``) with the
Claude Agent SDK's *model-driven* orchestration: the coordinator is given the
``Task`` tool plus a roster of :class:`~claude_agent_sdk.AgentDefinition`
subagents, and **the model itself** decides which subagents to spawn, with what
context, and how many to run in parallel.

Key SDK primitives demonstrated (see ``docs/adr/ADR-025-sdk-task-orchestration.md``):

* ``allowed_tools`` includes ``"Task"`` — this is what lets the coordinator
  delegate at all. Without it the model cannot spawn subagents.
* Three ``AgentDefinition``s, each with a **distinct system prompt** and a
  **least-privilege ``tools`` list** (the SDK-native analogue of ARP's
  per-agent ``CapabilitySet``).
* **Dynamic** subagent selection: the coordinator prompt asks the model to pick
  *only the relevant* subagents from intermediate findings, rather than running
  a fixed researcher→coder→reviewer pipeline.
* **Explicit context in each spawn prompt**: the coordinator is instructed to
  restate the facts a subagent needs inside the ``Task`` prompt instead of
  relying on context auto-inheritance.
* **Parallel ``Task`` calls in one assistant turn**: the prompt explicitly asks
  for independent subtasks to be dispatched together so the SDK runs them
  concurrently.

Run guard: the example **no-ops with a clear message when ``ANTHROPIC_API_KEY``
is unset**, so it is safe to import and to run in CI without credentials.

Usage::

    export ANTHROPIC_API_KEY=sk-ant-...
    python examples/sdk_task_orchestrator.py "Audit the auth module for risks"
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("sdk_task_orchestrator")

# Default model: Claude Opus 4.8 (most capable; 1M context at standard pricing).
COORDINATOR_MODEL = "claude-opus-4-8"

# Least-privilege subagent roster. Each entry mirrors one of ARP's specialized
# agents but expressed as an SDK ``AgentDefinition`` — a name, a focused system
# prompt, and the *minimum* tool set that role needs.
SUBAGENT_SPECS: dict[str, dict[str, object]] = {
    "explorer": {
        "description": "Read-only codebase explorer. Finds relevant files and "
        "reports facts; never edits.",
        "prompt": (
            "You are a read-only codebase explorer. Locate the files and symbols "
            "relevant to the coordinator's question and report concrete findings "
            "(paths, line ranges, summaries). You MUST NOT modify any file."
        ),
        # Least privilege: read + search only, no Write/Edit/Bash.
        "tools": ["Read", "Grep", "Glob"],
        "effort": "low",
    },
    "analyzer": {
        "description": "Per-file deep analyzer. Reasons about a single file's "
        "logic, risks, and edge cases.",
        "prompt": (
            "You are a senior engineer analyzing ONE file at a time. The "
            "coordinator will give you a specific file path and the facts you "
            "need. Report bugs, security risks, and edge cases for that file "
            "only. Read the file before reasoning about it."
        ),
        "tools": ["Read", "Grep"],
        "effort": "high",
    },
    "synthesizer": {
        "description": "Cross-file integrator. Combines per-file findings into "
        "one prioritized report.",
        "prompt": (
            "You are a tech lead. The coordinator will hand you the analyzers' "
            "per-file findings as text. Integrate them into a single prioritized "
            "report (cross-file interactions first). Do not re-read files; work "
            "only from the findings you are given."
        ),
        "tools": [],  # pure reasoning over provided context
        "effort": "high",
    },
}

# The coordinator's allowed tools. ``Task`` is the delegation primitive (without
# it the model cannot spawn subagents); the read-only tools let the coordinator
# do light triage itself. No Write/Edit/Bash — least privilege at the coordinator
# level too. Defined as a plain constant so the load-bearing ARP-1 assertions can
# be checked without importing ``claude_agent_sdk``.
COORDINATOR_ALLOWED_TOOLS: list[str] = ["Task", "Read", "Grep", "Glob"]

COORDINATOR_SYSTEM_PROMPT = (
    "You are a task coordinator. You have a `Task` tool that spawns specialized "
    "subagents: 'explorer' (read-only discovery), 'analyzer' (per-file deep "
    "analysis), and 'synthesizer' (cross-file integration).\n\n"
    "Operating rules:\n"
    "1. Start by spawning ONE 'explorer' subtask to discover the relevant files.\n"
    "2. From the explorer's findings, spawn one 'analyzer' subtask PER discovered "
    "file. Dispatch these analyzer Tasks together in a SINGLE turn so they run in "
    "parallel.\n"
    "3. Select subagents dynamically — only spawn analyzers for files that are "
    "actually relevant; do not run a fixed pipeline.\n"
    "4. In every Task prompt, restate the exact context the subagent needs "
    "(the file path, the goal, the relevant facts). Never assume the subagent "
    "inherits your conversation.\n"
    "5. Finish by spawning ONE 'synthesizer' subtask, passing it the analyzers' "
    "findings inline.\n"
    "Keep your own narration terse."
)


def _build_agents() -> dict[str, object]:
    """Construct the ``AgentDefinition`` roster from :data:`SUBAGENT_SPECS`.

    Imported lazily so this module imports even when ``claude-agent-sdk`` is not
    installed (the run guard reports the missing dependency at call time).
    """
    from claude_agent_sdk import AgentDefinition

    agents: dict[str, object] = {}
    for name, spec in SUBAGENT_SPECS.items():
        agents[name] = AgentDefinition(
            description=str(spec["description"]),
            prompt=str(spec["prompt"]),
            tools=list(spec["tools"]),  # type: ignore[arg-type]
            model=COORDINATOR_MODEL,
            effort=spec.get("effort"),  # type: ignore[arg-type]
        )
    return agents


def _build_options(agents: dict[str, object]) -> object:
    """Construct ``ClaudeAgentOptions`` for the coordinator."""
    from claude_agent_sdk import ClaudeAgentOptions

    return ClaudeAgentOptions(
        model=COORDINATOR_MODEL,
        system_prompt=COORDINATOR_SYSTEM_PROMPT,
        # "Task" is the delegation primitive; the read-only tools let the
        # coordinator do light triage itself. No Write/Edit/Bash — least
        # privilege at the coordinator level too.
        allowed_tools=list(COORDINATOR_ALLOWED_TOOLS),
        agents=agents,  # type: ignore[arg-type]
        permission_mode="bypassPermissions",
        effort="high",
    )


async def run_orchestration(task: str) -> int:
    """Run the SDK ``Task`` coordinator for *task*.

    Returns a process exit code: ``0`` on success, ``2`` when ``ANTHROPIC_API_KEY``
    is unset (the no-op guard), ``3`` when the SDK is not installed.
    """
    if not os.environ.get("ANTHROPIC_API_KEY"):
        logger.warning(
            "ANTHROPIC_API_KEY is not set — this example makes real Claude Agent "
            "SDK calls and will no-op. Set the key and re-run to see the "
            "Task-tool coordinator spawn subagents."
        )
        return 2

    try:
        from claude_agent_sdk import (
            AssistantMessage,
            ResultMessage,
            TextBlock,
            ToolUseBlock,
            query,
        )
    except ImportError:
        logger.error(
            "claude-agent-sdk is not installed. Install with: "
            "pip install -e '.[claude]'"
        )
        return 3

    agents = _build_agents()
    options = _build_options(agents)

    logger.info("Coordinator model: %s", COORDINATOR_MODEL)
    logger.info("Subagents: %s", ", ".join(SUBAGENT_SPECS))
    logger.info("Task: %s\n", task)

    task_spawns = 0
    async for message in query(prompt=task, options=options):
        if isinstance(message, AssistantMessage):
            for block in message.content:
                if isinstance(block, TextBlock) and block.text.strip():
                    logger.info("[coordinator] %s", block.text.strip())
                elif isinstance(block, ToolUseBlock) and block.name == "Task":
                    task_spawns += 1
                    subagent = block.input.get("subagent_type", "?")
                    logger.info("[spawn #%d] -> %s", task_spawns, subagent)
        elif isinstance(message, ResultMessage):
            logger.info("\n--- done (Task spawns observed: %d) ---", task_spawns)

    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    args = argv if argv is not None else sys.argv[1:]
    task = (
        " ".join(args)
        if args
        else "Investigate the agent orchestration code for correctness risks "
        "and summarize the top issues."
    )
    return asyncio.run(run_orchestration(task))


if __name__ == "__main__":
    raise SystemExit(main())
