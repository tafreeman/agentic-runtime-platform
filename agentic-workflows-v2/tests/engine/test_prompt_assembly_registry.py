"""Tests for the registry-backed persona lookup in prompt_assembly (ADR-056).

Verifies :func:`load_agent_system_prompt`'s role-based lookup branch
delegates to :func:`agentic_v2.prompts.registry.default_registry` when a
role is registered, that the explicit ``prompt_file_override`` branch
still reads directly from disk (never consults the registry), and that a
role absent from the registry falls back to the pre-existing direct file
read unchanged.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

from agentic_v2.engine.prompt_assembly import load_agent_system_prompt


def test_registered_role_delegates_to_default_registry():
    """A registered role ('reviewer') returns the registry record's content.

    default_registry() is patched to return a sentinel record so a pass
    can only happen via delegation, not by coincidentally matching the
    real prompts/reviewer.md content.
    """
    sentinel_record = SimpleNamespace(
        content="SENTINEL PERSONA CONTENT",
        qualified_version="v1@deadbeef",
    )
    fake_registry = SimpleNamespace(get_or_none=lambda name: sentinel_record)

    with patch(
        "agentic_v2.engine.prompt_assembly.default_registry",
        return_value=fake_registry,
    ):
        result = load_agent_system_prompt("tier2_reviewer")

    assert result == "SENTINEL PERSONA CONTENT"


def test_registered_role_extracts_correct_role_suffix():
    """The role suffix after the first '_' is what's looked up in the registry.

    'tier2_reviewer' -> 'reviewer', not 'tier2' or the full agent name.
    """
    seen_names: list[str] = []

    def _get_or_none(name: str):
        seen_names.append(name)
        return SimpleNamespace(content="X", qualified_version="v1@aaaaaaaa")

    fake_registry = SimpleNamespace(get_or_none=_get_or_none)

    with patch(
        "agentic_v2.engine.prompt_assembly.default_registry",
        return_value=fake_registry,
    ):
        load_agent_system_prompt("tier2_reviewer")

    assert seen_names == ["reviewer"]


def test_prompt_file_override_bypasses_registry():
    """An explicit prompt_file_override reads the file directly.

    default_registry() is patched to always return a sentinel so a pass
    can only happen if the override branch never consults it.
    """
    sentinel_record = SimpleNamespace(
        content="SHOULD NOT BE RETURNED",
        qualified_version="v1@deadbeef",
    )
    fake_registry = SimpleNamespace(get_or_none=lambda name: sentinel_record)

    with patch(
        "agentic_v2.engine.prompt_assembly.default_registry",
        return_value=fake_registry,
    ):
        result = load_agent_system_prompt(
            "tier2_reviewer", prompt_file_override="coder.md"
        )

    assert result is not None
    assert result != "SHOULD NOT BE RETURNED"
    assert "SENTINEL" not in result


def test_unregistered_role_falls_back_to_direct_file_read(tmp_path, monkeypatch):
    """A role with no registry entry falls back to the pre-existing direct
    file read from the prompts directory."""
    (tmp_path / "madeuprole.md").write_text(
        "Direct-read fallback content.", encoding="utf-8"
    )
    empty_registry = SimpleNamespace(get_or_none=lambda name: None)

    monkeypatch.setattr("agentic_v2.engine.prompt_assembly._PROMPTS_DIR", tmp_path)
    with patch(
        "agentic_v2.engine.prompt_assembly.default_registry",
        return_value=empty_registry,
    ):
        result = load_agent_system_prompt("tier2_madeuprole")

    assert result == "Direct-read fallback content."


def test_unregistered_role_and_missing_file_returns_none(tmp_path, monkeypatch):
    """No registry entry and no file on disk falls through to the default.md
    fallback (or None if that's also absent), matching pre-existing
    behavior -- never raises."""
    empty_registry = SimpleNamespace(get_or_none=lambda name: None)

    monkeypatch.setattr("agentic_v2.engine.prompt_assembly._PROMPTS_DIR", tmp_path)
    with patch(
        "agentic_v2.engine.prompt_assembly.default_registry",
        return_value=empty_registry,
    ):
        result = load_agent_system_prompt("tier2_totally_unknown_role")

    assert result is None
