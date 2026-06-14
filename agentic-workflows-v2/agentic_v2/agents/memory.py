"""Conversation memory primitives for agent history management.

Provides the :class:`ConversationMessage` and :class:`ConversationMemory`
classes used by :class:`~agentic_v2.agents.base.BaseAgent` to maintain
bounded, summarised conversation history across LLM turns.

Key abstractions:
    ConversationMessage:
        Immutable, frozen dataclass representing a single turn in the
        conversation (user, assistant, system, or tool role).

    CaseFacts:
        Immutable, frozen dataclass holding the *durable* findings of a run
        (key numbers, dates, and open questions) separate from the lossy
        rolling-history summaries.  Survives summarization so the model never
        loses load-bearing facts to a trim.

    ConversationMemory:
        Sliding-window buffer that automatically summarises and evicts
        older messages when the window exceeds ``max_messages`` or the
        estimated ``max_tokens`` budget.  Also persists a durable case-facts
        block, supports a ``/compact``-equivalent command, can round-trip its
        full state through a crash-recovery manifest, and projects verbose
        tool results down to an allowlist of fields before storing them.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from typing import Any, Callable

logger = logging.getLogger(__name__)

# Schema version for the crash-recovery manifest. Bump on a breaking
# change to ``to_manifest``/``from_manifest`` so stale manifests are rejected.
MANIFEST_VERSION = 1


@dataclass(frozen=True)
class ConversationMessage:
    """A single message in the agent's conversation history.

    Attributes:
        role: The message role (``"user"``, ``"assistant"``, ``"system"``,
            or ``"tool"``).
        content: The textual content of the message.
        timestamp: UTC timestamp of when the message was created.
        tool_call_id: Optional identifier linking a tool result to its
            originating tool call.
        tool_name: Name of the tool that produced this message (only set
            when ``role`` is ``"tool"``).
        metadata: Arbitrary key-value pairs for extensibility.
    """

    role: str  # "user", "assistant", "system", "tool"
    content: str
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))
    tool_call_id: str | None = None
    tool_name: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dict for LLM API."""
        msg = {"role": self.role, "content": self.content}
        if self.tool_call_id:
            msg["tool_call_id"] = self.tool_call_id
        if self.tool_name and self.role == "tool":
            msg["name"] = self.tool_name
        return msg

    def to_manifest(self) -> dict[str, Any]:
        """Serialize to a JSON-safe dict for the crash-recovery manifest."""
        return {
            "role": self.role,
            "content": self.content,
            "timestamp": self.timestamp.isoformat(),
            "tool_call_id": self.tool_call_id,
            "tool_name": self.tool_name,
            "metadata": dict(self.metadata),
        }

    @classmethod
    def from_manifest(cls, data: dict[str, Any]) -> ConversationMessage:
        """Reconstruct a message from its manifest representation."""
        raw_ts = data.get("timestamp")
        if isinstance(raw_ts, str):
            timestamp = datetime.fromisoformat(raw_ts)
        else:
            timestamp = datetime.now(UTC)
        return cls(
            role=str(data["role"]),
            content=str(data.get("content", "")),
            timestamp=timestamp,
            tool_call_id=data.get("tool_call_id"),
            tool_name=data.get("tool_name"),
            metadata=dict(data.get("metadata") or {}),
        )


