# Contributing

Use this guide when preparing a change for review. For installation and normal
usage, start with [Getting started](docs/getting-started/index.md).

> **Last verified:** 2026-10-18

## Repository boundaries

This monorepo contains three Python packages and one frontend:

| Path | Ownership |
|---|---|
| `agentic-workflows-v2/` | Runtime, CLI, FastAPI server, integrations, and UI |
| `agentic-v2-eval/` | Evaluation models, rubrics, runners, and reporters |
| `tools/` | Shared provider and benchmark utilities packaged as `agentic-tools` |
| `tests/e2e/` | Cross-package behavior |
| `proofs/` | Lean 4 model of `DAGExecutor` and its replay tests ([ADR-060](docs/adr/ADR-060-scheduler-guarantees-lean.md)) |

The runtime and evaluation packages depend on the root `agentic-tools` package
through the workspace configuration. Do not introduce another cross-package
import or an editable sibling-repository dependency without reviewing
[Architecture](docs/ARCHITECTURE.md) and the relevant ADRs. The existing
`agentic_v2/models/llm.py` import from `agentic_v2_eval` is a known legacy
exception; do not add more.

Package-specific notes are in
[`agentic-workflows-v2/CONTRIBUTING.md`](agentic-workflows-v2/CONTRIBUTING.md).

## Set up the workspace

Use Python 3.11 or newer and Node.js 22.22.2 or newer (CI uses Node 22).

```powershell
git clone https://github.com/tafreeman/agentic-runtime-platform.git
cd agentic-runtime-platform
just setup
.\.venv\Scripts\Activate.ps1
python -m pip install pre-commit
pre-commit install --install-hooks
```

`just setup` installs into `.venv` but does not activate it, so activate it
before the `pip` and `agentic` commands below.

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
  Set-Content -Encoding ascii .\agentic-input.json
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
- Add a `## Unreleased - <title>` entry to `CHANGELOG.md` for user-visible
  changes.
- Add an ADR for a material architecture or security-boundary decision.
- Do not reformat unrelated files.
- Preserve generated files unless the source contract changed.
- Keep one concern per pull request, preferably under about 400 changed lines
  (guidance, not a gate). When a change spans layers, slice it: contract and
  generated code first, then backend with tests, then UI and documentation.

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

Use `just ui-check` instead of the last command when you changed the frontend
or the wire contracts: it also runs the UI tests with their coverage floors.

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
python scripts/check-doc-drift.py
python scripts/generate_doc_stats.py --check
```

`just docs` runs all three. `python scripts/validate-workflows.py` validates the
workflow YAML files.

If MkDocs and its plugins are installed:

```bash
mkdocs build --strict
```

Do not add a command to documentation until it has been run from the directory
the page specifies.

### Fast smoke check

A quick pre-push check that needs no provider key. Activate the environment
from `just setup` first, because `agentic validate` needs the `langchain`
extra. Run it from the repository root.

Bash:

```bash
export AGENTIC_NO_LLM=1
agentic validate test_deterministic
agentic run test_deterministic \
  --input agentic-workflows-v2/tests/fixtures/deterministic_input.json
python -m pytest agentic-workflows-v2/tests/test_approval_gates.py -k fails_closed -q
```

PowerShell:

```powershell
$env:AGENTIC_NO_LLM = "1"
agentic validate test_deterministic
agentic run test_deterministic `
  --input agentic-workflows-v2/tests/fixtures/deterministic_input.json
python -m pytest agentic-workflows-v2/tests/test_approval_gates.py -k fails_closed -q
```

### Match the checks to what you changed

The checks in "Run checks" are the pre-PR gate. While you work, run the ones
that match the surface you touched. This list is a development aid, not a
substitute for that gate.

Runtime Python (`agentic-workflows-v2/agentic_v2/` and its tests). Run these
from `agentic-workflows-v2/`:

```bash
cd agentic-workflows-v2
python -m ruff check agentic_v2/ tests/
python -m mypy agentic_v2/engine agentic_v2/contracts --config-file pyproject.toml \
  --follow-imports=skip --disallow-untyped-defs --warn-return-any --no-incremental
python -m pytest tests/ -q -m "not integration and not slow" \
  --cov=agentic_v2 --cov-report=term-missing
python -m coverage report --fail-under=80
cd ..
python agentic-workflows-v2/scripts/check_suppression_ratchet.py
```

- CI also fails when `ruff check --fix` would still change a file, so run it
  with `--fix` deliberately and commit the result.
- The coverage gate is the whole-package `coverage report --fail-under=80`
  step, with `precision = 2`, so 79.93% fails. New code should aim for 80% on
  its changed lines.
- Use these exact `mypy` flags. A plain `mypy` run does not reproduce the
  gate: `--follow-imports=skip` makes everything outside `engine` and
  `contracts` `Any`, so returning its attributes raises `no-any-return` only
  with the CI flags.
- CI also runs `pydocstyle` on `core/` and `contracts/`:

  ```bash
  python -m pydocstyle --convention=google --add-ignore=D100,D104 agentic-workflows-v2/agentic_v2/core/
  python -m pydocstyle --convention=google --add-ignore=D100,D101,D104 agentic-workflows-v2/agentic_v2/contracts/
  ```

Wire contracts (`agentic_v2/contracts/*.py` and the Pydantic classes in
`agentic_v2/server/models.py`): follow "Change generated contracts" below.

UI (`agentic-workflows-v2/ui/`):

```bash
just ui-check
```

`just ui-check` runs the unit tests with coverage floors (including the
design-drift and contrast guards), then the production build.

UI end-to-end tests (see `agentic-workflows-v2/ui/e2e/README.md`): Playwright
starts and owns the backend on `127.0.0.1:8010` and Vite on `127.0.0.1:5173`
and does not reuse running services, so stop `just dev` first.

