---
title: Integration recipes
description: Short, runnable Python recipes for switching execution engines, capping model cost, wiring tool approval, and scoring output.
tags:
  - getting-started
  - integration
---

# Integration recipes

Each recipe uses the public Python surface and runs without a provider
credential unless it says otherwise. Run them from an environment installed
with [`just setup` or the manual steps](installation.md), which include the
`langchain` extra, and set `AGENTIC_NO_LLM=1` so nothing can reach a provider.

If you install pieces by hand, install the root tools package first and pass
the constraints file to every install:

```bash
python -m pip install -e . -c ci-constraints.txt
python -m pip install -e "./agentic-workflows-v2[langchain]" -c ci-constraints.txt
```

Without the `langchain` extra the LangChain adapter is not registered and
`list_adapters()` returns only `['native']`.

## 1. Run a workflow on either execution engine

Both engines are reached through the `AdapterRegistry`. A **named YAML
workflow** loads and runs the same way on each of them:

```python
import asyncio

from agentic_v2.adapters import get_registry


async def main() -> None:
    registry = get_registry()
    print("adapters:", registry.list_adapters())
    for name in ("native", "langchain"):
        engine = registry.get_adapter(name)
        workflow = engine.load_workflow("test_deterministic")
        result = await engine.execute(
            workflow, workflow_inputs={"input_text": "Hello World"}
        )
        print(name, result.overall_status.value, result.final_output)


asyncio.run(main())
```

Both lines report `success` with the same `processed_text` and `step_count`.
The command-line equivalent is
`agentic compare test_deterministic --input in.json --adapters native,langchain`;
see the [CLI reference](../cli-reference.md).

A **runtime-built `DAG`** is different: only the native engine accepts it.
`LangChainEngine` takes a workflow name, a path, or a LangChain
`WorkflowConfig` and raises `TypeError` for a `DAG`, and `NativeEngine` raises
`TypeError` for a bare workflow name. Step functions are `async`, and what a
step returns lands under that step's outputs unless `output_mapping` copies it
into a context variable for later steps:

```python
import asyncio

from agentic_v2.adapters import get_registry
from agentic_v2.engine import DAG, ExecutionContext, StepDefinition


async def ingest(ctx: ExecutionContext) -> dict[str, str]:
    return {"cleaned": ctx.get_sync("raw").strip().upper()}


async def count(ctx: ExecutionContext) -> dict[str, int]:
    return {"length": len(ctx.get_sync("cleaned"))}


async def main() -> None:
    dag = DAG(name="adapter_demo")
    dag.add(
        StepDefinition(
            name="ingest", func=ingest, output_mapping={"cleaned": "cleaned"}
        )
    ).add(
        StepDefinition(
            name="count",
            func=count,
            depends_on=["ingest"],
            output_mapping={"length": "length"},
        )
    )
    ctx = ExecutionContext(variables={"raw": "  agentic runtime  "})
    result = await get_registry().get_adapter("native").execute(dag, ctx)
    print(result.overall_status.value, ctx.get_sync("cleaned"), ctx.get_sync("length"))


asyncio.run(main())
```

This prints `success AGENTIC RUNTIME 15`. See
[Runtime architecture](../architecture-runtime.md) for how the registry
selects an engine.

## 2. Cap model cost with a cost-lane ceiling

`AGENTIC_MAX_COST_LANE` (`local`, `free`, or `paid`, the default) drops
candidate models above the ceiling by their curated `cost_lane` in
`model_registry.yaml`. An id missing from the registry counts as `paid`. The
variable is read on every call, so set it in the process environment; the
assignment below only keeps the example self-contained.

`SmartModelRouter` excludes over-ceiling models inside a tier and, when a tier
has none left, degrades to another tier and records that on `last_selection`.
It raises only when every tier is exhausted (and `AGENTIC_NO_LLM` is unset):

