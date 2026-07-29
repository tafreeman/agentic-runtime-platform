# Development guide

This guide covers the normal edit, run, and test loop. See
[Contributing](CONTRIBUTING.md) for review and change-management rules.

## Requirements

- Python 3.11 or newer
- Node.js 20 or newer
- Git
- PowerShell for the repository's `just` recipes and `.ps1` scripts

Docker, Redis, PostgreSQL, provider credentials, and telemetry services are
optional unless the feature under test needs them.

## Set up

On Windows, from the repository root:

```text
just setup
python -m pip install pre-commit
pre-commit install --install-hooks
```

`just setup` creates `.venv`, installs the three Python packages in editable
mode, and installs UI dependencies.

The `justfile` currently uses `powershell.exe`. On Linux, macOS, or a Windows
machine without `just`, use the
[manual installation steps](getting-started/installation.md#manual-setup).

Copy `.env.example` only when the work needs runtime configuration:

```powershell
Copy-Item .env.example .env
```

Set only the providers and features you use. `.env` is ignored by Git. See
[Configuration](configuration.md) for current variables and loading behavior.

## Start the development services

On Windows:

```text
just dev
```

| Service | Default |
|---|---|
| FastAPI | `http://127.0.0.1:8010` |
| Vite dashboard | `http://127.0.0.1:5173` |
| Vite hot-module WebSocket | port `5183` |
| OTLP gRPC, when configured | port `4317` |
| OTLP HTTP, when configured | port `4318` |

Manage the processes with:

```text
just dev-status
just dev-reload
just dev-stop
```

The scripts write logs under `agentic-workflows-v2/.run-logs/`.

For separate terminals:

```text
python -m uvicorn agentic_v2.server.app:app --host 127.0.0.1 --port 8010 --reload
npm --prefix agentic-workflows-v2/ui run dev
```

The second command assumes UI dependencies are already installed. Set
`VITE_API_PROXY_TARGET` before starting Vite if the backend is not on port
`8010`.

`agentic serve` is another backend-only option. It defaults to port `8000`;
pass `--port 8010` to match the dashboard proxy.

## Verify a local run

Use the deterministic workflow before debugging a provider:

```powershell
$env:AGENTIC_NO_LLM = "1"
.\.venv\Scripts\agentic.exe run test_deterministic `
  --input agentic-workflows-v2\tests\fixtures\deterministic_input.json
```

A successful result verifies local runtime behavior without proving provider
access, streaming quality, retry behavior, or structured model output.

Remove placeholder mode before a deliberate provider test:

```powershell
Remove-Item Env:AGENTIC_NO_LLM
```

## CLI during development

Common commands:

```text
agentic list workflows
agentic list agents
agentic list tools
agentic list adapters
agentic validate <workflow-name-or-yaml-path>
agentic run <workflow> --input <input.json>
agentic compare <workflow> --input <input.json>
agentic serve --port 8010 --no-open
```

The `run` and `compare` input is a JSON file path. Use
[CLI reference](cli-reference.md) for flags, defaults, and exit behavior.

The RAG CLI is only a component demonstration: ingest and search use separate
in-process indexes. Use the Python RAG API for persistent applications.

## Choose the right test

Run the smallest relevant suite while editing:

```text
python -m pytest agentic-workflows-v2/tests -q
python -m pytest agentic-v2-eval/tests -q
python -m pytest tools/tests -q
python -m pytest tests/e2e -q
npm --prefix agentic-workflows-v2/ui test
```

Useful focused forms:

```text
python -m pytest agentic-workflows-v2/tests/test_<area>.py -q
python -m pytest agentic-workflows-v2/tests -m "not slow and not e2e" -q
npm --prefix agentic-workflows-v2/ui test -- <test-name>
```

Registered Python markers vary by package:

| Marker | Use |
|---|---|
| `slow` | Long-running local checks |
| `e2e` | End-to-end runtime checks |
| `integration` | External or multi-component integration checks |

Check each package's `pyproject.toml` before adding a marker. Do not invent an
unregistered marker to skip a test.

## Coverage

The runtime and evaluation packages each configure an 80% coverage floor:

```text
python -m pytest agentic-workflows-v2/tests `
  --cov=agentic_v2 `
  --cov-report=term-missing

python -m pytest agentic-v2-eval/tests `
  --cov=agentic_v2_eval `
  --cov-report=term-missing
```

The UI enforces 60% for lines, statements, and functions and 56% for branches:

```text
npm --prefix agentic-workflows-v2/ui run test:coverage
```

Use `just test` on Windows for the runtime, evaluation, cross-package, and UI
unit suites in sequence.

## Build the dashboard

```text
npm --prefix agentic-workflows-v2/ui run build
```

This runs the TypeScript project build and writes the production bundle to
`agentic-workflows-v2/ui/dist/`. FastAPI serves that bundle when it exists.

The Vite development server can hide import-path mistakes that the production
bundle rejects. Always run the build after renaming TypeScript files or changing
imports.

## Format, lint, and type-check

Run all configured hooks:

```text
pre-commit run --all-files
```

The hooks are the source of truth for formatter and linter versions. Current
hooks include Black, Ruff, docformatter, mypy, and secret detection.

Useful focused commands:

```text
ruff check agentic-workflows-v2/agentic_v2
black --check agentic-workflows-v2/agentic_v2
python -m mypy agentic-workflows-v2/agentic_v2/engine `
  agentic-workflows-v2/agentic_v2/contracts
```

Python public interfaces should be typed. Use Pydantic v2 APIs:

| Do not use | Use |
|---|---|
| `model.dict()` | `model.model_dump()` |
| `Model.parse_obj(data)` | `Model.model_validate(data)` |
| `Model.__fields__` | `Model.model_fields` |
| `model.copy()` | `model.model_copy()` |

## Change a wire contract

When a generated Pydantic contract changes, run from
`agentic-workflows-v2`:

```text
python -m scripts.generate_ts_types
npm --prefix ui run generate:types
npm --prefix ui run build
```

Review the JSON Schema and TypeScript diff. Do not hand-edit generated files.
The CI drift job repeats generation and fails if committed outputs are stale.

## Change documentation

Run from the repository root:

```text
python agentic-workflows-v2/scripts/check_docs_refs.py
python scripts/generate_doc_stats.py --check
python scripts/check-doc-drift.py
```

When the MkDocs dependencies from `.github/workflows/docs.yml` are installed:

```text
mkdocs build --strict
```

Do not document a command until it has been run from the directory stated on
the page.

## Optional services

The root Compose file can start the backend, frontend, OpenTelemetry collector,
and Jaeger:

```text
docker compose up --build backend frontend otel-collector jaeger
```

Stop it with:

```text
docker compose down --remove-orphans
```

Redis, SQLite, PostgreSQL, LanceDB, MCP, Claude SDK, and tracing dependencies
are installed through runtime extras. See
[Installation](getting-started/installation.md#runtime-extras) before testing
one of those paths.

## Common development problems

- If the CLI is missing, activate `.venv` or call its executable directly.
- If ports are busy, identify the owning process before stopping it.
- If only a provider-backed test fails, inspect provider configuration before
  changing engine code.
- If native and LangGraph differ, check workflow capabilities; the engines do
  not support every feature equally.
- If generated UI types fail, regenerate Python schemas first and TypeScript
  second.
- On Windows, use `npm run` or `npm exec --` instead of relying on `npx`
  through Git Bash.

See [Troubleshooting](operations/troubleshooting.md) for detailed diagnostics.
