# Coding standards

> **Audience:** Anyone writing Python for this repo.
> **Outcome:** After reading, you know the style, typing, testing, and review rules a change must satisfy — every one of them is enforced by CI or pre-commit, not by convention.
> **Last verified:** 2026-07-05

These are the standards the Agentic Runtime Platform actually enforces. The authoritative gate definitions live in [`CONTRIBUTING.md`](CONTRIBUTING.md) and `.github/workflows/ci.yml`; this page is the summary.

---

## Style and formatting

- **Black** (line-length 88) and **isort** (profile=black) run via pre-commit; unformatted code never reaches the repo.
- **Ruff** is the linter, with rules `E, F, W, I, N, UP, S, B, A, C4, SIM, TCH, RUF` enabled. CI fails if `ruff check --fix` would still change anything — apply autofixes and commit them.
- PEP 8 naming: `snake_case` functions/variables/modules, `PascalCase` classes, `UPPER_SNAKE` constants, `_private` prefix for internal APIs.
- All tool configuration lives in `pyproject.toml`; docformatter and pydocstyle run as scoped pre-commit hooks.

## Types

- Type hints on **every** function signature.
- mypy runs **strict** on `agentic_v2/engine` and `agentic_v2/contracts` (`--disallow-untyped-defs --warn-return-any`); the rest of the runtime runs the relaxed baseline in `pyproject.toml` while type debt is paid down.

## Design rules

- **Immutable patterns** — return new objects; never mutate inputs.
- **Files under 800 lines** — split before a module grows past this.
- **Reuse existing infrastructure** instead of re-implementing it: `SmartModelRouter` for tier/model selection, `ExecutionContext` for run state and checkpoints, `ConversationMemory` for history, the MCP client stack for tool calls, and the shared error classification helpers.
- **Additive-only contracts** — Pydantic v2 models in `contracts/` never remove or rename existing fields; any wire-format change must regenerate the committed schemas and TypeScript types (the `wire-format-drift` CI job enforces this — see [ADR-014](adr/ADR-014-pydantic-wire-format.md)).
- Smallest coherent change; one concern per PR. Match the surrounding code — do not refactor unrelated subsystems.

## Errors and logging

- **No bare `except:`** — catch the specific exception you expect; every handler must log with context, re-raise, or return a meaningful error.
- **Structured logging, no `print`** — use the structlog-based logger; `LOG_FORMAT=json` emits NDJSON in production.
- Never log secrets or PII — the sanitization middleware and detect-secrets baseline back this up, but do not rely on them to catch what you should not have logged.

## Testing

- pytest, Arrange–Act–Assert, behavior over implementation. Full conventions in [`.claude/rules/testing.md`](https://github.com/tafreeman/agentic-runtime-platform/blob/main/.claude/rules/testing.md).
- **80% coverage is the floor**, not a target range: `[tool.coverage.report] fail_under = 80` with `precision = 2` (79.93% fails), enforced in a dedicated `coverage report --fail-under=80` CI step. The UI package holds a separate 60% floor. New backend code targets 80% on changed lines.
- Unit tests are deterministic and key-free — set `AGENTIC_NO_LLM=1` or patch the model client. Mark anything slow or network-bound with `@pytest.mark.slow` / `@pytest.mark.integration` so it stays out of the fast CI pass. Flaky tests are bugs.

## Secrets and configuration

- Configuration flows through environment variables and `.env.example` only. Never read, edit, or commit `.env`.
- Resolve runtime secrets through `agentic_v2.models.secrets.get_secret()` / `get_first_secret()`, not `os.environ` directly.

## Review

This is a single-maintainer repository: correctness is gated by **automated evidence**, not peer approval. Treat AI-generated code as untrusted input — run the full lint + type-check + test set (`just test && just docs && pre-commit run --all-files`) before accepting it. Keep PRs small, use conventional-commit subjects (`type(scope): subject`), and write an ADR when a change meets the criteria in [CONTRIBUTING §6](CONTRIBUTING.md#6-when-to-write-an-adr).