```python
import os

from agentic_v2.models import FallbackChain, ModelTier, SmartModelRouter

os.environ["AGENTIC_MAX_COST_LANE"] = "free"

router = SmartModelRouter()
router.register_chain(
    ModelTier.TIER_2,
    FallbackChain.build("lane")
    .add("anthropic:claude-sonnet-4-6")  # paid: excluded by the ceiling
    .add("ollama:qwen3-coder:30b")  # local: allowed
    .done(),
)
print(router.get_model_for_tier(ModelTier.TIER_2), router.last_selection)

# A tier whose whole chain is above the ceiling degrades to another tier.
router.register_chain(
    ModelTier.TIER_4,
    FallbackChain(("anthropic:claude-sonnet-4-6",), name="paid-only"),
)
print(router.get_model_for_tier(ModelTier.TIER_4), router.last_selection)
```

The first selection is `TIER_2` with `is_degraded=False`; the second reports
`requested_tier='TIER_4'`, `actual_tier='TIER_3'`, and `is_degraded=True`.

The simpler `ModelRouter`, and the LangChain model builder, behave differently:
when the ceiling filters out every candidate they refuse instead of degrading,
raising `CostLaneCeilingExceededError`:

```python
import os

from agentic_v2.models import FallbackChain, ModelRouter, ModelTier
from agentic_v2.models.model_registry import CostLaneCeilingExceededError

os.environ["AGENTIC_MAX_COST_LANE"] = "free"

router = ModelRouter()
router.register_chain(
    ModelTier.TIER_4, FallbackChain(("anthropic:claude-sonnet-4-6",), name="paid-only")
)
try:
    router.get_model_for_tier(ModelTier.TIER_4)
except CostLaneCeilingExceededError as exc:
    print("refused:", exc)
```

Tiers run from `TIER_0` (deterministic, no model) to `TIER_5`. Mistral and
DigitalOcean model ids are served only by the LangChain engine; the native
backend fails loudly for them. See [Configuration](../configuration.md) and
[ADR-059](../adr/ADR-059-model-cost-lane-ceiling.md).

## 3. Wire tool approval

Every tool call that needs approval goes through
`evaluate_tool_approval()`. A call needs approval when the tool sets
`requires_approval` (the high-impact built-ins such as `file_write`), when
`AGENTIC_REQUIRE_TOOL_APPROVAL` is on (every tool), or when its name is listed
in `AGENTIC_APPROVAL_REQUIRED_TOOLS`. Read-only tools such as `file_read` are
not gated by default.

With no provider registered, a gated call is **denied** (fail-closed).
`AutoDenyProvider` is a separate, explicit kill switch and is never installed
for you:

```python
import asyncio

from agentic_v2.governance import (
    ApprovalDecision,
    ApprovalRequest,
    CallbackApprovalProvider,
    PolicyApprovalProvider,
    evaluate_tool_approval,
    set_approval_provider,
)
from agentic_v2.tools.builtin import FileReadTool, FileWriteTool


async def check(tool, name: str, label: str) -> None:
    outcome = await evaluate_tool_approval(
        tool, name, {"path": "notes.txt"}, call_id="c1", agent_or_step="demo"
    )
    print(f"{label:<28} allowed={outcome.allowed} via {outcome.provider_label}")


async def main() -> None:
    write, read = FileWriteTool(), FileReadTool()

    await check(write, "file_write", "no provider, gated tool")
    await check(read, "file_read", "no provider, read-only tool")

    set_approval_provider(PolicyApprovalProvider(frozenset({"file_write"})))
    await check(write, "file_write", "allowlisted tool")

    def operator_prompt(request: ApprovalRequest) -> ApprovalDecision:
        print("  asked to approve:", request.tool_name)
        return ApprovalDecision.DENIED

    set_approval_provider(CallbackApprovalProvider(operator_prompt))
    await check(write, "file_write", "callback provider")

    set_approval_provider(None)


asyncio.run(main())
```

The first line is denied via `no provider registered`, the read-only tool is
`not-required`, the allowlisted tool is approved, and the callback decides for
itself. The callback may also be `async`, which is the hook for an interactive
prompt or a remote approval service. Register a provider once at process
start. The structural gate itself (`BaseTool.__init_subclass__`) needs no
extra install; see [ADR-041](../adr/ADR-041-approval-gate-timeout.md),
[ADR-047](../adr/ADR-047-structural-tool-approval-gate.md), and
[Known limitations section 4.3](../KNOWN_LIMITATIONS.md).

### ExecutionKit delegation (`ek` extra)

Separately from the gate, the optional `ek` extra routes model calls through
the ExecutionKit-backed provider:

