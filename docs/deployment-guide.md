# Deployment Guide

This guide covers the CI/CD pipeline, Docker containerization, environment variable configuration for production, security hardening, and observability setup for the `agentic-runtime-platform` monorepo.

---

## CI/CD Pipeline

The primary CI workflow is defined in `.github/workflows/ci.yml`. It runs on every push to `main` and `agenticv2`, and on all pull requests targeting those branches.

### Pipeline Jobs

The `ci.yml` workflow contains eight jobs. All jobs run on `ubuntu-latest`.

| Job | Trigger | Key Steps |
|---|---|---|
| `lint-and-test` | Every push/PR | pre-commit hooks, pytest --cov (80% gate), docs reference check |
| `frontend` | Every push/PR | `npm ci`, TypeScript + Vite build, Vitest coverage |
| `eval-tests` | Every push/PR | Install eval package, pytest on `agentic-v2-eval/tests/` |
| `tools-tests` | Every push/PR | Install tools package, pytest --cov (70% gate) |
| `type-check` | Every push/PR | mypy on `agentic_v2/` with `--ignore-missing-imports` |
| `integration` | Every push/PR | Validate all YAML workflow definitions, run deterministic examples, verify critical imports |
| `cross-package-e2e` | Every push/PR | Install all three packages, run `tests/e2e/test_cross_package.py -m e2e` |
| `security` | Every push/PR | bandit SAST scan, pip-audit CVE scan |

A single job failure blocks the merge. There are no bypass mechanisms for CI failures.

### Additional Workflow Files

| File | Purpose |
|---|---|
| `deploy.yml` | Production deployment (triggered manually or on release tags) |
| `dependency-review.yml` | Dependency license and vulnerability review on every PR |
| `docs-verify.yml` | Validates internal documentation cross-references |
| `eval-package-ci.yml` | Isolated CI for the eval package |
| `tools-ci.yml` | Isolated CI for the tools package |
| `performance-benchmark.yml` | LLM latency and throughput benchmarks (scheduled) |
| `prompt-quality-gate.yml` | Automated prompt quality scoring |
| `prompt-validation.yml` | YAML workflow definition validation |
| `eval-poc.yml` | Evaluation proof-of-concept runs |
| `manifest-temperature-check.yml` | Detects drift in model configuration defaults |

---

## Pre-commit Hooks

Pre-commit hooks run automatically before every local commit. The CI `lint-and-test` job also runs `pre-commit run --all-files` to enforce identical checks.

| Hook | Tool | Purpose |
|---|---|---|
| `black` | Black | Python code formatting (line-length 88) |
| `isort` | isort (profile=black) | Python import sorting |
| `ruff` | Ruff | Comprehensive linting (replaces Flake8/pylint/pycodestyle) |
| `docformatter` | docformatter | Docstring formatting |
| `mypy` | mypy | Static type checking |
| `pydocstyle` | pydocstyle | Docstring style enforcement |
| `detect-secrets` | detect-secrets | Secret and credential leak prevention |

Install hooks: `pre-commit install`

Run all hooks manually: `pre-commit run --all-files`

---

## Security Scanning

### SAST — bandit

`bandit` scans all Python source for common security anti-patterns (hardcoded passwords, unsafe use of subprocess, SQL injection sinks, etc.).

```bash
bandit -r agentic-workflows-v2/agentic_v2/ agentic-v2-eval/src/agentic_v2_eval/ tools/ -ll -q
```

The `-ll` flag reports issues at MEDIUM severity and above. LOW severity findings are suppressed in CI to reduce noise; they should still be reviewed during security audits.

### Dependency Audit — pip-audit

`pip-audit` checks all installed package versions against the OSV database for known CVEs.

```bash
pip-audit --progress-spinner off --desc
```

Any known vulnerability at any severity level fails the CI security job.

### Secret Detection — detect-secrets

`detect-secrets` scans file content for patterns matching API keys, tokens, passwords, and other credentials before every commit. A `.secrets.baseline` file in the repository root contains approved false positives.

