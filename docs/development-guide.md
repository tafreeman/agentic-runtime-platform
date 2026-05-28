# Development Guide

This guide covers everything needed to set up a local development environment, run the full stack, test changes, use the CLI, and follow the project's coding standards for the `agentic-runtime-platform` monorepo.

---

## Prerequisites

| Requirement | Version | Notes |
|---|---|---|
| Python | 3.11+ | Required by all three Python packages |
| Node.js | 20+ | Required by the React dashboard |
| uv | Latest | Python package and workspace manager — install via `pip install uv` or `curl -LsSf https://astral.sh/uv/install.sh \| sh` |
| Git | Any recent | Required for pre-commit hooks |
| pre-commit | Latest | Installed via `pip install pre-commit` or included in dev extras |

Optional but recommended:

- Docker + Docker Compose — for running the full containerized stack
- A supported LLM provider key — at least one is required to execute real workflows (see Environment Variables below)

---

## Installation

### 1. Clone the repository

```bash
git clone https://github.com/tafreeman/agentic-runtime-platform.git
cd agentic-runtime-platform
```

### 2. Install the uv workspace

```bash
uv sync
```

This installs all three Python packages (`agentic-workflows-v2`, `agentic-v2-eval`, and `agentic-tools`) into a shared virtual environment, respecting the version pins in `uv.lock`.

### 3. Install runtime extras

For active runtime development, install the full extras set:

```bash
pip install -e "agentic-workflows-v2/[dev,server,langchain]"
```

Available extras:

| Extra | Contents |
|---|---|
| `dev` | pytest, pytest-asyncio, pytest-cov, black, ruff, mypy, pre-commit |
| `server` | FastAPI, uvicorn, websockets, python-multipart |
| `langchain` | langchain-core, langgraph, langchain-openai, langchain-anthropic |
| `rag` | sentence-transformers, rank_bm25, PyPDF2, python-docx |
| `tracing` | opentelemetry-sdk, opentelemetry-exporter-otlp |
| `claude` | anthropic SDK extras for Claude models |

### 4. Install the eval framework

```bash
pip install -e "agentic-v2-eval/[dev]"
```

### 5. Install frontend dependencies

```bash
cd agentic-workflows-v2/ui
npm install
cd ../..
```

### 6. Install pre-commit hooks

```bash
pre-commit install
```

### Windows Quick Start (alternative to steps 2–5)

On Windows, a single script handles the full bring-up:

```powershell
cd agentic-workflows-v2
.\scripts\setup-dev.ps1
```

This checks prerequisites (`uv`, `node`, `npm`), runs `uv sync` with all required extras,
installs and builds the frontend, validates all 6 bundled workflows, runs a deterministic
smoke test, and probes the backend health endpoint to confirm the server starts. Flags:

- `-SkipSmokeTest` — skip workflow validation, smoke test, and health probe (faster)
- `-SkipFrontend` — skip `npm install`, `npm run build`, and the node/npm prerequisite checks

After setup completes, launch the dev servers with `.\scripts\start-dev.ps1`.

---

## Environment Variables

Copy `.env.example` to `.env` and set at least one LLM provider key:

```bash
cp .env.example .env
```

Then edit `.env`. The minimum required configuration to run workflows is one provider key:

```
# Choose at least one:
GITHUB_TOKEN=your_github_token          # Free tier available
OPENAI_API_KEY=your_openai_key          # Paid
ANTHROPIC_API_KEY=your_anthropic_key    # Paid
GEMINI_API_KEY=your_gemini_key          # Free tier available
```

### Full Environment Variable Reference

#### LLM Providers

| Variable | Description |
|---|---|
| `GITHUB_TOKEN` | GitHub Models API key (free tier; supports many models via GitHub Marketplace) |
| `OPENAI_API_KEY` | OpenAI API key |
| `ANTHROPIC_API_KEY` | Anthropic Claude API key |
| `GEMINI_API_KEY` | Google Gemini API key |
| `AZURE_OPENAI_API_KEY_0` | Azure OpenAI key (supports `_0` through `_n` for failover rotation) |
| `AZURE_OPENAI_ENDPOINT_0` | Azure OpenAI endpoint URL |
| `AZURE_AI_SERVICES_ENDPOINT` | Azure AI Services endpoint (optional) |
| `AZURE_COGNITIVE_ENDPOINT` | Azure Cognitive Services endpoint (optional) |
| `LOCAL_MODEL_PATH` | Path to local ONNX model directory (auto-detected from `~/.cache/aigallery` if unset) |
| `PHI_SILICA_LAF_FEATURE_ID` | Windows AI (Phi Silica) LAF feature ID (optional) |
| `PHI_SILICA_LAF_TOKEN` | Windows AI LAF token |
| `PHI_SILICA_LAF_ATTESTATION` | Windows AI LAF attestation string |

