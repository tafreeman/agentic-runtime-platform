"""LLM model-family ranking service.

Ranks model *families* (provider- and size-agnostic model names such as
``qwen3-coder`` or ``gpt-4o``) for agentic coding-workflow use by asking a
ranker model to score each family against its current public standing
(LMArena/Chatbot Arena, Artificial Analysis, SWE-bench and coding
leaderboards, provider announcements).

Honesty rule: a ranking payload always carries its provenance — the ranker
model id (``ranked_with``), whether web-search grounding was actually active
(``grounded``), and when the cache was produced (``updated_at``). Consumers
must never render a score as a live fact without all three.

The cache is a small JSON document at ``<repo>/.agentic_model_rankings.json``
(anchored at the repo root like ``ui_settings``  — never the process CWD).
Override with ``AGENTIC_MODEL_RANKINGS_PATH`` (used by tests). Writes are
atomic (tempfile + ``os.replace``) so concurrent readers see either the old
or the new document, never a torn one.

LLM replies are parsed with the shared lenient-JSON extraction from
:mod:`agentic_v2.engine.llm_output_parsing` — this repo forbids new local
LLM-output parsers.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from ..engine.llm_output_parsing import extract_json_candidates

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Repo-root cache location (mirrors ``ui_settings._DEFAULT_SETTINGS_PATH``).
_DEFAULT_RANKINGS_PATH = (
    Path(__file__).resolve().parents[3] / ".agentic_model_rankings.json"
)

#: Ranker used when neither the request nor the environment names one.
#: gemini-2.5-flash is live-verified working on this deployment via /api/chat.
DEFAULT_RANKER_MODEL = "gemini:gemini-2.5-flash"

#: Cache entries older than this are considered stale by the autorank route.
RANKINGS_MAX_AGE = timedelta(days=7)

#: Maximum family names sent to the ranker per call.
RANKING_BATCH_SIZE = 40

#: Hard cap on the per-family reasoning string persisted to the cache.
MAX_REASONING_LEN = 140

#: Provider prefixes stripped by family normalization (contract rule 2).
_KNOWN_PROVIDER_PREFIXES = frozenset(
    {
        "ollama",
        "openai",
        "nvidia",
        "gh",
        "gemini",
        "anthropic",
        "claude",
        "openrouter",
        "onnx",
        "lmstudio",
        "local",
        "local-api",
        "notebooklm",
    }
)

#: Google Search grounding tool in the dict form the installed
#: langchain-google-genai (2.1.x) accepts for ``ChatGoogleGenerativeAI``.
_GOOGLE_SEARCH_TOOL: dict[str, Any] = {"google_search": {}}

RANKING_SYSTEM_PROMPT = (
    "You rank LLM model families for agentic coding-workflow use by their "
    "CURRENT public standing (LMArena/Chatbot Arena, Artificial Analysis, "
    "SWE-bench and coding leaderboards, provider announcements). For every "
    "family in the list, return an integer score 0-100 and a reasoning of at "
    "most 140 characters naming the basis. For unknown or obscure families "
    "return a low score with reasoning 'no public benchmark presence found'. "
    "Reply with a STRICT JSON array of objects "
    '[{"family": str, "score": int, "reasoning": str}] and nothing else.'
)

RankingStatus = Literal["empty", "running", "ready", "failed"]

# ---------------------------------------------------------------------------
# Wire-shape models
# ---------------------------------------------------------------------------


class FamilyRanking(BaseModel):
    """Score and provenance-bearing reasoning for one model family."""

    score: int
    reasoning: str


class RankingsPayload(BaseModel):
    """The full rankings cache document — identical to the GET wire shape."""

    status: RankingStatus = "empty"
    ranked_with: str | None = None
    grounded: bool | None = None
    updated_at: str | None = None
    error: str | None = None
    families: dict[str, FamilyRanking] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Family-key normalization (shared wire contract)
# ---------------------------------------------------------------------------


def normalize_family(model_id: str) -> str:
    """Normalize a prefixed model id to its family key.

    Contract rules (identical on the UI side):

    1. lowercase the id;
    2. if the segment before the first ``:`` is a known provider prefix,
       drop it and the ``:``;
    3. drop any org path up to and including the last ``/``;
    4. keep only the part before the next ``:`` (drops size/quant tags).

    Examples: ``ollama:qwen3-coder:30b`` -> ``qwen3-coder``;
    ``nvidia:deepseek-ai/deepseek-v4-flash`` -> ``deepseek-v4-flash``;
    ``hf.co/lmstudio-community/qwen3.6-27b-gguf:q8_0`` -> ``qwen3.6-27b-gguf``.
    """
    family = model_id.strip().lower()
    prefix, sep, rest = family.partition(":")
    if sep and prefix in _KNOWN_PROVIDER_PREFIXES:
        family = rest
    slash = family.rfind("/")
    if slash != -1:
        family = family[slash + 1 :]
    return family.partition(":")[0].strip()


# ---------------------------------------------------------------------------
# Cache store (mirrors ui_settings: env override + atomic replace)
# ---------------------------------------------------------------------------


def get_rankings_path() -> Path:
    """Resolve the rankings cache path (env override wins)."""
    override = (os.environ.get("AGENTIC_MODEL_RANKINGS_PATH") or "").strip()
    if override:
        return Path(override)
    return _DEFAULT_RANKINGS_PATH


def load_rankings(path: Path | None = None) -> RankingsPayload:
    """Load the rankings cache, returning the empty shape when absent/invalid.

    A corrupt file is logged and treated as empty rather than failing the
    request path — the next autorank run re-writes a clean document.
    """
    rankings_path = path or get_rankings_path()
    if not rankings_path.exists():
        return RankingsPayload()
    try:
        data = json.loads(rankings_path.read_text(encoding="utf-8"))
        return RankingsPayload.model_validate(data)
    except (OSError, ValueError) as exc:
        logger.warning("Ignoring invalid rankings cache at %s: %s", rankings_path, exc)
        return RankingsPayload()


def save_rankings(payload: RankingsPayload, path: Path | None = None) -> Path:
    """Atomically persist the rankings document and return its path."""
    rankings_path = path or get_rankings_path()
    rankings_path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(payload.model_dump(mode="json"), indent=2, sort_keys=False)
    fd, tmp_name = tempfile.mkstemp(
        dir=str(rankings_path.parent), prefix=rankings_path.name, suffix=".tmp"
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(serialized)
        os.replace(tmp_name, rankings_path)
    except OSError:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise
    return rankings_path


def rankings_cache_is_fresh(
    payload: RankingsPayload,
    max_age: timedelta = RANKINGS_MAX_AGE,
    now: datetime | None = None,
) -> bool:
    """Return True when *payload* is a ready cache younger than *max_age*."""
    if payload.status != "ready" or not payload.updated_at:
        return False
    try:
        updated = datetime.fromisoformat(payload.updated_at)
    except ValueError:
        return False
    if updated.tzinfo is None:
        updated = updated.replace(tzinfo=UTC)
    reference = now or datetime.now(UTC)
    return (reference - updated) <= max_age


# ---------------------------------------------------------------------------
# Ranker resolution and prompt building
# ---------------------------------------------------------------------------


def resolve_ranker_model(explicit: str | None = None) -> str:
    """Resolve the ranker id: explicit arg -> env -> default.

    Precedence: the caller's explicit model, then ``AGENTIC_RANKING_MODEL``,
    then :data:`DEFAULT_RANKER_MODEL`.
    """
    if explicit and explicit.strip():
        return explicit.strip()
    env_model = (os.environ.get("AGENTIC_RANKING_MODEL") or "").strip()
    if env_model:
        return env_model
    return DEFAULT_RANKER_MODEL


def batch_families(
    families: Sequence[str], batch_size: int = RANKING_BATCH_SIZE
) -> list[list[str]]:
    """Split *families* into order-preserving batches of at most *batch_size*."""
    if batch_size < 1:
        raise ValueError(f"batch_size must be >= 1, got {batch_size}")
    return [
        list(families[start : start + batch_size])
        for start in range(0, len(families), batch_size)
    ]


def build_ranking_prompt(batch: Sequence[str]) -> str:
    """Build the human-turn prompt listing one batch of family names."""
    return (
        "Rank the following model families. Return one entry per family, "
        "using these exact family strings:\n" + json.dumps(list(batch))
    )


# ---------------------------------------------------------------------------
# Autorank execution
# ---------------------------------------------------------------------------


def _default_model_factory(model_id: str) -> Any:
    """Build the ranker via the same entry point the /api/chat playground uses."""
    from ..langchain.models import get_chat_model

    return get_chat_model(model_id, temperature=0.0)


def _content_to_text(content: Any) -> str:
    """Flatten a chat reply ``content`` (string or content blocks) to text."""
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return str(content)
    parts: list[str] = []
    for block in content:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict) and isinstance(block.get("text"), str):
            parts.append(block["text"])
    return "".join(parts)


def _invoke_ranker(
    model: Any, ranker_model: str, batch: Sequence[str]
) -> tuple[str, bool]:
    """Send one batch to the ranker; return ``(reply_text, grounded)``.

    For ``gemini:`` rankers a Google Search grounding attempt is made first;
    any failure falls back to a plain ungrounded call so ``grounded`` is True
    only when the grounding path actually produced the reply.
    """
    messages: list[tuple[str, str]] = [
        ("system", RANKING_SYSTEM_PROMPT),
        ("human", build_ranking_prompt(batch)),
    ]
    if ranker_model.strip().lower().startswith("gemini:"):
        try:
            reply = model.invoke(messages, tools=[_GOOGLE_SEARCH_TOOL])
            return _content_to_text(getattr(reply, "content", reply)), True
        except Exception as exc:
            logger.warning(
                "Gemini web grounding failed for %s; retrying ungrounded: %s",
                ranker_model,
                exc,
            )
    reply = model.invoke(messages)
    return _content_to_text(getattr(reply, "content", reply)), False


def _parse_ranking_entries(reply_text: str) -> list[dict[str, Any]]:
    """Extract the ranking array from a possibly fenced/dirty model reply.

    Reuses the shared lenient-JSON candidate generation
    (:func:`extract_json_candidates`) — the array bracket-span candidate also
    recovers arrays wrapped in prose or an enclosing object.
    """
    for candidate in extract_json_candidates(reply_text):
        try:
            parsed = json.loads(candidate, strict=False)
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, list):
            return [entry for entry in parsed if isinstance(entry, dict)]
    return []


def _coerce_score(raw: Any) -> int | None:
    """Coerce a raw score to an int clamped to [0, 100]; None when unusable."""
    try:
        value = round(float(raw))
    except (TypeError, ValueError, OverflowError):
        return None
    return max(0, min(100, value))


def _rankings_from_entries(
    entries: Sequence[dict[str, Any]], batch: Sequence[str]
) -> dict[str, FamilyRanking]:
    """Keep only well-formed entries whose family was actually requested."""
    allowed = set(batch)
    rankings: dict[str, FamilyRanking] = {}
    for entry in entries:
        family = str(entry.get("family", "")).strip().lower()
        if family not in allowed or family in rankings:
            continue
        score = _coerce_score(entry.get("score"))
        if score is None:
            continue
        reasoning = str(entry.get("reasoning", "")).strip()[:MAX_REASONING_LEN]
        rankings[family] = FamilyRanking(score=score, reasoning=reasoning)
    return rankings


def _dedupe_families(families: Sequence[str]) -> list[str]:
    """Return lowercased, order-preserving, non-empty unique family names."""
    seen: set[str] = set()
    unique: list[str] = []
    for name in families:
        family = name.strip().lower()
        if family and family not in seen:
            seen.add(family)
            unique.append(family)
    return unique


def run_autorank(
    families: Sequence[str],
    ranker_model: str,
    *,
    model_factory: Callable[[str], Any] | None = None,
) -> RankingsPayload:
    """Rank *families* with *ranker_model* and return the cache payload.

    Family names are deduped, sent in batches of at most
    :data:`RANKING_BATCH_SIZE`, parsed leniently, clamped to [0, 100], and
    merged. ``grounded`` is True only when EVERY batch was answered through
    the web-grounding path; provenance (``ranked_with``/``updated_at``) is
    always recorded per the honesty rule.

    ``model_factory`` exists for deterministic tests; production callers use
    the default (``langchain.models.get_chat_model``, the same entry the
    /api/chat playground uses).
    """
    factory = model_factory or _default_model_factory
    model = factory(ranker_model)
    requested = _dedupe_families(families)

    merged: dict[str, FamilyRanking] = {}
    all_grounded = bool(requested)
    for batch in batch_families(requested):
        reply_text, batch_grounded = _invoke_ranker(model, ranker_model, batch)
        all_grounded = all_grounded and batch_grounded
        entries = _parse_ranking_entries(reply_text)
        merged.update(_rankings_from_entries(entries, batch))

    logger.info(
        "Autorank complete: ranker=%s, requested=%d, scored=%d, grounded=%s",
        ranker_model,
        len(requested),
        len(merged),
        all_grounded,
    )
    return RankingsPayload(
        status="ready",
        ranked_with=ranker_model,
        grounded=all_grounded,
        updated_at=datetime.now(UTC).isoformat(),
        error=None,
        families=merged,
    )