---

## Docker Builds

### Backend Image

Build:

```bash
docker build -t prompts-backend:latest -f Dockerfile .
```

The `Dockerfile` installs the `agentic-workflows-v2` package with `[server,langchain,rag]` extras and starts `uvicorn agentic_v2.server.app:app`.

### Frontend Image

Build:

```bash
docker build -t prompts-ui:latest -f Dockerfile.ui .
```

The `Dockerfile.ui` runs `npm ci && npm run build` and serves the resulting `dist/` directory via nginx.

### Full Stack with Docker Compose

```bash
docker-compose up
```

The `docker-compose.yml` starts:

- `backend` — FastAPI server on port 8010
- `otel-collector` — OpenTelemetry Collector (OTLP gRPC on 4317, HTTP on 4318)

The frontend image is not included in the default Compose stack because the backend serves `ui/dist/` statically in production mode.

---

## Environment Variable Reference (Production)

Set these in your deployment environment (Kubernetes secrets, cloud provider secrets manager, or `.env` file for Docker Compose).

### Required — at Least One LLM Provider Key

| Variable | Description |
|---|---|
| `GITHUB_TOKEN` | GitHub Models API — free tier, good default choice |
| `OPENAI_API_KEY` | OpenAI GPT-4o, GPT-4.1, o-series |
| `ANTHROPIC_API_KEY` | Anthropic Claude 3/4 family |
| `GEMINI_API_KEY` | Google Gemini 2.5 family |
| `AZURE_OPENAI_API_KEY_0` | Azure OpenAI key (supports `_0`–`_n` for failover) |
| `AZURE_OPENAI_ENDPOINT_0` | Azure OpenAI endpoint URL |
| `AZURE_AI_SERVICES_ENDPOINT` | Azure AI Services endpoint (optional) |
| `AZURE_COGNITIVE_ENDPOINT` | Azure Cognitive Services endpoint (optional) |
| `LOCAL_MODEL_PATH` | Path to ONNX model directory (optional) |

### Server Security

| Variable | Description | Production Requirement |
|---|---|---|
| `AGENTIC_API_KEY` | Bearer token for all `/api/` routes. Both `Authorization: Bearer <key>` and `X-API-Key: <key>` headers are accepted. Token comparison uses `secrets.compare_digest` to prevent timing attacks. | **Mandatory** |
| `AGENTIC_CORS_ORIGINS` | Comma-separated list of allowed CORS origins. Example: `https://app.example.com,https://admin.example.com` | **Mandatory** — restrict to actual frontend origins |
| `AGENTIC_FILE_BASE_DIR` | Base directory for all file operations via the `file_ops` built-in tool. When set, all file paths are resolved relative to this directory and any attempt to traverse outside it is rejected. Example: `/app/data` | **Strongly recommended** — prevents path traversal |
| `AGENTIC_BLOCK_PRIVATE_IPS` | Default **ON** (`1`). Blocks HTTP tool requests to private/loopback/link-local/reserved IPs, performs DNS resolution to catch hostname-based SSRF, and re-validates each redirect hop. Set to `0` only when workflows need internal network access and you have applied compensating controls. | Default ON — opt out with `0` only with explicit justification |

### Agent Configuration

| Variable | Description |
|---|---|
| `AGENTIC_EXTERNAL_AGENTS_DIR` | Path to a directory of additional agent definition files. Allows custom agents without modifying the package. |
| `AGENTIC_MEMORY_PATH` | File path for the persistent memory store. When unset, memory is in-process only and lost on restart. |
| `AGENTIC_MODEL_TIER_1` | Override the tier-1 (fast, low-cost) model name used by the router. |
| `AGENTIC_MODEL_TIER_2` | Override the tier-2 (capable) model name. |
| `AGENTIC_JUDGE_MODEL` | Model used by the LLM-as-judge scorer. Defaults to tier-2 if unset. |

### OpenTelemetry