@dataclass(frozen=True)
class CaseFacts:
    """Durable, structured findings for a run.

    Held separately from the rolling-history summaries so the load-bearing
    facts of an investigation (concrete numbers, dates, decided findings, and
    still-open questions) are never lost to a summarization trim.  All update
    helpers return a **new** instance rather than mutating in place.

    Attributes:
        findings: Durable statements the run has established as true.
        key_numbers: Named numeric facts (e.g. ``{"latency_ms": 240}``).
        key_dates: Named date/time facts (e.g. ``{"incident": "2026-06-13"}``).
        open_questions: Questions the run has not yet resolved.
        updated_at: UTC timestamp of the last mutation.
    """

    findings: tuple[str, ...] = ()
    key_numbers: dict[str, Any] = field(default_factory=dict)
    key_dates: dict[str, str] = field(default_factory=dict)
    open_questions: tuple[str, ...] = ()
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def is_empty(self) -> bool:
        """Return True when no facts have been recorded yet."""
        return not (
            self.findings or self.key_numbers or self.key_dates or self.open_questions
        )

    def with_finding(self, finding: str) -> CaseFacts:
        """Return a copy with ``finding`` appended (de-duplicated)."""
        finding = finding.strip()
        if not finding or finding in self.findings:
            return self
        return replace(
            self,
            findings=(*self.findings, finding),
            updated_at=datetime.now(UTC),
        )

    def with_number(self, name: str, value: Any) -> CaseFacts:
        """Return a copy with a named numeric fact set/overwritten."""
        merged = {**self.key_numbers, name: value}
        return replace(self, key_numbers=merged, updated_at=datetime.now(UTC))

    def with_date(self, name: str, value: str) -> CaseFacts:
        """Return a copy with a named date fact set/overwritten."""
        merged = {**self.key_dates, name: value}
        return replace(self, key_dates=merged, updated_at=datetime.now(UTC))

    def with_open_question(self, question: str) -> CaseFacts:
        """Return a copy with ``question`` appended to the open list."""
        question = question.strip()
        if not question or question in self.open_questions:
            return self
        return replace(
            self,
            open_questions=(*self.open_questions, question),
            updated_at=datetime.now(UTC),
        )

    def resolve_question(self, question: str) -> CaseFacts:
        """Return a copy with ``question`` removed from the open list."""
        if question not in self.open_questions:
            return self
        remaining = tuple(q for q in self.open_questions if q != question)
        return replace(self, open_questions=remaining, updated_at=datetime.now(UTC))

    def render(self) -> str:
        """Render the facts as a compact, position-anchorable text block."""
        lines: list[str] = ["CASE FACTS (durable; do not discard):"]
        if self.findings:
            lines.append("Findings:")
            lines.extend(f"  - {f}" for f in self.findings)
        if self.key_numbers:
            lines.append("Key numbers:")
            lines.extend(f"  - {k}: {v}" for k, v in self.key_numbers.items())
        if self.key_dates:
            lines.append("Key dates:")
            lines.extend(f"  - {k}: {v}" for k, v in self.key_dates.items())
        if self.open_questions:
            lines.append("Open questions:")
            lines.extend(f"  - {q}" for q in self.open_questions)
        return "\n".join(lines)

    def to_manifest(self) -> dict[str, Any]:
        """Serialize to a JSON-safe dict for the crash-recovery manifest."""
        return {
            "findings": list(self.findings),
            "key_numbers": dict(self.key_numbers),
            "key_dates": dict(self.key_dates),
            "open_questions": list(self.open_questions),
            "updated_at": self.updated_at.isoformat(),
        }

    @classmethod
    def from_manifest(cls, data: dict[str, Any]) -> CaseFacts:
        """Reconstruct case-facts from their manifest representation."""
        raw_ts = data.get("updated_at")
        if isinstance(raw_ts, str):
            updated_at = datetime.fromisoformat(raw_ts)
        else:
            updated_at = datetime.now(UTC)
        return cls(
            findings=tuple(data.get("findings") or ()),
            key_numbers=dict(data.get("key_numbers") or {}),
            key_dates=dict(data.get("key_dates") or {}),
            open_questions=tuple(data.get("open_questions") or ()),
            updated_at=updated_at,
        )


