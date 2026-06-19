"""Agent resolver -- maps YAML agent names to executable step functions.

This is the bridge between the declarative YAML workflow definitions and
the executable runtime.  Each step in a YAML workflow declares an ``agent``
field (e.g. ``tier2_coder``).  The resolver:

1. **Infers the model tier** from the agent name prefix (``tier{N}_``).
2. **Selects an implementation**:
   - Tier 0 agents -> deterministic Python function from ``TIER0_REGISTRY``.
   - Tier 1+ agents -> auto-generated LLM-backed step via :func:`_make_llm_step`.
3. **Assembles the prompt** from persona Markdown files (``prompts/<role>.md``),
   task description, available context, tool contracts, and the universal
   sentinel output format instructions.
4. **Executes multi-turn tool loops** -- LLM steps can call registered tools
   (up to 8 rounds, 12 calls/round) with truncated results.
5. **Parses LLM output** via sentinel artifacts (``<<<ARTIFACT>>>``), JSON
   extraction, and robust review-report normalization for gating conditions.

Implementation is split across focused sub-modules:
- :mod:`.llm_output_parsing` — JSON/artifact extraction and normalization
- :mod:`.prompt_assembly` — system-message and tool-contract construction
- :mod:`.tool_execution` — tool call dispatch and LLM chat fallback

Key constants:
- ``_TIER_MAX_TOKENS``: Conservative per-tier output token limits.
- ``_MAX_TOOL_ROUNDS`` / ``_MAX_TOOL_CALLS_PER_ROUND``: Tool loop bounds.
- ``_MAX_TOOL_RESULT_CHARS``: Truncation limit for tool results.
"""

from __future__ import annotations

import ast
import contextlib
import logging
from pathlib import Path
from typing import Any

