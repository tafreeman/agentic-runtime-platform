# agentic-runtime-platform

## Working agreement

- One concern per PR. Match the surrounding code — do not refactor unrelated
  subsystems.
- Reuse existing infrastructure instead of re-implementing it: `SmartModelRouter`
  for tier/model selection, `ExecutionContext` for run state and checkpoints,
  `ConversationMemory` for history, the MCP client stack for tool calls, and the
  shared error classification helpers.
- Secrets only via environment variables or `.env.example`. Never read, edit, or
  commit `.env`.

CI gates and the review checklist load from `.claude/rules/ci.md`; CI gotchas and
the exact commands CI runs from `.claude/rules/portfolio-context.md`. Test
conventions (`.claude/rules/testing.md`) load when a test file is in context.

## Where things live

- Architecture decisions: `docs/adr/` — `docs/adr/ADR-INDEX.md` tracks the next
  free number and the intentionally-unused numbering gaps; don't hardcode the
  gap list here, it drifts.
- Contributor gates and the full command catalogue: `CONTRIBUTING.md`.
- Runnable demonstrations of platform primitives: `examples/` — not uniformly
  safe to run without a provider; see `examples/README.md` for which files
  need one and which are currently broken.
