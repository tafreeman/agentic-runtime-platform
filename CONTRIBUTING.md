# Contributing

Use this guide when preparing a change for review. For installation and normal
usage, start with [Getting started](docs/getting-started/index.md).

> **Last verified:** 2026-07-28

## Repository boundaries

This monorepo contains three Python packages and one frontend:

| Path | Ownership |
|---|---|
| `agentic-workflows-v2/` | Runtime, CLI, FastAPI server, RAG, integrations, and UI |
| `agentic-v2-eval/` | Evaluation models, rubrics, runners, and reporters |
| `tools/` | Shared provider and benchmark utilities packaged as `agentic-tools` |
| `tests/e2e/` | Cross-package behavior |

The runtime and evaluation packages depend on the root `agentic-tools` package
through the workspace configuration. Do not introduce another cross-package
import or an editable sibling-repository dependency without reviewing
[Architecture](docs/ARCHITECTURE.md) and the relevant ADRs.

Package-specific notes are in
[`agentic-workflows-v2/CONTRIBUTING.md`](agentic-workflows-v2/CONTRIBUTING.md).

## Set up the workspace

Use Python 3.11 or newer and Node.js 20 or newer.

```powershell
git clone https://github.com/tafreeman/agentic-runtime-platform.git
cd agentic-runtime-platform
just setup
python -m pip install pre-commit
pre-commit install --install-hooks
```

The current `justfile` uses PowerShell. Manual installation for Linux, macOS,
or a system without `just` is documented in
[Installation](docs/getting-started/installation.md).

Verify the deterministic path:

```bash
printf '{"input_text":"hello"}\n' > /tmp/agentic-input.json
AGENTIC_NO_LLM=1 agentic run test_deterministic \
  --input /tmp/agentic-input.json
```

PowerShell:

```powershell
'{"input_text":"hello"}' |
  Set-Content -Encoding utf8 .\agentic-input.json
$env:AGENTIC_NO_LLM = "1"
agentic run test_deterministic --input .\agentic-input.json
```

Do not place provider credentials in committed files. Copy `.env.example` to
the ignored `.env` file when a live-provider test is required.

## Create a branch

Branch from the current `main`:

```bash
git switch main
git pull --ff-only
git switch -c feature/short-description
```

Use one of these prefixes:

- `feature/`
- `fix/`
- `chore/`
- `docs/`

Do not push directly to `main`.

## Make a focused change

- Keep package boundaries intact.
- Add or update tests with behavior changes.
- Update user documentation when a command, endpoint, environment variable,
  schema, workflow, or UI behavior changes.
- Update `CHANGELOG.md` under `Unreleased` for user-visible changes.
- Add an ADR for a material architecture or security-boundary decision.
- Do not reformat unrelated files.
- Preserve generated files unless the source contract changed.

Python uses 4-space indentation, Black with an 88-character target, Ruff, and
typed public interfaces. Use `snake_case` for Python modules and functions,
`PascalCase` for classes and React components, and `UPPER_CASE` for constants.

React components use `PascalCase.tsx`. Hooks and helpers use descriptive
camelCase names.

## Run checks

Run the broad repository checks before requesting review:

```bash
just test
just docs
pre-commit run --all-files
npm --prefix agentic-workflows-v2/ui run build
```

`just test` runs the runtime, evaluation, cross-package, and UI unit tests.
Some live-provider and slow checks are intentionally separate.

Use narrower commands during development:

```bash
python -m pytest agentic-workflows-v2/tests -q
python -m pytest agentic-v2-eval/tests -q
python -m pytest tests/e2e -q
npm --prefix agentic-workflows-v2/ui test
npm --prefix agentic-workflows-v2/ui run test:coverage
```

Documentation checks:

```bash
python agentic-workflows-v2/scripts/check_docs_refs.py
python scripts/generate_doc_stats.py --check
```

If MkDocs and its plugins are installed:

```bash
mkdocs build --strict
```

Do not add a command to documentation until it has been run from the directory
the page specifies.

## What CI checks

The blocking checks include:

| Check | Scope |
|---|---|
| Runtime tests | Unit tests excluding marked integration and slow tests in the fast job |
| Runtime coverage | 80% over the configured core subset |
| UI tests and coverage | Vitest thresholds defined in `ui/vitest.config.ts` |
| UI build | TypeScript project build and Vite production bundle |
| Ruff | Runtime source and tests |
| Mypy | Strict settings for `agentic_v2/engine`, `agentic_v2/contracts`, and `agentic-v2-eval` source |
| Wire-format drift | Pydantic schemas and generated TypeScript types |
| Documentation drift | Workflow validation, architecture protocol names, local references, and generated homepage statistics |
| Security and dependencies | Secret detection, CodeQL, dependency review, and audit workflows |
| E2E streaming | Repeated Playwright streaming path |
| Optional ExecutionKit path | Dedicated tests with the `ek` extra installed |