from ..integrations.otel import get_tracer as _get_tracer
from ..models.router import ModelTier
from .context import ExecutionContext
from .llm_output_parsing import (
    extract_files_from_artifact,
    extract_json_candidates,
    normalize_expected_structure,
    parse_llm_json_output,
    parse_sentinel_output,
)
from .prompt_assembly import (
    SENTINEL_OUTPUT_INSTRUCTIONS,
    build_system_prompt,
    load_agent_system_prompt,
)
from .step import StepDefinition, StepFunction
from .tool_execution import (
    MAX_TOOL_CALLS_PER_ROUND,
    MAX_TOOL_RESULT_CHARS,
    MAX_TOOL_ROUNDS,
    _executionkit_available,
    build_tool_contracts,
    complete_chat_with_fallback,
    run_tool_calls,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Backward-compatibility aliases (private names used by tests and scripts)
# ---------------------------------------------------------------------------

# llm_output_parsing.py re-exports
_extract_json_candidates = extract_json_candidates
_normalize_expected_structure = normalize_expected_structure
_parse_llm_json_output = parse_llm_json_output
_extract_files_from_artifact = extract_files_from_artifact
_parse_sentinel_output = parse_sentinel_output

# prompt_assembly.py re-exports
_load_agent_system_prompt = load_agent_system_prompt
_SENTINEL_OUTPUT_INSTRUCTIONS = SENTINEL_OUTPUT_INSTRUCTIONS

# tool_execution.py re-exports
_MAX_TOOL_ROUNDS = MAX_TOOL_ROUNDS
_MAX_TOOL_CALLS_PER_ROUND = MAX_TOOL_CALLS_PER_ROUND
_MAX_TOOL_RESULT_CHARS = MAX_TOOL_RESULT_CHARS
_build_tool_contracts = build_tool_contracts
_complete_chat_with_fallback = complete_chat_with_fallback
_run_tool_calls = run_tool_calls

# Maximum output tokens per model tier.  These are conservative values that
# work across all providers at each tier.  Tier 2+ use capable models that
# support at least 8 192 output tokens; tier 3+ supports 16 384.
_TIER_MAX_TOKENS: dict[ModelTier, int] = {
    ModelTier.TIER_0: 0,  # deterministic, no LLM
    ModelTier.TIER_1: 4096,
    ModelTier.TIER_2: 8192,
    ModelTier.TIER_3: 16384,
    ModelTier.TIER_4: 16384,
    ModelTier.TIER_5: 32768,
}


# ---------------------------------------------------------------------------
# Tier-0 deterministic step implementations
# ---------------------------------------------------------------------------


async def _parse_code_step(ctx: ExecutionContext) -> dict[str, Any]:
    """Tier-0: Parse a code file and return basic structure info."""
    file_path = None
    # Try multiple ways to get the file path from context
    for key in ("file_path", "code_file"):
        try:
            file_path = await ctx.get(key)
            if file_path:
                break
        except Exception as exc:
            logger.debug("Could not retrieve context key %r: %s", key, exc)

    # Also check parent context
    if not file_path:
        try:
            all_vars = ctx.all_variables()
            file_path = all_vars.get("file_path") or all_vars.get("code_file")
        except Exception as exc:
            logger.debug("Could not retrieve all_variables from context: %s", exc)

    source = ""
    if file_path:
        p = Path(file_path)
        if p.exists():
            source = p.read_text(encoding="utf-8", errors="replace")
        else:
            source = str(file_path)  # Might be inline code

    # Basic AST analysis for Python files
    parsed_ast: dict[str, Any] = {"raw_source": source[:500]}
    metrics: dict[str, Any] = {"lines": len(source.splitlines()), "chars": len(source)}

    try:
        tree = ast.parse(source)
        functions = [
            n.name
            for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        ]
        classes = [n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
        imports = [
            n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)
        ] + [
            alias.name
            for n in ast.walk(tree)
            if isinstance(n, ast.Import)
            for alias in n.names
        ]
        parsed_ast.update(
            {
                "language": "python",
                "functions": functions,
                "classes": classes,
                "imports": imports,
            }
        )
        metrics.update(
            {
                "function_count": len(functions),
                "class_count": len(classes),
                "import_count": len(imports),
            }
        )
    except SyntaxError:
        parsed_ast["language"] = "unknown"
        parsed_ast["parse_error"] = "Could not parse as Python"

    return {"parsed_ast": parsed_ast, "code_metrics": metrics}


async def _noop_step(_ctx: ExecutionContext) -> dict[str, Any]:
    """Tier-0 fallback: return empty outputs."""
    return {}


def _resolve_sample_item(ctx: ExecutionContext, item: Any) -> Any:
    """Resolve a single ``samples`` entry, expanding ``${...}`` expressions.

    List-valued step inputs are stored unresolved by the engine (only scalar
    ``${...}`` strings are resolved during input preparation), so the consensus
    step resolves each entry itself against the live context.
    """
    if isinstance(item, str):
        expr = item.strip()
        if expr.startswith("${") and expr.endswith("}"):
            from .expressions import ExpressionEvaluator

            return ExpressionEvaluator(ctx).resolve_variable(expr[2:-1].strip())
    return item


async def _gather_consensus_samples(ctx: ExecutionContext) -> list[Any]:
    """Read and resolve the ``samples`` input for the consensus aggregator."""
    raw_samples = await ctx.get("samples")
    if raw_samples is None:
        return []
    if not isinstance(raw_samples, (list, tuple)):
        raw_samples = [raw_samples]
    return [_resolve_sample_item(ctx, item) for item in raw_samples]


async def _consensus_step(ctx: ExecutionContext) -> dict[str, Any]:
    """Tier-0: majority-vote over ``samples`` and expose the winner for gating.

    Reads from the child context:
    - ``samples`` (required): a list of candidate values to vote on.  Entries
      that are ``${...}`` expressions are resolved against the live context.
    - ``min_agreement`` (optional, default ``0.0``): threshold for
      ``meets_threshold``.
    - ``mode`` (optional, default ``"majority"``): voting strategy.

    Returns the consensus fields downstream steps and ``when:`` conditions can
    branch on (e.g. ``when: ${steps.vote.outputs.meets_threshold}``).
    """
    from .consensus import majority_vote

    samples = await _gather_consensus_samples(ctx)

    min_agreement_raw = await ctx.get("min_agreement")
    try:
        min_agreement = float(min_agreement_raw) if min_agreement_raw is not None else 0.0
    except (TypeError, ValueError):
        min_agreement = 0.0

    mode = await ctx.get("mode") or "majority"
    if mode != "majority":
        logger.warning("Unknown consensus mode '%s'; using majority vote.", mode)

    result = majority_vote(samples, min_agreement=min_agreement)
    return {
        "winner": result.winner,
        "agreement": result.agreement,
        "votes": result.votes,
        "tied": result.tied,
        "meets_threshold": result.meets_threshold,
        "total_samples": result.total_samples,
    }


# Registry of known tier-0 deterministic step implementations
TIER0_REGISTRY: dict[str, StepFunction] = {
    "tier0_parser": _parse_code_step,
    "tier0_consensus": _consensus_step,
}


def _build_placeholder_output(
    agent_name: str,
    description: str,
    expected_output_keys: list[str] | None,
    error: Exception,
) -> dict[str, Any]:
    """Build deterministic placeholder output when the LLM call fails.

    Preserves workflow handoff contracts by emitting all declared output keys
    with placeholder payloads so downstream gating conditions still resolve.
    """
    placeholder_output: dict[str, Any] = {
        "agent": agent_name,
        "status": "llm_unavailable",
        "description": description,
        "note": str(error),
    }

    for key in expected_output_keys or []:
        if key in placeholder_output:
            continue
        if key in {"review_report", "code_review"}:
            placeholder_output[key] = {
                "overall_status": "NEEDS_FIXES",
                "reason": "llm_unavailable",
            }
        elif key == "overall_status":
            placeholder_output[key] = "NEEDS_FIXES"
        else:
            placeholder_output[key] = {
                "placeholder": True,
                "key": key,
                "reason": "llm_unavailable",
            }

    return placeholder_output


# ---------------------------------------------------------------------------
# LLM-backed step factory
# ---------------------------------------------------------------------------


def _attach_step_meta(
    parsed: dict[str, Any],
    model_used: str,
    tokens_used: int,
    tool_call_count: int,
) -> dict[str, Any]:
    """Attach LLM execution metadata so StepExecutor can populate StepResult."""
    parsed["_meta"] = {
        "model_used": model_used,
        "tokens_used": tokens_used,
        "tool_calls": tool_call_count,
    }
    return parsed


async def _run_ek_tool_loop(
    *,
    client: Any,
    tier: ModelTier,
    prompt: str,
    tool_schemas: Any,
    bound_tools: dict[str, Any],
    max_tokens: int,
    expected_output_keys: list[str] | None,
) -> dict[str, Any]:
    """ADR-023 Phase 6b: drive the step's tool loop via EK react_loop."""
    from .ek_step_delegation import run_tool_loop_via_ek

    response, model_used, tokens_used, tool_call_count = await run_tool_loop_via_ek(
        router=client.router,
        backend=client.backend,
        tier=tier,
        prompt=prompt,
        tool_schemas=tool_schemas,
        bound_tools=bound_tools,
        max_tokens=max_tokens,
        budget=getattr(client, "budget", None),
        max_rounds=MAX_TOOL_ROUNDS,
        max_observation_chars=MAX_TOOL_RESULT_CHARS,
    )
    parsed = (
        parse_sentinel_output(response, expected_output_keys)
        or parse_llm_json_output(response, expected_output_keys)
        or {}
    )
    return _attach_step_meta(parsed, model_used, tokens_used, tool_call_count)


async def _run_native_tool_loop(
    *,
    client: Any,
    agent_name: str,
    tier: ModelTier,
    messages: list[dict[str, Any]],
    tool_schemas: Any,
    bound_tools: dict[str, Any],
    max_tokens: int,
    tool_choice: str | dict[str, Any] = "auto",
) -> tuple[str, str, int, int]:
    """Legacy ``run_tool_calls`` multi-turn loop.

    A forced/``required`` *tool_choice* is applied only to the FIRST turn. On
    later turns the choice reverts to ``"auto"`` so the model can synthesize a
    final answer after seeing tool results — otherwise a forced choice would
    make every turn emit another tool call and never terminate.

    Returns ``(response, model_used, tokens_used, tool_call_count)``.
    """
    response = ""
    model_used = ""
    tokens_used = 0
    tool_call_count = 0

    for iteration in range(MAX_TOOL_ROUNDS + 1):
        turn_tool_choice = tool_choice if iteration == 0 else "auto"
        chat_response, model_used, turn_tokens = await complete_chat_with_fallback(
            client=client,
            tier=tier,
            messages=messages,
            max_tokens=max_tokens,
            tools=tool_schemas if bound_tools else None,
            tool_choice=turn_tool_choice,
        )
        tokens_used += turn_tokens

        response = str(chat_response.get("content", "") or "")
        tool_calls = chat_response.get("tool_calls") or []

        assistant_message: dict[str, Any] = {
            "role": "assistant",
            "content": response,
        }
        if tool_calls:
            assistant_message["tool_calls"] = tool_calls
        messages.append(assistant_message)

        if not tool_calls:
            break

        if iteration >= MAX_TOOL_ROUNDS:
            logger.warning(
                "Tool loop maxed out for agent '%s' after %s rounds.",
                agent_name,
                MAX_TOOL_ROUNDS,
            )
            break

        executed = await run_tool_calls(tool_calls, bound_tools, messages)
        tool_call_count += executed
        if executed == 0:
            break

    return response, model_used, tokens_used, tool_call_count


def _should_use_ek_tool_loop(bound_tools: dict[str, Any], tool_path: str | None) -> bool:
    """ADR-023 Phase 6b gate: is the EK react_loop the owner of this step?

    DEFAULT OFF — only ``True`` when ``AGENTIC_EK_PROVIDER`` is set AND the step
    did not opt out with ``tool_path: native`` AND the step has tools AND the
    optional ``executionkit`` package is installed. When this is ``False`` the
    legacy ``run_tool_calls`` loop runs byte-for-byte (so an EK-on deployment
    without ``executionkit`` degrades gracefully to native, not to placeholder).
    Single-owner: exactly one loop drives this step (never both mid-thread).
    """
    from ..settings import get_settings

    return (
        bool(bound_tools)
        and tool_path != "native"
        and get_settings().agentic_ek_provider
        and _executionkit_available()
    )


async def _execute_llm_step(
    ctx: ExecutionContext,
    *,
    agent_name: str,
    description: str,
    tier: ModelTier,
    expected_output_keys: list[str] | None,
    enabled_tools: list[str] | None,
    tool_path: str | None,
    persona_prompt: str | None,
    tool_choice: str | dict[str, Any] = "auto",
) -> dict[str, Any]:
    """Assemble the prompt, run the owning tool loop, and parse the output."""
    # Gather available context as step input
    all_vars = ctx.all_variables()

    # Build tool contracts (also validates + normalizes the tool choice).
    tool_schemas, bound_tools, normalized_tool_choice = build_tool_contracts(
        tier, enabled_tools, tool_choice
    )

    # Assemble the full prompt
    prompt = build_system_prompt(
        agent_name=agent_name,
        description=description,
        all_vars=all_vars,
        expected_output_keys=expected_output_keys,
        bound_tool_names=list(bound_tools.keys()),
        persona_prompt=persona_prompt,
    )

    # Try to get a model client from the service container
    try:
        from ..models.client import get_client

        client = get_client(auto_configure=True)
        max_tokens = _TIER_MAX_TOKENS.get(tier, 8192)
        messages: list[dict[str, Any]] = [{"role": "user", "content": prompt}]

        if _should_use_ek_tool_loop(bound_tools, tool_path):
            return await _run_ek_tool_loop(
                client=client,
                tier=tier,
                prompt=prompt,
                tool_schemas=tool_schemas,
                bound_tools=bound_tools,
                max_tokens=max_tokens,
                expected_output_keys=expected_output_keys,
            )

        response, model_used, tokens_used, tool_call_count = (
            await _run_native_tool_loop(
                client=client,
                agent_name=agent_name,
                tier=tier,
                messages=messages,
                tool_schemas=tool_schemas,
                bound_tools=bound_tools,
                max_tokens=max_tokens,
                tool_choice=normalized_tool_choice,
            )
        )
    except Exception as e:
        logger.warning(
            "LLM call failed for agent '%s' (tier %s): %s. "
            "Returning placeholder output.",
            agent_name,
            tier.name,
            e,
        )
        return _build_placeholder_output(
            agent_name, description, expected_output_keys, e
        )

    parsed = parse_sentinel_output(
        response, expected_output_keys
    ) or parse_llm_json_output(response, expected_output_keys)

    return _attach_step_meta(parsed, model_used, tokens_used, tool_call_count)


def _make_llm_step(
    agent_name: str,
    description: str,
    tier: ModelTier,
    expected_output_keys: list[str] | None = None,
    prompt_file_override: str | None = None,
    enabled_tools: list[str] | None = None,
    tool_path: str | None = None,
    tool_choice: str | dict[str, Any] = "auto",
) -> StepFunction:
    """Create an async step function that calls an LLM for its output.

    Prompt assembly (in order):
    1. Agent persona from ``prompts/<role>.md`` (or ``prompt_file_override``)
    2. Task description and available context
    3. Required artifact key list (if ``expected_output_keys`` provided)
    4. ``SENTINEL_OUTPUT_INSTRUCTIONS`` -- always appended so the output
       contract is enforced regardless of which persona prompt is loaded.

    Args:
        expected_output_keys: Keys that MUST appear as <<<ARTIFACT>>> blocks.
        prompt_file_override: Optional filename (relative to prompts/) to use
            instead of the role-based lookup.
        enabled_tools: Optional explicit tool allowlist. ``None`` means all
            tools available for the step's tier.
        tool_path: ADR-023 Phase 6b per-step tool-loop selector. ``"native"``
            keeps the bespoke ``run_tool_calls`` loop. Any other value (or
            ``None``) uses the DEFAULT path: when ``agentic_ek_provider`` is ON
            the step's tool loop is driven by EK ``react_loop``; when the flag
            is OFF the legacy ``run_tool_calls`` loop runs byte-for-byte.
            Single-owner: exactly one loop drives a given step.
        tool_choice: How the step selects among its tools. ``"auto"`` (default)
            lets the model decide; ``"any"``/``"required"`` forces *some* tool;
            a tool name or ``{"type": "tool", "name": ...}`` dict forces that
            specific tool. Honored on the native tool loop; validated against
            the resolved tool set by ``build_tool_contracts``.
    """
    persona_prompt = load_agent_system_prompt(agent_name, prompt_file_override)

    async def _llm_step(ctx: ExecutionContext) -> dict[str, Any]:
        _tracer = _get_tracer()
        _span_cm = (
            _tracer.start_as_current_span(f"agent.{agent_name}")
            if _tracer
            else contextlib.nullcontext()
        )
        with _span_cm:
            return await _execute_llm_step(
                ctx,
                agent_name=agent_name,
                description=description,
                tier=tier,
                expected_output_keys=expected_output_keys,
                enabled_tools=enabled_tools,
                tool_path=tool_path,
                tool_choice=tool_choice,
                persona_prompt=persona_prompt,
            )

    _llm_step.__qualname__ = f"llm_step[{agent_name}]"
    return _llm_step


# ---------------------------------------------------------------------------
# Resolver
# ---------------------------------------------------------------------------


def _infer_tier(agent_name: str) -> ModelTier:
    """Infer model tier from agent name convention: tier{N}_{role}."""
    if agent_name.startswith("tier0_"):
        return ModelTier.TIER_0
    elif agent_name.startswith("tier1_"):
        return ModelTier.TIER_1
    elif agent_name.startswith("tier2_"):
        return ModelTier.TIER_2
    elif agent_name.startswith("tier3_"):
        return ModelTier.TIER_3
    elif agent_name.startswith("tier4_"):
        return ModelTier.TIER_4
    elif agent_name.startswith("tier5_"):
        return ModelTier.TIER_5
    else:
        return ModelTier.TIER_2  # Default to balanced tier


def resolve_agent(step_def: StepDefinition) -> StepDefinition:
    """Resolve a step definition's agent metadata into an executable function.

    If `step_def.func` is already set, this is a no-op.
    Otherwise, looks up the agent name from metadata and either:
      - Uses a registered Tier-0 deterministic implementation, or
      - Generates an LLM-backed step function for higher tiers.

    The step's `tier` field is also updated based on the agent name.

    Returns the mutated StepDefinition (same object).
    """
    if step_def.func is not None:
        return step_def  # Already has a function

    agent_name = step_def.metadata.get("agent")
    if not agent_name:
        raise ValueError(
            f"Step '{step_def.name}' has no agent and no func -- "
            f"check YAML 'agent:' field or provide a 'func:' reference"
        )

    tier = _infer_tier(agent_name)
    step_def.tier = tier

    # Check tier-0 registry first
    if tier == ModelTier.TIER_0 and agent_name in TIER0_REGISTRY:
        step_def.func = TIER0_REGISTRY[agent_name]
        logger.debug(
            "Resolved step '%s' -> deterministic %s", step_def.name, agent_name
        )
    else:
        # Generate an LLM-backed step
        step_def.func = _make_llm_step(
            agent_name=agent_name,
            description=step_def.description,
            tier=tier,
            expected_output_keys=list(step_def.output_mapping.keys()) or None,
            prompt_file_override=step_def.metadata.get("prompt_file"),
            enabled_tools=step_def.metadata.get("tools"),
            tool_path=step_def.metadata.get("tool_path"),
            tool_choice=step_def.metadata.get("tool_choice", "auto"),
        )
        logger.debug(
            "Resolved step '%s' -> LLM agent %s (tier %s)",
            step_def.name,
            agent_name,
            tier.name,
        )

    return step_def


# ---------------------------------------------------------------------------
# Re-exports for backward compatibility
# ---------------------------------------------------------------------------
# Every name that was importable from this module before the split remains
# importable here.  The sub-modules are the authoritative definitions.
# The explicit imports at the top of this file make all names available
# as ``engine.agent_resolver.<name>`` without any further action needed.