#### Server Configuration

| Variable | Description | Default |
|---|---|---|
| `AGENTIC_API_KEY` | Bearer token for API authentication. When unset, all routes are public. | (unset = open) |
| `AGENTIC_CORS_ORIGINS` | Comma-separated list of allowed CORS origins. | localhost:5173, :8000, :8010 |
| `AGENTIC_FILE_BASE_DIR` | Base directory for all file operations. Prevents path traversal. Set in production. | (unset = unrestricted) |
| `AGENTIC_BLOCK_PRIVATE_IPS` | Block HTTP tool requests to private IP ranges. Set to `1` in production. | (unset) |
| `AGENTIC_EXTERNAL_AGENTS_DIR` | Path to directory containing additional agent definitions. | (unset) |
| `AGENTIC_MEMORY_PATH` | Path for persistent memory store. | (unset = in-memory only) |

#### LLM Routing

| Variable | Description |
|---|---|
| `AGENTIC_MODEL_TIER_1` | Override default tier-1 (fast) model name. |
| `AGENTIC_MODEL_TIER_2` | Override default tier-2 (capable) model name. |
| `AGENTIC_JUDGE_MODEL` | Model name used for LLM-as-judge evaluation scoring. |

#### OpenTelemetry

| Variable | Description | Default |
|---|---|---|
| `AGENTIC_TRACING` | Enable OTEL tracing. Set to `1` to enable. | disabled |
| `AGENTIC_TRACE_SENSITIVE` | Include prompts and outputs in spans. Set to `1` with caution. | excluded |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | OTLP exporter endpoint URL. | `http://localhost:4317` |
| `OTEL_EXPORTER_OTLP_PROTOCOL` | OTLP protocol: `grpc` or `http/protobuf`. | `grpc` |

---

## Running Development Servers

### ⚡ One-Click Start (Windows — recommended)

From the **repo root**, run one command that starts both the backend and frontend:

```powershell
.\agentic-workflows-v2\scripts\start-dev.ps1 -BackendPort 8010 -FrontendPort 5173 -ApiProxyTarget "http://127.0.0.1:8010"
```

Wait for the output:

```
Backend:  http://127.0.0.1:8010
Frontend: http://127.0.0.1:5173
```

Then open **http://localhost:5173** in a browser.

To stop all dev servers:

```powershell
.\agentic-workflows-v2\scripts\stop-dev.ps1
```

Logs are written to `agentic-workflows-v2/.run-logs/` (`backend.out.log`, `backend.err.log`, `frontend.out.log`).

---

### Manual Start (two terminals)

If you prefer separate terminals for easier log visibility:

#### Terminal 1 — Backend

```bash
cd agentic-workflows-v2
python -m uvicorn agentic_v2.server.app:app --host 127.0.0.1 --port 8010 --reload
```

The `--reload` flag enables hot-reload on source file changes. The server starts a lifespan hook on startup that probes all configured LLM providers and logs which are available.

Verify the backend is running:

```bash
curl http://localhost:8010/api/health
```

#### Terminal 2 — Frontend

```bash
cd agentic-workflows-v2/ui
npm run dev
```

The Vite dev server starts on port 5173 and proxies all `/api/*` and `/ws/*` requests to the backend at `localhost:8010`. Open `http://localhost:5173` in a browser.

---

## CLI Usage

The `agentic` CLI is installed as a script when the `agentic-workflows-v2` package is installed.

```bash
# List all available workflows, agents, or tools
agentic list workflows
agentic list agents
agentic list tools

# Execute a workflow
agentic run code_review --input input.json

# Validate a workflow YAML file
agentic validate agentic_v2/workflows/definitions/code_review.yaml

# Start the server (alternative to uvicorn directly)
agentic serve

# Compare native and LangGraph engine outputs for the same workflow
agentic compare code_review --input input.json

# RAG pipeline operations
agentic rag ingest --source ./docs
agentic rag search "how does the DAG executor work"
```

---

## Testing

### Backend Tests

```bash
cd agentic-workflows-v2
python -m pytest tests/ -v
```

Run with coverage (80% gate enforced in CI):

