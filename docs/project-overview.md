# Project overview — Agentic Runtime Platform

---

## Project identity

| Field | Value |
|---|---|
| Repository | `tafreeman/agentic-runtime-platform` |
| Primary branch | `main` |
| Python version | 3.11+ |
| Node version | 20+ |
| Build system | hatchling (all Python packages), Vite 6 (frontend) |
| Workspace manager | uv (workspace with three Python members) |
| License | See `LICENSE` in repository root |

---

## Executive summary

The `agentic-runtime-platform` monorepo is a multi-agent AI workflow platform built for regulated production environments. At its core, the system provides a runtime engine for defining, executing, and observing multi-step AI workflows in which each step is handled by a specialized agent (Coder, Reviewer, Architect, Orchestrator, Planner, Tester, Validator, and others). Workflows are described as directed acyclic graphs in YAML and can be executed through either a native Python DAG executor or a LangGraph-backed engine, depending on deployment requirements. The server exposes a FastAPI backend with real-time WebSocket streaming so that a React 19 dashboard can display live execution progress, step outputs, and run history.

The monorepo serves two purposes: a working production platform, and a reference implementation of engineering practices for regulated environments. Every architectural decision — dual execution engines, protocol-based abstractions, layered sanitization, rubric-driven evaluation — is documented. The evaluation framework (`agentic-v2-eval`) and shared tools library (`agentic-tools`) are independently installable packages, enabling teams to adopt the LLM client, benchmarking utilities, or evaluation pipeline independently of the full runtime.

Security and observability are first-class concerns throughout. A sanitization middleware pipeline protects all inbound prompt content from secret leakage, PII exposure, and prompt injection — and is fail-closed, returning HTTP 400 on any unhandled exception rather than passing unvalidated content. An optional OpenTelemetry integration instruments the full execution pipeline — from HTTP request through agent steps, LLM calls, and RAG retrieval — for distributed tracing. CI enforces 80% test coverage on the runtime, 80% on the eval package, and 70% on shared tools, with bandit and pip-audit running in every pull request.

---

## Current state (as of July 2026)

The platform has shipped the following epics:

| Epic | Status | Summary |
|------|--------|---------|
| Epic 1 — Platform Foundation | Shipped (v0.3.0) | Typed core protocols, consolidated Settings, adapter registry isolation, schema-drift CI gate, OTEL trace assertion, golden-output regression test |
| Epic 2 — Observable Execution | Shipped (v0.3.0) | Typed execution-event wire format, live DAG animation, StepNode B2 redesign, step drill-down panel, Playwright streaming gate, WebSocket reconnect-replay test, SLO p95 gate |
| Epic 3 — DevEx / Windows | Shipped (v0.3.0) | Windows bring-up script, port-guard tool, workspace-test-runner, workflow-linter, Windows Unicode CLI fix |
| Epic 4 | Tombstoned | Number skipped during planning — not a regression |
| Epic 5 — Console UI Polish | Shipped (v0.3.0) | Dashboard redesign, dark/light/bolt themes, populated states |
| Epic 6 — Evaluation Depth | Shipped (v0.3.0) | Rubric library expansion, LLM-as-judge integration, production gating |
| Sprint A/B Stabilization | Shipped | SLO trivial-pass fix, mypy strict for eval (35 findings cleared), wire-format drift gate, placeholder/no-LLM mode, security hardening (S1-01 through S1-07) |
| Epic 7 — First-Run Experience | Shipped (May 2026) | Zero-credential onboarding path (`test_deterministic` first run), `GettingStartedCard` dashboard component, `NoProviderConfiguredError` guidance, devcontainer PR gate |
| Epic 8 — Production Readiness Pack | Shipped (May 2026) | OIDC JWT authentication, tenant isolation, append-only audit logging, model-weight integrity verification, security posture report |

---

## Tech stack

| Package | Key Technologies |
|---|---|
| **Runtime** (`agentic-workflows-v2/`) | Python 3.11+, FastAPI, uvicorn, Pydantic v2, LangGraph (optional), hatchling, OpenTelemetry, PyYAML |
| **UI** (`agentic-workflows-v2/ui/`) | React 19, TypeScript, Vite 6, TanStack Query, @xyflow/react 12, Tailwind CSS, Vitest |
| **Eval** (`agentic-v2-eval/`) | Python 3.11+, Pydantic v2, PyYAML, hatchling, pytest-asyncio |
| **Tools** (`tools/` / `agentic-tools`) | Python 3.11+, aiohttp, openai SDK, anthropic SDK, numpy, hatchling |

