<div align="center">

# Agentic Runtime Platform

Run YAML-defined AI workflows through a native DAG engine or a LangGraph adapter.

[![CI](https://github.com/tafreeman/agentic-runtime-platform/actions/workflows/ci.yml/badge.svg)](https://github.com/tafreeman/agentic-runtime-platform/actions/workflows/ci.yml)
[![Nightly E2E](https://github.com/tafreeman/agentic-runtime-platform/actions/workflows/nightly.yml/badge.svg)](https://github.com/tafreeman/agentic-runtime-platform/actions/workflows/nightly.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
![coverage](https://img.shields.io/badge/coverage-80%25%20gated%20subset-brightgreen)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Documentation](https://img.shields.io/badge/docs-MkDocs-blue.svg)](https://tafreeman.github.io/agentic-runtime-platform/)

[Documentation](https://tafreeman.github.io/agentic-runtime-platform/) ·
[Quick start](https://tafreeman.github.io/agentic-runtime-platform/getting-started/quickstart/) ·
[Architecture](https://tafreeman.github.io/agentic-runtime-platform/ARCHITECTURE/) ·
[Known limitations](https://tafreeman.github.io/agentic-runtime-platform/KNOWN_LIMITATIONS/)

</div>

Agentic Runtime Platform is a Python and React monorepo for defining, running,
observing, and evaluating multi-step AI workflows. A workflow is a YAML file
whose steps form a directed acyclic graph (DAG). Independent steps can run at
the same time, dependent steps wait for their inputs, and failures prevent
downstream work from running with incomplete data.

The repository is an inspectable implementation and development platform. It
includes operational controls, but it is not a hosted service or a claim that
every deployment concern is solved. Read
[Known limitations](docs/KNOWN_LIMITATIONS.md) before using it in a
long-running or multi-tenant environment.

## What is included

| Area | What it provides |
|---|---|
| Workflow runtime | YAML loading, input validation, DAG scheduling, conditional steps, bounded loops, retries, timeouts, and run records |
| Execution engines | A dependency-light native DAG engine and an optional LangGraph adapter behind one `ExecutionEngine` interface |
| Model routing | Capability tiers, provider selection, health tracking, fallback chains, and circuit breakers |
| Tool controls | Explicit tool allowlists and approval checks for high-impact tools; approval-required calls fail closed when no approval provider is registered |
| Server and UI | FastAPI endpoints, SSE and WebSocket run events, a React dashboard, workflow editing, run history, model settings, and evaluation views |
| Evaluation | YAML rubrics, objective metrics, batch and streaming runners, LLM-as-judge support, and report generation |
| RAG library | Loading, chunking, embeddings, in-memory or LanceDB storage, BM25, hybrid retrieval, reranking, and context assembly |
| Integrations | OpenTelemetry, Prometheus, Redis-backed shared state, and an MCP client |

## Quick start

### Requirements

- Python 3.11 or newer
- Node.js 20 or newer
- npm
- PowerShell and [`just`](https://github.com/casey/just) for the shortest setup path

Clone and install the workspace on Windows:

```bash
git clone https://github.com/tafreeman/agentic-runtime-platform.git
cd agentic-runtime-platform
just setup
```

The current `justfile` selects `powershell.exe`. On Linux or macOS, use the
[manual installation steps](docs/getting-started/installation.md#manual-setup).

Create an input file and run the deterministic workflow:

```bash
printf '{"input_text":"Hello World"}\n' > /tmp/agentic-input.json
AGENTIC_NO_LLM=1 agentic run test_deterministic \
  --input /tmp/agentic-input.json
```

PowerShell:

```powershell
'{"input_text":"Hello World"}' |
  Set-Content -Encoding utf8 .\agentic-input.json
$env:AGENTIC_NO_LLM = "1"
agentic run test_deterministic --input .\agentic-input.json
```

The command should finish with `Status: SUCCESS`. The `--input` option accepts
a JSON file path, not inline JSON.

`AGENTIC_NO_LLM=1` replaces model calls with a fixed response. It is useful for
testing workflow shape, server wiring, and streaming without provider
credentials. It does not test response quality, structured model output, or
tool selection. See [No-LLM mode](docs/NO_LLM_MODE.md).

On Windows, start the backend and UI for local development:

```bash
just dev
```

The development launcher uses:

- UI: `http://127.0.0.1:5173`
- API: `http://127.0.0.1:8010`
- OpenAPI: `http://127.0.0.1:8010/docs`

Use `just dev-stop` to stop both processes. The standalone `agentic serve`
command defaults to port `8000`; pass `--port 8010` when you want it to match
the UI development proxy.

If `just` is not available, follow the
[manual installation steps](docs/getting-started/installation.md).

## Workflow example

This two-step workflow runs without a model. The second step waits for the
first step's output:

```yaml
name: test_deterministic
description: Simple deterministic workflow for testing
version: "1.0"

inputs:
  input_text:
    type: string
    required: true

outputs:
  processed_text:
    from: ${steps.step1.outputs.result}

steps:
  - name: step1
    agent: tier0_process
    description: Process the input text
    inputs:
      text: ${inputs.input_text}
    outputs:
      result: processed_text

  - name: step2
    agent: tier0_counter
    description: Count characters
    depends_on: [step1]
    inputs:
      text: ${steps.step1.outputs.result}
    outputs:
      count: count_value
```

Built-in definitions live in
[`agentic_v2/workflows/definitions`](agentic-workflows-v2/agentic_v2/workflows/definitions/).
Use the CLI to inspect and validate them:

```bash
agentic list workflows
agentic validate test_deterministic
agentic run test_deterministic --input .\agentic-input.json --dry-run
```

See the [workflow authoring guide](docs/WORKFLOW_AUTHORING.md) for the complete
schema and [workflow reference](docs/workflows/index.md) for the shipped
definitions.

## Execution engines

Named YAML workflows use the LangGraph adapter by default. Install the
`langchain` extra for that path. The native engine has no LangGraph dependency
and is selected explicitly:

```bash
agentic run code_review --input review-input.json --adapter langchain
agentic run code_review --input review-input.json --adapter native
```

Runtime-generated `DAG` and `Pipeline` objects use the native engine. The
server validates `AGENTIC_DEFAULT_ADAPTER` at startup and stops with an install
hint when the selected adapter is unavailable.

The two engines are both supported. ADR-031 proposed removing LangGraph but was
superseded; the adapter remains part of the current architecture. See
[Architecture](docs/ARCHITECTURE.md) and the
[ADR index](docs/adr/ADR-INDEX.md).

## Model providers

The runtime supports OpenAI, Anthropic, Gemini, Azure OpenAI, Azure AI Foundry,
NVIDIA NIM, OpenRouter, Ollama, and compatible local endpoints. Provider
packages and credentials depend on the selected execution path.

Copy the environment template before using a real provider:

```bash
cp .env.example .env
```

PowerShell:

```powershell
Copy-Item .env.example .env
```

Set only the credentials you need. Do not commit `.env`. The
[configuration reference](docs/configuration.md) lists the supported variables
and explains which settings are read at startup or per request.

RAG embedding providers are configured separately from chat providers. The
Python RAG factory can create LiteLLM-backed OpenAI, Voyage, Ollama, or
fully-qualified LiteLLM embedders. The current `agentic rag` CLI still uses a
process-local deterministic embedder and does not persist an index between
separate commands. See [RAG pipeline](docs/rag/index.md) before relying on that
CLI.

## Repository layout

```text
agentic-runtime-platform/
├── agentic-workflows-v2/
│   ├── agentic_v2/           # Runtime, CLI, server, providers, RAG, and MCP
│   ├── tests/                # Python tests
│   └── ui/                   # React and Vite dashboard
├── agentic-v2-eval/          # Rubric and evaluation package
├── tools/                    # Shared provider and benchmark utilities
├── tests/e2e/                # Cross-package tests
├── docs/                     # Published documentation and ADRs
├── examples/                 # Runnable Python examples
├── datasets/                 # Evaluation fixtures
├── infra/                    # Deployment examples
└── otel/                     # Local observability configuration
```

Package boundaries are intentional. Review
[Architecture](docs/ARCHITECTURE.md) and the relevant ADR before adding a
cross-package import.

## Documentation

| Need | Start here |
|---|---|
| Install and run one workflow | [Quick start](docs/getting-started/quickstart.md) |
| Understand every CLI command | [CLI reference](docs/cli-reference.md) |
| Author a workflow | [Workflow authoring](docs/WORKFLOW_AUTHORING.md) |
| Understand the runtime | [Architecture](docs/ARCHITECTURE.md) |
| Integrate with HTTP or WebSocket | [API contracts](docs/api-contracts-runtime.md) |
| Configure providers and security | [Configuration](docs/configuration.md) |
| Run or extend the UI | [UI architecture](docs/architecture-ui.md) |
| Build a RAG pipeline | [RAG pipeline](docs/rag/index.md) |
| Evaluate outputs | [Evaluation overview](docs/architecture-eval.md) |
| Deploy and operate the service | [Operations](docs/operations/index.md) |
| Check known gaps | [Known limitations](docs/KNOWN_LIMITATIONS.md) |
| Review architecture decisions | [ADR index](docs/adr/ADR-INDEX.md) |

## Development

Run commands from the repository root unless a command says otherwise:

```bash
just test
just docs
pre-commit run --all-files
npm --prefix agentic-workflows-v2/ui run build
```

Useful narrower checks:

```bash
python -m pytest agentic-workflows-v2/tests -q
python -m pytest agentic-v2-eval/tests -q
python -m pytest tests/e2e -q
npm --prefix agentic-workflows-v2/ui test
python agentic-workflows-v2/scripts/check_docs_refs.py
python scripts/generate_doc_stats.py --check
```

The runtime coverage gate is 80% over the configured core subset. Optional
provider and plugin modules are excluded from that calculation and require
their own targeted tests. The UI coverage thresholds are defined in
`agentic-workflows-v2/ui/vitest.config.ts`.

See [Contributing](CONTRIBUTING.md) for branch, commit, test, documentation,
and pull-request requirements.

## Security and operational scope

- High-impact tools require approval. When no approval provider is registered,
  the call is denied.
- API authentication is disabled until `AGENTIC_API_KEY` or OIDC is configured.
- The built-in rate limiter is process-local. Use a shared edge or gateway
  limiter for multi-replica deployments.
- Redis can share circuit-breaker state and persist replay events, but it does
  not replace every in-process control.
- The SSRF guard blocks private, loopback, link-local, and reserved targets by
  default. Network-level egress controls are still required for hostile DNS or
  high-assurance environments.

Read [Security hardening](docs/operations/security-hardening.md),
[Known limitations](docs/KNOWN_LIMITATIONS.md), and the
[security policy](agentic-workflows-v2/SECURITY.md) before deployment.

## License

MIT. See [LICENSE](LICENSE).