The workflow files under `.github/workflows/` are the current source of truth.
Do not infer a green full matrix from one local test command.

### Run without provider keys

Use:

```bash
export AGENTIC_NO_LLM=1
just test
```

PowerShell:

```powershell
$env:AGENTIC_NO_LLM = "1"
just test
```

The `no-llm-smoke` CI job validates workflow loading, the deterministic run,
the LangGraph placeholder path, and the unit suite without provider
credentials.

Placeholder mode is not a substitute for provider integration tests.
Structured-output, tool-choice, latency, retry, quota, and content-quality
behavior still need live or provider-specific tests.

## Change generated contracts

When a Pydantic event or server model changes, regenerate the committed
schemas and TypeScript types:

```bash
cd agentic-workflows-v2
python -m scripts.generate_ts_types
cd ui
npm run generate:types
```

Review the generated diff. Do not edit generated TypeScript or JSON schema
files by hand.

## Write documentation

Use the shortest page that answers the reader's task. Prefer:

- an exact command over a description of a command;
- a table for field or endpoint mappings;
- a small verified example over a hypothetical large example;
- a direct limitation over promotional wording;
- links to one canonical explanation instead of copied sections.

Update these documents with the matching change:

| Change | Update |
|---|---|
| CLI command or option | `docs/cli-reference.md` |
| Workflow schema or shipped definition | `docs/WORKFLOW_AUTHORING.md` and `docs/workflows/index.md` |
| Environment variable | `.env.example` and `docs/configuration.md` |
| HTTP, SSE, or WebSocket route | `docs/api-contracts-runtime.md` |
| UI route or component contract | `docs/ui/pages.md` or `docs/ui/api-integration.md` |
| Architecture boundary | `docs/ARCHITECTURE.md` and the relevant deep dive |
| Known defect or deployment gap | `docs/KNOWN_LIMITATIONS.md` |
| User-visible behavior | `CHANGELOG.md` |
| Breaking change | `docs/MIGRATIONS.md` |

The root `CONTRIBUTING.md` is the source for the published
`docs/CONTRIBUTING.md`. The docs deployment workflow rewrites repository-root
links for the published site.

## Write an ADR

Add an ADR when a change:

- introduces or changes a public wire format;
- adds, replaces, or removes an execution engine, provider, or storage
  backend;
- changes authentication, tool approval, path containment, egress, or another
  security boundary; or
- establishes a pattern future contributors will need to follow.

Use [ADR-INDEX.md](docs/adr/ADR-INDEX.md) to choose the next number and review
the status of related decisions. Do not reuse a documented numbering gap.

An ADR is not required for a local refactor that preserves public behavior.

## Commit

Use Conventional Commits:

```text
feat(ui): add run filter
fix(server): validate adapter override
docs(rag): correct CLI persistence limits
test(engine): cover timeout cancellation
```

Use a short, present-tense subject and keep one concern per commit. Temporary
`wip` commits may be used on a feature branch but must be squashed before
merge.

Install the commit-message hook with:

```bash
pre-commit install --install-hooks
```

The repository removes AI-assistant co-author trailers. Human and service-bot
co-authors are preserved.

## Pull request

A pull request should include:

- the problem and intended behavior;
- the main implementation choices;
- tests and commands that passed;
- known checks that were not run and why;
- linked issues or ADRs;
- screenshots for visible UI changes; and
- migration or rollout notes when behavior changes.

Use this checklist:

```text
- [ ] Change is focused and package boundaries are preserved
- [ ] Regression tests cover the behavior change
- [ ] just test passed, or narrower checks and omissions are listed
- [ ] just docs passed
- [ ] pre-commit run --all-files passed
- [ ] UI build passed when frontend or wire contracts changed
- [ ] Documentation and CHANGELOG.md are updated when needed
- [ ] No credentials, .env files, run data, or private customer data are included
- [ ] Commit messages use Conventional Commits
```

## Security reports

Do not open a public issue for a vulnerability. Follow
[`agentic-workflows-v2/SECURITY.md`](agentic-workflows-v2/SECURITY.md).

Runtime secrets must be resolved through the repository's secret-provider
abstraction. Do not add new direct `os.environ` reads for credentials without
reviewing the existing provider path.

## Help

- [Architecture](docs/ARCHITECTURE.md)
- [Development guide](docs/development-guide.md)
- [Glossary](docs/GLOSSARY.md)
- [Troubleshooting](docs/operations/troubleshooting.md)
- [Package contribution notes](agentic-workflows-v2/CONTRIBUTING.md)