### Cross-cutting concerns

| Concern | Technology |
|---|---|
| Dependency management | uv workspace + lockfile |
| Linting and formatting | ruff, black, isort |
| Type checking | mypy --strict |
| Secret scanning | detect-secrets (pre-commit) |
| Security scanning | bandit (SAST), pip-audit (dependency CVEs) |
| Distributed tracing | OpenTelemetry SDK + OTLP exporter |
| Documentation | MkDocs Material + mermaid2 plugin |
| Containerization | Docker (backend + frontend separate images) |
| CI/CD | GitHub Actions (15 workflow files) |

---

## Architecture overview

The monorepo is organized as a **uv workspace** with four packages occupying distinct architectural layers:

```
┌─────────────────────────────────────────────────────────┐
│                    React 19 Dashboard                    │
│         (agentic-workflows-v2/ui/)                       │
│    REST /api/*  |  WebSocket /ws/execution/{run_id}     │
└─────────────────────────┬───────────────────────────────┘
                          │ HTTP + WebSocket
┌─────────────────────────▼───────────────────────────────┐
│              FastAPI Runtime Server                      │
│         (agentic-workflows-v2/)                          │
│                                                          │
│  ┌────────────────┐   ┌─────────────────────────────┐   │
│  │ Native DAG     │   │ LangGraph Engine             │   │
│  │ Executor       │   │ (optional extra)             │   │
│  │ (engine/)      │   │ (langchain/)                 │   │
│  └────────────────┘   └─────────────────────────────┘   │
│                                                          │
│  RAG Pipeline │ Middleware (sanitize) │ Models (routing) │
└──────────────────────────┬──────────────────────────────┘
                           │ imports
┌──────────────────────────▼──────────────────────────────┐
│              Shared Tools (agentic-tools)                │
│         (tools/)                                         │
│   LLMClient (8 providers)  │ Benchmarks │ Cache │ Errors │
│   windows_ai_bridge/ (Phi Silica on-device inference)   │
└──────────────────────────┬──────────────────────────────┘
                           │ lazy imports
┌──────────────────────────▼──────────────────────────────┐
│              Evaluation Framework                        │
│         (agentic-v2-eval/)                               │
│   Rubrics │ Evaluators │ Runners │ Reporters │ Metrics  │
└─────────────────────────────────────────────────────────┘
```

### Architectural characteristics

**Dual execution engine.** Named YAML workflows can execute through either the LangGraph engine (`adapter=langchain`) or the native DAG engine (`adapter=native`). CLI, server, and dashboard requests default to LangGraph during the migration window; runtime-generated DAGs default to the native engine. The `agentic compare` CLI command runs both engines on the same input and diffs their outputs. The `AdapterRegistry` in `adapters/registry.py` maps names (`"native"`, `"langchain"`) to `ExecutionEngine` protocol implementations.

**Protocol-based abstraction.** `core/protocols.py` defines all inter-component contracts as `@runtime_checkable` protocols. Concrete implementations are registered at startup, not hard-coded. This makes the system testable with minimal mocking and allows new engine backends or agent types to be added without modifying the core.

**Layered LLM routing.** `ModelRouter` maps tiers to model names via code-level fallback chains (`models/router.py` `DEFAULT_CHAINS`, mirrored by `langchain/models.py` `_TIER_FALLBACK_CHAINS`), refreshed at runtime by the provider probe and live model discovery (ADR-037/038/039). `SmartRouter` adds circuit breakers, per-provider bulkhead concurrency limits, latency-weighted selection, and tier-fallback degradation. Both are backed by the shared `tools.llm.LLMClient`.

**Additive-only contracts.** Pydantic v2 models in `contracts/` follow a strict additive-only policy: existing fields are never removed or renamed. This ensures backward compatibility for any consumer of saved run outputs or API responses. The wire format is enforced by an automated Python-to-TypeScript type generation pipeline and a CI drift gate.

**Fail-closed security.** The sanitization middleware pipeline returns HTTP 400 on any unhandled exception rather than passing unvalidated content. Tool operations default to DENY without explicit configuration. Subprocess environments are scrubbed of API keys before any shell or git tool invocation.

**Zero-credential development.** `AGENTIC_NO_LLM=1` installs deterministic placeholder providers at both engine chokepoints, allowing full end-to-end execution with the entire test suite passing without provider credentials. It affects provider calls only; adapter selection remains explicit (`langchain` by default for named YAML workflows, `native` for runtime-generated DAGs or `--adapter native`). The `no-llm-smoke` CI job and the fast unit pass run in placeholder mode; the nightly and E2E provider-integration jobs intentionally make live GitHub Models calls via `GITHUB_TOKEN` (see [ADR-016](adr/ADR-016-github-token-as-default-e2e-llm.md)).

