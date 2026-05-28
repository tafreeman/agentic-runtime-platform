"""Conversation memory primitives for agent history management.

Provides the :class:`ConversationMessage` and :class:`ConversationMemory`
classes used by :class:`~agentic_v2.agents.base.BaseAgent` to maintain
bounded, summarised conversation history across LLM turns.

Key abstractions:
    ConversationMessage:
        Immutable, frozen dataclass representing a single turn in the
        conversation (user, assistant, system, or tool role).

    ConversationMemory:
        Sliding-window buffer that automatically summarises and evicts
        older messages when the window exceeds ``max_messages`` or the
        estimated ``max_tokens`` budget.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable


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
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
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


@dataclass
class ConversationMemory:
    """Sliding-window conversation buffer with automatic summarization.

    Maintains a bounded list of :class:`ConversationMessage` instances.  When
    the window exceeds ``max_messages`` or ``max_tokens``, older messages are
    compressed into textual summaries and evicted.  System messages and recent
    context are preserved during compaction.

    Attributes:
        messages: The current message window.
        max_messages: Maximum number of messages before summarization triggers.
        max_tokens: Approximate token budget for messages plus summaries.
        summaries: Accumulated textual summaries of evicted messages.
        max_summaries: Maximum number of summary blocks to retain.
        token_counter: Optional callable for precise token counting.  Falls
            back to a ``len(text) // 4`` heuristic when ``None``.
    """

    messages: list[ConversationMessage] = field(default_factory=list)
    max_messages: int = 50
    max_tokens: int = 8000
    summaries: list[str] = field(default_factory=list)
    max_summaries: int = 5
    token_counter: Callable[[str], int] | None = None

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

    def get_messages(self, include_system: bool = True) -> list[dict[str, Any]]:
        """Get messages for LLM API."""
        msgs = []

        # Add summaries as system context if available
        if self.summaries:
            summary_text = "\n\n".join(self.summaries)
            msgs.append(
                {
                    "role": "system",
                    "content": f"Previous conversation summary:\n{summary_text}",
                }
            )

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
            except Exception:
                # Fall back to heuristic if the counter fails.
                pass
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

    def clear(self) -> None:
        """Clear all history."""
        self.messages.clear()
        self.summaries.clear()

    @property
    def last_message(self) -> ConversationMessage | None:
        """Get the last message."""
        return self.messages[-1] if self.messages else None
