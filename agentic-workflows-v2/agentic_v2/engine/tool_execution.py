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

import json
import logging
from typing import Any

from ..models.router import ModelTier

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


def build_tool_contracts(
    tier: ModelTier,
    requested_tools: list[str] | None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Return OpenAI-compatible tool schemas and bound tool instances.

    Args:
        tier: The model tier for this step — tools with a higher tier are
            excluded unless explicitly requested.
        requested_tools: Explicit allowlist of tool names, or ``None`` to
            include all tools whose tier does not exceed *tier*.

    Returns:
        A ``(tool_schemas, bound_tools)`` tuple where *tool_schemas* is a list
        of OpenAI function-calling schema dicts and *bound_tools* maps each
        tool name to its registry instance.
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

    return tool_schemas, bound_tools


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
        call_id = (
            f"tool-{abs(hash((name, json.dumps(args, sort_keys=True, default=str)))):x}"
        )

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
) -> tuple[dict[str, Any], str, int]:
    """Call backend.complete_chat with router-based model fallback.

    Iterates through available models for *tier* (up to 6 attempts), recording
    successes, rate-limits, timeouts, and permanent failures on the router so
    that subsequent calls benefit from learned health state.

    Returns:
        A ``(response_dict, model_name, tokens_used)`` triple.

    Raises:
        RuntimeError: When all candidate models are exhausted or no backend is
            configured.
    """
    return await client.complete_chat(
        messages=messages,
        tier=tier,
        max_retries=6,
        tools=tools,
        max_tokens=max_tokens,
    )


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
        if tool is None:
            tool_result_text = json.dumps(
                {"success": False, "error": f"Unknown tool: {tool_name}"}
            )
        else:
            is_valid, validation_error = tool.validate_parameters(**tool_args)
            if not is_valid:
                tool_result_text = json.dumps(
                    {
                        "success": False,
                        "error": (
                            f"Invalid parameters for {tool_name}: {validation_error}"
                        ),
                    }
                )
            else:
                try:
                    tool_result = await tool.execute(**tool_args)
                    tool_result_text = serialize_tool_result(tool_result)
                except Exception as exc:
                    tool_result_text = json.dumps(
                        {
                            "success": False,
                            "error": f"Tool execution error for {tool_name}: {exc}",
                        }
                    )

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


# Backward-compatibility alias
_run_tool_calls = run_tool_calls
