<div align="center">

# Agentic Runtime Platform

**Production-grade multi-agent AI orchestration — DAG execution, tiered model routing, rubric-based evaluation. Works with 8+ LLM providers.**

[![CI](https://github.com/tafreeman/agentic-runtime-platform/actions/workflows/ci.yml/badge.svg)](https://github.com/tafreeman/agentic-runtime-platform/actions/workflows/ci.yml)
[![Nightly E2E](https://github.com/tafreeman/agentic-runtime-platform/actions/workflows/nightly.yml/badge.svg)](https://github.com/tafreeman/agentic-runtime-platform/actions/workflows/nightly.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
![coverage](https://img.shields.io/badge/coverage-80%25-brightgreen)
[![Coverage visibility: whole repo](https://img.shields.io/badge/coverage%20visibility-whole%20repo-informational.svg)](.github/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Documentation](https://img.shields.io/badge/docs-MkDocs-blue.svg)](https://tafreeman.github.io/agentic-runtime-platform/)
[![Code style: black](https://img.shields.io/badge/code%20style-black-000000.svg)](https://github.com/psf/black)
[![Linting: ruff](https://img.shields.io/badge/linting-ruff-261230.svg)](https://github.com/astral-sh/ruff)
[![Type checking](https://img.shields.io/badge/type%20checking-eval%20strict%20%7C%20runtime%20in%20progress-blue.svg)](docs/KNOWN_LIMITATIONS.md)

[Documentation](https://tafreeman.github.io/agentic-runtime-platform/) • [Quick Start](https://tafreeman.github.io/agentic-runtime-platform/ONBOARDING/) • [Architecture](https://tafreeman.github.io/agentic-runtime-platform/ARCHITECTURE/) • [Docs Site](https://tafreeman.github.io/agentic-runtime-platform/)

</div>

---

Agentic Runtime Platform orchestrates multi-agent AI pipelines where each agent occupies a specific role (planner, researcher, coder, reviewer) and operates at a defined capability tier. Workflows are authored as declarative YAML files and compiled into executable DAGs with automatic parallel scheduling, conditional branching, iterative loops, and failure cascade propagation.

## What's in the Box

| Component | What it does |
|-----------|-------------|
| **DAG Executor** | Kahn's algorithm scheduling with `asyncio` parallel dispatch — diamond dependencies, conditional execution, iterative refinement |
| **Tiered Model Router** | Health-weighted selection across 8+ providers with adaptive cooldowns and circuit breakers — no single-provider lock-in |
| **Evaluation Framework** | YAML-defined rubrics, multidimensional scoring (S/A/B/C/D/F tiers), LLM-as-judge integration for subjective quality |
| **React Dashboard** | Live DAG visualization with SSE/WebSocket streaming, token usage tracking, historical runs |
| **Zero-credential dev mode** | `AGENTIC_NO_LLM=1` runs end-to-end with placeholder backends — the full test suite passes without API keys |

**Engine defaults:** CLI, server, and dashboard requests use the LangGraph adapter (`adapter=langchain`) for named YAML workflows during the migration window. Use `--adapter native` or request `adapter: "native"` for the dependency-light native DAG/Pipeline path. Runtime-generated DAGs use the native engine by default. `AGENTIC_NO_LLM=1` changes provider calls to deterministic placeholders; it does not change engine selection.

## Quick Start

> **`just` is required for `just setup`.** Install: `winget install --id Casey.Just` (Windows), `brew install just` (macOS), `apt install just` (Ubuntu 22.04+). See [the onboarding guide](docs/ONBOARDING.md) for a manual install path if you prefer to skip `just`.

```bash
# Clone and setup
git clone https://github.com/tafreeman/agentic-runtime-platform.git
cd agentic-runtime-platform
just setup

# Run your first workflow — no API key required
# The --input flag accepts a JSON file path (not inline JSON)
echo '{"input_text": "Hello World"}' > /tmp/test-input.json
AGENTIC_NO_LLM=1 agentic run test_deterministic --input /tmp/test-input.json

# Windows PowerShell:
# '{"input_text": "Hello World"}' | Out-File -Encoding utf8 test-input.json
# $env:AGENTIC_NO_LLM = "1"
# agentic run test_deterministic --input test-input.json

# To use LLM-powered workflows, add a provider key:
cp .env.example .env
# Add at least one LLM provider API key to .env

# Start the dashboard
uvicorn agentic_v2.server.app:create_app --factory --reload --port 8010
# In another terminal:
cd ui && npm run dev
```

See [the full onboarding guide](https://tafreeman.github.io/agentic-runtime-platform/ONBOARDING/) for detailed setup instructions.

## Built with AI Assistance

This project uses AI development tools as part of its engineering workflow. Architecture, implementation choices, tests, and public documentation are owned and reviewed by the maintainer; the tooling is used as an accelerator for an agentic-runtime project rather than as a substitute for design review or validation.

## Workflow Example

```yaml
# workflows/definitions/code_review.yml
steps:
  - name: parse_code
    agent: tier2_parser
    description: Extract structure and dependencies
    tools: [file_read, ast_parse]
    inputs:
      code_path: ${inputs.code_path}
    outputs:
      structure: structure

  - name: review_architecture    # Runs in parallel
    agent: tier3_architect         # with review_quality
    depends_on: [parse_code]
    inputs:
      structure: ${steps.parse_code.outputs.structure}
    outputs:
      architecture_report: report

  - name: review_quality          # Runs in parallel
    agent: tier3_reviewer           # with review_architecture
    depends_on: [parse_code]
    inputs:
      structure: ${steps.parse_code.outputs.structure}
    outputs:
      quality_report: report

  - name: synthesize
    agent: tier4_synthesizer
    depends_on: [review_architecture, review_quality]
    inputs:
      reports: [
        ${steps.review_architecture.outputs.architecture_report},
        ${steps.review_quality.outputs.quality_report}
      ]
    outputs:
      final_report: report
```

Run it:

```python
from agentic_v2.workflows import run_workflow

result = await run_workflow(
    "code_review",
    inputs={"code_path": "src/api/handlers.py"}
)

print(result.outputs["final_report"])  # Consolidated review
print(result.metadata["agents_used"])  # ["tier2_parser", "tier3_architect", "tier3_reviewer", "tier4_synthesizer"]
print(result.cost)                      # TokenUsage(input_tokens=2500, output_tokens=450, llm_calls=4)
```

## Architecture

```mermaid
graph TD
    A[YAML Workflow DSL] --> B[Workflow Loader]
    B --> C[Workflow Model / Step DAG]
    C --> D[Native DAG Executor]
    C --> G[LangGraph Compiler]
    G --> H[LangGraph Runtime]
    D --> E[Tiered Model Router]
    H --> E
    E --> F[Provider Backends]

    subgraph Router
        E
        E1[Tier 1: flash-lite, 4o-mini]
        E2[Tier 2: flash, haiku]
        E3[Tier 3: 2.5-flash, gpt-4o]
        E4[Tier 4: 2.5-pro, claude-sonnet]
        E5[Health-weighted selection]
        E6[Circuit breakers]
    end

    subgraph Providers
        F
        F1[OpenAI]
        F2[Anthropic]
        F3[Google Gemini]
        F4[Azure OpenAI]
        F5[GitHub Models]
        F6[Ollama / Local]
    end
```

## Key Design Decisions

### Why DAG over Pipeline?

Multi-agent workflows rarely execute linearly. After planning, two specialist analysts run **in parallel** over the same evidence. Their outputs merge into verification, which conditionally triggers another research round. A pipeline would serialize unnecessarily; a DAG with `asyncio.wait(FIRST_COMPLETED)` maximizes throughput.

### Why Tiered Model Routing?

Mapping workflow steps to models by name creates brittleness: model names change, endpoints go down, pricing shifts. Instead, each agent is assigned a **capability tier** (e.g., `tier3_analyst`). The router resolves this to the best available model at runtime, with fallback chains like:

```
Tier 3: gemini-2.5-flash → gh:gpt-4o → openai:gpt-4o → anthropic:claude-sonnet
```

The `SmartModelRouter` extends this with health-weighted selection, adaptive cooldowns (exponential backoff on failures), and circuit breaker patterns.

### Why Rubric-Based Scoring?

LLM outputs resist binary pass/fail evaluation. The scoring system uses YAML-defined rubrics with weighted criteria, score normalization, and explicit handling of missing criteria. For complex evaluations, a multidimensional scoring engine classifies outputs across five orthogonal dimensions (coverage, source quality, agreement, verification, recency) into lettered tiers (S/A/B/C/D/F).

## Workflow Definitions

The engine ships with **6 production workflow definitions**:

| Workflow | Pattern | Description |
|----------|---------|-------------|
| `code_review` | Fan-out / fan-in | Parse code → parallel architecture + quality reviews → synthesis |
| `bug_resolution` | Sequential with verification | Reproduce → root cause → fix → test → verify |
| `fullstack_generation` | Parallel sub-steps | API design → frontend + backend in parallel → integration |
| `iterative_review` | Multi-loop with bounded iteration | Review → feedback → revise until quality gates pass |
| `conditional_branching` | Conditional DAG | Steps execute or skip based on runtime conditions |
| `test_deterministic` | Tier-0 only | Deterministic step for testing without LLM calls |

## Project Structure

```
agentic-runtime-platform/
├── agentic-workflows-v2/          # Core runtime package
│   ├── agentic_v2/
│   │   ├── engine/                # DAG executor, step runner, expression engine
│   │   ├── models/                # Tiered routing, provider backends
│   │   ├── agents/                # Agent implementations
│   │   ├── workflows/definitions/ # 6 YAML workflow definitions
│   │   ├── langchain/             # LangGraph integration
│   │   ├── server/                # FastAPI backend
│   │   ├── rag/                   # Full RAG pipeline
│   │   └── contracts/             # Pydantic I/O models
│   ├── ui/                        # React 19 dashboard
│   └── tests/                     # 100+ test files
│
├── agentic-v2-eval/               # Evaluation framework
│   └── src/agentic_v2_eval/
│       ├── evaluators/            # Rubric-based evaluators
│       ├── scoring/               # Scoring utilities
│       └── reporters/             # Result reporting
│
└── tools/                         # Shared utilities
    └── llm/                       # Multi-provider LLM client
```

## Features

- **Dual execution engine**: LangGraph for default named YAML workflow runs; native DAG/Pipeline execution for explicit `--adapter native` runs and runtime-generated DAGs
- **8+ LLM providers**: OpenAI, Anthropic, Gemini, Azure OpenAI, Azure Foundry, GitHub Models, Ollama, local ONNX
- **Tiered model routing** with health-weighted selection and circuit breakers
- **Observable execution**: SSE/WebSocket streaming to React dashboard
- **Rubric-based evaluation** with YAML-defined criteria and LLM-as-judge
- **Zero-credential dev mode**: Run all tests and workflows without API keys
- **Type-safe interfaces**: Full Pydantic v2 contracts; `mypy --strict` is enforced for `agentic-v2-eval`, with broader runtime coverage in progress
- **Production-ready core**: The DAG executor, model router, and evaluation framework are hardened with pre-commit hooks (black, ruff, mypy for `agentic-v2-eval`), 100+ tests, and 80%+ coverage. RAG, Redis state, and some provider adapters are explicitly in-progress — see [KNOWN_LIMITATIONS.md](docs/KNOWN_LIMITATIONS.md)
- **Rate limiting + 401 throttle**: `slowapi` global limiter (`AGENTIC_RATE_LIMIT_DEFAULT`, default `60/minute`); per-IP sliding-window lockout after repeated auth failures (`AGENTIC_AUTH_LOCKOUT_THRESHOLD`, `AGENTIC_AUTH_LOCKOUT_WINDOW_SECONDS`, `AGENTIC_AUTH_LOCKOUT_DURATION_SECONDS`)
- **DAG executor timeout watchdog**: pass `timeout=` to the executor; in-flight tasks are cancelled structurally, downstream steps are cascade-skipped, and a `dag.timeout_exceeded` OTEL span attribute is emitted

## Documentation

Full documentation is published at **https://tafreeman.github.io/agentic-runtime-platform/**.

- [Quick Start](https://tafreeman.github.io/agentic-runtime-platform/ONBOARDING/) — 5-minute to 1-hour first-run path
- [Architecture Overview](https://tafreeman.github.io/agentic-runtime-platform/ARCHITECTURE/) — System map and load-bearing mechanisms
- [Workflow Authoring](https://tafreeman.github.io/agentic-runtime-platform/WORKFLOW_AUTHORING/) — YAML DSL guide
- [Pattern Catalog](https://tafreeman.github.io/agentic-runtime-platform/PATTERN_CATALOG/) — Agentic pattern reference
- [API Reference](https://tafreeman.github.io/agentic-runtime-platform/api-contracts-runtime/) — REST endpoints and contracts
- [Development Guide](https://tafreeman.github.io/agentic-runtime-platform/development-guide/) — Setup, testing, CLI

## Development

### Prerequisites

- Python 3.11+
- Node.js 20+ (for UI)
- At least one LLM provider API key (or use `AGENTIC_NO_LLM=1` for placeholder mode)

### Installation

```bash
# Clone the repository
git clone https://github.com/tafreeman/agentic-runtime-platform.git
cd agentic-runtime-platform

# One-command bootstrap (installs all packages and dependencies)
just setup

# Or install manually:
cd agentic-workflows-v2
pip install -e ".[dev,server,langchain]"

# Configure environment
cp ../.env.example ../.env
# Edit .env with your API keys
```

### Running Tests

```bash
# Runtime tests (100+ test files)
cd agentic-workflows-v2
pytest tests/ -v --cov=agentic_v2

# Evaluation framework tests
cd ../agentic-v2-eval
pytest tests/ -v

# UI tests
cd ../agentic-workflows-v2/ui
npm test
```

### Code Quality

This project enforces code quality through pre-commit hooks:

```bash
# Install pre-commit hooks
pre-commit install

# Run all hooks manually
pre-commit run --all-files
```

| Tool | Purpose |
|------|---------|
| **black** | Code formatting (88 char line length) |
| **isort** | Import sorting (black-compatible) |
| **ruff** | Fast linting with auto-fix |
| **mypy** | Static type checking for `agentic-v2-eval` |
| **docformatter** | Docstring formatting |
| **pydocstyle** | Google-style docstring enforcement |

## Relationship to ExecutionKit

ExecutionKit and Agentic Runtime Platform occupy different layers of the same stack:

| | ExecutionKit | Agentic Runtime Platform |
|---|---|---|
| **Role** | Pattern library | Orchestration runtime |
| **Scope** | Single LLM call patterns | Multi-agent DAG workflows |
| **Workflow authoring** | Python functions | Declarative YAML |
| **Dependencies** | Zero (stdlib only) | FastAPI, LangGraph, Pydantic |
| **Use when** | You need reasoning primitives | You need to orchestrate many agents |

**Agentic Runtime Platform uses ExecutionKit patterns internally** as execution primitives for agent steps.

## Standards & Governance

| Area | Artifact | Description |
|------|----------|-------------|
| Architecture decisions | [ADR Index](docs/adr/ADR-INDEX.md) | 13 decisions with lineage chains and implementation tracking |
| Known debt | [KNOWN_LIMITATIONS.md](docs/KNOWN_LIMITATIONS.md) | Honest accounting with severity, workaround, and upstream-fix fields |
| Security | [SECURITY.md](agentic-workflows-v2/SECURITY.md) | Coordinated disclosure policy and hardening guidance; includes rate-limit and per-IP 401 lockout configuration |
| Supply chain | [Dependabot](.github/dependabot.yml) | Automated updates for pip, npm, and GitHub Actions |
| Roadmap | [ROADMAP.md](docs/ROADMAP.md) | Shipped epics, in-flight sprint, and proposed work |
| Migrations | [MIGRATIONS.md](docs/MIGRATIONS.md) | Breaking changes since v0.3.0 |

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for monorepo-wide contribution guidelines — local gates, commit format, when an ADR is required, and the PR checklist.

## License

This project is licensed under the MIT License — see [LICENSE](LICENSE) for details.
