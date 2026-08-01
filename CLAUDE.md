# agentic-runtime-platform

Tier-based multi-model AI workflow orchestration. Python 3.11, FastAPI +
Pydantic v2 + asyncio + OpenTelemetry. The runtime lives in
`agentic-workflows-v2/agentic_v2/`; the offline evaluation harness lives in
`agentic-v2-eval/`. A uv workspace ties the two packages plus the repo-root
`agentic-tools` together.

This file is intentionally thin. It injects the CI context an agent needs to
make a change that survives the pipeline, and delegates the detail to modular
rule files under `.claude/rules/` via `@import`.

## Working agreement

- Make the smallest coherent change; one concern per PR. Match the surrounding
  code — do not refactor unrelated subsystems.
- Reuse existing infrastructure instead of re-implementing it: `SmartModelRouter`
  for tier/model selection, `ExecutionContext` for run state and checkpoints,
  `ConversationMemory` for history, the MCP client stack for tool calls, and the
  shared error classification helpers.
- Secrets only via environment variables or `.env.example`. Never read, edit, or
  commit `.env`.

## CI context

The 80% coverage gate, ruff/mypy lints, the no-API-key (`AGENTIC_NO_LLM=1`)
baseline, the wire-format drift check, and the review checklist are documented in
the imported CI rules. Read them before validating a change.

@.claude/rules/ci.md

## Test conventions

Fixture, golden-file, marker, and isolation conventions for the Python suites
are in the imported testing rules. A path-scoped copy
(`paths: ["**/*_test.py", "tests/**/*.py"]`) auto-applies whenever a test file
is in context.

@.claude/rules/testing.md

## Portfolio context

The command catalogue CI actually runs, the architecture seams, and the CI gotchas that
neither rules file covers (constraints generation, the suppression ratchet, coverage omits,
the EK-extra blind spot) live in the imported portfolio rules.

@.claude/rules/portfolio-context.md

## Where things live

- Architecture decisions: `docs/adr/` — `docs/adr/ADR-INDEX.md` tracks the next
  free number and the intentionally-unused numbering gaps; don't hardcode the
  gap list here, it drifts.
- Contributor gates and the full command catalogue: `CONTRIBUTING.md`.
- Runnable demonstrations of platform primitives: `examples/` — not uniformly
  safe to run without a provider; see `examples/README.md` for which files
  need one and which are currently broken.
