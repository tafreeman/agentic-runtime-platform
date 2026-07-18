"""Prompt versioning registry (WP3-A).

Centralizes prompt content behind a single frozen, content-addressed
record so that every prompt consumer -- the role-based persona lookup in
:mod:`agentic_v2.engine.prompt_assembly`, the legacy
:func:`agentic_v2.prompts.load_prompt` API, and the inline judge prompt in
:mod:`agentic_v2.scoring.judge` -- can report a fingerprint that actually
changes when the prompt content changes, instead of a hand-maintained
version string that never drifts on its own.

See ``docs/adr/ADR-056-prompt-versioning-registry.md`` for the design
rationale.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from hashlib import sha256
from pathlib import Path

# ---------------------------------------------------------------------------
# Normalization + hashing
# ---------------------------------------------------------------------------


def normalize_prompt_text(raw: str) -> str:
    r"""Normalize line endings to LF.

    Defends against two independent sources of line-ending drift: a
    Windows editor re-introducing CRLF in a working tree that
    ``.gitattributes`` pins to ``eol=lf``, and any caller that reads a file
    in binary mode (bypassing Python's own universal-newline translation).

    Args:
        raw: Prompt text in any line-ending convention.

    Returns:
        The same text with ``\r\n`` and bare ``\r`` replaced by ``\n``.
    """
    return raw.replace("\r\n", "\n").replace("\r", "\n")


def compute_content_hash(text: str) -> str:
    """Compute a stable content fingerprint for prompt text.

    The text is LF-normalized before hashing so that a CRLF vs. LF
    checkout of the same logical prompt never produces a different
    fingerprint.

    Args:
        text: Prompt text to fingerprint.

    Returns:
        Hex-encoded SHA-256 digest of the normalized, UTF-8-encoded text.
    """
    normalized = normalize_prompt_text(text)
    return sha256(normalized.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# PromptRecord
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class PromptRecord:
    """Immutable, content-addressed record of one registered prompt.

    Attributes:
        name: Registry key (e.g. ``"reviewer"``, ``"judge"``).
        declared_version: Human-assigned version tag (e.g. ``"v1"``,
            ``"judge-v1"``) -- does not change automatically with content.
        content: LF-normalized prompt text.
        content_sha256: :func:`compute_content_hash` of ``content``.
        source: Provenance tag, either ``"file:<basename>"`` for
            file-backed prompts or ``"inline:<name>"`` for prompts defined
            directly in Python source.
    """

    name: str
    declared_version: str
    content: str
    content_sha256: str
    source: str

    @property
    def short_hash(self) -> str:
        """Return the first 8 hex characters of :attr:`content_sha256`."""
        return self.content_sha256[:8]

    @property
    def qualified_version(self) -> str:
        """Return the fingerprinted version: ``{declared_version}@{short_hash}``."""
        return f"{self.declared_version}@{self.short_hash}"


# ---------------------------------------------------------------------------
# PromptRegistry
# ---------------------------------------------------------------------------


class PromptRegistry:
    """In-memory registry mapping prompt names to :class:`PromptRecord`.

    Registration is explicit and content-addressed: callers register a
    prompt's raw text (inline or file-backed) and receive back a frozen
    record carrying a fingerprint that changes if and only if the
    underlying content changes.
    """

    def __init__(self) -> None:
        self._records: dict[str, PromptRecord] = {}

    def register_inline(
        self, name: str, text: str, *, declared_version: str
    ) -> PromptRecord:
        """Register prompt text defined directly in Python source.

        Args:
            name: Registry key.
            text: Raw prompt text.
            declared_version: Human-assigned version tag.

        Returns:
            The newly created, frozen :class:`PromptRecord`.
        """
        normalized = normalize_prompt_text(text)
        record = PromptRecord(
            name=name,
            declared_version=declared_version,
            content=normalized,
            content_sha256=compute_content_hash(normalized),
            source=f"inline:{name}",
        )
        self._records[name] = record
        return record

    def register_file(
        self, name: str, path: Path, *, declared_version: str
    ) -> PromptRecord:
        """Register prompt text read from a Markdown file.

        Args:
            name: Registry key.
            path: Path to the prompt file, read as UTF-8.
            declared_version: Human-assigned version tag.

        Returns:
            The newly created, frozen :class:`PromptRecord`.
        """
        raw = path.read_text(encoding="utf-8")
        normalized = normalize_prompt_text(raw)
        record = PromptRecord(
            name=name,
            declared_version=declared_version,
            content=normalized,
            content_sha256=compute_content_hash(normalized),
            source=f"file:{path.name}",
        )
        self._records[name] = record
        return record

    def get(self, name: str) -> PromptRecord:
        """Return the record for *name*.

        Raises:
            KeyError: If *name* was never registered.
        """
        return self._records[name]

    def get_or_none(self, name: str) -> PromptRecord | None:
        """Return the record for *name*, or ``None`` if unregistered."""
        return self._records.get(name)

    def text(self, name: str) -> str:
        """Return the LF-normalized content for *name*.

        Raises:
            KeyError: If *name* was never registered.
        """
        return self.get(name).content

    def records(self) -> tuple[PromptRecord, ...]:
        """Return every registered record as an immutable tuple snapshot."""
        return tuple(self._records.values())

    def names(self) -> list[str]:
        """Return every registered prompt name."""
        return list(self._records.keys())


# ---------------------------------------------------------------------------
# Default registry: the 7 role persona prompts
# ---------------------------------------------------------------------------

#: Declared version per role prompt. New roles default to "v1" until a
#: content change warrants bumping the declared tag; the fingerprint
#: (:attr:`PromptRecord.qualified_version`) still changes automatically
#: whenever the underlying Markdown content changes.
PROMPT_VERSIONS: dict[str, str] = {
    "architect": "v1",
    "coder": "v1",
    "orchestrator": "v1",
    "planner": "v1",
    "reviewer": "v1",
    "tester": "v1",
    "validator": "v1",
}

_PROMPTS_DIR = Path(__file__).parent


@lru_cache(maxsize=1)
def default_registry() -> PromptRegistry:
    """Return the process-wide singleton registry of role persona prompts.

    Auto-registers the 7 ``prompts/<role>.md`` files using
    :data:`PROMPT_VERSIONS` for their declared versions. Cached so every
    caller shares one registry instance and each file is read exactly
    once per process.
    """
    registry = PromptRegistry()
    for role_name, declared_version in PROMPT_VERSIONS.items():
        registry.register_file(
            role_name,
            _PROMPTS_DIR / f"{role_name}.md",
            declared_version=declared_version,
        )
    return registry


__all__ = [
    "PROMPT_VERSIONS",
    "PromptRecord",
    "PromptRegistry",
    "compute_content_hash",
    "default_registry",
    "normalize_prompt_text",
]
