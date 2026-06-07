"""LangGraph ReAct agent for repository analysis.

Builds a single-node ReAct agent backed by the project's LangChain model
registry. The agent uses repo-specific tools plus file/search tools from the
shared toolkit to produce a structured ``RepoReport``.

Quick start::

    import asyncio
    from tools.agents.repo_analyzer import run_analysis

    report = asyncio.run(run_analysis("/path/to/repo"))
    print(report.summary)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Annotated, Any

from langchain_core.messages import HumanMessage
from typing_extensions import TypedDict

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy imports — langgraph/langchain are optional extras
# ---------------------------------------------------------------------------

try:
    from langgraph.graph import END, START, MessagesState, StateGraph
    from langgraph.prebuilt import create_react_agent

    _LANGGRAPH_AVAILABLE = True
except ImportError:
    _LANGGRAPH_AVAILABLE = False


# ---------------------------------------------------------------------------
# Output types
# ---------------------------------------------------------------------------


@dataclass
class PackageInfo:
    """Summary of a single package within the monorepo."""

    name: str
    path: str
    description: str
    build_backend: str
    total_lines: int = 0
    code_lines: int = 0
    test_count: int = 0
    has_conftest: bool = False
    patterns: dict[str, int] = field(default_factory=dict)


@dataclass
class RepoReport:
    """Structured output from a completed repository analysis."""

    root: str
    branch: str
    last_tag: str
    packages: list[PackageInfo]
    top_contributors: list[dict[str, Any]]
    recent_commits: list[dict[str, Any]]
    agent_summary: str
    raw_messages: list[Any] = field(default_factory=list)


# ---------------------------------------------------------------------------
# LangGraph state
# ---------------------------------------------------------------------------


class RepoAnalysisState(TypedDict):
    """State flowing through the repo analysis graph."""

    messages: Annotated[list, "append-only message history"]
    repo_root: str
    report: dict[str, Any]  # intermediate structured findings


# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are a senior software architect performing a comprehensive analysis of a \
monorepo. Your goal is to produce a clear, actionable report covering:

1. **Package inventory** — names, paths, descriptions, build backends
2. **Code volume** — lines of code per package (Python + TypeScript)
3. **Test coverage posture** — number of test files, conftest presence, \
   coverage config
4. **Architectural patterns** — async usage, protocols, dataclasses, Pydantic, \
   LangChain/LangGraph, FastAPI, TypedDicts
5. **Git health** — recent commit velocity, top contributors, last release tag
6. **Key observations** — strengths, gaps, and 3-5 actionable recommendations

Use the available tools to gather data. Call `discover_packages` first, then \
analyze each package in turn. Finish with a concise Markdown report.

Be factual and grounded in what the tools return. Do not invent metrics."""


# ---------------------------------------------------------------------------
# Agent factory
# ---------------------------------------------------------------------------

DEFAULT_MODEL_TIER = 4


def build_agent(model_id: str | None = None) -> Any:
    """Build and return the compiled LangGraph repo analysis agent.

    Args:
        model_id: Provider-prefixed model identifier such as
            ``openai:gpt-4o`` or ``anthropic:claude-sonnet-4-6-20260219``.
            When omitted, the project tier-4 fallback chain is used.

    Returns:
        Compiled LangGraph ``CompiledGraph``.

    Raises:
        ImportError: If ``langgraph`` or the selected provider integration is not
            installed.
        ValueError: If the selected provider or model cannot be resolved.
    """
    if not _LANGGRAPH_AVAILABLE:
        raise ImportError(
            "langgraph is required. Install with: pip install langgraph"
        )

    # Combine repo-specific tools with shared file/search tools
    from agentic_v2.langchain.models import get_chat_model, get_model_for_tier
    from agentic_v2.langchain.tools import (
        code_analyze,
        file_list,
        file_read,
        search_files,
    )

    from .tools import REPO_TOOLS

    all_tools = [*REPO_TOOLS, file_read, file_list, code_analyze, search_files]
    resolved_model_id = _normalize_model_id(model_id)
    llm = (
        get_chat_model(resolved_model_id, temperature=0.0)
        if resolved_model_id
        else get_model_for_tier(DEFAULT_MODEL_TIER)
    )

    return create_react_agent(
        llm,
        tools=all_tools,
        prompt=_SYSTEM_PROMPT,
    )


def _normalize_model_id(model_id: str | None) -> str | None:
    """Normalize legacy repo-analyzer model IDs before provider dispatch."""
    if model_id is None:
        return None

    stripped = model_id.strip()
    if not stripped:
        return None
    if stripped.startswith("claude-"):
        return f"anthropic:{stripped}"
    return stripped