---

## Repository structure diagram

```
agentic-runtime-platform/
├── agentic-workflows-v2/   Runtime + UI
│   ├── agentic_v2/         Python source (~36,300 lines)
│   │   ├── adapters/       Pluggable engine backends
│   │   ├── agents/         Agent implementations
│   │   ├── cli/            Typer CLI
│   │   ├── config/         Runtime configuration
│   │   ├── contracts/      Pydantic v2 I/O models
│   │   ├── core/           Protocols, memory, errors
│   │   ├── devex/          Developer experience tooling
│   │   ├── engine/         Native DAG executor
│   │   ├── evaluation/     Inline evaluation primitives
│   │   ├── integrations/   OTEL, LangChain, MCP
│   │   ├── langchain/      LangGraph engine
│   │   ├── middleware/     Sanitization pipeline
│   │   ├── models/         LLM routing (eight providers across nine routing backends)
│   │   ├── prompts/        7 agent persona definitions
│   │   ├── rag/            Full RAG pipeline
│   │   ├── scoring/        Scoring/judge domain (extracted from server/)
│   │   ├── server/         FastAPI + WebSocket/SSE
│   │   ├── tools/builtin/  11 built-in tool modules
│   │   ├── utils/          General utilities
│   │   └── workflows/      8 YAML workflow definitions (6 production + 2 test)
│   ├── tests/              150+ test files
│   └── ui/                 React 19 dashboard
├── agentic-v2-eval/        Standalone evaluation framework
│   └── src/agentic_v2_eval/
│       ├── evaluators/     5 evaluator types
│       ├── rubrics/        8 YAML rubric definitions
│       ├── runners/        Batch + streaming runners
│       └── reporters/      JSON / Markdown / HTML
├── tools/                  Shared utilities (agentic-tools)
│   ├── llm/                Multi-provider LLM client (20+ modules)
│   │   └── windows_ai_bridge/  Phi Silica on-device inference
│   ├── agents/benchmarks/  8 benchmark definitions
│   └── core/               Shared errors, cache, config
├── _bmad/                  BMad methodology setup
├── _bmad-output/           BMad-generated artifacts
├── docs/                   MkDocs documentation source
├── .github/workflows/      15 CI/CD workflow files
├── otel/                   OpenTelemetry collector config
├── tests/e2e/              Cross-package smoke tests
└── pyproject.toml          uv workspace root + agentic-tools
```

---

## Links to related documentation

| Document | Description |
|---|---|
| [Architecture Overview](ARCHITECTURE.md) | Umbrella document linking all four architecture deep-dives |
| [Runtime Engine Architecture](architecture-runtime.md) | DAG executor, model router, adapter registry, RAG pipeline |
| [UI Dashboard Architecture](architecture-ui.md) | React 19 SPA, live streaming, component organization |
| [Evaluation Framework Architecture](architecture-eval.md) | Rubrics, evaluators, runners, production gating |
| [Tools & Providers Architecture](architecture-tools.md) | Multi-provider LLM client, benchmarks, Windows AI |
| [Integration Architecture](integration-architecture.md) | Cross-package communication contracts, REST API, WebSocket protocol, data flow |
| [Deep Dive: Server & API](deep-dive-server.md) | FastAPI endpoints, auth middleware, streaming implementation |
| [Deep Dive: Agents](deep-dive-agents.md) | Agent lifecycle, personas, capability declarations |
| [Deep Dive: RAG Pipeline](rag/index.md) | Ingestion, chunking, retrieval, reranking |
| [Deep Dive: Evaluation Engine](deep-dive-agentic-v2-eval.md) | Standalone eval package internals |
| [Development Guide](development-guide.md) | Local development setup, dev servers, testing, linting, CLI usage |
| [Deployment Guide](deployment-guide.md) | CI/CD pipeline, environment variable reference, Docker, production configuration |
| [Onboarding](ONBOARDING.md) | New contributor onboarding path (5 minutes to 1 hour) |
| [ADR Index](adr/ADR-INDEX.md) | All architecture decision records (the index is the authoritative count) |
| [Roadmap](ROADMAP.md) | Shipped epics and sprints, in-flight work, and proposals |
| [Known Limitations](KNOWN_LIMITATIONS.md) | Honest accounting of current caveats and open debt |
