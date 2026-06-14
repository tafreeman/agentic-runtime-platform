---
description: Test conventions for the agentic-runtime-platform Python suites
paths:
  - "**/*_test.py"
  - "tests/**/*.py"
---

# Test conventions

These conventions apply to every file under a `tests/` tree and to any
`*_test.py` module. They mirror what the suite in
`agentic-workflows-v2/tests/` already does — follow the existing patterns
rather than inventing new ones.

## Structure and naming

- Tests live under the owning package's `tests/` directory
  (`agentic-workflows-v2/tests/`, `agentic-v2-eval/tests/`); cross-package
  end-to-end tests live in the repo-root `tests/e2e/`.
- Mirror the source layout: a test for `agentic_v2/engine/context.py` belongs in
  `tests/engine/` or a top-level `tests/test_context_*.py`.
- Files are `test_*.py`; functions are `test_*`; use Arrange–Act–Assert and
  assert on behavior/output for an input, not on internal implementation.
- `asyncio_mode = "auto"` is configured, so `async def test_*` functions run
  without an explicit `@pytest.mark.asyncio` decorator.

## Markers (keep the fast pass fast)

CI's unit pass runs `-m "not integration and not slow"` and ignores `tests/e2e`.

- `@pytest.mark.slow` — anything taking more than 5 seconds.
- `@pytest.mark.integration` — anything that needs a live service or network.
- `@pytest.mark.e2e` — cross-package integration (also lives under `tests/e2e/`).

A unit test must be deterministic and key-free: set `AGENTIC_NO_LLM=1` (or patch
the model client) instead of calling a real provider. Flaky tests are bugs —
fix or delete them.

## Fixtures and isolation

- Shared fixtures live in the nearest `conftest.py`. The root
  `tests/conftest.py` already resets the global LLM client to backend-less
  placeholder mode and snapshots/restores `os.environ` around every test.
- Never write to `os.environ` directly — use `monkeypatch.setenv` so the change
  is unwound. Direct writes leak across tests and make the suite order-dependent.
- Static inputs go under `tests/fixtures/` (e.g. `deterministic_input.json`,
  `code_review_input.json`). Reference them via
  `Path(__file__).parent / "fixtures"`, not hardcoded absolute paths.

## Golden / snapshot tests

- Golden outputs live in `tests/golden/`; compare against them with LLM calls
  mocked so the result is stable without API keys (see
  `tests/test_golden_workflow.py`).
- Strip volatile keys (`start_time`, `end_time`, `*_id`, `*_duration_ms`) before
  comparing — never assert on wall-clock timing or generated ids.
- Regenerate a golden file deliberately (delete it, rerun with the documented
  `--update-golden` flow) and commit the diff; do not hand-edit golden JSON.
- Pydantic wire-format schemas under `tests/schemas/` are generated artifacts —
  a contract change must regenerate and commit them (the `wire-format-drift`
  CI job enforces this). Do not edit them by hand.

## Coverage expectation

New backend code targets 80% coverage on changed lines (the suite-wide gate is
80% on `agentic_v2`). Cover the happy path plus at least one edge case — error
paths, boundaries, and the empty/permission-denied distinctions are where real
bugs hide, so prioritize those over trivial getter/constructor tests.

## Don't

- No `print` in tests — assert instead.
- No bare `except:` — catch the specific exception you expect.
- No real secrets in fixtures; use the redaction/secrets corpora under
  `tests/fixtures/` when exercising sanitization.