```bash
just dev-stop
cd agentic-workflows-v2/ui
npx playwright install chromium
npm run test:e2e -- streaming.spec.ts
npm run test:e2e:5x
```

The single spec is the fast subset. `test:e2e:5x` runs the whole Playwright
suite five times and is the flake gate the nightly workflow uses.

Evaluation (`agentic-v2-eval/`, `datasets/`, `scripts/eval_gate.py`, or
`agentic_v2/scoring/`):

```bash
AGENTIC_NO_LLM=1 python scripts/eval_gate.py \
  --cases datasets/default/golden_cases.json --threshold 0.80
python -m pytest agentic-workflows-v2/tests/test_eval_gate_independence.py \
  agentic-workflows-v2/tests/test_eval_gate_live.py -q --no-cov
cd agentic-v2-eval
python -m pytest tests -q --cov=src/agentic_v2_eval --cov-fail-under=80
python -m ruff check src/
python -m ruff format --check src/
python -m mypy src/agentic_v2_eval --config-file pyproject.toml
```

The live evaluation gate is opt-in: add the `run-live-eval` label to a pull
request that changes live provider routing or judge prompts. With no provider
secrets configured it exits successfully as skipped, which is not evidence of
a live pass.

Optional extras. These test modules skip themselves when the extra is missing,
so a green run proves nothing until the extra is installed. Install it and
confirm the import first. Run the pytest commands from
`agentic-workflows-v2/`:

```bash
python -m pip install -e "./agentic-workflows-v2[dev,server,mcp,langchain,tracing,ek]" -c ci-constraints.txt
python -c "import executionkit"
cd agentic-workflows-v2
python -m pytest tests/engine/test_step_ek_delegation.py tests/engine/test_step_tool_path.py \
  tests/models/test_ek_adapters.py tests/models/test_ek_provider.py \
  tests/models/test_ek_provider_attempts.py tests/models/test_ek_provider_wrapper.py \
  -q --timeout=120
```

- `eval` extra (also install `agentic-v2-eval[dev]`): confirm
  `python -c "import agentic_evalkit"`, then run
  `tests/test_evalkit_bridge.py`, `tests/test_scoring_policy_differential.py`,
  and `tests/contract/test_evalkit_boundary.py`.
- `claude` extra: confirm `python -c "import claude_agent_sdk"`, then run
  `tests/models/test_backends_claude.py`, `tests/test_claude_sdk_agent.py`,
  `tests/test_sdk_task_orchestrator_example.py`, and
  `tests/test_implementations_sanitization.py`.
- `tools/` needs only `[dev]`: `python -m pytest tools/tests -q --timeout=120`
  from the repository root.

Dependencies (`pyproject.toml`, `uv.lock`, `ci-constraints.txt`, the
`Dockerfile`). `ci-constraints.txt` is generated from `uv.lock`; CI pins a uv
version (the `uv==` line in `.github/workflows/ci.yml`), and a different local
version can produce a spurious diff. Regenerate and commit both files:

```bash
uv lock
just update-constraints
```

Dependabot bumps `pyproject.toml` and `ci-constraints.txt` but not `uv.lock`;
`just relock` (or the `dependabot-relock` workflow) reconciles it. Every
`pip install` line in a Dockerfile except `--upgrade pip` must carry
`-c ci-constraints.txt`.

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
| E2E streaming | Full Playwright e2e suite once per PR; repeat-run flake detection (full suite 5x, streaming spec 50x) runs nightly |
| Optional extras (`ek`, `eval`, `claude`) | Dedicated tests with those extras installed together, in the `EK step-delegation (approval-gate) tests` job |

The workflow files under `.github/workflows/` are the current source of truth.
Do not infer a green full matrix from one local test command.

Pull requests that change only documentation (`docs/`, root and package-level
`*.md`, `mkdocs.yml`, issue and PR templates, `.claude/`) skip the backend, UI and
wire-format jobs; `lint` and the documentation-drift gates still run. Any other
changed path runs the full pipeline.

### Governance ratchets

- **Suppression ratchet.** Adding a ruff `ignore`, a `per-file-ignores` entry,
  or a mypy `ignore_errors` override beyond the counts in
  `agentic-workflows-v2/.ruff-suppression-baseline.json` fails CI. Inline
  `# noqa` and `# type: ignore` comments are not counted. Run
  `python agentic-workflows-v2/scripts/check_suppression_ratchet.py`. After a
  cleanup that shrinks a count, lock it in with the script's
  `--update-baseline` flag. Silencing a lint error to get a change through is
  a blocked path.
- **Coverage precision.** The 80% gate uses `precision = 2`, so 79.93% fails
  rather than rounding up.
- **Constraints pinning.** Python jobs that install the project packages pass
  `-c ci-constraints.txt`, which is generated from `uv.lock`; see
  "Dependencies" above.

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

Review the generated diff and check `git status --short` for new generated
files, which `git diff` alone does not show. Do not edit generated TypeScript
or JSON schema files by hand.

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
docs(engine): correct CLI persistence limits
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
- screenshots for visible UI changes;
- migration or rollout notes when behavior changes; and
- how to roll back. `main` is protected, so a revert lands as a revert pull
  request.

The pull request template in `.github/PULL_REQUEST_TEMPLATE.md` carries this
checklist and the per-surface checks:

```text
- [ ] Change is focused and package boundaries are preserved
- [ ] Regression tests cover the behavior change
- [ ] just test passed, or narrower checks and omissions are listed
- [ ] just docs passed
- [ ] pre-commit run --all-files passed
- [ ] The checks for each surface you changed passed
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
