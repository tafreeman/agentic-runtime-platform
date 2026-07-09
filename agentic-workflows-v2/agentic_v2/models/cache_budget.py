"""Token budget and response cache data structures.

Extracted from ``client.py`` so these pure data classes are independently
testable and the coverage gate applies to them.

Public surface:
    ``TokenBudget``            — per-run token cap (reservation model)
    ``ProcessWideTokenBudget`` — cumulative always-accumulating cap (ADR-048)
    ``CachedResponse``         — single cached LLM response with TTL metadata
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass
class TokenBudget:
    """Track token usage against a per-run cap.

    Attributes:
        max_tokens: Hard ceiling on total tokens consumed.
        used_tokens: Tokens consumed so far.
    """

    max_tokens: int
    used_tokens: int = 0

    @property
    def remaining(self) -> int:
        """Remaining tokens (floored at 0)."""
        return max(0, self.max_tokens - self.used_tokens)

    @property
    def percentage_used(self) -> float:
        """Fraction of budget consumed as a percentage (0–100)."""
        if self.max_tokens == 0:
            return 100.0
        return (self.used_tokens / self.max_tokens) * 100

    def consume(self, tokens: int) -> bool:
        """Consume *tokens* from the budget.

        Returns:
            ``True`` if the budget had enough headroom; ``False`` if the cap
            would be exceeded (tokens are NOT consumed in that case).
        """
        if self.used_tokens + tokens > self.max_tokens:
            return False
        self.used_tokens += tokens
        return True

    def can_afford(self, tokens: int) -> bool:
        """Check whether *tokens* can be consumed without exceeding the cap."""
        return self.used_tokens + tokens <= self.max_tokens


class ProcessWideTokenBudget(TokenBudget):
    """A cumulative, process-wide token budget that ALWAYS records spend.

    :class:`TokenBudget` is a per-run *reservation* model: ``consume`` declines
    — and does NOT record — a charge that would exceed the cap. That is wrong
    for the process-wide budget armed on the shared client singleton (ADR-048),
    whose ``consume`` runs on the *post-dispatch* accounting paths where the
    tokens are already spent upstream. There a plain ``TokenBudget`` leaves an
    overrun unrecorded, so ``used_tokens`` stays below reality and the next
    pre-flight ``can_afford`` check under-counts — making the cap bypassable.

    This subclass always accumulates, so an actual overrun is recorded and
    exhausts the cap for every subsequent call (a real circuit breaker).
    """

    def consume(self, tokens: int) -> bool:
        """Record *tokens* as spent; report whether the cap still holds.

        Always accumulates (the tokens are already spent upstream), unlike
        :meth:`TokenBudget.consume`. Returns ``False`` once cumulative usage
        exceeds ``max_tokens`` so the checked call sites can raise, while the
        pre-flight ``can_afford`` gate blocks the following call outright.
        """
        self.used_tokens += tokens
        return self.used_tokens <= self.max_tokens


@dataclass
class CachedResponse:
    """A single cached LLM response.

    Attributes:
        response: The cached response text (or serialised dict for chat).
        model: The model that produced this response.
        timestamp: UTC wall-clock time when the entry was stored.
        tokens_used: Token count recorded at cache-store time.
    """

    response: str
    model: str
    timestamp: datetime
    tokens_used: int

    @property
    def age_seconds(self) -> float:
        """Wall-clock age of this cache entry in seconds."""
        return (datetime.now(UTC) - self.timestamp).total_seconds()