```bash
python -m pytest tests/ -q --cov=agentic_v2 --cov-report=term-missing --cov-fail-under=80
```

Skip slow or integration tests for faster local iteration:

```bash
python -m pytest tests/ -m "not integration and not slow" -q
```

### Eval Framework Tests

```bash
cd agentic-v2-eval
python -m pytest tests/ -q
```

### Tools Package Tests

```bash
python -m pytest tools/tests/ -q --cov=tools --cov-report=term-missing --cov-fail-under=70
```

### Frontend Tests

```bash
cd agentic-workflows-v2/ui
npm run test
```

Run with coverage (60% threshold):

```bash
npm run test:coverage
```

### Cross-Package E2E Tests

```bash
# From the repo root
python -m pytest tests/e2e/test_cross_package.py -q -m e2e
```

### Test Markers

| Marker | Description |
|---|---|
| `integration` | Tests that require external services or real LLM calls |
| `slow` | Tests that take more than 5 seconds |
| `e2e` | Cross-package end-to-end smoke tests |
| `security` | Security-focused tests |

Exclude integration tests: `pytest -m "not integration"`

---

## Linting and Type Checking

Run all pre-commit hooks (black, isort, ruff, docformatter, mypy, pydocstyle, detect-secrets):

```bash
pre-commit run --all-files
```

Run individual tools:

```bash
# Ruff linter
ruff check agentic-workflows-v2/agentic_v2/

# Black formatter
black agentic-workflows-v2/agentic_v2/

# isort import sorter
isort agentic-workflows-v2/agentic_v2/

# mypy type checker
cd agentic-workflows-v2
python -m mypy agentic_v2/ --ignore-missing-imports
```

The `pyproject.toml` at the workspace root defines shared ruff, black, and pytest configuration inherited by all workspace members.

---

## Frontend Build

```bash
cd agentic-workflows-v2/ui
npm run build
```

This runs TypeScript type checking and then produces a production build in `ui/dist/`. The FastAPI server automatically serves this directory when it exists.

---

## Common Issues and Solutions

### Windows Paths

Use forward slashes in all Python `pathlib.Path` operations. The codebase uses `pathlib.Path` throughout, which handles Windows path separators automatically.

Avoid `sys.path` manipulation. Always use proper package imports (`from agentic_v2.core import ...`, not relative `sys.path` hacks).

### pytest-asyncio Auto Mode

All tests in `agentic-workflows-v2/tests/` use `asyncio_mode = "auto"` (configured in `pyproject.toml`). This means async test functions run automatically without `@pytest.mark.asyncio` decorators. Do not add the decorator — it causes a warning.

### Optional LangChain Imports

All imports from `agentic_v2.langchain` must be guarded:

```python
try:
    from agentic_v2.langchain.runner import LangGraphRunner
except ImportError:
    LangGraphRunner = None  # type: ignore[assignment,misc]
```

If the `[langchain]` extra is not installed, these imports will fail. Never make LangGraph a hard dependency from outside the `langchain/` subpackage.

### Port Conflicts

Check for processes using the ports before starting servers:

```bash
# Check port 8010 (backend)
netstat -ano | findstr :8010   # Windows
lsof -i :8010                  # Linux/macOS

# Check port 5173 (frontend)
netstat -ano | findstr :5173
```

Ports in use by this project: 8010 (backend), 5173 (Vite dev), 6006 (Storybook, not installed by default), 4317 (OTLP gRPC), 4318 (OTLP HTTP).

### Pydantic v2 API

The codebase uses Pydantic v2 exclusively. The legacy v1 methods are not available:

| Wrong (v1) | Correct (v2) |
|---|---|
| `model.dict()` | `model.model_dump()` |
| `Model.parse_obj(data)` | `Model.model_validate(data)` |
| `Model.__fields__` | `Model.model_fields` |
| `model.copy()` | `model.model_copy()` |

### Vite `.js` to `.ts` Resolution

Vite's dev server auto-resolves `.js` imports to `.ts` files, but Rollup (used in the production build) does not. When renaming a file from `.js` to `.ts`, update all explicit `.js` import paths, or the production build will fail with a module not found error.

### npx on Windows

`npx` is unreliable on the Windows PATH in Git Bash. Use `npm run <script>` instead of `npx <tool>` for all Node.js tooling.

### Pre-commit detect-secrets

If `detect-secrets` blocks a commit due to a false positive, add a baseline entry:

```bash
detect-secrets scan --baseline .secrets.baseline
```

Never add real secrets to the baseline — investigate all flagged strings before excluding.