| Variable | Description | Default |
|---|---|---|
| `AGENTIC_TRACING` | Set to `1` to enable OTEL span export. | disabled |
| `AGENTIC_TRACE_SENSITIVE` | Set to `1` to include prompt text, LLM outputs, and tool arguments in spans. Do not enable in environments subject to data retention or PII regulations. | excluded |
| `OTEL_EXPORTER_OTLP_ENDPOINT` | OTLP collector endpoint. For gRPC: `http://collector:4317`. For HTTP: `http://collector:4318/v1/traces` | `http://localhost:4317` |
| `OTEL_EXPORTER_OTLP_PROTOCOL` | `grpc` or `http/protobuf` | `grpc` |

### Windows AI (Optional)

| Variable | Description |
|---|---|
| `PHI_SILICA_LAF_FEATURE_ID` | Windows AI (Phi Silica) LAF feature identifier |
| `PHI_SILICA_LAF_TOKEN` | Phi Silica LAF token |
| `PHI_SILICA_LAF_ATTESTATION` | Phi Silica attestation string |

---

## Port Configuration

| Service | Port | Protocol | Configuration |
|---|---|---|---|
| FastAPI backend | 8010 | HTTP / WebSocket | `uvicorn --port 8010` or `AGENTIC_PORT` |
| Vite dev server | 5173 | HTTP | Configured in `vite.config.ts` |
| Storybook | 6006 | HTTP | Not installed by default |
| OTLP gRPC | 4317 | gRPC | `OTEL_EXPORTER_OTLP_ENDPOINT` |
| OTLP HTTP | 4318 | HTTP/protobuf | Use with `OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf` |

---

## Production Configuration Checklist

Before deploying to a production or shared environment, verify the following:

### Authentication and Network

- [ ] `AGENTIC_API_KEY` is set to a strong random value (minimum 32 characters)
- [ ] `AGENTIC_CORS_ORIGINS` is restricted to the actual frontend origin(s)
- [ ] `AGENTIC_BLOCK_PRIVATE_IPS=1` is set if the `http_ops` tool is enabled
- [ ] TLS termination is in place upstream of the FastAPI server (nginx, ALB, etc.)
- [ ] The backend is not publicly accessible on port 8010 without TLS

### File and Path Safety

- [ ] `AGENTIC_FILE_BASE_DIR` is set to an appropriate restricted directory
- [ ] The directory specified in `AGENTIC_FILE_BASE_DIR` does not contain sensitive system files
- [ ] Workflow definitions have been reviewed for tool allowlists — high-risk tools (`shell_ops`, `git_ops`, `file_delete`) require explicit per-step allowlisting

### LLM Provider Keys

- [ ] All API keys are stored in a secrets manager or environment injection — never in source code or Docker images
- [ ] Unused provider keys are not configured (reduces attack surface)
- [ ] Azure failover keys (`_1`, `_2`, ...) are configured if using Azure OpenAI under load

### Observability

- [ ] `AGENTIC_TRACING=1` with OTEL collector configured for production trace ingestion
- [ ] `AGENTIC_TRACE_SENSITIVE` is NOT set (or explicitly reviewed) in environments subject to PII regulations
- [ ] Server logs are routed to a centralized log aggregator
- [ ] Health check endpoint (`GET /api/health`) is monitored by the load balancer or orchestrator

### Persistence

- [ ] `AGENTIC_MEMORY_PATH` is set to a persistent volume mount if cross-restart memory is needed
- [ ] The `runs/` directory is either mounted on persistent storage or backed up — it contains all run result JSON files

---

## Coverage Gates Summary

| Package | Tool | Gate |
|---|---|---|
| `agentic-workflows-v2` | pytest | 80% (`--cov-fail-under=80`) |
| `agentic-v2-eval` | pytest | No explicit gate in current CI (tests must pass) |
| `agentic-tools` | pytest | 70% (`--cov-fail-under=70`) |
| `agentic-workflows-v2/ui` | Vitest | 60% threshold (configured in vitest config) |
