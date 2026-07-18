"""Tests for the prompt-versioning registry (ADR-056).

Covers the pure normalization/hashing helpers, :class:`PromptRecord` /
:class:`PromptRegistry` behavior, the ``default_registry()`` singleton of
the 7 role persona prompts, and back-compat with the legacy
``agentic_v2.prompts.load_prompt`` / ``list_prompts`` API.
"""

from __future__ import annotations

import re

import pytest

from agentic_v2.prompts import list_prompts, load_prompt
from agentic_v2.prompts.registry import (
    PROMPT_VERSIONS,
    PromptRecord,
    PromptRegistry,
    compute_content_hash,
    default_registry,
    normalize_prompt_text,
)

ROLE_NAMES = frozenset(PROMPT_VERSIONS.keys())

# ---------------------------------------------------------------------------
# normalize_prompt_text
# ---------------------------------------------------------------------------


def test_normalize_crlf_to_lf():
    """CRLF line endings normalize to bare LF."""
    assert normalize_prompt_text("line one\r\nline two\r\n") == "line one\nline two\n"


def test_normalize_bare_cr_to_lf():
    """Bare CR (old Mac-style) line endings normalize to LF."""
    assert normalize_prompt_text("line one\rline two\r") == "line one\nline two\n"


def test_normalize_lf_is_idempotent():
    """Text already using LF is returned unchanged."""
    text = "line one\nline two\n"
    assert normalize_prompt_text(text) == text


def test_normalize_mixed_endings_all_become_lf():
    """A mix of CRLF and bare CR in one string all collapse to LF."""
    mixed = "a\r\nb\rc\n"
    assert normalize_prompt_text(mixed) == "a\nb\nc\n"


def test_crlf_and_lf_variants_normalize_to_same_text():
    """The same logical content, differing only in line endings, is equal."""
    lf_text = "Title\n\nBody line.\n"
    crlf_text = "Title\r\n\r\nBody line.\r\n"
    assert normalize_prompt_text(lf_text) == normalize_prompt_text(crlf_text)


# ---------------------------------------------------------------------------
# compute_content_hash
# ---------------------------------------------------------------------------


def test_hash_stable_across_line_endings():
    """Hash is identical for CRLF vs. LF versions of the same content."""
    lf_text = "Title\n\nBody line.\n"
    crlf_text = "Title\r\n\r\nBody line.\r\n"
    assert compute_content_hash(lf_text) == compute_content_hash(crlf_text)


def test_hash_stable_across_bare_cr():
    """Hash is identical for bare-CR vs. LF versions of the same content."""
    lf_text = "Title\nBody.\n"
    cr_text = "Title\rBody.\r"
    assert compute_content_hash(lf_text) == compute_content_hash(cr_text)


def test_hash_changes_on_content_change():
    """A single-character content change produces a different hash."""
    original = compute_content_hash("The quick brown fox.")
    changed = compute_content_hash("The quick brown fax.")
    assert original != changed


def test_hash_is_hex_sha256_length():
    """Hash is a 64-character lowercase hex string (SHA-256 digest)."""
    digest = compute_content_hash("some text")
    assert len(digest) == 64
    assert re.fullmatch(r"[0-9a-f]{64}", digest)


# ---------------------------------------------------------------------------
# PromptRecord
# ---------------------------------------------------------------------------


def test_prompt_record_short_hash_is_first_8_hex_chars():
    """short_hash is exactly the first 8 hex characters of content_sha256."""
    digest = compute_content_hash("content")
    record = PromptRecord(
        name="x",
        declared_version="v1",
        content="content",
        content_sha256=digest,
        source="inline:x",
    )
    assert record.short_hash == digest[:8]
    assert len(record.short_hash) == 8


def test_prompt_record_qualified_version_format():
    """qualified_version is '{declared_version}@{short_hash}'."""
    digest = compute_content_hash("content")
    record = PromptRecord(
        name="x",
        declared_version="v1",
        content="content",
        content_sha256=digest,
        source="inline:x",
    )
    assert record.qualified_version == f"v1@{digest[:8]}"
    assert re.fullmatch(r"v1@[0-9a-f]{8}", record.qualified_version)


def test_prompt_record_is_frozen():
    """PromptRecord is an immutable (frozen) dataclass."""
    record = PromptRecord(
        name="x",
        declared_version="v1",
        content="content",
        content_sha256=compute_content_hash("content"),
        source="inline:x",
    )
    with pytest.raises(AttributeError):
        record.name = "mutated"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# PromptRegistry.register_inline / register_file
# ---------------------------------------------------------------------------


def test_register_inline_source_tag():
    """register_inline tags the record with 'inline:<name>'."""
    registry = PromptRegistry()
    record = registry.register_inline("judge", "Some prompt.", declared_version="v1")
    assert record.source == "inline:judge"


def test_register_inline_normalizes_content():
    """register_inline stores LF-normalized content, not the raw CRLF input."""
    registry = PromptRegistry()
    record = registry.register_inline(
        "judge", "line one\r\nline two\r\n", declared_version="v1"
    )
    assert record.content == "line one\nline two\n"
    assert "\r" not in record.content