@dataclass(frozen=True)
class FieldReductionResult:
    """Outcome of projecting a verbose tool result onto a field allowlist.

    Attributes:
        kept: The projected mapping containing only allowlisted fields that
            were actually present in the source.
        dropped_count: Number of top-level fields removed by the projection.
        dropped_fields: Names of the removed fields (sorted for determinism).
    """

    kept: dict[str, Any]
    dropped_count: int
    dropped_fields: tuple[str, ...]

    def render(self, tool_name: str | None = None) -> str:
        """Render the reduced result as compact JSON plus a drop note."""
        label = f"{tool_name} result" if tool_name else "result"
        body = json.dumps(self.kept, default=str, sort_keys=True)
        if self.dropped_count <= 0:
            return body
        note = (
            f"[{label}: reduced to {len(self.kept)} field(s); "
            f"dropped {self.dropped_count} verbose field(s)]"
        )
        return f"{note}\n{body}"


def reduce_tool_result(
    result: dict[str, Any], allowlist: list[str] | tuple[str, ...]
) -> FieldReductionResult:
    """Project ``result`` onto ``allowlist``, reporting dropped fields.

    Implements the "40+ fields -> keep 5" pattern: verbose tool output is
    trimmed to a small allowlist of load-bearing fields before it is stored in
    conversation memory, so a single chatty tool call cannot blow the token
    budget.  Only top-level keys are considered; nested values pass through
    untouched.

    Args:
        result: The raw tool-result mapping.
        allowlist: The field names to retain.  Order is irrelevant; missing
            fields are simply skipped (not an error).

    Returns:
        A :class:`FieldReductionResult` carrying the kept projection, the
        count of dropped top-level fields, and their names.
    """
    allow = set(allowlist)
    kept = {k: v for k, v in result.items() if k in allow}
    dropped = tuple(sorted(k for k in result if k not in allow))
    return FieldReductionResult(
        kept=kept,
        dropped_count=len(dropped),
        dropped_fields=dropped,
    )


