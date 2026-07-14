# ADR-053: memoryctl — deterministic maintenance core for agent memory

**Status:** Accepted
**Date:** 2026-07-14

## Context

The agent context system design (maintained in a separate private
workspace) defines a file-based, self-managed memory layer for Claude
Code agents:
topic files with YAML frontmatter, a generated `MEMORY.md` index, and a
maintenance loop (validate, index, links, budget, staleness, verify,
dedupe, archive, stats, report). The design's core principle is
**deterministic before generative** — every maintenance operation that
can be a script is a script (the design maps this onto
`ModelTier.TIER_0`); LLM calls are reserved for judgment (semantic
dedupe, consolidation splits) and consume the findings queue this
subsystem emits.

## Decision

Add `agentic_v2/memoryctl/`: a self-contained package of command
modules sharing one contract (`_shared.py`), exposed as a Typer CLI
(`memoryctl` script entry, `python -m agentic_v2.memoryctl`). Zero LLM
calls anywhere in the package.

Key semantics a future contributor might challenge:

- **Harvest-then-regenerate index.** Claude Code's native auto-memory
  writes `MEMORY.md` without memoryctl's advisory lock, so `index`
  never blind-overwrites: unindexed lines are preserved into a single
  `harvested-<date>.md` topic file per run (one file, not one per line —
  a rich hand-written index must not be shredded; the weekly LLM
  consolidation pass splits it with context).
- **Older-signal-wins staleness.** Doc freshness is the *older* of
  git-last-commit date and mtime: an initial tracking commit must not
  launder a stale mtime into freshness. Tuned recall-first; false
  positives are cheap (verified downstream), misses rot silently.
- **`verify:` commands run with `shell=True`.** Frontmatter verify
  commands are user-authored shell snippets in the same trust domain as
  hooks; the executor is the point of the feature.
- **Stats are idempotent by run-id and rotation is guarded.** `archive`
  refuses to rotate any run directory whose id is not already reduced
  into `registry/stats.json` — learning data is never destroyed before
  it is aggregated.
- **Hand-deleting a topic file leaves a dangling index line** that the
  next `index` run harvests (by design — dangling lines may carry
  meaning). Deletions should flow through `archive`
  (supersede/tombstone), which regenerates the index in the same lock
  cycle.

## Consequences

- The weekly LLM consolidation pass (design §5.4) consumes
  `reports/<date>/findings.jsonl`; its writes are the only non-
  deterministic mutations in the system, and they happen outside this
  package.
- FileLock is advisory and only coordinates memoryctl-vs-memoryctl;
  concurrent Claude Code sessions are tolerated via harvest semantics,
  not excluded.
- 111 unit tests, 94% package coverage; no network, no git fixtures
  (date sources are monkeypatch seams in `_shared`).
