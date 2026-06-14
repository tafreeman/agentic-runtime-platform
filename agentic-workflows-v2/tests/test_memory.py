"""Tests for ARP-8 ConversationMemory extensions.

Covers the durable case-facts block, the crash-recovery manifest round-trip,
the ``/compact``-equivalent command, position-aware ordering (case-facts ahead
of trimmed history), and per-field tool-result reduction.
"""

from __future__ import annotations

import json

import pytest

from agentic_v2.agents.memory import (
    CaseFacts,
    ConversationMemory,
    ConversationMessage,
    FieldReductionResult,
    reduce_tool_result,
)

# ============================================================================
# CaseFacts (immutability + accessors)
# ============================================================================


class TestCaseFacts:
    """The durable structured-findings dataclass."""

    def test_empty_by_default(self) -> None:
        assert CaseFacts().is_empty() is True

    def test_with_finding_returns_new_instance(self) -> None:
        original = CaseFacts()
        updated = original.with_finding("root cause is a race condition")

        # Immutable: original untouched, copy carries the change.
        assert original.findings == ()
        assert updated.findings == ("root cause is a race condition",)
        assert updated is not original

    def test_finding_dedup_and_blank_ignored(self) -> None:
        facts = (
            CaseFacts().with_finding("same").with_finding("same").with_finding("   ")
        )
        assert facts.findings == ("same",)

    def test_numbers_and_dates_overwrite_by_name(self) -> None:
        facts = (
            CaseFacts()
            .with_number("latency_ms", 240)
            .with_number("latency_ms", 310)
            .with_date("incident", "2026-06-13")
        )
        assert facts.key_numbers == {"latency_ms": 310}
        assert facts.key_dates == {"incident": "2026-06-13"}

    def test_open_question_lifecycle(self) -> None:
        facts = CaseFacts().with_open_question("which service emitted the 500?")
        assert facts.open_questions == ("which service emitted the 500?",)

        resolved = facts.resolve_question("which service emitted the 500?")
        assert resolved.open_questions == ()
        # Original copy still has the open question (immutability).
        assert facts.open_questions == ("which service emitted the 500?",)

    def test_render_includes_all_sections(self) -> None:
        facts = (
            CaseFacts()
            .with_finding("db pool exhausted")
            .with_number("max_conns", 20)
            .with_date("incident", "2026-06-13")
            .with_open_question("is it reproducible?")
        )
        rendered = facts.render()
        assert "db pool exhausted" in rendered
        assert "max_conns: 20" in rendered
        assert "incident: 2026-06-13" in rendered
        assert "is it reproducible?" in rendered


# ============================================================================
# Case-facts survive summarization (acceptance criterion)
# ============================================================================


class TestCaseFactsSurviveSummarization:
    """Durable findings must outlive an aggressive history trim."""

    def test_facts_survive_auto_trim(self) -> None:
        memory = ConversationMemory(max_messages=6)
        memory.record_finding("the bug is in the retry loop")
        memory.record_number("failed_requests", 1284)

        # Flood the buffer to force several summarization passes.
        for i in range(40):
            memory.add_user(f"message {i}")

        # History was trimmed and summarized...
        assert len(memory.messages) <= 6
        assert len(memory.summaries) > 0
        # ...but the durable facts are intact.
        assert "the bug is in the retry loop" in memory.case_facts.findings
        assert memory.case_facts.key_numbers["failed_requests"] == 1284

    def test_facts_injected_ahead_of_summaries_and_history(self) -> None:
        memory = ConversationMemory(max_messages=6)
        memory.record_finding("durable finding")
        for i in range(40):
            memory.add_user(f"message {i}")

        rendered = memory.get_messages()
        # Position-aware ordering: case-facts block is the very first message.
        assert rendered[0]["role"] == "system"
        assert "CASE FACTS" in rendered[0]["content"]
        assert "durable finding" in rendered[0]["content"]
        # The lossy summary block, if present, comes after the facts block.
        summary_indexes = [
            i
            for i, m in enumerate(rendered)
            if "Previous conversation summary" in m.get("content", "")
        ]
        assert summary_indexes  # a summary exists
        assert summary_indexes[0] > 0  # and it is not first

    def test_no_facts_block_when_empty(self) -> None:
        memory = ConversationMemory()
        memory.add_user("hello")
        rendered = memory.get_messages()
        assert all("CASE FACTS" not in m.get("content", "") for m in rendered)


