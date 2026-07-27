---
title: Installation
description: Install Agentic Runtime Platform — Python runtime, optional UI, optional providers — for development, evaluation, or production.
tags:
  - getting-started
---

# Installation

The runtime is a Python package, the dashboard a Vite-built React 19 app;
providers are optional extras.

## Python runtime

The runtime targets Python 3.11+ and is a uv-style monorepo with three
installable packages: `agentic-workflows-v2`, `agentic-v2-eval`, and
`agentic-tools`. The runtime depends on the tools package; the eval harness
is self-contained.

```bash
git clone https://github.com/tafreeman/agentic-runtime-platform.git
cd agentic-runtime-platform
```

### Editable install with development extras

```bash
cd agentic-workflows-v2
python -m venv .venv
# Linux/macOS:
source .venv/bin/activate
# Windows PowerShell:
.\.venv\Scripts\Activate.ps1

pip install -e ".[dev,server,langchain]"
```

The extras break down as follows (source of truth:
`agentic-workflows-v2/pyproject.toml` `[project.optional-dependencies]`):

| Extra | Pulls in | When you want it |
|-------|----------|-------------------|
| `dev` | `pytest` (+ asyncio/cov/mock/timeout plugins), `black`, `ruff`, `mypy`, `fakeredis`, `jsonschema`, `pydocstyle` | Always — required to run the test suite |
| `server` | `fastapi`, `uvicorn`, `python-multipart`, `slowapi`, `pyjwt` | If you plan to expose the REST/WebSocket API |
| `langchain` | `langchain`, `langchain-core`, `langgraph` (+ provider adapters and checkpointers) | The default adapter for named YAML workflows; also enables the deep `agentic validate` check |
| `tracing` | `opentelemetry-sdk`, OTLP/Prometheus exporters | If you want OTEL traces for every step and tool call |
| `claude` | `anthropic`, `claude-agent-sdk` | If Anthropic is one of your providers |
| `rag` | `lancedb`, `litellm` | If you plan to use the RAG pipeline (loaders, chunker, vectorstore) |
| `ek` | `executionkit` | Optional ExecutionKit execution kernel |
| `devex` | `psutil` | Developer-experience commands (`agentic devex`) |
| `mcp` | `websockets` | MCP client transport |
| `redis` / `sqlite` / `postgres` | `redis`, `aiosqlite`, `psycopg` + checkpointer | Optional storage backends |

### Verify the install

```bash
agentic --help
agentic list workflows
python -m pytest tests/ -q
```

The full test suite runs in roughly 90 seconds on a modern laptop with
`AGENTIC_NO_LLM=1` set.

### Windows one-command bring-up

A PowerShell script is provided to install dependencies, validate every
workflow, and run a smoke test in one go:

```powershell
cd agentic-workflows-v2
.\scripts\setup-dev.ps1
```

Use `-SkipFrontend` to skip the UI build and `-SkipSmokeTest` to skip
workflow validation when you only want a fast dependency install.

## React dashboard

The dashboard is optional. The runtime is fully usable from the CLI and the
REST API; the UI exists for live visualization, run history browsing, and
rubric inspection.

```bash
cd agentic-workflows-v2/ui
npm install
npm run dev          # Vite dev server on http://localhost:5173
npm run build        # production build with TypeScript check
npm run test         # Vitest + React Testing Library
```

The dev server proxies API requests to the FastAPI server on port `8010`,
so start the backend in a second terminal:

```bash
cd agentic-workflows-v2
python -m uvicorn agentic_v2.server.app:app --host 127.0.0.1 --port 8010
```

If port `8010` or `5173` is taken, override with `--port` on the backend
and `npm run dev -- --port 5174` on the frontend.

## Providers

The runtime supports multiple production providers and one offline placeholder
backend. Configuration is a single environment variable per provider —
no provider plugin to install separately, no SDK to pin.

### Provider matrix

| Provider | Variable | Notes |
|----------|----------|-------|
| **None (placeholder)** | `AGENTIC_NO_LLM=1` | Default for development and CI; fully deterministic |
| **OpenAI** | `OPENAI_API_KEY` | Standard OpenAI cloud |
| **Anthropic** | `ANTHROPIC_API_KEY` | Requires the `claude` extra |
| **Google Gemini** | `GEMINI_API_KEY` | Native client, no LangChain wrapper |
| **Azure OpenAI** | `AZURE_OPENAI_API_KEY_0` + `AZURE_OPENAI_ENDPOINT_0` | Supports `_0` through `_n` for round-robin failover |
| **Azure Foundry** | `AZURE_FOUNDRY_API_KEY` + `AZURE_FOUNDRY_ENDPOINT` | Inference SDK path |
| **GitHub Models** | `GITHUB_TOKEN` | Free-tier evaluation; the canonical default for E2E LLM tests in CI ([ADR-016](../adr/ADR-016-github-token-as-default-e2e-llm.md)) |
| **Ollama** | `OLLAMA_BASE_URL` (defaults to `http://localhost:11434`) | Local models, no key required |
| **Local ONNX** | `LOCAL_MODEL_PATH` | Auto-detected from `~/.cache/aigallery` if unset |

An `.env.example` ships at the repo root covering the common providers.
Copy it to `.env` and fill in only the providers you need — the model
router skips providers without credentials at startup. A few variables
(such as the `AZURE_FOUNDRY_*` keys) are read from the environment but not
templated in `.env.example`; set those directly.

### Verify providers

```bash
agentic version            # confirm the CLI entry point resolves
agentic list workflows     # confirm workflow discovery works
agentic serve --no-open    # startup probes configured providers and logs which are available
```

The quickest end-to-end check is a deterministic run that needs no
credentials at all:

```bash
echo '{"input_text": "hello"}' > /tmp/test-input.json
AGENTIC_NO_LLM=1 agentic run test_deterministic --input /tmp/test-input.json
```

## Evaluation harness

The eval harness is its own installable package. Most users do not install
it directly because the runtime invokes it programmatically, but it can be
exercised standalone:

```bash
cd agentic-v2-eval
pip install -e ".[dev]"
python -m agentic_v2_eval evaluate path/to/results.json
python -m agentic_v2_eval report path/to/results.json --format html
```

## Pre-commit hooks

The repo enforces formatting, linting, type checking, and secret detection
on every commit. From the repo root:

```bash
pre-commit install
pre-commit run --all-files
```

The chain is `black` → `isort` → `ruff` → `docformatter` → `mypy` →
`pydocstyle` → `detect-secrets`. CI re-runs the same chain, but also
enforces gates the hooks do not cover — the 80% coverage threshold and the
wire-format drift check — so a passing local hook run is necessary, not
sufficient. See `.claude/rules/ci.md` and `CONTRIBUTING.md` for the full
gate list.

## Next steps

- New to the project? [Quick start](quickstart.md) walks the first run
  end-to-end.
- Want to write your own workflow? [First workflow](first-workflow.md)
  builds a two-step DAG from scratch.
- Wiring a longer-lived environment? [Architecture overview](../ARCHITECTURE.md)
  explains how the runtime, evaluation harness, and UI interact.
