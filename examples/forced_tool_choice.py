"""Forced / ``any`` / ``auto`` ``tool_choice`` + the cross-role ``verify_fact`` tool.

Demonstrates ARP's counterpart to the Agent SDK / provider ``tool_choice``
primitive (see ``docs/adr/ADR-027-forced-tool-choice.md``):

* **Force a specific tool first.** ``build_tool_contracts(..., tool_choice=...)``
  validates and normalizes the requested choice against the resolved tool set,
  so a step can require the model to call ``verify_fact`` on its first turn —
  "verify before you reason" — and then revert to ``auto`` for follow-up turns.
* **``any`` / ``required``.** Force *some* tool without naming which.
* **``auto`` (default).** Let the model decide — unchanged legacy behavior.
* **A cross-role shared tool.** ``verify_fact`` is registered at tier 0, so it is
  selectable by every model tier and therefore by every role (orchestrator,
  coder, reviewer, ...). This is the exam's shared-tool pattern: one verification
  primitive instead of each role re-implementing claim-checking.

The deterministic parts (contract building + ``verify_fact`` execution) run
**without any API key**. The optional live tool-loop section no-ops with a clear
message unless ``ANTHROPIC_API_KEY`` is set.

Usage::

    python examples/forced_tool_choice.py            # deterministic walkthrough
    ANTHROPIC_API_KEY=sk-ant-... python examples/forced_tool_choice.py --live
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys

from agentic_v2.engine.tool_execution import build_tool_contracts
from agentic_v2.models.router import ModelTier
from agentic_v2.tools import get_registry

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("forced_tool_choice")

# A step that wants to verify a claim before reasoning about it.
SHARED_TOOLS = ["verify_fact", "search"]


def _show_choice(label: str, choice: object) -> None:
    logger.info("  %-28s -> %s", label, choice)


async def _deterministic_walkthrough() -> None:
    """Build contracts under each tool_choice mode and run verify_fact directly."""
    tier = ModelTier.TIER_2

    logger.info("1. tool_choice normalization (validated against the tool set):")
    _, _, auto = build_tool_contracts(tier, SHARED_TOOLS, "auto")
    _show_choice("auto (model decides)", auto)
    _, _, required = build_tool_contracts(tier, SHARED_TOOLS, "any")
    _show_choice("any / required (some tool)", required)
    _, _, forced = build_tool_contracts(tier, SHARED_TOOLS, "verify_fact")
    _show_choice("forced 'verify_fact'", forced)
    _, _, forced_dict = build_tool_contracts(
        tier, SHARED_TOOLS, {"type": "tool", "name": "verify_fact"}
    )
    _show_choice("forced {type:tool,...}", forced_dict)

    logger.info("\n2. Forcing an unknown tool fails fast:")
    try:
        build_tool_contracts(tier, SHARED_TOOLS, "no_such_tool")
    except ValueError as exc:
        logger.info("  ValueError: %s", exc)

    logger.info("\n3. verify_fact is a tier-0 cross-role tool (every tier sees it):")
    for cross_tier in (ModelTier.TIER_0, ModelTier.TIER_3, ModelTier.TIER_5):
        _, bound, _ = build_tool_contracts(cross_tier, ["verify_fact"], "auto")
        logger.info(
            "  tier %s: verify_fact available = %s",
            cross_tier.value,
            "verify_fact" in bound,
        )

    logger.info("\n4. Running the forced tool deterministically (no model call):")
    verify = get_registry().get("verify_fact")
    assert verify is not None  # registered via builtin auto-discovery
    grounded = await verify.execute(
        claim="p99 latency is 42ms",
        evidence="Load test report: measured 42ms p99 under 1k RPS.",
        mode="numeric",
    )
    logger.info("  grounded claim   -> %s", grounded.data)
    ungrounded = await verify.execute(
        claim="uptime was 99.99%",
        evidence="Status page shows 99.9% uptime last quarter.",
        mode="numeric",
    )
    logger.info("  ungrounded claim -> %s", ungrounded.data)


async def _live_tool_loop() -> int:
    """Optional: drive a real step that forces verify_fact on its first turn."""
    if not os.environ.get("ANTHROPIC_API_KEY"):
        logger.info(
            "\n[--live] ANTHROPIC_API_KEY is not set; skipping the live tool loop. "
            "The deterministic walkthrough above needs no credentials."
        )
        return 0

    from agentic_v2.engine.agent_resolver import _run_native_tool_loop
    from agentic_v2.models.client import get_client

    tier = ModelTier.TIER_4
    tool_schemas, bound_tools, forced_choice = build_tool_contracts(
        tier, ["verify_fact"], tool_choice="verify_fact"
    )
    client = get_client(auto_configure=True)
    messages = [
        {
            "role": "user",
            "content": (
                "Claim: 'the release ships in Q3 2026'. Evidence: 'The roadmap "
                "lists the GA milestone for Q3 2026.' Verify the claim, then "
                "summarize whether downstream planning can rely on it."
            ),
        }
    ]
    response, model_used, tokens, tool_calls = await _run_native_tool_loop(
        client=client,
        agent_name="tier4_reviewer",
        tier=tier,
        messages=messages,
        tool_schemas=tool_schemas,
        bound_tools=bound_tools,
        max_tokens=512,
        tool_choice=forced_choice,  # forced on turn 1, auto thereafter
    )
    logger.info(
        "\n[--live] model=%s tokens=%s tool_calls=%s\n%s",
        model_used,
        tokens,
        tool_calls,
        response,
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI entry point for the example."""
    args = argv if argv is not None else sys.argv[1:]
    asyncio.run(_deterministic_walkthrough())
    if "--live" in args:
        return asyncio.run(_live_tool_loop())
    logger.info(
        "\nPass --live (with ANTHROPIC_API_KEY) to drive a real forced-tool step."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