# ============================================================================
# Crash-recovery manifest round-trip (acceptance criterion)
# ============================================================================


class TestManifestRoundTrip:
    """The full buffer state must survive a serialize/deserialize cycle."""

    def _seed(self) -> ConversationMemory:
        memory = ConversationMemory(max_messages=8, max_tokens=4000)
        memory.add_system("You are a debugging assistant")
        memory.add_user("the service is throwing 500s")
        memory.add_assistant("let me investigate")
        memory.add_tool_result("read_logs", "ERROR pool exhausted", "call_1")
        memory.record_finding("connection pool exhausted under load")
        memory.record_number("pool_size", 20)
        memory.record_date("first_seen", "2026-06-13T10:00:00+00:00")
        memory.record_open_question("does it recur after a restart?")
        return memory

    def test_round_trip_preserves_state(self) -> None:
        memory = self._seed()
        restored = ConversationMemory.from_manifest(memory.to_manifest())

        assert [m.content for m in restored.messages] == [
            m.content for m in memory.messages
        ]
        assert [m.role for m in restored.messages] == [m.role for m in memory.messages]
        assert restored.case_facts.findings == memory.case_facts.findings
        assert restored.case_facts.key_numbers == memory.case_facts.key_numbers
        assert restored.case_facts.key_dates == memory.case_facts.key_dates
        assert restored.case_facts.open_questions == (memory.case_facts.open_questions)
        assert restored.max_messages == memory.max_messages
        assert restored.max_tokens == memory.max_tokens

    def test_round_trip_preserves_tool_message_fields(self) -> None:
        memory = self._seed()
        restored = ConversationMemory.from_manifest(memory.to_manifest())
        tool_msg = next(m for m in restored.messages if m.role == "tool")
        assert tool_msg.tool_name == "read_logs"
        assert tool_msg.tool_call_id == "call_1"

    def test_json_round_trip(self) -> None:
        memory = self._seed()
        payload = memory.to_manifest_json()
        # Must be valid, self-contained JSON (crash-recovery on disk).
        assert isinstance(json.loads(payload), dict)
        restored = ConversationMemory.from_manifest_json(payload)
        assert restored.case_facts.findings == memory.case_facts.findings

    def test_token_counter_reattached_on_restore(self) -> None:
        memory = self._seed()
        restored = ConversationMemory.from_manifest(
            memory.to_manifest(), token_counter=lambda _t: 1
        )
        assert restored.token_counter is not None
        assert restored.estimate_tokens("anything") == 1

    def test_rendered_messages_match_after_restore(self) -> None:
        memory = self._seed()
        restored = ConversationMemory.from_manifest(memory.to_manifest())
        assert restored.get_messages() == memory.get_messages()

    def test_unsupported_version_rejected(self) -> None:
        manifest = self._seed().to_manifest()
        manifest["version"] = 999
        with pytest.raises(ValueError, match="Unsupported manifest version"):
            ConversationMemory.from_manifest(manifest)


# ============================================================================
# Per-field tool-result reduction (acceptance criterion)
# ============================================================================


