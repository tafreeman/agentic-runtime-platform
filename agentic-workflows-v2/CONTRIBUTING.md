# Contributing to Agentic Runtime Platform v2

> **Scope:** this file covers contributions specific to the `agentic-workflows-v2/` package (runtime + UI).
> For monorepo-wide policy — local gates, commit format, when to write an ADR, the PR checklist — see the root [`CONTRIBUTING.md`](../CONTRIBUTING.md).
> **Last verified:** 2026-04-22

Thanks for contributing. This project uses docs-as-code, typed contracts, and test-first changes.

## Scope

Contributions are welcome for:
- Workflow runtime improvements (`agentic_v2/engine`, `agentic_v2/workflows`)
- Agent/model/tool integrations
- API/UI improvements
- Tests and fixtures
- Documentation and examples

## Prerequisites

- Python 3.11+
- Node.js 20+ (for `ui/`)
- `pip` and `npm`

## Local Setup

```bash
# From the repo root
just setup
```

If you prefer a containerized workspace, open the repo in the provided devcontainer instead of bootstrapping locally.

## Development Workflow

1. Create a branch for your change.
2. Make the smallest coherent change set.
3. Add or update tests.
4. Update docs for behavior, API, config, or workflow changes.
5. Run local checks before opening a PR.

## Required Local Checks

```bash
# From the repo root
just test
just docs
pre-commit run --all-files
```

UI checks (when frontend files changed):

```bash
cd ui
npm run build
npm test
npm run test:coverage
```

The UI package enforces a 60% coverage floor in `ui/vitest.config.ts`.

## Pull Request Expectations

Use `.github/PULL_REQUEST_TEMPLATE.md` and include:
- Problem statement
- What changed
- Validation evidence (tests/screenshots/logs)
- Risks and rollback notes
- Documentation updates

## Documentation Rules

If your change affects users or contributors, update the docs in the same PR.

Typical mappings:
- New workflow: `docs/WORKFLOWS.md`
- New environment variable: `README.md` and `docs/DEVELOPMENT.md`
- New endpoint: `docs/API_REFERENCE.md`
- New architecture pattern: `docs/ARCHITECTURE.md`
- New bootstrap command or devcontainer behavior: `README.md`, `docs/ONBOARDING.md`, and `CONTRIBUTING.md`

### Editing the execution-event wire format

`agentic_v2/contracts/events.py` is the single source of truth for the
WebSocket / SSE execution event contract. The TypeScript mirror in
`ui/src/api/events.generated.ts` is produced from a committed JSON Schema
(`tests/schemas/events.schema.json`) and **must never be hand-edited**.

If you change any event model in `contracts/events.py`:

1. Regenerate both sides:
   ```bash
   cd agentic-workflows-v2
   python scripts/generate_ts_types.py      # Python  -> JSON Schema
   cd ui && npm run generate:types          # JSON Schema -> TypeScript
   ```
2. Commit the regenerated `tests/schemas/events.schema.json` and
   `ui/src/api/events.generated.ts` alongside the Python change.

The `wire-format-drift` CI job regenerates both files and fails any PR
that forgets either step. Editing the generated TypeScript by hand will
also fail CI on the next regeneration.

## Code Style

- Keep functions and classes focused.
- Prefer explicit schemas/contracts over untyped dicts.
- Keep workflow YAML declarative; avoid hidden runtime coupling.
- Add concise comments only where behavior is non-obvious.

## Security

- Never commit secrets, keys, or production tokens.
- Prefer environment variables for credentials.
- Resolve runtime secrets through `agentic_v2.models.secrets.get_secret()` / `get_first_secret()` instead of reading `os.environ` directly in application code.
- Follow `SECURITY.md` for vulnerability reporting.

## Need Help?

Open a discussion or issue and use `SUPPORT.md` for support channels and expected response paths.