@dataclass
class ConversationMemory:
    """Sliding-window conversation buffer with automatic summarization.

    Maintains a bounded list of :class:`ConversationMessage` instances.  When
    the window exceeds ``max_messages`` or ``max_tokens``, older messages are
    compressed into textual summaries and evicted.  System messages and recent
    context are preserved during compaction.

    Beyond the rolling history this buffer also keeps a durable
    :class:`CaseFacts` block (which survives summarization and is injected
    *ahead of* the trimmed history), supports a :meth:`compact`
    ``/compact``-equivalent command, round-trips its full state through a
    crash-recovery manifest (:meth:`to_manifest`/:meth:`from_manifest`), and
    can project verbose tool results onto a field allowlist before storing
    them (:meth:`add_reduced_tool_result`).

    Attributes:
        messages: The current message window.
        max_messages: Maximum number of messages before summarization triggers.
        max_tokens: Approximate token budget for messages plus summaries.
        summaries: Accumulated textual summaries of evicted messages.
        max_summaries: Maximum number of summary blocks to retain.
        token_counter: Optional callable for precise token counting.  Falls
            back to a ``len(text) // 4`` heuristic when ``None``.
        case_facts: Durable structured findings, kept separate from summaries.
    """

    messages: list[ConversationMessage] = field(default_factory=list)
    max_messages: int = 50
    max_tokens: int = 8000
    summaries: list[str] = field(default_factory=list)
    max_summaries: int = 5
    token_counter: Callable[[str], int] | None = None
    case_facts: CaseFacts = field(default_factory=CaseFacts)

    def add(self, role: str, content: str, **kwargs: Any) -> ConversationMessage:
        """Add a message to history."""
        msg = ConversationMessage(role=role, content=content, **kwargs)
        self.messages.append(msg)

        # Auto-trim if needed
        if (
            len(self.messages) > self.max_messages
            or self.total_tokens > self.max_tokens
        ):
            self._summarize_and_trim()

        return msg

    def add_user(self, content: str) -> ConversationMessage:
        """Add a user message."""
        return self.add("user", content)

    def add_assistant(self, content: str) -> ConversationMessage:
        """Add an assistant message."""
        return self.add("assistant", content)

    def add_system(self, content: str) -> ConversationMessage:
        """Add a system message."""
        return self.add("system", content)

    def add_tool_result(
        self, tool_name: str, result: str, tool_call_id: str
    ) -> ConversationMessage:
        """Add a tool result message."""
        return self.add("tool", result, tool_name=tool_name, tool_call_id=tool_call_id)

    def add_reduced_tool_result(
        self,
        tool_name: str,
        result: dict[str, Any],
        tool_call_id: str,
        allowlist: list[str] | tuple[str, ...],
    ) -> ConversationMessage:
        """Project a verbose tool result onto ``allowlist``, then store it.

        Applies :func:`reduce_tool_result` so only the allowlisted fields are
        retained, records the dropped-field count in the message metadata, and
        stores the compact rendering as a ``tool``-role message.

        Args:
            tool_name: Name of the tool that produced ``result``.
            result: The raw tool-result mapping (often dozens of fields).
            tool_call_id: Id linking this result to its originating call.
            allowlist: The small set of fields to retain.

        Returns:
            The stored :class:`ConversationMessage` (with reduction metadata).
        """
        reduction = reduce_tool_result(result, allowlist)
        if reduction.dropped_count > 0:
            logger.debug(
                "Reduced %s result: kept %d field(s), dropped %d (%s)",
                tool_name,
                len(reduction.kept),
                reduction.dropped_count,
                ", ".join(reduction.dropped_fields),
            )
        return self.add(
            "tool",
            reduction.render(tool_name),
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            metadata={
                "reduced": reduction.dropped_count > 0,
                "kept_fields": sorted(reduction.kept),
                "dropped_count": reduction.dropped_count,
                "dropped_fields": list(reduction.dropped_fields),
            },
        )

    # -- Case-facts -------------------------------------------------------

    def record_finding(self, finding: str) -> CaseFacts:
        """Record a durable finding in the case-facts block."""
        self.case_facts = self.case_facts.with_finding(finding)
        return self.case_facts

    def record_number(self, name: str, value: Any) -> CaseFacts:
        """Record a named numeric fact in the case-facts block."""
        self.case_facts = self.case_facts.with_number(name, value)
        return self.case_facts

    def record_date(self, name: str, value: str) -> CaseFacts:
        """Record a named date fact in the case-facts block."""
        self.case_facts = self.case_facts.with_date(name, value)
        return self.case_facts

    def record_open_question(self, question: str) -> CaseFacts:
        """Record an unresolved question in the case-facts block."""
        self.case_facts = self.case_facts.with_open_question(question)
        return self.case_facts

    def resolve_open_question(self, question: str) -> CaseFacts:
        """Remove a previously-open question from the case-facts block."""
        self.case_facts = self.case_facts.resolve_question(question)
        return self.case_facts

    def get_messages(self, include_system: bool = True) -> list[dict[str, Any]]:
        """Get messages for LLM API.

        Position-aware ordering: durable case-facts are injected **ahead of**
        the (lossy) rolling-history summaries and the trimmed message window,
        so the model always sees the load-bearing facts first regardless of
        how aggressively older turns were summarized.
        """
        msgs: list[dict[str, Any]] = []

        # 1. Durable case-facts first (survive summarization, position-anchored).
        if not self.case_facts.is_empty():
            msgs.append({"role": "system", "content": self.case_facts.render()})

        # 2. Lossy rolling-history summaries.
        if self.summaries:
            summary_text = "\n\n".join(self.summaries)
            msgs.append(
                {
                    "role": "system",
                    "content": f"Previous conversation summary:\n{summary_text}",
                }
            )

        # 3. Trimmed live message window.
        for msg in self.messages:
            if not include_system and msg.role == "system":
                continue
            msgs.append(msg.to_dict())

        return msgs

    def estimate_tokens(self, text: str) -> int:
        """Estimate tokens for the given text.

        If a token_counter is provided, it will be used. Otherwise, uses
        a simple heuristic of ~4 characters per token.
        """
        if not text:
            return 0
        if self.token_counter is not None:
            try:
                return max(0, int(self.token_counter(text)))
            except Exception as exc:
                # Fall back to heuristic if the counter fails.
                logger.debug("token_counter failed; using heuristic: %s", exc)
        return max(1, len(text) // 4)

    @property
    def total_tokens(self) -> int:
        """Estimate total tokens across all stored messages and summaries."""
        msg_tokens = sum(self.estimate_tokens(m.content) for m in self.messages)
        summary_tokens = sum(self.estimate_tokens(s) for s in self.summaries)
        return msg_tokens + summary_tokens

    def _preview(self, text: str, max_chars: int = 160) -> str:
        cleaned = " ".join((text or "").split())
        if len(cleaned) <= max_chars:
            return cleaned
        return cleaned[: max_chars - 3] + "..."

    def _build_summary(self, to_summarize: list[ConversationMessage]) -> str:
        if not to_summarize:
            return ""

        lines: list[str] = []
        for msg in to_summarize:
            if msg.role == "tool":
                tool_name = msg.tool_name or "tool"
                lines.append(f"tool({tool_name}): {self._preview(msg.content)}")
            else:
                lines.append(f"{msg.role}: {self._preview(msg.content)}")

        if not lines:
            return ""

        # Keep summaries bounded and predictable.
        max_lines = 30
        shown = lines[:max_lines]
        omitted = len(lines) - len(shown)
        header = f"[Summary of {len(to_summarize)} messages]"
        if omitted > 0:
            shown.append(f"... ({omitted} more omitted) ...")
        return header + "\n" + "\n".join(shown)

    def _compact_summaries(self) -> None:
        """Bound the number and size of summaries."""
        if len(self.summaries) > self.max_summaries:
            self.summaries = self.summaries[-self.max_summaries :]

        # If summaries alone consume too much budget, drop oldest.
        while self.summaries and sum(
            self.estimate_tokens(s) for s in self.summaries
        ) > (self.max_tokens // 2):
            self.summaries.pop(0)

    def _summarize_and_trim(self) -> None:
        """Summarize older messages and trim history."""
        if not self.messages:
            return

        # Keep a stable core: system prompt (first system message) + most recent messages.
        first_system = next((m for m in self.messages if m.role == "system"), None)

        keep_count = max(4, self.max_messages // 2)
        recent = self.messages[-keep_count:]

        kept: list[ConversationMessage] = []
        if first_system and first_system not in recent:
            kept.append(first_system)
        kept.extend(recent)

        # De-duplicate while preserving order.
        seen: set[int] = set()
        kept_unique: list[ConversationMessage] = []
        for m in kept:
            mid = id(m)
            if mid in seen:
                continue
            seen.add(mid)
            kept_unique.append(m)

        to_summarize = [m for m in self.messages if id(m) not in seen]
        self.messages = kept_unique

        summary = self._build_summary(to_summarize)
        if summary:
            self.summaries.append(summary)
            self._compact_summaries()

        # Enforce token budget by moving oldest non-system messages into a summary.
        extra: list[ConversationMessage] = []
        while self.messages and (
            len(self.messages) > self.max_messages
            or self.total_tokens > self.max_tokens
        ):
            # Prefer to keep the first message if it's system.
            pop_index = (
                1
                if (
                    self.messages
                    and self.messages[0].role == "system"
                    and len(self.messages) > 1
                )
                else 0
            )
            extra.append(self.messages.pop(pop_index))

        extra_summary = self._build_summary(extra)
        if extra_summary:
            self.summaries.append(extra_summary)
            self._compact_summaries()

    def compact(self, keep_recent: int | None = None) -> int:
        """Force a ``/compact``-equivalent summarization of live history.

        Summarizes the older portion of the live message window into a single
        summary block immediately, regardless of whether the size/token
        thresholds have been crossed.  The first system message and the most
        recent ``keep_recent`` messages are preserved; durable case-facts are
        untouched (they are not part of the lossy summary path).

        Args:
            keep_recent: How many trailing messages to keep verbatim.  Defaults
                to ``max(2, max_messages // 4)`` for an aggressive compaction.

        Returns:
            The number of messages folded into a summary (0 if nothing to do).
        """
        if not self.messages:
            return 0

        if keep_recent is None:
            keep_recent = max(2, self.max_messages // 4)
        keep_recent = max(0, keep_recent)

        first_system = next((m for m in self.messages if m.role == "system"), None)
        recent = self.messages[-keep_recent:] if keep_recent else []

        kept: list[ConversationMessage] = []
        if first_system and first_system not in recent:
            kept.append(first_system)
        kept.extend(recent)

        seen: set[int] = set()
        kept_unique: list[ConversationMessage] = []
        for m in kept:
            mid = id(m)
            if mid in seen:
                continue
            seen.add(mid)
            kept_unique.append(m)

        to_summarize = [m for m in self.messages if id(m) not in seen]
        if not to_summarize:
            return 0

        self.messages = kept_unique
        summary = self._build_summary(to_summarize)
        if summary:
            self.summaries.append(summary)
            self._compact_summaries()
        return len(to_summarize)

    def to_manifest(self) -> dict[str, Any]:
        """Serialize the full buffer state to a crash-recovery manifest.

        The manifest is a JSON-serializable mapping capturing the live message
        window, the rolling summaries, the durable case-facts, and the buffer
        configuration.  It is the durable counterpart to a process that may
        crash mid-run: :meth:`from_manifest` rehydrates an equivalent buffer.
        """
        return {
            "version": MANIFEST_VERSION,
            "saved_at": datetime.now(UTC).isoformat(),
            "config": {
                "max_messages": self.max_messages,
                "max_tokens": self.max_tokens,
                "max_summaries": self.max_summaries,
            },
            "messages": [m.to_manifest() for m in self.messages],
            "summaries": list(self.summaries),
            "case_facts": self.case_facts.to_manifest(),
        }

    def to_manifest_json(self) -> str:
        """Serialize :meth:`to_manifest` to a JSON string."""
        return json.dumps(self.to_manifest(), default=str)

    @classmethod
    def from_manifest(
        cls,
        manifest: dict[str, Any],
        token_counter: Callable[[str], int] | None = None,
    ) -> ConversationMemory:
        """Rehydrate a buffer from a crash-recovery manifest.

        Args:
            manifest: A mapping produced by :meth:`to_manifest`.
            token_counter: Optional token counter to re-attach (counters are
                not serializable, so they must be supplied on restore).

        Returns:
            A new :class:`ConversationMemory` equivalent to the saved one.

        Raises:
            ValueError: If the manifest version is unsupported.
        """
        version = manifest.get("version")
        if version != MANIFEST_VERSION:
            raise ValueError(
                f"Unsupported manifest version {version!r}; expected {MANIFEST_VERSION}"
            )

        config = manifest.get("config") or {}
        messages = [
            ConversationMessage.from_manifest(m)
            for m in (manifest.get("messages") or [])
        ]
        case_facts_data = manifest.get("case_facts") or {}

        return cls(
            messages=messages,
            max_messages=int(config.get("max_messages", 50)),
            max_tokens=int(config.get("max_tokens", 8000)),
            summaries=list(manifest.get("summaries") or []),
            max_summaries=int(config.get("max_summaries", 5)),
            token_counter=token_counter,
            case_facts=CaseFacts.from_manifest(case_facts_data),
        )

    @classmethod
    def from_manifest_json(
        cls,
        manifest_json: str,
        token_counter: Callable[[str], int] | None = None,
    ) -> ConversationMemory:
        """Rehydrate a buffer from a JSON manifest string."""
        return cls.from_manifest(json.loads(manifest_json), token_counter)

    def clear(self) -> None:
        """Clear all history (durable case-facts are also reset)."""
        self.messages.clear()
        self.summaries.clear()
        self.case_facts = CaseFacts()

    @property
    def last_message(self) -> ConversationMessage | None:
        """Get the last message."""
        return self.messages[-1] if self.messages else None
