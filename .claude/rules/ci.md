# CI gates and local validation

These are the gates a change must clear before it can merge. They are enforced
in `.github/workflows/ci.yml`; run the local equivalents before pushing.

## Test commands

Run from the repo root unless a per-package entrypoint is noted.

| Scope | Command |
|-------|---------|
| Everything (backend + eval + UI) | `just test` |
| Runtime unit suite | `cd agentic-workflows-v2 && python -m pytest tests/ -q` |
| Runtime + coverage | `cd agentic-workflows-v2 && python -m pytest tests/ -q --cov=agentic_v2 --cov-report=term-missing` |
| Eval package | `cd agentic-v2-eval && python -m pytest tests/ -q` |
| UI unit | `cd agentic-workflows-v2/ui && npm test` |
| Docs link/fence check | `just docs` |

CI runs the unit suite with `-m "not integration and not slow"` and
`--ignore=tests/e2e`. Mark anything that hits the network or takes >5s with
`@pytest.mark.integration` or `@pytest.mark.slow` so it stays out of the fast
pass. `asyncio_mode = "auto"` is set, so `async def test_*` needs no decorator.

## Running without provider credentials

Set `AGENTIC_NO_LLM=1` to force every tier-1/tier-2 agent onto the deterministic
`PlaceholderChatModel`. This is the supported no-API-key baseline (the
`no-llm-smoke` CI job uses it); a contributor with no keys should be able to run
the whole unit suite green this way.

## Coverage threshold

The gate is **80%** on `agentic-workflows-v2/agentic_v2` (`[tool.coverage.report]
fail_under = 80`, `precision = 2` so 79.93% fails rather than rounding up). New
backend code targets 80% coverage on changed lines. CI collects coverage
without `--cov-fail-under` and enforces it in a dedicated
`coverage report --fail-under=80` step (pytest-cov 7.x does not propagate the
failure exit code reliably).

UI: vitest coverage floors (branches ≥56, ratcheting toward 60; statements/
functions/lines ≥60) defined in `ui/vitest.config.ts` and enforced by the
`frontend-test` CI job (`npm run test:coverage`, which runs `vitest run
--coverage`). The branches floor is a deliberate ratchet — it may only move up
as coverage improves, never down; see the comment above the thresholds in
`vitest.config.ts` for the full policy.

Some modules are listed under `[tool.coverage.run] omit` because they require
live providers or an optional `executionkit` install — do not add new code to an
omitted module expecting it to be measured.

## Lint and types

- **Ruff** (`E,F,W,I,N,UP,S,B,A,C4,SIM,TCH,RUF`, line-length 88) must be clean on
  changed files: `cd agentic-workflows-v2 && python -m ruff check agentic_v2/ tests/`.
  CI also fails if `ruff check --fix` would still change anything, so apply
  autofixes and commit them.
- **mypy** runs strict on `agentic_v2/engine` + `agentic_v2/contracts`
  (`--disallow-untyped-defs --warn-return-any`). Type hints on every signature.
- `pre-commit run --all-files` covers black, isort (profile=black), ruff,
  docformatter, detect-secrets, and the scoped mypy/pydocstyle hooks.

## Wire-format drift

Pydantic contracts in `agentic_v2/contracts/` and several `server/models` types
are the source of truth for committed JSON schemas and generated TypeScript. Any
shape change must be accepted by regenerating both
(`python -m scripts.generate_ts_types`, then `npm run generate:types` in
`ui/`) and committing the result; the `wire-format-drift` job fails on a
mismatch. See ADR-014.

## Review criteria

This repo is built solo with AI-assisted tooling, so correctness is gated by
**automated evidence**, not peer sign-off. Treat AI-generated code as untrusted
input: run the full lint + type-check + test set before accepting it. Before
opening a PR, confirm:

- Tests added or updated; coverage holds on changed lines.
- `just test && just docs && pre-commit run --all-files` are green locally.
- Conventional-commit subject (`type(scope): subject`); scope matches the
  package/subsystem (`engine`, `contracts`, `server`, `mcp/results`, `eval`, …).
- An ADR is added under `docs/adr/` when the change introduces a wire-format
  contract, swaps an engine/adapter/storage backend, moves a security boundary,
  or picks a pattern a future contributor might challenge. Use the existing
  numbering scheme; ADRs 004-006 are intentionally unused.
- No secrets committed — configuration flows through env vars and `.env.example`.
