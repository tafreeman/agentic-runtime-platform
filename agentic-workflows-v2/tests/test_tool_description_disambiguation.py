"""Tests for ARP-6: builtin tool descriptions are disambiguated.

The model selects a tool primarily from its ``description`` (see
``docs/adr/ADR-028-tool-descriptions-as-selection-mechanism.md``). These tests
guard two invariants that keep selection reliable:

1. No two builtin tools carry near-identical descriptions, so overlapping
   tools (``search``/``grep``, ``file_copy``/``file_move``, ...) stay
   distinguishable.
2. Every overlapping pair states explicit *when-to-prefer-which* guidance and
   the descriptions are input-format/edge-case rich (not one-liners).

They assert on the public schema surface, not on implementation details, and
run without any model or network access.
"""

from __future__ import annotations

import re

from agentic_v2.tools.base import BaseTool
from agentic_v2.tools.registry import ToolRegistry

# Minimum unique-word ratio expected of a promoted description. A bare
# one-liner like "Delete a file" scores far below this; the rewritten
# descriptions are multi-sentence and clear it comfortably.
_MIN_DESCRIPTION_WORDS = 25

# Jaccard similarity over lowercased word sets above which two descriptions are
# treated as "near-identical". 0.6 flags genuine duplicates while tolerating
# shared vocabulary between, say, the two HTTP wrappers.
_NEAR_DUPLICATE_JACCARD = 0.6

# Tools whose domains overlap and therefore MUST spell out when to prefer one
# over its sibling(s). Each tool name here must mention "prefer" in its
# description.
_OVERLAPPING_TOOLS_REQUIRING_PREFERENCE = {
    "search",
    "grep",
    "file_copy",
    "file_move",
    "git",
    "git_status",
    "git_diff",
    "http",
    "http_get",
    "http_post",
    "shell",
    "shell_exec",
    "code_analysis",
    "ast_dump",
    "memory_upsert",
    "memory_get",
    "memory_list",
    "memory_search",
    "memory_delete",
    "memory_clear",
}


def _builtin_tools() -> list[BaseTool]:
    """Discover every builtin tool via a fresh, isolated registry."""
    registry = ToolRegistry()
    registry.discover_builtin()
    return registry.list_tools()


def _word_set(text: str) -> set[str]:
    """Lowercase word tokens of a description, for set-similarity comparison."""
    return set(re.findall(r"[a-z_]+", text.lower()))


def _jaccard(a: set[str], b: set[str]) -> float:
    """Jaccard similarity of two word sets (0.0 when either is empty)."""
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def test_builtin_tools_discovered() -> None:
    """Sanity: discovery finds the search/grep pair and many siblings."""
    names = {tool.name for tool in _builtin_tools()}

    assert names >= {"search", "grep"}
    assert names >= _OVERLAPPING_TOOLS_REQUIRING_PREFERENCE


def test_no_two_builtin_descriptions_are_near_identical() -> None:
    """No builtin tool may share a near-duplicate description with another."""
    tools = _builtin_tools()

    duplicates: list[tuple[str, str, float]] = []
    for i, left in enumerate(tools):
        left_words = _word_set(left.description)
        for right in tools[i + 1 :]:
            similarity = _jaccard(left_words, _word_set(right.description))
            if similarity >= _NEAR_DUPLICATE_JACCARD:
                duplicates.append((left.name, right.name, round(similarity, 3)))

    assert not duplicates, f"Near-identical tool descriptions: {duplicates}"


def test_search_and_grep_disambiguate_each_other() -> None:
    """The flagship overlapping pair cross-references the other by name."""
    by_name = {tool.name: tool for tool in _builtin_tools()}

    search_desc = by_name["search"].description.lower()
    grep_desc = by_name["grep"].description.lower()

    # Each names the other so the model can route between them.
    assert "grep" in search_desc
    assert "search" in grep_desc

    # Each states its distinguishing capability/limitation.
    assert "regex" in search_desc and "semantic" in search_desc
    assert "literal" in grep_desc

    # Both carry explicit preference guidance.
    assert "prefer" in search_desc
    assert "prefer" in grep_desc


def test_search_description_matches_actual_behavior() -> None:
    """The search description must not over-claim (ARP-6 accuracy fix).

    The 500-char ReDoS guard lives only in ``_regex_search`` (regex mode), and
    semantic results are scored/sorted PER FILE, not globally. The model-facing
    description must say so rather than implying a global cap or a global rank.
    """
    by_name = {tool.name: tool for tool in _builtin_tools()}
    search_desc = by_name["search"].description.lower()

    # The 500-char guard is scoped to regex mode, not stated as universal.
    assert "500" in search_desc
    guard_index = search_desc.index("500")
    window = search_desc[max(0, guard_index - 40) : guard_index + 40]
    assert (
        "regex" in window
    ), "the 500-char guard must be scoped to regex mode in the description"

    # Semantic ordering is described as per-file (no global cross-file re-rank).
    assert "within each file" in search_desc or "per file" in search_desc
    assert "no global cross-file" in search_desc


def test_overlapping_tools_state_when_to_prefer() -> None:
    """Every overlapping tool spells out a when-to-prefer-which contrast."""
    by_name = {tool.name: tool for tool in _builtin_tools()}

    missing = [
        name
        for name in _OVERLAPPING_TOOLS_REQUIRING_PREFERENCE
        if "prefer" not in by_name[name].description.lower()
    ]

    assert not missing, f"Tools missing when-to-prefer guidance: {missing}"


def test_promoted_descriptions_are_input_format_rich() -> None:
    """The promoted tools have substantial, multi-sentence descriptions."""
    by_name = {tool.name: tool for tool in _builtin_tools()}

    thin = [
        name
        for name in _OVERLAPPING_TOOLS_REQUIRING_PREFERENCE
        if len(by_name[name].description.split()) < _MIN_DESCRIPTION_WORDS
    ]

    assert not thin, f"Descriptions still too thin (one-liners): {thin}"


def test_file_copy_and_move_describe_destructiveness() -> None:
    """The copy/move pair makes the source-survival distinction explicit."""
    by_name = {tool.name: tool for tool in _builtin_tools()}

    copy_desc = by_name["file_copy"].description.lower()
    move_desc = by_name["file_move"].description.lower()

    # Copy keeps the source; move removes it. The descriptions must say so.
    assert "leav" in copy_desc or "preserv" in copy_desc or "survive" in copy_desc
    assert "remov" in move_desc or "delete" in move_desc
    assert "file_move" in copy_desc
    assert "file_copy" in move_desc