```bash
python -m pip install -e "./agentic-workflows-v2[ek]" -c ci-constraints.txt
```

With the package installed, `AGENTIC_EK_PROVIDER` defaults to `1` and ordinary
`get_client().complete(...)` calls and LLM steps use it automatically; set
`AGENTIC_EK_PROVIDER=0` to roll back to the legacy path. To observe each
physical attempt, build the provider yourself and pass an `attempt_callback`
(each `ProviderAttempt` records `model`, `latency_ms`, `ok`, `error_type`, and
`streaming`):

```python
import asyncio

from agentic_v2.models import MockBackend, ModelTier, SmartModelRouter
from agentic_v2.models.ek_provider import ProviderAttempt, SmartRouterProvider


async def main() -> None:
    attempts: list[ProviderAttempt] = []
    provider = SmartRouterProvider(
        SmartModelRouter(),
        MockBackend(default_response="hello"),
        ModelTier.TIER_2,
        attempt_callback=attempts.append,
    )
    response = await provider.complete([{"role": "user", "content": "Say hi"}])
    print(response.content, attempts)


asyncio.run(main())
```

See [ADR-023](../adr/ADR-023-executionkit-runtime-contract-relationship.md).

## 4. Use Claude through a subscription sign-in (`claude` extra)

This recipe needs the `claude` extra and a signed-in Claude Code, so it does
not run in a key-free environment:

```bash
python -m pip install -e "./agentic-workflows-v2[claude]" -c ci-constraints.txt
```

`ClaudeSDKAgent` wraps the Claude Agent SDK. It is not a `BaseAgent` and
bypasses the tool registry; the SDK's own tools (`Read`, `Glob`, `Grep`,
`Bash`, ...) do the work:

```python
import asyncio

from agentic_v2.agents.implementations import ClaudeSDKAgent


async def main() -> None:
    agent = ClaudeSDKAgent(tools=["Read", "Glob", "Grep"], cwd=".")
    print(await agent.run("List the top-level directories in one line each."))


asyncio.run(main())
```

To use the same sign-in as a model backend, use an id with the `claude:`
prefix. The backend registers itself when the SDK is importable. The child
process has `ANTHROPIC_API_KEY` blanked so the subscription, not an API key, is
billed ([ADR-058](../adr/ADR-058-claude-subscription-backend.md)). See
[Agents deep dive](../deep-dive-agents.md).

## 5. Score output against a rubric

`CriterionScorer` is the key-free weighted scorer and needs no extra. Weights
live in the rubric:

```python
from agentic_v2.scoring.criterion_aggregation import CriterionScorer

rubric = {
    "criteria": [
        {"name": "correctness", "weight": 0.5},
        {"name": "completeness", "weight": 0.3},
        {"name": "safety", "weight": 0.2},
    ]
}
scorer = CriterionScorer(rubric)

full = scorer.score({"correctness": 0.92, "completeness": 0.85, "safety": 1.0})
print(round(full.weighted_score, 4), full.missing_criteria)

partial = scorer.score({"correctness": 0.92, "completeness": 0.85})
print(round(partial.weighted_score, 4), partial.missing_criteria)
```

This prints `0.915 ()` and then `0.715 ('safety',)`: a missing criterion keeps
its weight in the denominator, so it lowers the score and is listed in
`missing_criteria`.

With the `eval` extra (`agentic-evalkit`, see
[ADR-042](../adr/ADR-042-agentic-evalkit-adoption.md)), the evalkit bridge
scores the same input and returns `0.915`:

```python
from agentic_v2.scoring import evalkit_bridge

print(evalkit_bridge.EVALKIT_AVAILABLE)
print(
    evalkit_bridge.score_criteria(
        rubric, {"correctness": 0.92, "completeness": 0.85, "safety": 1.0}
    )
)
```

The `0.80` figure is not a general pass mark. It is the `--threshold` the
golden-dataset gate in CI uses, and you can run that gate locally from the
repository root:

```bash
AGENTIC_NO_LLM=1 python scripts/eval_gate.py \
  --cases datasets/default/golden_cases.json --threshold 0.80
```

The runtime scorer's own default pass threshold is `70.0` on a 0-100 scale;
see [Gating](../evaluation/gating.md).
