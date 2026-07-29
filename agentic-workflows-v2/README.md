# Agentic Workflows v2

`agentic-workflows-v2` is the repository's workflow runtime. It provides:

- a typed Python package named `agentic_v2`;
- YAML workflow definitions;
- native and LangGraph execution engines;
- the `agentic` command-line interface;
- a FastAPI backend; and
- a React dashboard in `ui/`.

The native engine is the implementation for runtime features such as conditional
edges, retry policies, execution budgets, and observer hooks. The LangGraph
adapter remains available for compatible workflows and engine comparisons.

## Install

The supported contributor setup starts at the repository root:

```text
just setup
```

That command creates the root `.venv`, installs all Python workspace packages
in editable mode, and installs the dashboard dependencies. The current
`justfile` uses PowerShell; use the central manual installation guide on other
operating systems.

To install only this package, change to `agentic-workflows-v2` and run:

```text
python -m pip install -e ".[dev,server,langchain]"
```

Useful optional extras are:

| Extra | Adds |
|---|---|
| `ek` | ExecutionKit integration |
| `eval` | Agentic EvalKit integration |
| `tracing` | OpenTelemetry exporters and metrics support |
| `claude` | Claude SDK adapters |
| `rag` | LanceDB and document-loading support |
| `devex` | Process and port-management helpers |
| `mcp` | MCP support |
| `redis` | Redis event and replay support |
| `sqlite` | SQLite LangGraph checkpoints |
| `postgres` | PostgreSQL LangGraph checkpoints |

## Run a workflow

From the repository root:

```powershell
$env:AGENTIC_NO_LLM = "1"
.\.venv\Scripts\agentic.exe run test_deterministic `
  --input agentic-workflows-v2\tests\fixtures\deterministic_input.json
```

This uses a deterministic test workflow and does not call a model provider.
The default `run` adapter is `langchain`; select the native engine explicitly
when needed:

```text
agentic run test_deterministic --input <input.json> --adapter native
```

Other common commands:

```text
agentic list workflows
agentic validate code_review
agentic compare test_deterministic --input <input.json>
agentic run code_review --dry-run
agentic version
```

The `--input` value is a path to a JSON file, not inline JSON. See the
[CLI reference](../docs/cli-reference.md) for all commands and exit behavior.

## Start the backend and dashboard

From the repository root:

```text
just dev
```

This starts:

- FastAPI at `http://127.0.0.1:8010`;
- the Vite development server at `http://127.0.0.1:5173`; and
- API and WebSocket proxies from Vite to FastAPI.

Use `just dev-stop` to stop both processes.

To run only the backend from this directory:

```text
python -m uvicorn agentic_v2.server.app:app --host 127.0.0.1 --port 8010
```

The packaged `agentic serve` command also starts the backend, but its default
port is `8000`.

## Workflow definitions

Production examples in `agentic_v2/workflows/definitions/`:

| Workflow | Demonstrates |
|---|---|
| `bug_resolution` | Analyze, implement, test, and review a fix |
| `code_review` | Parallel review followed by synthesis |
| `conditional_branching` | Route execution from a condition |
| `consensus_review` | Combine multiple review perspectives |
| `fullstack_generation` | Coordinate backend and frontend generation |
| `iterative_review` | Repeat a review step until an exit condition |

`test_deterministic` and `test_workflow` are test fixtures. They are useful for
smoke tests but are not production examples.

Workflow names resolve against the definitions packaged with `agentic_v2`.
The CLI also accepts a direct path to a `.yaml` or `.yml` file. Python callers
can pass a custom `definitions_dir` to `WorkflowLoader` or `WorkflowRunner`.

See [Workflows](docs/WORKFLOWS.md) for the YAML format and runtime behavior.

## Project map

| Path | Purpose |
|---|---|
| `agentic_v2/agents/` | Agent definitions and model-backed execution |
| `agentic_v2/engine/` | Native and LangGraph execution |
| `agentic_v2/contracts/` | Stable request, result, and event models |
| `agentic_v2/workflows/` | Workflow loading, validation, and definitions |
| `agentic_v2/server/` | FastAPI application and routes |
| `agentic_v2/rag/` | Retrieval components and embedding adapters |
| `tests/` | Runtime and server tests |
| `ui/` | React dashboard |
| `scripts/` | Contract generation and local utilities |

See [Repository map](docs/REPO_MAP.md) for a more detailed package guide.

## Configuration

Copy the root `.env.example` to `.env` and set only the providers and features
you use. Important behavior:

- `AGENTIC_NO_LLM=1` prevents provider calls and returns deterministic
  placeholder output.
- `AGENTIC_MODEL_TIER_1` through `AGENTIC_MODEL_TIER_3` override model routing.
- `AGENTIC_API_KEY` protects `/api/*` except public health and documentation
  paths.
- `AGENTIC_CORS_ORIGINS` sets the browser origin allowlist.
- `AGENTIC_TRACING=true` enables tracing when the `tracing` extra is installed.

The full variable reference, including RAG, OIDC, replay, checkpoint, and
tool-boundary settings, is in [Configuration](../docs/configuration.md).

## Development checks

Run the broad checks from the repository root:

```text
just test
just docs
pre-commit run --all-files
```

During iteration, use the smallest relevant command:

```text
python -m pytest agentic-workflows-v2/tests -q
npm --prefix agentic-workflows-v2/ui test
npm --prefix agentic-workflows-v2/ui run build
```

Changes to Pydantic wire contracts require regenerated JSON Schemas and
TypeScript types. Follow the commands in the root
[contributor guide](../CONTRIBUTING.md#change-generated-contracts).

## More documentation

- [Architecture](../docs/ARCHITECTURE.md)
- [Getting started](../docs/getting-started/index.md)
- [Runtime API](../docs/api-contracts-runtime.md)
- [RAG](../docs/rag/index.md)
- [Known limitations](../docs/KNOWN_LIMITATIONS.md)
- [Package development guide](docs/DEVELOPMENT.md)

## License

MIT. See the repository's [LICENSE](../LICENSE).
