# Deployment guide

This guide covers the CI/CD pipeline, Docker containerization, environment variable configuration for production, security hardening, and observability setup for the `agentic-runtime-platform` monorepo.

---

## CI/CD pipeline

The primary CI workflow is defined in `.github/workflows/ci.yml`. It runs on every push to `main` and `agenticv2`, and on all pull requests targeting those branches.

### Pipeline jobs

The `ci.yml` workflow contains fourteen jobs. All jobs run on `ubuntu-latest`.

| Job | What it does |
|---|---|
| `python-smoke` | Installs all three packages, verifies critical imports, runs the unit suite (`-m "not integration and not slow"`, e2e excluded) |
| `frontend-build` | `npm ci` and production Vite build of the UI |
| `lint` | Ruff on `agentic_v2/` and `tests/`; also fails if `ruff check --fix` would still change anything |
| `suppression-ratchet` | Fails a PR that grows the ruff/mypy suppression counts beyond the committed baseline |
| `typecheck-core-contracts` | Strict mypy on `agentic_v2/engine` and `agentic_v2/contracts` (`--disallow-untyped-defs --warn-return-any`) |
| `test-coverage` | Unit suite with coverage on `agentic_v2`, then enforces the 80% gate in a dedicated `coverage report --fail-under=80` step; also uploads a whole-repo coverage report for visibility |
| `wire-format-drift` | Regenerates JSON schemas and TypeScript types from the Pydantic contracts and fails on any diff |
| `e2e-streaming` | Runs the Playwright streaming spec 5× with `AGENTIC_NO_LLM=1` |
| `no-llm-smoke` | Validates and runs a deterministic workflow plus the full unit suite with `AGENTIC_NO_LLM=1` and zero API keys |
| `validate-workflows` | Validates all workflow YAML definitions against the schema |
| `check-doc-drift` | Checks that protocol names appear in `ARCHITECTURE.md` |
| `pydocstyle` | Google-convention docstring checks on `agentic_v2/core/` and `agentic_v2/contracts/` |
| `lockfile-constraints` | Regenerates `ci-constraints.txt` from `uv.lock` and fails on drift |
| `dockerfile-constraints` | Verifies every `pip install` line in the Dockerfile pins `-c ci-constraints.txt` |

A single job failure blocks the merge. There are no bypass mechanisms for CI failures.

### Additional workflow files

The other workflows in `.github/workflows/`:

| File | Purpose |
|---|---|
| `codeql.yml` | CodeQL static analysis on push and PR |
| `dependabot-auto-merge.yml` | Auto-merges passing Dependabot PRs |
| `dependency-audit.yml` | pip-audit (Python packages) and npm audit (UI) CVE scans |
| `dependency-review.yml` | Dependency license and vulnerability review on PRs |
| `deploy.yml` | Release pipeline, triggered on version tags (`v*`) |
| `devcontainer-validate.yml` | Validates the devcontainer on changes to `.devcontainer/` |
| `docs.yml` | Builds and deploys the docs site to GitHub Pages |
| `eval-package-ci.yml` | Isolated CI for the `agentic-v2-eval` package |
| `infra-deploy.yml` | Reference infrastructure deployment workflow (manual dispatch only; never run automatically) |
| `load-report-pages.yml` | Deploys the load report to GitHub Pages |
| `manifest-temperature-check.yml` | Detects drift in `run-manifest.yaml` model temperature defaults |
| `nightly.yml` | Nightly E2E reliability run (scheduled) |
| `sbom.yml` | SBOM generation on release and weekly |
| `windows-workflows-ci.yml` | Windows workflow verification |

---

## Pre-commit hooks

Pre-commit hooks run automatically before every local commit. CI does not run pre-commit directly — the `lint` job in `ci.yml` enforces the same ruff rules, and `pre-commit run --all-files` is a required local gate before opening a PR (see `.claude/rules/ci.md`).

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

## Security scanning

### SAST — bandit

`bandit` scans Python source for common security anti-patterns (hardcoded passwords, unsafe use of subprocess, SQL injection sinks, etc.). It is not currently wired into a CI job — run it manually during security audits:

```bash
bandit -r agentic-workflows-v2/agentic_v2/ agentic-v2-eval/src/agentic_v2_eval/ tools/ -ll -q
```

The `-ll` flag reports issues at MEDIUM severity and above. LOW severity findings should still be reviewed during security audits.

### Dependency audit — pip-audit

`pip-audit` checks installed package versions against the OSV database for known CVEs. It runs in the `dependency-audit.yml` workflow on every push and PR (alongside `npm audit` for the UI), and the audit results JSON is retained as a build artifact.

```bash
pip-audit --progress-spinner off --desc
```

### Secret detection — detect-secrets

`detect-secrets` scans file content for patterns matching API keys, tokens, passwords, and other credentials before every commit. A `.secrets.baseline` file in the repository root contains approved false positives.

---

## Docker builds

### Backend image

Build:

```bash
docker build --target production -t prompts-backend:latest -f Dockerfile .
```

The `production` target installs the repo-root `agentic-tools` package plus
`agentic-workflows-v2` with `[server,tracing,langchain]` extras, pinned to
`ci-constraints.txt`, and starts the FastAPI application factory on port 8010.

### Frontend image

Build:

```bash
docker build --target frontend -t prompts-ui:latest -f Dockerfile.ui .
```

