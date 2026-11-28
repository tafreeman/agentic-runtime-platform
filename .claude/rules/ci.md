# CI gates and local validation

These are the gates a change must clear before it can merge. They are enforced
in `.github/workflows/ci.yml`; the exact commands CI runs are in
`portfolio-context.md`.

## Running without provider credentials

Set `AGENTIC_NO_LLM=1` to force every tier-1/tier-2 agent onto the deterministic
`PlaceholderChatModel`. This is the supported no-API-key baseline (the
`no-llm-smoke` CI job uses it); a contributor with no keys should be able to run
the whole unit suite green this way.

## Coverage

- Runtime: `fail_under = 80` with `precision = 2`, so 79.93% fails rather than
  rounding up. CI collects coverage without `--cov-fail-under` and enforces it in
  a dedicated `coverage report --fail-under=80` step (pytest-cov 7.x does not
  propagate the failure exit code reliably).
- UI: floors live in `ui/vitest.config.ts`. The branches floor is a deliberate
  ratchet — it may only move up, never down.
- Modules listed under `[tool.coverage.run] omit` need live providers or an
  optional `executionkit` install — do not add new code to an omitted module
  expecting it to be measured.

## Lint

CI fails if `ruff check --fix` would still change anything, so apply autofixes
and commit them.

## Wire-format drift

Pydantic contracts in `agentic_v2/contracts/` and several `server/models` types
are the source of truth for committed JSON schemas and generated TypeScript. Any
shape change must be accepted by regenerating both
(`python -m scripts.generate_ts_types`, then `npm run generate:types` in
`ui/`) and committing the result; the `wire-format-drift` job fails on a
mismatch. See ADR-014.

## Review criteria

This repo is built solo with AI-assisted tooling, so correctness is gated by
**automated evidence**, not peer sign-off. Before opening a PR, confirm:

- `just test && just docs && pre-commit run --all-files` are green locally.
- Conventional-commit subject (`type(scope): subject`); scope matches the
  package/subsystem (`engine`, `contracts`, `server`, `mcp/results`, `eval`, …).
- An ADR is added when the change warrants one — see CONTRIBUTING.md's "Write
  an ADR" section for the criteria, and `docs/adr/ADR-INDEX.md` for the next
  free number.