# ---------------------------------------------------------------------------
# Public async entry point
# ---------------------------------------------------------------------------


async def run_analysis(
    repo_root: str | Path,
    model_id: str | None = None,
) -> RepoReport:
    """Analyze a repository and return a structured ``RepoReport``.

    Args:
        repo_root: Absolute path to the repository root.
        model_id: Optional provider-prefixed model to use as the reasoning engine.
            When omitted, the project tier-4 fallback chain is used.

    Returns:
        ``RepoReport`` populated from the agent's tool calls and final summary.
    """
    root = str(Path(repo_root).resolve())
    agent = build_agent(model_id=model_id)

    user_message = (
        f"Please analyze the repository located at: {root}\n\n"
        "Start by discovering all packages, then gather code metrics, test "
        "coverage indicators, architectural patterns, and git statistics for "
        "each package. Finish with a structured Markdown report."
    )

    logger.info("Starting repo analysis: root=%s model=%s", root, model_id)

    result = await agent.ainvoke(
        {"messages": [HumanMessage(content=user_message)]},
        config={"recursion_limit": 50},
    )

    messages = result.get("messages", [])
    final_text = _extract_last_ai_text(messages)

    # Best-effort: re-run tool results to populate structured report fields
    report = _build_structured_report(root, messages, final_text)
    return report


# ---------------------------------------------------------------------------
# Streaming variant
# ---------------------------------------------------------------------------


async def stream_analysis(
    repo_root: str | Path,
    model_id: str | None = None,
):
    """Stream agent events for a repository analysis.

    Yields ``(event_type, data)`` tuples where ``event_type`` is one of
    ``"token"``, ``"tool_call"``, ``"tool_result"``, or ``"done"``.

    Args:
        repo_root: Absolute path to the repository root.
        model_id: Optional provider-prefixed model to use.
    """
    root = str(Path(repo_root).resolve())
    agent = build_agent(model_id=model_id)

    user_message = (
        f"Please analyze the repository located at: {root}\n\n"
        "Discover all packages, then gather code metrics, test coverage "
        "indicators, architectural patterns, and git statistics. "
        "Finish with a structured Markdown report."
    )

    async for event in agent.astream_events(
        {"messages": [HumanMessage(content=user_message)]},
        version="v2",
        config={"recursion_limit": 50},
    ):
        kind = event.get("event", "")
        if kind == "on_chat_model_stream":
            chunk = event["data"].get("chunk")
            if chunk and hasattr(chunk, "content") and chunk.content:
                yield "token", chunk.content
        elif kind == "on_tool_start":
            yield "tool_call", {
                "name": event.get("name"),
                "input": event["data"].get("input"),
            }
        elif kind == "on_tool_end":
            yield "tool_result", {
                "name": event.get("name"),
                "output": event["data"].get("output"),
            }

    yield "done", None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_last_ai_text(messages: list[Any]) -> str:
    """Return the content of the last AI message as a string."""
    for msg in reversed(messages):
        content = getattr(msg, "content", None)
        if content is None:
            continue
        if isinstance(content, str) and content.strip():
            return content
        if isinstance(content, list):
            parts = [
                p["text"] for p in content if isinstance(p, dict) and "text" in p
            ]
            combined = " ".join(parts).strip()
            if combined:
                return combined
    return ""


def _add_discovered_packages(data: Any, packages: list[PackageInfo]) -> None:
    """Append ``discover_packages`` tool results to *packages*."""
    if not isinstance(data, list):
        return
    for pkg in data:
        packages.append(
            PackageInfo(
                name=pkg.get("name", ""),
                path=pkg.get("path", ""),
                description=pkg.get("description", ""),
                build_backend=pkg.get("build_backend", ""),
            )
        )


def _apply_package_tool_result(
    tool_name: str,
    data: dict[str, Any],
    root: str,
    msg: Any,
    tool_call_args: dict[str, dict[str, Any]],
    packages: list[PackageInfo],
) -> None:
    """Apply a package-scoped tool result onto its matching ``PackageInfo``."""
    pkg = _package_from_tool_result(root, msg, tool_call_args, packages)
    if pkg is None:
        return

    if tool_name == "count_lines_of_code":
        total = data.get("total", {})
        pkg.total_lines = total.get("lines", 0)
        pkg.code_lines = total.get("code", 0)
    elif tool_name == "list_test_files":
        pkg.test_count = data.get("test_count", 0)
        pkg.has_conftest = data.get("has_conftest", False)
    elif tool_name == "find_key_patterns":
        pkg.patterns = data


