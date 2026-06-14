# ADR-028: Tool descriptions are the primary tool-selection mechanism

**Status:** Accepted
**Date:** 2026-06-13
**Related:** [ADR-027](ADR-027-forced-tool-choice.md) (forced / `any` `tool_choice`), [ADR-001](ADR-001-002-003-architecture-decisions.md) (native engine / tool loop)

---

## Context

When a step exposes more than one tool, the model chooses which to call almost
entirely from each tool's **`description`** (and secondarily its parameter
descriptions and `name`) — that text is what the engine serializes into the
provider's tool schema. ARP's builtin tools shipped with terse, overlapping
one-liners: `search` was "Search for patterns in files using regex, fuzzy
matching, or semantic search" while `grep` was "Quick grep-like search for
patterns in files"; `file_copy` and `file_move` differed by a single verb;
`git`, `git_status`, and `git_diff` (and the `http`/`http_get`/`http_post` and
`memory_*` families) read almost identically. Near-duplicate descriptions give
the model no signal to disambiguate, so it picks arbitrarily — a silent
correctness and cost problem that no amount of `tool_choice` plumbing
(ADR-027) fixes, because forcing presupposes you already know which tool is
right.

## Decision

**Treat the tool `description` as the primary tool-selection mechanism and hold
every builtin description to an input-format / edge-case / when-to-prefer-which
standard.** A good description states: what the tool does, the exact input
formats it accepts (and how each is interpreted), representative example
queries, the edge cases and boundaries (failure modes, caps, what it will *not*
do), and — for any tool whose domain overlaps a sibling — explicit guidance on
which to prefer and why. The flagship `search` vs `grep` pair was rewritten
first (regex/fuzzy/semantic vs verbatim-literal recursive sweep, with mutual
cross-references), and the same standard was applied across the `file_ops`,
`git_ops`, `http_ops`, `shell_ops`, `code_analysis`, and `memory_ops` families.
The invariant is enforced by
`tests/test_tool_description_disambiguation.py`, which fails if any two builtin
descriptions are near-identical (word-set Jaccard ≥ 0.6) or if any overlapping
tool omits its when-to-prefer guidance. `verify_fact` (ADR-027) already met this
bar and is the reference shape.

## Consequences

- **Positive:** The model has a real basis to route between overlapping tools;
  a regression toward terse, ambiguous descriptions now breaks CI rather than
  degrading selection silently.
- **Positive:** Descriptions double as authoritative human documentation of each
  tool's contract, edge cases, and intended use.
- **Neutral:** No behavior, signature, or wire-format change — only description
  text and one new test; existing description-keyword assertions still hold.
- **Negative:** Richer descriptions cost more prompt tokens per exposed tool, and
  the no-near-duplicate test adds a light authoring constraint when introducing a
  new builtin (it must differentiate itself from its neighbors).
