# Repository Guidelines

## Project Structure & Module Organization

This is a Python 3.11+/Node 20 monorepo. `agentic-workflows-v2/` contains the runtime, CLI, FastAPI server, and DAG engine; its React/Vite dashboard lives in `agentic-workflows-v2/ui/`. `agentic-v2-eval/` is the rubric-based evaluation package, while `tools/` contains shared LLM and benchmark utilities. Python tests sit beside each package in `tests/`, with cross-package checks in root `tests/e2e/`. Documentation and ADRs are under `docs/`; sample workflows, datasets, deployment files, and telemetry configuration live in `examples/`, `datasets/`, `infra/`, and `otel/`.

Keep package boundaries intact. In particular, do not introduce cross-package imports without reviewing the architecture guidance in `docs/ARCHITECTURE.md` and relevant ADRs.

## Build, Test, and Development Commands

- `just setup`: create `.venv`, install all Python packages editable, and install UI dependencies.
- `just dev` / `just dev-reload`: start the backend and UI locally; use `just dev-stop` to stop them.
- `just test`: run runtime, eval, cross-package, and UI unit tests.
- `just docs`: validate documentation references and generated statistics.
- `pre-commit run --all-files`: run formatting, linting, typing, and secret checks.
- `npm --prefix agentic-workflows-v2/ui run build`: type-check and build the dashboard.

Use narrower package commands during iteration, for example `python -m pytest agentic-v2-eval/tests -q` or `npm --prefix agentic-workflows-v2/ui test`.

## Coding Style & Naming Conventions

Python uses 4-space indentation, Black formatting and an 88-character target, Ruff linting/import sorting, and typed public interfaces. Use `snake_case` for modules/functions, `PascalCase` for classes, and `UPPER_CASE` for constants. React components use `PascalCase.tsx`; helpers and hooks use descriptive camelCase names. Let pre-commit apply mechanical fixes.

## Testing Guidelines

Use pytest for Python, Vitest for UI unit tests, and Playwright for browser flows. Name Python tests `test_*.py`, UI unit tests `*.test.ts(x)`, and E2E tests `*.spec.ts`. Add regression coverage with behavior changes. Maintain at least 80% runtime coverage and the UI's 60% configured floor; mark slow or end-to-end Python tests with the registered `slow` or `e2e` markers.

## Commit & Pull Request Guidelines

Follow Conventional Commits: `feat(ui): add run filter`, `fix(server): validate override`, or `docs(adr): clarify routing`. Use a short, present-tense subject and one concern per commit. Branch from `main` using `feature/`, `fix/`, `chore/`, or `docs/`.

PRs should explain intent and verification, link relevant issues, include screenshots for UI changes, update tests/docs and `CHANGELOG.md` when user-visible, and add an ADR for material architectural decisions. Before requesting review, run `just test`, `just docs`, and all pre-commit hooks. Never commit `.env`, provider tokens, generated run data, or other secrets. The one deliberate exception is the SWE-bench A/B campaign's evidence under `agentic-workflows-v2/evals/swe_ab/` — `reports/*.json`, the `dataset/cases.swebench*.jsonl` manifests and `ledger/export/` — which is tracked on purpose so results outlive the machine that produced them (`evals/swe_ab/docs/WAVE-RUNBOOK.md`, rule 3); its `artifacts/`, `sandbox/`, case trees and ledger databases stay ignored.
