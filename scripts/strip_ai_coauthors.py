#!/usr/bin/env python3
"""Strip AI-assistant authorship trailers from a commit message.

Runs as a ``commit-msg`` hook. It removes *only* the trailers that mark this
repository's AI coding assistant (Claude / Claude Code) as a co-author or
generator. It deliberately leaves every other ``Co-authored-by`` line intact --
human collaborators and the legitimate bots that actually open PRs here
(``dependabot``, ``gemini-code-assist``, ``copilot``) are preserved, because
those records are accurate and useful.

Rationale: authorship metadata on this repo should reflect who is accountable
for the architectural decisions. The assistant pair-programs, but the decisions
and the authorship are the maintainer's. See CONTRIBUTING.md.

Usage (invoked automatically by the hook):
    python scripts/strip_ai_coauthors.py <path-to-commit-msg-file>
"""

from __future__ import annotations

import re
import sys

# A Co-authored-by line is dropped only when it names the AI assistant:
#   - any name beginning with "Claude" (Claude, Claude Opus 4.8, Claude Sonnet...)
#   - the Anthropic no-reply identity
_AI_COAUTHOR = re.compile(
    r"^\s*co-authored-by:\s*(?:claude\b|.*<[^>]*noreply@anthropic\.com>)",
    re.IGNORECASE,
)

# The "Generated with Claude Code" footer (with or without the robot emoji),
# and a lone robot-emoji line left dangling once the footer is gone.
_GENERATED_FOOTER = re.compile(
    r"^\s*(?:\U0001F916\s*)?generated with\s*\[?claude code\]?",
    re.IGNORECASE,
)
_LONE_ROBOT = re.compile(r"^\s*\U0001F916\s*$")


def _strip(lines: list[str]) -> list[str]:
    kept = [
        ln
        for ln in lines
        if not (
            _AI_COAUTHOR.match(ln)
            or _GENERATED_FOOTER.match(ln)
            or _LONE_ROBOT.match(ln)
        )
    ]
    # Collapse any trailing blank lines created by the removal.
    while len(kept) > 1 and kept[-1].strip() == "" and kept[-2].strip() == "":
        kept.pop()
    return kept


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        sys.stderr.write("usage: strip_ai_coauthors.py <commit-msg-file>\n")
        return 2
    path = argv[1]
    with open(path, encoding="utf-8") as fh:
        original = fh.read().splitlines()
    cleaned = _strip(original)
    if cleaned != original:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("\n".join(cleaned).rstrip("\n") + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
