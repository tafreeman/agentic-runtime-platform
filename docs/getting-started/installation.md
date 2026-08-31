---
title: Installation
description: Install the Python workspace, optional runtime features, and the React dashboard.
tags:
  - getting-started
---

# Installation

The repository contains three Python packages and one Node application:

| Path | Package | Purpose |
|---|---|---|
| repository root | `agentic-tools` | Shared model and benchmark utilities |
| `agentic-workflows-v2/` | `agentic-workflows-v2` | Runtime, CLI, and server |
| `agentic-v2-eval/` | `agentic-v2-eval` | Rubrics, evaluators, runners, and reporters |
| `agentic-workflows-v2/ui/` | private npm package | React dashboard |

Use Python 3.11 or newer and Node.js 20 or newer.

## Full development setup

Clone the repository:

```bash
git clone https://github.com/tafreeman/agentic-runtime-platform.git
cd agentic-runtime-platform
```

On Windows, the repository shortcut creates `.venv`, installs all Python
packages, and installs the UI dependencies:

```bash
just setup
```

The current `justfile` selects `powershell.exe`. Use the manual setup below on
Linux or macOS.

Verify the installation:

```bash
agentic version
agentic list workflows
npm --prefix agentic-workflows-v2/ui run build
```

## Manual setup

Run these commands from the repository root.

### Bash

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e . -c ci-constraints.txt
python -m pip install \
  -e "./agentic-workflows-v2[dev,server,langchain,tracing]" \
  -c ci-constraints.txt
python -m pip install -e "./agentic-v2-eval[dev]" -c ci-constraints.txt
npm --prefix agentic-workflows-v2/ui install
```

### PowerShell

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e . -c ci-constraints.txt
python -m pip install `
  -e "./agentic-workflows-v2[dev,server,langchain,tracing]" `
  -c ci-constraints.txt
python -m pip install -e "./agentic-v2-eval[dev]" -c ci-constraints.txt
npm --prefix agentic-workflows-v2/ui install
```

Installing the root package first matters: both child packages resolve shared
code through the workspace's `agentic-tools` package.

`ci-constraints.txt` is generated from `uv.lock`. Using it keeps local
dependency versions aligned with CI.

## Runtime extras

Extras are declared in `agentic-workflows-v2/pyproject.toml`.

| Extra | Use it for |
|---|---|
| `dev` | pytest, coverage, Ruff, Black, mypy, test fakes, and schema tools |
| `server` | FastAPI, Uvicorn, multipart uploads, rate limiting, and JWT verification |
| `langchain` | The default adapter for named YAML workflows and LangGraph compilation during validation |
| `tracing` | OpenTelemetry SDK, OTLP exporters, Prometheus exporter, and client |
| `ek` | ExecutionKit integration |
| `devex` | Process inspection used by development commands |
| `mcp` | WebSocket transport for the MCP client |
| `redis` | Redis-backed shared state and replay storage |
| `sqlite` | Async SQLite support |
| `postgres` | PostgreSQL LangGraph checkpointer |
| `claude` | Claude Agent SDK integration |

Add extras to the same editable install:

```bash
python -m pip install \
  -e "./agentic-workflows-v2[dev,server,langchain,tracing,redis]" \
  -c ci-constraints.txt
```

Optional packages fail when their feature is selected, not when the base
runtime is imported. For example, requesting the PostgreSQL checkpointer
without the `postgres` extra raises an install hint.

## Deterministic verification

Create an input file:

```bash
printf '{"input_text":"hello"}\n' > /tmp/agentic-input.json
AGENTIC_NO_LLM=1 agentic run test_deterministic \
  --input /tmp/agentic-input.json
```

PowerShell:

```powershell
'{"input_text":"hello"}' |
  Set-Content -Encoding utf8 .\agentic-input.json
$env:AGENTIC_NO_LLM = "1"
agentic run test_deterministic --input .\agentic-input.json
```

Expected result: `Status: SUCCESS`.

The deterministic workflow itself does not call a model. Setting
`AGENTIC_NO_LLM=1` also protects you if you continue with an LLM-backed
workflow before configuring provider credentials.

## Provider configuration

Copy the environment template:

```bash
cp .env.example .env
```

PowerShell:

```powershell
Copy-Item .env.example .env
```

Set only the providers you intend to use. Common chat-provider variables are:

| Provider | Main variable |
|---|---|
| OpenAI | `OPENAI_API_KEY` |
| Anthropic | `ANTHROPIC_API_KEY` |
| Gemini | `GEMINI_API_KEY` or `GOOGLE_API_KEY` |
| Azure OpenAI | `AZURE_OPENAI_API_KEY` and `AZURE_OPENAI_ENDPOINT` |
| Azure AI Foundry | `AZURE_FOUNDRY_API_KEY` and a configured Foundry endpoint |
| NVIDIA NIM | `NVIDIA_API_KEY`, or `NVIDIA_BASE_URL` for a self-hosted endpoint |
| OpenRouter | `OPENROUTER_API_KEY` |
| GitHub Models | `GITHUB_TOKEN` or `GH_TOKEN` |
| Ollama | `OLLAMA_HOST`; `OLLAMA_API_KEY` only when the endpoint requires it |

See [Configuration](../configuration.md) for model overrides, endpoint
settings, authentication, storage, and security controls.

Do not commit `.env` or provider credentials.

## Dashboard

After installing the UI dependencies:

```bash
just dev
```

Or start the two processes manually.

Terminal 1:

```bash
agentic serve --port 8010 --dev --no-open
```

Terminal 2:

```bash
npm --prefix agentic-workflows-v2/ui run dev
```

Open `http://127.0.0.1:5173`. Vite proxies `/api` and `/ws` to
`http://127.0.0.1:8010`.

Build the production UI:

```bash
npm --prefix agentic-workflows-v2/ui run build
```

When `ui/dist` exists, the FastAPI application can serve that build from the
same origin as the API.

## PowerShell bootstrap

The runtime package also includes a Windows setup script:

```powershell
.\agentic-workflows-v2\scripts\setup-dev.ps1
```

Run it from the repository root. Use `-SkipFrontend` to skip the UI and
`-SkipSmokeTest` to skip its workflow smoke check.

## Evaluation package

The full setup installs the evaluation package. Verify its command:

```bash
agentic-v2-eval --help
python -m agentic_v2_eval --help
```

See [Evaluation architecture](../architecture-eval.md) and
[evaluation runners](../evaluation/runners.md) before supplying result files.

## Pre-commit hooks

Install the configured pre-commit and commit-message hooks:

```bash
pre-commit install --install-hooks
pre-commit run --all-files
```

The current hook configuration runs Black, Ruff with import sorting,
docformatter, detect-secrets, and strict mypy for the evaluation package
source. Pydocstyle is enforced on selected runtime modules in CI, not by the
local hook.

## Next steps

- [Quick start](quickstart.md)
- [CLI reference](../cli-reference.md)
- [First workflow](first-workflow.md)
- [Development guide](../development-guide.md)
