# Contributing to Agentic Workflows v2

This page adds runtime- and UI-specific rules to the repository
[contributor guide](../CONTRIBUTING.md). The root guide owns branch, commit,
pull-request, documentation, and full validation policy.

Last verified: 2026-07-28.

## Package boundaries

Keep runtime concerns inside their existing areas:

| Area | Path |
|---|---|
| Execution engines | `agentic_v2/engine/`, `agentic_v2/langchain/`, `agentic_v2/adapters/` |
| Agents and prompts | `agentic_v2/agents/`, `agentic_v2/prompts/` |
| Public wire models | `agentic_v2/contracts/` and selected `agentic_v2/server/models*` |
| Server | `agentic_v2/server/` |
| Model routing | `agentic_v2/models/` |
| RAG | `agentic_v2/rag/` |
| Workflow definitions | `agentic_v2/workflows/` |
| Dashboard | `ui/src/` |

Do not import source directly from `agentic-v2-eval` or a sibling repository.
Review the root architecture and relevant ADR before adding a package
dependency.

## Set up

The supported full setup runs from the repository root:

```text
just setup
```

The root `justfile` uses PowerShell. Other environments should follow the
[manual setup](../docs/getting-started/installation.md#manual-setup).

To install only this package, run from `agentic-workflows-v2`:

```text
python -m pip install -e ".[dev,server,langchain]"
```

## Run focused checks

From the repository root:

```text
python -m pytest agentic-workflows-v2/tests -q
npm --prefix agentic-workflows-v2/ui test
npm --prefix agentic-workflows-v2/ui run build
```

The runtime configures an 80% Python coverage floor. The UI configures 60% for
lines, statements, and functions and a 56% branch ratchet. Use the values in
`pyproject.toml` and `ui/vitest.config.ts` as the source of truth.

Before review, also run the root checks:

```text
just test
just docs
pre-commit run --all-files
```

Live-provider, slow, and some end-to-end tests are separate from the normal
unit path. Report exactly which commands ran.

## Test behavior changes

- Put Python regression tests in `tests/test_*.py`.
- Put UI unit tests in `ui/src/**/__tests__/` or `*.test.ts(x)`.
- Put browser flows in `ui/e2e/*.spec.ts`.
- Use the registered `slow`, `e2e`, or `integration` marker when its definition
  matches the test.
- Use deterministic fakes for normal CI. Do not silently convert a live test
  into a mock-only claim.

## Change a wire contract

Pydantic models generate committed JSON Schemas, which then generate
TypeScript types. Do not edit the generated artifacts by hand.

From `agentic-workflows-v2`:

```text
python -m scripts.generate_ts_types
npm --prefix ui run generate:types
npm --prefix ui run build
```

Commit the Python model, JSON Schema, generated TypeScript, and tests together.
The `wire-format-drift` CI job repeats generation.

## Update the matching documentation

| Change | Document |
|---|---|
| CLI behavior | `../docs/cli-reference.md` |
| Configuration variable | `../.env.example` and `../docs/configuration.md` |
| Workflow syntax | `../docs/WORKFLOW_AUTHORING.md` |
| API route or schema | `../docs/api-contracts-runtime.md` |
| UI route or API use | `../docs/ui/` |
| Architecture boundary | `../docs/ARCHITECTURE.md` and an ADR when needed |
| Current unsupported behavior | `../docs/KNOWN_LIMITATIONS.md` |

Keep examples small and executable. Do not copy the environment-variable
catalog into another page.

## Security

- Never commit credentials, provider responses containing private data, or
  generated run artifacts.
- Resolve runtime secrets through the secret-provider layer instead of reading
  environment variables directly in new application code.
- Keep file, shell, HTTP, MCP, and tool-approval boundaries fail-closed.
- Follow [SECURITY.md](../SECURITY.md) for vulnerability reports.
