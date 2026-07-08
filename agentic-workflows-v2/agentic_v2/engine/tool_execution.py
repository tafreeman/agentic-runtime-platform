"""Tool execution — tool contract resolution, call normalization, and the tool loop.

Provides the full machinery for multi-turn tool-use inside LLM step functions:

1. :func:`parameter_spec_to_json_schema` — convert internal tool parameter
   specs to OpenAI-compatible JSON schema objects.
2. :func:`build_tool_contracts` — resolve the registry into OpenAI-format
   schemas and a bound ``{name: tool}`` dict for a given tier and allowlist.
3. :func:`extract_usage_tokens` — best-effort total-token extraction across
   provider response shapes.
4. :func:`messages_to_text` — flatten chat message lists for token estimation.
5. :func:`parse_tool_args` / :func:`normalize_tool_call` — normalize
   provider-specific tool-call shapes into ``(call_id, name, args)`` tuples.
6. :func:`truncate_tool_result` / :func:`serialize_tool_result` — bound and
   serialize tool results before appending them to the message thread.
7. :func:`complete_chat_with_fallback` — LLM chat completion with router-based
   model fallback and budget tracking.
8. :func:`run_tool_calls` — execute one round of tool calls and append results
   to the running message list.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import logging
from functools import lru_cache
from typing import Any

from ..models.router import ModelTier


@lru_cache(maxsize=1)
def _executionkit_available() -> bool:
    """Whether the optional ``executionkit`` package is importable.

    Both EK seams (this module's ``complete_chat_with_fallback`` and the engine's
    ``_run_ek_tool_loop``) import ``executionkit`` only inside the EK branch, so
    when the package is absent the branch must be skipped in favour of the native
    path rather than raising ``ImportError`` into the placeholder fallback.
    ``executionkit`` is an OPTIONAL install (coverage ``omit`` list; not present
    in the no-extras CI test env), so ``AGENTIC_EK_PROVIDER`` being on does not
    guarantee it is importable. An EK-on deployment without it degrades to the
    fully functional native loop instead of emitting placeholder output.
    """
    return importlib.util.find_spec("executionkit") is not None


logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Tool loop limits
# ---------------------------------------------------------------------------

MAX_TOOL_ROUNDS = 8
MAX_TOOL_CALLS_PER_ROUND = 12
MAX_TOOL_RESULT_CHARS = 12000

# Backward-compatibility aliases
_MAX_TOOL_ROUNDS = MAX_TOOL_ROUNDS
_MAX_TOOL_CALLS_PER_ROUND = MAX_TOOL_CALLS_PER_ROUND
_MAX_TOOL_RESULT_CHARS = MAX_TOOL_RESULT_CHARS


def _classify_router_error(router: Any, model: str, exc: Exception) -> None:
    """Record model-call failures using SmartModelRouter classification when present."""
    classifier = getattr(router, "_classify_and_record_error", None)
    if callable(classifier):
        classifier(model, exc)
        return

    error_str = str(exc).lower()
    if "rate limit" in error_str or "429" in error_str:
        router.record_rate_limit(model)
    elif "timeout" in error_str:
        router.record_timeout(model)
    elif "not found" in error_str or "no access" in error_str:
        router.record_failure(model, "permanent", is_permanent=True)
    else:
        router.record_failure(model, type(exc).__name__)


# ---------------------------------------------------------------------------
# Tool contract resolution
# ---------------------------------------------------------------------------


def parameter_spec_to_json_schema(spec: Any) -> dict[str, Any]:
    """Convert internal tool parameter spec to JSON schema object."""
    if not isinstance(spec, dict):
        return {"type": "string"}

    normalized: dict[str, Any] = {}
    for key, value in spec.items():
        if key == "required":
            continue
        normalized[key] = value

    normalized.setdefault("type", "string")
    return normalized


def normalize_tool_choice(
    tool_choice: str | dict[str, Any] | None,
    available_tool_names: set[str] | None = None,
) -> str | dict[str, Any]:
    """Validate and normalize a ``tool_choice`` into the OpenAI wire shape.

    Accepts:
        - ``None`` or ``"auto"`` → ``"auto"`` (model decides).
        - ``"any"`` / ``"required"`` → ``"required"`` (model must call a tool).
        - ``"none"`` → ``"none"`` (model may not call a tool).
        - A tool name string → forced ``{"type": "function", "function":
          {"name": <name>}}``.
        - A dict in either OpenAI (``{"type": "function", ...}``) or Anthropic
          (``{"type": "tool", "name": ...}``) shape → normalized to OpenAI.

    Args:
        tool_choice: The requested choice (see accepted forms above).
        available_tool_names: When provided, a forced tool name not in this set
            raises ``ValueError`` (fail-fast on a typo'd tool name).

    Returns:
        The normalized choice. ``"auto"`` / ``"required"`` / ``"none"`` are
        returned as bare strings; a forced tool is an OpenAI ``tool_choice`` dict.
    """
    if tool_choice is None:
        return "auto"

    if isinstance(tool_choice, str):
        lowered = tool_choice.strip().lower()
        if lowered in ("auto", ""):
            return "auto"
        if lowered in ("any", "required"):
            return "required"
        if lowered == "none":
            return "none"
        # Treat any other string as a forced tool name.
        forced_name = tool_choice.strip()
        _validate_forced_tool(forced_name, available_tool_names)
        return {"type": "function", "function": {"name": forced_name}}

    if isinstance(tool_choice, dict):
        # OpenAI shape: {"type": "function", "function": {"name": ...}}
        func = tool_choice.get("function")
        if isinstance(func, dict) and func.get("name"):
            _validate_forced_tool(str(func["name"]), available_tool_names)
            return {"type": "function", "function": {"name": str(func["name"])}}
        # Anthropic shape: {"type": "tool", "name": ...}
        name = tool_choice.get("name")
        if tool_choice.get("type") == "tool" and name:
            _validate_forced_tool(str(name), available_tool_names)
            return {"type": "function", "function": {"name": str(name)}}
        # Bare-mode dicts ({"type": "auto"|"any"|"none"}) → normalize via type.
        type_value = str(tool_choice.get("type", "auto")).lower()
        return normalize_tool_choice(type_value, available_tool_names)

    raise ValueError(f"Unsupported tool_choice: {tool_choice!r}")


def _validate_forced_tool(name: str, available_tool_names: set[str] | None) -> None:
    """Raise ``ValueError`` if *name* is forced but not in the available set."""
    if available_tool_names is not None and name not in available_tool_names:
        raise ValueError(
            f"Forced tool_choice '{name}' is not in the available tool set "
            f"{sorted(available_tool_names)}"
        )


def _is_forced_tool_choice(tool_choice: str | dict[str, Any] | None) -> bool:
    """Return True when *tool_choice* genuinely forces a tool call.

    Forced means the model is compelled to call (some or a specific) tool:
        - the strings ``"required"`` / ``"any"`` (model MUST call a tool), or
        - a dict naming a specific tool (OpenAI ``{"type": "function", ...}`` or
          Anthropic ``{"type": "tool", "name": ...}``), including a bare
          ``{"type": "any"|"required"}``.

    NOT forced (model still decides whether/which tool, or no tool at all):
        - ``None`` / ``"auto"`` / ``""`` (model-decided), and
        - ``"none"`` (model may NOT call a tool — a constraint, but not a forced
          tool selection the EK path must honor).
    """
    if tool_choice is None:
        return False
    if isinstance(tool_choice, str):
        return tool_choice.strip().lower() in ("required", "any")
    if isinstance(tool_choice, dict):
        # A dict that names a tool, or a bare-mode dict requiring a call.
        func = tool_choice.get("function")
        if isinstance(func, dict) and func.get("name"):
            return True
        if tool_choice.get("type") == "tool" and tool_choice.get("name"):
            return True
        return str(tool_choice.get("type", "")).lower() in ("required", "any")
    return False


def build_tool_contracts(
    tier: ModelTier,
    requested_tools: list[str] | None,
    tool_choice: str | dict[str, Any] | None = "auto",
) -> tuple[list[dict[str, Any]], dict[str, Any], str | dict[str, Any]]:
    """Return OpenAI-compatible tool schemas, bound tools, and a tool choice.

    Args:
        tier: The model tier for this step — tools with a higher tier are
            excluded unless explicitly requested.
        requested_tools: Explicit allowlist of tool names, or ``None`` to
            include all tools whose tier does not exceed *tier*.
        tool_choice: How the model should select among the contracts. Defaults
            to ``"auto"``. ``"any"``/``"required"`` forces *some* tool; a tool
            name (or forced dict) forces that specific tool. Validated against
            the resolved tool set — forcing a tool that was not selected raises
            ``ValueError``.

    Returns:
        A ``(tool_schemas, bound_tools, normalized_tool_choice)`` triple.
        *tool_schemas* is a list of OpenAI function-calling schema dicts,
        *bound_tools* maps each tool name to its registry instance, and
        *normalized_tool_choice* is the validated choice ready to pass to a
        backend ``complete_chat``.
    """
    from ..tools import get_registry

    registry = get_registry()
    available = {tool.name: tool for tool in registry.list_tools()}

    selected: list[Any] = []
    if requested_tools is None:
        selected = [tool for tool in available.values() if tool.tier <= tier.value]
    else:
        for tool_name in requested_tools:
            tool = available.get(tool_name)
            if tool is None:
                logger.warning("Unknown tool '%s' requested; skipping.", tool_name)
                continue
            if tool.tier > tier.value:
                logger.warning(
                    "Tool '%s' (tier %s) exceeds step tier %s; skipping.",
                    tool_name,
                    tool.tier,
                    tier.value,
                )
                continue
            selected.append(tool)

    selected.sort(key=lambda t: t.name)

    tool_schemas: list[dict[str, Any]] = []
    bound_tools: dict[str, Any] = {}
    for tool in selected:
        schema = tool.get_schema()
        params = schema.parameters if schema else {}
        required_fields = [
            name
            for name, spec in params.items()
            if isinstance(spec, dict) and bool(spec.get("required"))
        ]

        tool_schemas.append(
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": {
                        "type": "object",
                        "properties": {
                            name: parameter_spec_to_json_schema(spec)
                            for name, spec in params.items()
                        },
                        "required": required_fields,
                    },
                },
            }
        )
        bound_tools[tool.name] = tool

    normalized_choice = normalize_tool_choice(tool_choice, set(bound_tools.keys()))
    return tool_schemas, bound_tools, normalized_choice


# Backward-compatibility aliases
_build_tool_contracts = build_tool_contracts


# ---------------------------------------------------------------------------
# Token and message utilities
# ---------------------------------------------------------------------------


def extract_usage_tokens(usage: Any) -> int:
    """Best-effort extraction of total token usage across providers."""
    if not isinstance(usage, dict):
        return 0

    direct_keys = ("total_tokens", "totalTokenCount", "total")
    for key in direct_keys:
        value = usage.get(key)
        if isinstance(value, (int, float)):
            return max(0, int(value))

    prompt = usage.get("prompt_tokens", usage.get("input_tokens"))
    completion = usage.get("completion_tokens", usage.get("output_tokens"))
    if isinstance(prompt, (int, float)) and isinstance(completion, (int, float)):
        return max(0, int(prompt) + int(completion))

    return 0


# Backward-compatibility alias
_extract_usage_tokens = extract_usage_tokens


def messages_to_text(messages: list[dict[str, Any]]) -> str:
    """Flatten chat messages for fallback token estimation."""
    parts: list[str] = []
    for msg in messages:
        role = str(msg.get("role", ""))
        content = msg.get("content", "")
        if isinstance(content, str):
            parts.append(f"{role}:{content}")
        else:
            parts.append(f"{role}:{json.dumps(content, default=str)}")
    return "\n".join(parts)


# Backward-compatibility alias
_messages_to_text = messages_to_text


# ---------------------------------------------------------------------------
# Tool call normalization
# ---------------------------------------------------------------------------


def parse_tool_args(raw_args: Any) -> dict[str, Any]:
    """Normalize tool-call arguments into a dict."""
    if isinstance(raw_args, dict):
        return raw_args

    if isinstance(raw_args, str):
        stripped = raw_args.strip()
        if not stripped:
            return {}
        try:
            parsed = json.loads(stripped)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}

    return {}


# Backward-compatibility alias
_parse_tool_args = parse_tool_args


def call_id_for(tool_name: str, tool_args: dict[str, Any]) -> str:
    """Deterministic, process-stable call id for a tool call.

    Used as the fallback identifier when a provider omits a tool-call ``id``.
    Derived with :mod:`hashlib` (not the builtin ``hash``) so the value is
    stable across processes regardless of ``PYTHONHASHSEED``.
    """
    material = f"{tool_name}\x00{json.dumps(tool_args, sort_keys=True, default=str)}"
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]
    return f"tool-{digest}"


# Backward-compatibility / internal alias (kept for existing imports).
_call_id_for = call_id_for


def normalize_tool_call(call: dict[str, Any]) -> tuple[str, str, dict[str, Any]]:
    """Normalize provider-specific tool call shape.

    Supports both OpenAI-style ``{"function": {"name": ..., "arguments": ...}}``
    and Anthropic-style ``{"type": "tool_use", "name": ..., "input": {...}}``
    blocks.

    Returns:
        A ``(call_id, tool_name, tool_args)`` triple.
    """
    fn = call.get("function")
    if isinstance(fn, dict):
        name = str(fn.get("name", "")).strip()
        args = parse_tool_args(fn.get("arguments"))
        call_id = str(call.get("id", "")).strip()
    else:
        # Anthropic-style blocks: {"type":"tool_use","name":"...","input":{...}}
        name = str(call.get("name", "")).strip()
        args = parse_tool_args(call.get("input"))
        call_id = str(call.get("id", "")).strip()

    if not call_id:
        call_id = call_id_for(name, args)

    return call_id, name, args


# Backward-compatibility alias
_normalize_tool_call = normalize_tool_call


# ---------------------------------------------------------------------------
# Tool result serialization
# ---------------------------------------------------------------------------


def truncate_tool_result(text: str) -> str:
    """Bound tool payload size to avoid runaway context growth."""
    if len(text) <= MAX_TOOL_RESULT_CHARS:
        return text
    return text[:MAX_TOOL_RESULT_CHARS] + "\n[truncated]"


# Backward-compatibility alias
_truncate_tool_result = truncate_tool_result


def serialize_tool_result(tool_result: Any) -> str:
    """Serialize a ToolResult-like object as compact JSON."""
    payload = {
        "success": bool(getattr(tool_result, "success", False)),
        "data": getattr(tool_result, "data", None),
        "error": getattr(tool_result, "error", None),
        "metadata": getattr(tool_result, "metadata", {}),
        "execution_time_ms": getattr(tool_result, "execution_time_ms", 0.0),
        "tool_name": getattr(tool_result, "tool_name", ""),
    }
    return truncate_tool_result(json.dumps(payload, default=str))


# Backward-compatibility alias
_serialize_tool_result = serialize_tool_result


# ---------------------------------------------------------------------------
# LLM chat completion with fallback
# ---------------------------------------------------------------------------


async def complete_chat_with_fallback(
    client: Any,
    tier: ModelTier,
    messages: list[dict[str, Any]],
    max_tokens: int,
    tools: list[dict[str, Any]] | None,
    tool_choice: str | dict[str, Any] = "auto",
) -> tuple[dict[str, Any], str, int]:
    """Call backend.complete_chat with router-based model fallback.

    Iterates through available models for *tier* (up to 6 attempts), recording
    successes, rate-limits, timeouts, and permanent failures on the router so
    that subsequent calls benefit from learned health state.

    Args:
        client: The model client exposing ``complete_chat`` and a ``router``.
        tier: Model tier to route within.
        messages: The running chat thread.
        max_tokens: Per-turn completion ceiling.
        tools: OpenAI-format tool schemas, or ``None`` to disable tool use.
        tool_choice: Normalized tool choice (``"auto"`` / ``"required"`` /
            ``"none"`` / a forced ``{"type": "function", ...}`` dict). Forwarded
            to ``backend.complete_chat`` only when *tools* is provided; ignored
            otherwise. Defaults to ``"auto"`` so existing callers are unaffected.

    Returns:
        A ``(response_dict, model_name, tokens_used)`` triple.

    Raises:
        RuntimeError: When all candidate models are exhausted or no backend is
            configured.
    """
    if client.backend is None:
        raise RuntimeError("No LLM backend configured")

    # ADR-023 Phase 6a: flag-gated EK delegation of the inner completion turn.
    # DEFAULT OFF — when AGENTIC_EK_PROVIDER is unset/false the call delegates to
    # ``client.complete_chat`` (router-based fallback + budget tracking) exactly
    # as before. When on, the plain-completion turn is routed through EK
    # ``_TrackedProvider`` / ``checked_complete`` over a ``SmartRouterProvider``
    # (budget-checked, retry-wrapped, truncation-tracked), with the runtime
    # ``TokenBudget`` token-sum ceiling enforced FIRST. The
    # ``(response_dict, model, tokens)`` contract is preserved so the caller's
    # downstream parsing and ReviewStatus.normalize (DAG layer) are unchanged.
    from ..settings import get_settings

    if get_settings().agentic_ek_provider:
        # The EK provider stack does not thread a tool_choice; a genuinely
        # FORCED choice cannot be honored on this opt-in path. Silently
        # downgrading it to model-decided would let a step that REQUIRES a tool
        # quietly skip it, so raise instead. This is a FLAG-level policy: with
        # AGENTIC_EK_PROVIDER on, a forced choice is rejected regardless of
        # whether the optional ``executionkit`` package is installed, so the
        # failure mode does not silently depend on the deploy's extras. A plain
        # 'auto'/None (and 'none', which forces *no* tool) passes through.
        if tools and _is_forced_tool_choice(tool_choice):
            raise NotImplementedError(
                f"tool_choice={tool_choice!r} forces tool selection, but the EK "
                "completion path (AGENTIC_EK_PROVIDER) does not thread tool_choice "
                "and cannot honor a forced choice. Unset AGENTIC_EK_PROVIDER for "
                "steps that force a tool, or use the default completion path."
            )

    if get_settings().agentic_ek_provider and _executionkit_available():
        # Only take the EK execution path when the optional package is actually
        # importable; otherwise fall through to the native loop below (fully
        # functional without executionkit) rather than raising ImportError into
        # the caller's placeholder fallback.
        from executionkit.cost import CostTracker

        from .ek_step_delegation import complete_turn_via_ek

        return await complete_turn_via_ek(
            router=client.router,
            backend=client.backend,
            tier=tier,
            messages=messages,
            max_tokens=max_tokens,
            tools=tools,
            budget=getattr(client, "budget", None),
            tracker=CostTracker(),
            metadata={},
        )

    # Only forward tool_choice when there are tools to choose among; otherwise
    # leave it off so providers that reject a tool_choice without tools are not
    # tripped.
    extra: dict[str, Any] = {"tool_choice": tool_choice} if tools else {}
    result: tuple[dict[str, Any], str, int] = await client.complete_chat(
        messages=messages,
        tier=tier,
        max_retries=6,
        tools=tools,
        max_tokens=max_tokens,
        **extra,
    )
    return result


# Backward-compatibility alias
_complete_chat_with_fallback = complete_chat_with_fallback


# ---------------------------------------------------------------------------
# Tool execution loop
# ---------------------------------------------------------------------------


async def run_tool_calls(
    tool_calls: list[dict[str, Any]],
    bound_tools: dict[str, Any],
    messages: list[dict[str, Any]],
) -> int:
    """Execute one round of tool calls and append results to *messages*.

    Processes up to :data:`MAX_TOOL_CALLS_PER_ROUND` calls.  Each call result
    is serialized and truncated before being appended as a ``"tool"`` role
    message so the LLM receives feedback in the next turn.

    Args:
        tool_calls: Raw tool-call dicts from the assistant message.
        bound_tools: Registry of callable tool instances keyed by name.
        messages: Running chat message list — mutated in-place with tool results.

    Returns:
        The number of tool calls that were successfully dispatched (including
        those that raised errors — the error is reported back to the LLM rather
        than propagating up).
    """
    executed = 0
    for call in tool_calls[:MAX_TOOL_CALLS_PER_ROUND]:
        if not isinstance(call, dict):
            continue
        call_id, tool_name, tool_args = normalize_tool_call(call)
        if not tool_name:
            continue

        tool = bound_tools.get(tool_name)
        tool_result_text = await _dispatch_single_tool_call(tool, tool_name, tool_args)

        messages.append(
            {
                "role": "tool",
                "tool_call_id": call_id,
                "name": tool_name,
                "content": truncate_tool_result(tool_result_text),
            }
        )
        executed += 1

    return executed


async def _dispatch_single_tool_call(
    tool: Any,
    tool_name: str,
    tool_args: dict[str, Any],
) -> str:
    """Validate and execute one tool call, returning its serialized result text.

    Errors (unknown tool, invalid params, execution failure) are returned as a
    serialized ``{"success": False, "error": ...}`` payload rather than raised,
    so the LLM receives feedback in the next turn.

    The human-approval gate is enforced structurally inside
    ``BaseTool.execute`` (ADR-047): a denied or fail-closed call returns an
    error ``ToolResult`` carrying the decision in ``metadata`` and the tool body
    never runs. This path therefore no longer pre-gates — it validates and
    executes, and ``serialize_tool_result`` surfaces any denial payload.
    """
    if tool is None:
        return json.dumps({"success": False, "error": f"Unknown tool: {tool_name}"})

    is_valid, validation_error = tool.validate_parameters(**tool_args)
    if not is_valid:
        return json.dumps(
            {
                "success": False,
                "error": (f"Invalid parameters for {tool_name}: {validation_error}"),
            }
        )

    try:
        tool_result = await tool.execute(**tool_args)
        return serialize_tool_result(tool_result)
    except Exception as exc:
        # ``asyncio.CancelledError`` and ``KeyboardInterrupt`` derive from
        # ``BaseException`` (not ``Exception``), so they already propagate
        # through this handler untouched — cancellation and interrupt signals
        # are never swallowed here. Log the traceback before serializing so a
        # real tool failure is diagnosable from logs instead of only the
        # truncated str(exc) sent back to the LLM.
        logger.exception("Tool execution error for %s", tool_name)
        return json.dumps(
            {
                "success": False,
                "error": f"Tool execution error for {tool_name}: {exc}",
            }
        )


# Backward-compatibility alias
_run_tool_calls = run_tool_calls