class TestFieldReduction:
    """The '40+ fields -> keep 5' projection pattern."""

    def test_reduce_keeps_only_allowlisted_fields(self) -> None:
        verbose = {f"field_{i}": i for i in range(40)}
        verbose["status"] = "ok"
        verbose["id"] = "abc"

        result = reduce_tool_result(verbose, ["status", "id", "missing"])

        assert isinstance(result, FieldReductionResult)
        assert result.kept == {"status": "ok", "id": "abc"}
        # 40 numbered fields dropped; allowlisted-but-absent 'missing' is fine.
        assert result.dropped_count == 40
        assert "field_0" in result.dropped_fields
        assert "status" not in result.dropped_fields

    def test_reduce_reports_no_drops_when_all_allowed(self) -> None:
        result = reduce_tool_result({"a": 1, "b": 2}, ["a", "b"])
        assert result.dropped_count == 0
        assert result.dropped_fields == ()

    def test_render_notes_dropped_count(self) -> None:
        result = reduce_tool_result({"keep": 1, "drop": 2}, ["keep"])
        rendered = result.render("search_tool")
        assert "dropped 1 verbose field" in rendered
        assert "search_tool" in rendered
        assert '"keep": 1' in rendered

    def test_render_omits_note_when_nothing_dropped(self) -> None:
        result = reduce_tool_result({"keep": 1}, ["keep"])
        rendered = result.render("search_tool")
        assert "dropped" not in rendered
        assert json.loads(rendered) == {"keep": 1}

    def test_add_reduced_tool_result_stores_compact_message(self) -> None:
        memory = ConversationMemory()
        verbose = {f"f{i}": i for i in range(40)}
        verbose["title"] = "result title"
        verbose["url"] = "https://example.test"

        msg = memory.add_reduced_tool_result(
            tool_name="web_search",
            result=verbose,
            tool_call_id="call_42",
            allowlist=["title", "url"],
        )

        assert msg.role == "tool"
        assert msg.tool_name == "web_search"
        assert msg.tool_call_id == "call_42"
        assert msg.metadata["reduced"] is True
        assert msg.metadata["dropped_count"] == 40
        assert sorted(msg.metadata["kept_fields"]) == ["title", "url"]
        # Stored content carries only the kept fields, plus the drop note.
        assert "result title" in msg.content
        assert "f0" not in msg.content


# ============================================================================
# /compact-equivalent command
# ============================================================================


class TestCompact:
    """The on-demand compaction command."""

    def test_compact_folds_old_messages_into_a_summary(self) -> None:
        memory = ConversationMemory(max_messages=50)  # high threshold: no auto-trim
        memory.add_system("system prompt")
        for i in range(20):
            memory.add_user(f"message {i}")

        assert memory.summaries == []  # nothing auto-summarized yet
        folded = memory.compact(keep_recent=3)

        assert folded > 0
        assert len(memory.summaries) == 1
        # System prompt + the 3 most recent kept verbatim.
        assert memory.messages[0].role == "system"
        assert memory.messages[-1].content == "message 19"
        assert len(memory.messages) <= 4

    def test_compact_noop_when_nothing_to_fold(self) -> None:
        memory = ConversationMemory()
        memory.add_user("only one")
        # keep_recent large enough that there is nothing older to summarize.
        assert memory.compact(keep_recent=10) == 0
        assert memory.summaries == []

    def test_compact_preserves_case_facts(self) -> None:
        memory = ConversationMemory(max_messages=50)
        memory.record_finding("durable through compaction")
        for i in range(20):
            memory.add_user(f"message {i}")
        memory.compact()
        assert "durable through compaction" in memory.case_facts.findings


# ============================================================================
# clear() resets durable facts too
# ============================================================================


def test_clear_resets_case_facts() -> None:
    memory = ConversationMemory()
    memory.add_user("hi")
    memory.record_finding("temp finding")
    memory.summaries.append("a summary")

    memory.clear()

    assert memory.messages == []
    assert memory.summaries == []
    assert memory.case_facts.is_empty()


def test_message_manifest_round_trip_standalone() -> None:
    msg = ConversationMessage(role="tool", content="x", tool_name="t", tool_call_id="c")
    restored = ConversationMessage.from_manifest(msg.to_manifest())
    assert restored.role == "tool"
    assert restored.tool_name == "t"
    assert restored.tool_call_id == "c"
    assert restored.timestamp == msg.timestamp