def test_register_file_source_tag(tmp_path):
    """register_file tags the record with 'file:<basename>'."""
    prompt_path = tmp_path / "reviewer.md"
    prompt_path.write_text("Review carefully.", encoding="utf-8")

    registry = PromptRegistry()
    record = registry.register_file("reviewer", prompt_path, declared_version="v1")
    assert record.source == "file:reviewer.md"


def test_register_file_normalizes_crlf_on_disk(tmp_path):
    """A CRLF file on disk is normalized to LF content in the record."""
    prompt_path = tmp_path / "tester.md"
    prompt_path.write_bytes(b"Test thoroughly.\r\nAlways.\r\n")

    registry = PromptRegistry()
    record = registry.register_file("tester", prompt_path, declared_version="v1")
    assert record.content == "Test thoroughly.\nAlways.\n"


# ---------------------------------------------------------------------------
# PromptRegistry.get / get_or_none / text / records / names
# ---------------------------------------------------------------------------


def test_get_raises_key_error_for_unregistered_name():
    """get() raises KeyError for a name that was never registered."""
    registry = PromptRegistry()
    with pytest.raises(KeyError):
        registry.get("nonexistent")


def test_get_or_none_returns_none_for_unregistered_name():
    """get_or_none() returns None (no exception) for an unregistered name."""
    registry = PromptRegistry()
    assert registry.get_or_none("nonexistent") is None


def test_get_or_none_returns_record_for_registered_name():
    """get_or_none() returns the record once registered."""
    registry = PromptRegistry()
    registry.register_inline("judge", "text", declared_version="v1")
    record = registry.get_or_none("judge")
    assert record is not None
    assert record.name == "judge"


def test_text_returns_content():
    """text() returns the same string as get(name).content."""
    registry = PromptRegistry()
    registry.register_inline("judge", "line one\r\n", declared_version="v1")
    assert registry.text("judge") == registry.get("judge").content == "line one\n"


def test_records_returns_immutable_tuple_snapshot():
    """records() returns a tuple; registering afterward does not mutate it."""
    registry = PromptRegistry()
    registry.register_inline("a", "text a", declared_version="v1")
    snapshot = registry.records()

    assert isinstance(snapshot, tuple)
    registry.register_inline("b", "text b", declared_version="v1")

    assert len(snapshot) == 1
    assert len(registry.records()) == 2


def test_names_lists_all_registered_names():
    """names() lists every registered prompt name."""
    registry = PromptRegistry()
    registry.register_inline("a", "text a", declared_version="v1")
    registry.register_inline("b", "text b", declared_version="v1")
    assert set(registry.names()) == {"a", "b"}


# ---------------------------------------------------------------------------
# default_registry()
# ---------------------------------------------------------------------------


def test_default_registry_contains_exactly_the_7_role_names():
    """default_registry() carries exactly the 7 role persona prompts."""
    registry = default_registry()
    assert set(registry.names()) == ROLE_NAMES
    assert len(registry.names()) == 7


def test_default_registry_is_a_singleton():
    """default_registry() returns the same cached instance every call."""
    assert default_registry() is default_registry()


@pytest.mark.parametrize("role", sorted(ROLE_NAMES))
def test_default_registry_self_consistency(role):
    """Each role's registered hash matches an independent recomputation.

    Reads ``prompts/<role>.md`` directly (bypassing the registry) and
    verifies ``compute_content_hash`` of that independently-read text
    equals the registry record's ``content_sha256`` -- proving the
    registry did not silently transform content beyond LF-normalization.
    """
    from agentic_v2.prompts import PROMPTS_DIR

    record = default_registry().get(role)
    path = PROMPTS_DIR / f"{role}.md"
    assert record.content_sha256 == compute_content_hash(
        path.read_text(encoding="utf-8")
    )


@pytest.mark.parametrize("role", sorted(ROLE_NAMES))
def test_default_registry_declared_versions(role):
    """Each role's declared_version matches the PROMPT_VERSIONS map."""
    record = default_registry().get(role)
    assert record.declared_version == PROMPT_VERSIONS[role]


@pytest.mark.parametrize("role", sorted(ROLE_NAMES))
def test_default_registry_source_is_file_tag(role):
    """Each role record is tagged with its source file basename."""
    record = default_registry().get(role)
    assert record.source == f"file:{role}.md"


# ---------------------------------------------------------------------------
# Back-compat: agentic_v2.prompts.load_prompt / list_prompts
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("role", sorted(ROLE_NAMES))
def test_load_prompt_matches_registry_text(role):
    """load_prompt(role) returns the same content as the registry."""
    assert load_prompt(role) == default_registry().text(role)


def test_load_prompt_accepts_md_suffix():
    """load_prompt('reviewer.md') resolves the same as load_prompt('reviewer')."""
    assert load_prompt("reviewer.md") == load_prompt("reviewer")


def test_load_prompt_raises_for_unknown_name():
    """load_prompt raises FileNotFoundError for a name with no registry entry
    and no file on disk."""
    with pytest.raises(FileNotFoundError):
        load_prompt("does_not_exist_anywhere")


def test_list_prompts_returns_the_7_stems():
    """list_prompts() still returns the 7 role name stems."""
    assert set(list_prompts()) == ROLE_NAMES
