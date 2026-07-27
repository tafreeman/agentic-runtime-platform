# ADR-026: `--resume` and `fork_session` — and why a summary-seeded session often wins

**Status:** Accepted
**Date:** 2026-06-13
**Related:** [ADR-025](ADR-025-sdk-task-orchestration.md) (SDK `Task` orchestration), [ADR-001](ADR-001-002-003-architecture-decisions.md) (native engine / `ExecutionContext`)

---

## Context

`ExecutionContext` already supports `save_checkpoint` / `restore_checkpoint` for
fault tolerance and `child()` for hierarchical scoping
(`agentic_v2/engine/context.py`). Two SDK-native session primitives had no ARP
counterpart:

- **Resume** — rehydrating a named checkpoint to continue a prior run.
- **`fork_session`** — branching a *divergent* trajectory off a shared baseline
  without mutating the original.

A subtle hazard of resume specifically: a checkpoint captures variable state and
step status, but the **world the run observed may have moved on**. Files the
agent read and reasoned about can change on disk between sessions. Resuming
blindly carries *stale tool results* forward — the agent acts on a snapshot of
`config.txt` that no longer reflects reality.

---

## Decision

Add three thin capabilities on top of the existing checkpoint machinery:

1. **`agentic resume <name>` CLI command** (`cli/main.py`) — rehydrates
   `<checkpoint-dir>/<name>.json` into a fresh `ExecutionContext`, prints run
   status, and surfaces the changed-file notice.
2. **`ExecutionContext.fork_session(name)`** — branches a divergent run via
   `child()`, assigning a fresh `run_id` and recording
   `metadata["fork_name"]` / `metadata["forked_from_run"]` lineage. Writes in
   the fork never touch the baseline.
3. **On-resume changed-file detection** — `save_checkpoint(tracked_files=[...])`
   records a sha256 per tracked file; `detect_changed_files(checkpoint_path)`
   diffs current content against the recorded fingerprints, and
   `build_changed_files_notice(...)` renders a "these files changed; re-read
   them" string and surfaces it for the caller/operator to prepend to a resumed
   prompt (the helper returns/displays the notice; it does not assemble the
   prompt itself).

All three are additive; the existing `save_checkpoint`/`restore_checkpoint`/
`child` behavior is unchanged (the new `tracked_files` argument is optional and
defaults to recording no fingerprints).

---

## The tradeoff: resume with stale results vs. a summary-seeded new session

**A fresh session seeded with a structured summary frequently beats `--resume`
with the full stale transcript.** Resume restores *everything* — including tool
results captured against a world state that may no longer hold:

| | `--resume` (restore full state) | New session + structured summary |
|---|---|---|
| **Tool results** | Carried forward verbatim, even if the underlying files/services changed | Re-derived fresh against current reality |
| **Context budget** | Pays for the entire prior transcript again | Pays only for a compact summary |
| **Staleness risk** | High — the agent trusts a snapshot | Low — the agent re-reads what matters |
| **Reproducibility** | Exact prior state | Depends on summary fidelity |
| **Best when** | Short gap, world unchanged, want exact continuation | Long gap, files moved, or context is bloated |

The changed-file notice is the **mitigation** when you do resume: it tells the
agent precisely which restored tool results are now suspect so it re-reads them
instead of trusting the snapshot. But the notice is a patch, not a cure — when
many inputs have changed or the transcript is large and stale, the cheaper and
more correct path is to start a new session seeded with a structured summary of
the prior run's *conclusions* (not its raw tool outputs), and let the agent
rebuild current state on demand.

`fork_session` sits alongside both: use it to explore an alternative branch from
a known-good baseline (e.g. "try the same plan but with higher retries") without
disturbing the original run — the SDK `fork_session` analogue.

---

## Consequences

- **Positive:** Resume and fork are now fully supported and CLI-accessible, built on
  proven checkpoint primitives with no change to existing behavior.
- **Positive:** Stale-result risk is made *visible* via the changed-file notice
  rather than silently carried forward.
- **Neutral:** Fingerprinting is opt-in per checkpoint (`tracked_files`); runs
  that don't pass it behave exactly as before.
- **Negative:** Fingerprints capture content only — they do not detect changes
  in non-file inputs (databases, remote APIs). For those, prefer the
  summary-seeded new session described above.
