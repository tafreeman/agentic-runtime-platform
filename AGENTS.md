# Repository Guidelines

Claude Code also loads `CLAUDE.md` and `.claude/rules/`; CI gates and gotchas live
in `.claude/rules/ci.md` and `.claude/rules/portfolio-context.md`.

## Boundaries

`agentic-workflows-v2/` (runtime, server, DAG engine, `ui/` dashboard) and
`agentic-v2-eval/` share only the root `tools/` package. Do not introduce
cross-package imports without reviewing `docs/ARCHITECTURE.md` and the relevant ADRs.

## Validation

`justfile` recipes run in PowerShell against `.venv/Scripts/python.exe`. Set
`AGENTIC_NO_LLM=1` to run the suites without provider keys. Mark slow or
end-to-end Python tests with the registered `slow` or `e2e` markers.

## Commit & Pull Request Guidelines

Follow Conventional Commits: `feat(ui): add run filter`, `fix(server): validate override`, or `docs(adr): clarify routing`. One concern per commit. Branch from `main` using `feature/`, `fix/`, `chore/`, or `docs/`.

PRs should explain intent and verification, link relevant issues, include screenshots for UI changes, update tests/docs and `CHANGELOG.md` when user-visible, and add an ADR for material architectural decisions. Before requesting review, run `just test`, `just docs`, and all pre-commit hooks. Never commit `.env`, provider tokens, generated run data, or other secrets. The one deliberate exception is the SWE-bench A/B campaign's evidence under `agentic-workflows-v2/evals/swe_ab/` — `reports/*.json`, the `dataset/cases.swebench*.jsonl` manifests and `ledger/export/` — which is tracked on purpose so results outlive the machine that produced them (`evals/swe_ab/docs/WAVE-RUNBOOK.md`, rule 3); its `artifacts/`, `sandbox/`, case trees and ledger databases stay ignored.
