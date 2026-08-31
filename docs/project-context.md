# Project context

This page is a compact repository map for tools and contributors that need
orientation before reading source. It avoids counts that become stale.

Updated: 2026-07-28.

## Identity

| Field | Value |
|---|---|
| Repository | `tafreeman/agentic-runtime-platform` |
| Primary branch | `main` |
| Python | 3.11 or newer |
| Node.js | 20 or newer |
| Workspace | Root `agentic-tools` project plus two Python workspace members |
| UI | React 19 and Vite 8 |

## Packages

| ID | Path | Responsibility |
|---|---|---|
| `tools` | repository root and `tools/` | Shared provider, benchmark, cache, and error utilities; installs as `agentic-tools` |
| `runtime` | `agentic-workflows-v2/` | Workflow runtime, CLI, server, agents, model routing, and tools |
| `ui` | `agentic-workflows-v2/ui/` | Browser dashboard |
| `eval` | `agentic-v2-eval/` | Offline rubrics, evaluators, runners, metrics, and reports |

`tests/e2e/` checks behavior across package boundaries.

## Architecture rules

- Keep package boundaries intact.
- The runtime and evaluation package consume `agentic-tools` as an installed
  package.
- Do not add source-path imports between packages.
- The native and LangGraph engines are both active.
- Native owns platform-specific DAG features; LangGraph runs compatible
  workflows.
- Pydantic is the Python wire-format source of truth.
- Committed JSON Schemas generate the dashboard's TypeScript types.
- Secrets stay in environment variables or the secret-provider layer.
- File, shell, HTTP, and high-risk tool access must have explicit boundaries.
- Accepted ADRs are historical records; supersede them with a new ADR rather
  than rewriting the old decision.

## Runtime source map

```text
agentic-workflows-v2/agentic_v2/
|-- adapters/          engine discovery and wrappers
|-- agents/            agent classes and orchestration
|-- cli/               Typer CLI
|-- contracts/         public request, result, and event models
|-- core/              protocols, memory, and common errors
|-- engine/            native DAG and pipeline execution
|-- governance/        approval and escalation
|-- integrations/      telemetry and MCP
|-- langchain/         LangGraph compilation and execution
|-- models/            model routing, health, and provider state
|-- prompts/           persona prompt assets
|-- scoring/           runtime run scoring and judge logic
|-- security/          request and egress controls
|-- server/            FastAPI, routes, streaming, replay, and persistence
|-- tools/             runtime tools
`-- workflows/         workflow loading and bundled YAML definitions
```

## Entry points

| Surface | Entry |
|---|---|
| CLI executable | `agentic` |
| CLI module | `agentic_v2.cli:main` |
| FastAPI app | `agentic_v2.server.app:app` |
| App factory | `agentic_v2.server.app:create_app` |
| Native executor | `agentic_v2.engine.dag_executor:DAGExecutor` |
| Adapter registry | `agentic_v2.adapters.registry:AdapterRegistry` |
| Model router | `agentic_v2.models.smart_router:SmartModelRouter` |
| Offline evaluation CLI | `agentic-v2-eval` |

## CLI commands

```text
agentic run
agentic compare
agentic orchestrate
agentic resume
agentic list
agentic validate
agentic serve
agentic version
agentic devex
```

There is no `agentic eval` command. Offline evaluation uses
`agentic-v2-eval`; server evaluation uses `/api/eval/*` and run evaluation
routes.

The default `run` adapter is `langchain`. `agentic serve` defaults to port
`8000`; the combined development environment uses backend port `8010` and UI
port `5173`.

## Configuration

Settings load from constructor overrides, environment variables, `.env`, and
model defaults in that order. Some credentials are read again at call time
through the secret-provider layer.

Use:

- `.env.example` for a safe template;
- `docs/configuration.md` for behavior and variables; and
- `docs/KNOWN_LIMITATIONS.md` for unsupported or incomplete paths.

Do not copy quotas or provider availability into this file.

## Development

On Windows:

```text
just setup
just dev
just test
just docs
```

The root `justfile` selects `powershell.exe`. Other operating systems should use
the manual commands in `docs/getting-started/installation.md`.

Focused checks from the repository root:

```text
python -m pytest agentic-workflows-v2/tests -q
python -m pytest agentic-v2-eval/tests -q
python -m pytest tools/tests -q
python -m pytest tests/e2e -q
npm --prefix agentic-workflows-v2/ui test
npm --prefix agentic-workflows-v2/ui run build
```

The runtime and offline evaluation packages configure 80% coverage floors. UI
thresholds are defined in `agentic-workflows-v2/ui/vitest.config.ts`.

Provider-backed and live evaluation checks are separate from the deterministic
unit path. `AGENTIC_NO_LLM=1` is useful for local runtime flow but does not
prove provider behavior.

## Documentation sources

| Question | Source |
|---|---|
| How do I install and run it? | `docs/getting-started/` |
| What commands exist? | `docs/cli-reference.md` |
| What are the package boundaries? | `docs/ARCHITECTURE.md` |
| What does the server expose? | `docs/api-contracts-runtime.md` |
| Which settings are current? | `docs/configuration.md` |
| What is not supported? | `docs/KNOWN_LIMITATIONS.md` |
| Which decisions were accepted? | `docs/adr/ADR-INDEX.md` |
| What should a contributor run? | `CONTRIBUTING.md` |

Use current code, package manifests, the OpenAPI document, and CI workflows to
verify facts that can drift.