The `frontend` target runs `npm ci && npm run build` and serves the resulting
SPA from a non-root nginx container on port 8080. Production ingress must route
same-origin `/api` and `/ws` traffic to the backend.

### Full stack with Docker Compose

```bash
docker compose up
```

The `docker-compose.yml` starts four services:

- `backend` — FastAPI server on port 8010 (uvicorn with `--reload`)
- `frontend` — Vite dev server on port 5173, proxying API calls to `backend`
- `otel-collector` — OpenTelemetry Collector (OTLP gRPC on 4317, HTTP on 4318)
- `jaeger` — Jaeger all-in-one for trace viewing (UI on 16686)

---

## Environment variable reference (production)

Set these in your deployment environment (Kubernetes secrets, cloud provider secrets manager, or `.env` file for Docker Compose).

### LLM provider keys

Configure at least one of the following:

| Variable | Description |
|---|---|
| `GITHUB_TOKEN` | GitHub Models API — free tier, good default choice |
| `OPENAI_API_KEY` | OpenAI GPT-4o, GPT-4.1, o-series |
| `ANTHROPIC_API_KEY` | Anthropic Claude 3/4 family |
| `GEMINI_API_KEY` | Google Gemini 2.5 family |
| `AZURE_OPENAI_API_KEY_0` | Azure OpenAI key (supports `_0`–`_n` for failover) |
| `AZURE_OPENAI_ENDPOINT_0` | Azure OpenAI endpoint URL |

### Server security

| Variable | Description | Production requirement |
|---|---|---|
| `AGENTIC_API_KEY` | Bearer token for all `/api/` routes. Both `Authorization: Bearer <key>` and `X-API-Key: <key>` headers are accepted. Token comparison uses `secrets.compare_digest` to prevent timing attacks. | **Mandatory** |
| `AGENTIC_CORS_ORIGINS` | Comma-separated list of allowed CORS origins. Example: `https://app.example.com,https://admin.example.com` | **Mandatory** — restrict to actual frontend origins |
| `AGENTIC_FILE_BASE_DIR` | Base directory for all file operations via the `file_ops` built-in tool. When set, all file paths are resolved relative to this directory and any attempt to traverse outside it is rejected. Example: `/app/data` | **Strongly recommended** — prevents path traversal |
| `AGENTIC_BLOCK_PRIVATE_IPS` | Default **ON** (`1`). Blocks HTTP tool requests to private/loopback/link-local/reserved IPs, performs DNS resolution to catch hostname-based SSRF, and re-validates each redirect hop. Set to `0` only when workflows need internal network access and you have applied compensating controls. | Default ON — opt out with `0` only with explicit justification |

### Agent configuration

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

### Windows AI (optional)

| Variable | Description |
|---|---|
| `PHI_SILICA_LAF_FEATURE_ID` | Windows AI (Phi Silica) LAF feature identifier |
| `PHI_SILICA_LAF_TOKEN` | Phi Silica LAF token |
| `PHI_SILICA_LAF_ATTESTATION` | Phi Silica attestation string |

---

## Port configuration

| Service | Port | Protocol | Configuration |
|---|---|---|---|
| FastAPI backend | 8010 | HTTP / WebSocket | `uvicorn --port 8010` |
| Vite dev server | 5173 | HTTP | Configured in `vite.config.ts` |
| Storybook | 6006 | HTTP | Not installed by default |
| OTLP gRPC | 4317 | gRPC | `OTEL_EXPORTER_OTLP_ENDPOINT` |
| OTLP HTTP | 4318 | HTTP/protobuf | Use with `OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf` |
| Jaeger UI | 16686 | HTTP | Docker Compose `jaeger` service |

---

## Production configuration checklist

Before deploying to a production or shared environment, verify the following:

### Authentication and network

- [ ] `AGENTIC_API_KEY` is set to a strong random value (minimum 32 characters)
- [ ] `AGENTIC_CORS_ORIGINS` is restricted to the actual frontend origin(s)
- [ ] `AGENTIC_BLOCK_PRIVATE_IPS=1` is set if the `http_ops` tool is enabled
- [ ] TLS termination is in place upstream of the FastAPI server (nginx, ALB, etc.)
- [ ] The backend is not publicly accessible on port 8010 without TLS

### File and path safety

- [ ] `AGENTIC_FILE_BASE_DIR` is set to an appropriate restricted directory
- [ ] The directory specified in `AGENTIC_FILE_BASE_DIR` does not contain sensitive system files
- [ ] Workflow definitions have been reviewed for tool allowlists — high-risk tools (`shell_ops`, `git_ops`, `file_delete`) require explicit per-step allowlisting

### LLM provider keys

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

## Coverage gates summary

| Package | Tool | Gate |
|---|---|---|
| `agentic-workflows-v2` | pytest + coverage | 80% on `agentic_v2` — CI collects coverage without `--cov-fail-under` and enforces the gate in a dedicated `coverage report --fail-under=80` step (pytest-cov 7.x does not propagate the failure exit code reliably) |
| `agentic-v2-eval` | pytest | No explicit gate in current CI (tests must pass) |
| `agentic-tools` | pytest | No per-package gate — included in the whole-repo coverage report for visibility only |
| `agentic-workflows-v2/ui` | Vitest | 60% threshold (configured in `ui/vitest.config.ts`) |
