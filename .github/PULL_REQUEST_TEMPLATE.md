## Summary

Describe the problem, the fix, and the intended behavior. Keep one concern per
pull request, preferably under about 400 changed lines (guidance, not a gate).

## Linked Issues and ADRs

- Closes #
- Related #

## Change Type

- [ ] Bug fix
- [ ] New feature
- [ ] Refactor
- [ ] Documentation
- [ ] Tests only

## Validation

- [ ] Regression tests added or updated for the behavior change
- [ ] Type hints on all new function signatures
- [ ] Contracts are additive-only (no breaking schema changes)
- [ ] Manual verification completed
- [ ] `just test`
- [ ] `just docs`
- [ ] `pre-commit run --all-files`
- [ ] Commit subjects use Conventional Commits (`pre-commit install --install-hooks` also installs the commit-message hook)

List commands that were not run and explain why. Include a screenshot for a
visible UI change. See `CONTRIBUTING.md` for exact commands per surface.

Tick what applies to this change and delete the rest:

- [ ] Runtime Python: from `agentic-workflows-v2/`, `python -m ruff check agentic_v2/ tests/` and the strict `mypy` command in `CONTRIBUTING.md`; coverage held at the 80% gate; `python scripts/check_suppression_ratchet.py` shows no new suppressions
- [ ] Wire contracts (`agentic_v2/contracts/` or `agentic_v2/server/models.py`): from `agentic-workflows-v2/`, `python -m scripts.generate_ts_types`, then `npm --prefix ui run generate:types`; generated files committed, `git status` clean
- [ ] UI: `just ui-check` (unit tests, coverage floors, build)
- [ ] Eval, live provider routing, or judge prompts: `scripts/eval_gate.py` passes; add the `run-live-eval` label (without provider secrets that job exits as skipped, so it is not a live pass)
- [ ] Dependencies (`pyproject.toml`, `uv.lock`, `ci-constraints.txt`): `uv.lock` and `ci-constraints.txt` regenerated and committed (`just update-constraints` or `just relock`)
- [ ] Workflow YAML: `python scripts/validate-workflows.py`
- [ ] `tools/`: `python -m pytest tools/tests -q`
- [ ] Step delegation, approval gate, `claude`, or `eval` extras: the extra installed, so its tests ran instead of skipping

## Risk and Rollback

What could regress? How can this be rolled back? `main` is protected, so a
revert lands as a revert pull request; note any migration, lockfile, or
configuration step the revert needs.

## Docs Checklist

- [ ] Updated `README.md` if setup or behavior changed
- [ ] Updated docs in `docs/` for API, workflow, or architecture changes
- [ ] Added migration notes in `docs/MIGRATIONS.md` if behavior is breaking
- [ ] Added a `## Unreleased - <title>` entry to `CHANGELOG.md` for user-visible changes
- [ ] Added an ADR if a security boundary or wire format changed (`docs/adr/ADR-INDEX.md` has the next number)
- [ ] Regenerated schemas or statistics through their generator, if affected

## Security/Privacy Checklist

- [ ] No secrets, `.env` files, or private data committed
- [ ] Auth, access, and sensitive-logging implications considered
- [ ] New tool or model output is treated as untrusted data
- [ ] Tool dispatch, approval, or egress changes keep the `ApprovalProvider` gate and the `url_guard` SSRF guard fail-closed