def _parse_tool_message(msg: Any) -> tuple[str, Any] | None:
    """Return ``(tool_name, parsed_json)`` for a tool message, or ``None``."""
    import json

    if getattr(msg, "type", None) != "tool":
        return None
    raw = getattr(msg, "content", "")
    if not isinstance(raw, str):
        return None
    try:
        return getattr(msg, "name", ""), json.loads(raw)
    except json.JSONDecodeError:
        return None


_PACKAGE_SCOPED_TOOLS = frozenset(
    {"count_lines_of_code", "list_test_files", "find_key_patterns"}
)


def _build_structured_report(
    root: str,
    messages: list[Any],
    agent_summary: str,
) -> RepoReport:
    """Build a ``RepoReport`` by replaying tool outputs from the message history."""
    packages: list[PackageInfo] = []
    tool_call_args = _tool_call_args_by_id(messages)
    git_info: dict[str, Any] = {}

    # Extract tool results from message history
    for msg in messages:
        parsed = _parse_tool_message(msg)
        if parsed is None:
            continue
        tool_name, data = parsed

        if tool_name == "discover_packages":
            _add_discovered_packages(data, packages)
        elif tool_name == "get_git_stats" and isinstance(data, dict):
            git_info = data
        elif tool_name in _PACKAGE_SCOPED_TOOLS and isinstance(data, dict):
            _apply_package_tool_result(
                tool_name, data, root, msg, tool_call_args, packages
            )

    return RepoReport(
        root=root,
        branch=git_info.get("branch", "unknown"),
        last_tag=git_info.get("last_tag", "unknown"),
        packages=packages,
        top_contributors=git_info.get("contributors", [])[:5],
        recent_commits=git_info.get("recent_commits", [])[:10],
        agent_summary=agent_summary,
        raw_messages=messages,
    )


def _collect_native_tool_calls(
    msg: Any, calls: dict[str, dict[str, Any]]
) -> None:
    """Collect LangChain-native ``tool_calls`` from *msg* into *calls*."""
    for call in getattr(msg, "tool_calls", []) or []:
        if not isinstance(call, dict):
            continue
        call_id = call.get("id")
        args = call.get("args", {})
        if isinstance(call_id, str):
            calls[call_id] = _coerce_tool_args(args)


def _collect_openai_tool_calls(
    msg: Any, calls: dict[str, dict[str, Any]]
) -> None:
    """Collect OpenAI-style ``additional_kwargs`` tool calls from *msg*."""
    import json

    additional_kwargs = getattr(msg, "additional_kwargs", {}) or {}
    for call in additional_kwargs.get("tool_calls", []) or []:
        if not isinstance(call, dict):
            continue
        call_id = call.get("id")
        function = call.get("function", {})
        if not isinstance(call_id, str) or not isinstance(function, dict):
            continue
        args = function.get("arguments", {})
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                args = {}
        calls[call_id] = _coerce_tool_args(args)


def _tool_call_args_by_id(messages: list[Any]) -> dict[str, dict[str, Any]]:
    """Return normalized tool-call arguments keyed by tool call id."""
    calls: dict[str, dict[str, Any]] = {}
    for msg in messages:
        _collect_native_tool_calls(msg, calls)
        _collect_openai_tool_calls(msg, calls)
    return calls


def _coerce_tool_args(args: Any) -> dict[str, Any]:
    """Normalize tool-call args into a dict."""
    import json

    if isinstance(args, dict):
        return args
    if isinstance(args, str):
        try:
            parsed = json.loads(args)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _package_from_tool_result(
    root: str,
    tool_message: Any,
    tool_call_args: dict[str, dict[str, Any]],
    packages: list[PackageInfo],
) -> PackageInfo | None:
    """Find the package associated with a package-scoped tool result."""
    if not packages:
        return None

    tool_call_id = getattr(tool_message, "tool_call_id", None)
    args = tool_call_args.get(tool_call_id, {}) if isinstance(tool_call_id, str) else {}
    package_dir = args.get("package_dir")
    if isinstance(package_dir, str):
        package = _package_by_path(root, package_dir, packages)
        if package is not None:
            return package

    # Fallback for mocked or legacy message histories that omit tool-call args.
    return packages[-1]


def _package_by_path(
    root: str,
    package_dir: str,
    packages: list[PackageInfo],
) -> PackageInfo | None:
    """Match a tool's package_dir argument back to discovered PackageInfo."""
    root_path = Path(root).resolve()
    candidate = Path(package_dir)
    try:
        if candidate.is_absolute():
            rel = candidate.resolve().relative_to(root_path)
        else:
            rel = candidate
    except ValueError:
        rel = candidate

    normalized = rel.as_posix().rstrip("/")
    for package in packages:
        if Path(package.path).as_posix().rstrip("/") == normalized:
            return package
    return None
