# Coding standards

The configuration files and CI workflows are the enforcement source. This page
summarizes how to write code that fits the repository.

Last verified: 2026-07-28.

## Python

- Use Python 3.11 or newer.
- Indent with four spaces.
- Use Black formatting with an 88-character target.
- Use Ruff for linting and import ordering.
- Use `snake_case` for modules, functions, and variables.
- Use `PascalCase` for classes.
- Use `UPPER_CASE` for constants.
- Type public interfaces and any code covered by a strict mypy target.
- Use Pydantic v2 methods such as `model_validate()` and `model_dump()`.

The workspace root and package `pyproject.toml` files define the active Ruff,
Black, pytest, coverage, and mypy settings. Do not copy rule lists into a new
configuration file.

## Type boundaries

Strict mypy settings apply to the evaluation package and selected runtime
areas, including the engine and contracts. Other runtime modules still contain
typed-debt exceptions.

Do not weaken a type check globally to fix one error. Prefer:

1. a more precise annotation;
2. a narrow runtime validation;
3. a local, explained ignore when an external library is incorrectly typed.

Public wire models require special care. A breaking change to a saved result,
HTTP request, HTTP response, or event must be treated as an API change.

## Design

- Keep changes inside the owning package.
- Prefer small functions and modules with one clear responsibility.
- Do not mutate a caller's input unless the API explicitly documents mutation.
- Reuse the existing model router, execution context, error classification,
  secret provider, and tool boundaries.
- Keep workflow YAML declarative; do not hide workflow behavior in import side
  effects.
- Split files before they become difficult to review. Existing approved
  exceptions are recorded in
  [ADR-055](adr/ADR-055-file-size-exception-register.md).

Material changes to engines, public contracts, storage, authentication, or
security boundaries require an ADR. Use the
[ADR index](adr/ADR-INDEX.md) to find related decisions and the next number.

## Errors and logs

- Catch the exception you can handle.
- Preserve useful context when wrapping an error.
- Do not use an empty `except` block.
- Use the repository logger in library and server code.
- CLI commands may write intentional user output; do not replace those messages
  with application logs.
- Never log credentials, authorization headers, private prompts, or direct
  personal data.
- Do not assume middleware redaction will repair unsafe logging.

## Tests

- Add a regression test with a behavior change.
- Use pytest for Python, Vitest for UI units, and Playwright for browser flows.
- Keep normal unit tests deterministic and key-free.
- Use a registered `slow`, `e2e`, or `integration` marker when appropriate.
- Report live-provider coverage separately from mocked or placeholder coverage.
- Treat flaky tests as defects.

Configured floors:

| Area | Floor |
|---|---|
| Runtime Python coverage | 80% |
| Evaluation Python coverage | 80% |
| UI lines, statements, and functions | 60% |
| UI branches | 56% current ratchet |

The config files remain authoritative if these values change.

## React and TypeScript

- Name React components `PascalCase.tsx`.
- Give hooks a `use` prefix.
- Keep API calls and wire types under `ui/src/api/`.
- Reuse design tokens instead of embedding unrelated color values.
- Test route-level behavior at the page boundary and isolated behavior at the
  component boundary.
- Run the production build; Vite development resolution can hide an import that
  TypeScript or Rollup rejects.

## Generated contracts

Do not edit generated JSON Schema or TypeScript wire types by hand.

From `agentic-workflows-v2`:

```text
python -m scripts.generate_ts_types
npm --prefix ui run generate:types
npm --prefix ui run build
```

Review and commit the source model and generated artifacts together.

## Secrets and configuration

- Never commit `.env`, provider keys, tokens, or generated private run data.
- Add safe placeholders to `.env.example`.
- Add behavior and lifecycle details to `docs/configuration.md`.
- Resolve runtime secrets through `get_secret()` or `get_first_secret()` rather
  than adding a new direct environment lookup.
- Keep file, shell, HTTP, and tool access fail-closed.

## Validation

Run focused checks while editing. Before review, run the relevant broad checks:

```text
just test
just docs
pre-commit run --all-files
npm --prefix agentic-workflows-v2/ui run build
```

The `just` recipes currently require PowerShell. Other systems should run the
underlying commands from [Development](development-guide.md).

Use Conventional Commit subjects such as `fix(server): validate run input`.
Follow [Contributing](CONTRIBUTING.md) for the PR checklist and ADR criteria.
