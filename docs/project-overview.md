# Project overview

Agentic Runtime Platform is a monorepo for defining, running, observing, and
evaluating multi-step AI workflows.

Last verified: 2026-07-28.

## What the repository contains

| Area | Path | Purpose |
|---|---|---|
| Shared tools | repository root and `tools/` | Provider clients, benchmark helpers, cache, and shared errors |
| Runtime | `agentic-workflows-v2/` | Workflow loader, execution engines, agents, tools, model routing, CLI, and server |
| Dashboard | `agentic-workflows-v2/ui/` | Browser interface for workflows, models, runs, and evaluations |
| Evaluation | `agentic-v2-eval/` | Offline scoring, metrics, evaluators, runners, and reports |
| Cross-package tests | `tests/e2e/` | Verify public behavior across package boundaries |

The repository root installs as the `agentic-tools` Python package.
`agentic-workflows-v2` and `agentic-v2-eval` are separate workspace members.

## Main capabilities

### Workflow runtime

- Load typed workflow definitions from YAML.
- Validate inputs, dependencies, conditions, and graph structure.
- Run compatible workflows through either the native engine or LangGraph.
- Route model-backed steps by tier, provider availability, and fallback policy.
- Invoke approved tools and deterministic tier-0 steps.
- Emit typed events and save typed run results.
- Resume supported runs from checkpoints.

### Server and dashboard

- REST API for workflows, models, settings, runs, datasets, and evaluations.
- WebSocket execution with replay support.
- Server-sent events for chat and saved run streams.
- Browser views for workflow editing, live execution, model configuration, run
  history, datasets, and evaluations.
- API-key and optional OIDC authentication.
- CORS, rate limiting, sanitization, audit logging, and tool boundaries.

These controls reduce risk but do not make every deployment secure by default.
An exposed service still requires deliberate authentication, network, storage,
secret, and tool-policy configuration.

### Evaluation

There are two evaluation paths:

- the runtime server scores saved runs for the API and dashboard;
- `agentic-v2-eval` scores structured results offline with rubrics, metrics,
  batch runners, and JSON, Markdown, or HTML reports.

They exchange data rather than sharing an internal implementation.

## Execution engines

| Engine | Role |
|---|---|
| `native` | Owns platform-specific DAG behavior such as conditions, retries, budgets, and observers |
| `langchain` | Compiles compatible workflows to LangGraph |

The CLI defaults to `langchain` for named workflow runs. The native engine is
not deprecated or replaced. Use workflow capability checks and
`agentic compare` when engine compatibility matters.

## Technology

| Area | Main technology |
|---|---|
| Python packages | Python 3.11+, hatchling, Pydantic v2 |
| Runtime API | FastAPI and Uvicorn |
| Workflow adapter | LangGraph as an optional runtime extra |
| Dashboard | React 19, TypeScript 6, Vite 8, TanStack Query, XYFlow |
| Tests | pytest, Vitest, and Playwright |
| Documentation | MkDocs Material |
| Telemetry | Optional OpenTelemetry and OTLP |
| Containers | Docker and Docker Compose |
| Automation | GitHub Actions |

The lockfile and package manifests are the source of truth for exact dependency
versions.

## Repository map

```text
agentic-runtime-platform/
|-- pyproject.toml                 root agentic-tools package and workspace
|-- tools/                         shared Python source
|-- agentic-workflows-v2/
|   |-- agentic_v2/
|   |   |-- adapters/              engine registration
|   |   |-- agents/                agent implementations
|   |   |-- cli/                   Typer commands
|   |   |-- contracts/             public Pydantic wire models
|   |   |-- engine/                native execution
|   |   |-- langchain/             LangGraph adapter
|   |   |-- models/                routing and provider health
|   |   |-- server/                FastAPI, WebSocket, and SSE
|   |   |-- tools/                 runtime tools
|   |   `-- workflows/             loader and YAML definitions
|   |-- tests/                     runtime and server tests
|   `-- ui/                        React dashboard
|-- agentic-v2-eval/
|   |-- src/agentic_v2_eval/       offline evaluation package
|   `-- tests/
|-- tests/e2e/                     cross-package tests
|-- docs/                          maintained documentation and ADRs
|-- examples/                      small Python examples
|-- infra/                         deployment configuration
`-- otel/                          telemetry collector configuration
```

## Current boundaries and limits

- Provider-backed behavior requires current credentials and provider access.
- `AGENTIC_NO_LLM=1` is a deterministic development mode, not a provider
  integration test.
- Native and LangGraph execution do not support every feature equally.
- Some state is process-local even when Redis is configured.
- Live provider evaluation is separate from the default unit-test path.

The maintained list is [Known limitations](KNOWN_LIMITATIONS.md).

## Start here

| Need | Document |
|---|---|
| Install and run once | [Quick start](getting-started/quickstart.md) |
| Learn the repository | [Contributor onboarding](ONBOARDING.md) |
| Understand boundaries | [Architecture](ARCHITECTURE.md) |
| Author workflow YAML | [Workflow authoring](WORKFLOW_AUTHORING.md) |
| Use the command line | [CLI reference](cli-reference.md) |
| Call the server | [Runtime API](api-contracts-runtime.md) |
| Configure providers and services | [Configuration](configuration.md) |
| Develop and test | [Development guide](development-guide.md) |
| Deploy | [Deployment guide](deployment-guide.md) |
| Review decisions | [ADR index](adr/ADR-INDEX.md) |
