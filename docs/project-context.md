# Project Context — agentic-runtime-platform

> **Purpose:** Concise machine-readable summary for AI assistant context. Updated 2026-06-17.

---

## Project Identity

| Field | Value |
|---|---|
| Repository | `tafreeman/agentic-runtime-platform` |
| Architecture | Monorepo — 4 packages, uv workspace |
| Primary language | Python 3.11+ |
| Secondary language | TypeScript (React 19 SPA) |
| Architecture pattern | DAG-executor + tiered model router + RAG pipeline |
| CI/CD | GitHub Actions (15 workflows) |

---

## Packages

| Package ID | Directory | Type | Role |
|---|---|---|---|
| `runtime` | `agentic-workflows-v2/` | backend | FastAPI server + native DAG executor + LangGraph adapter + agent layer + RAG |
| `ui` | `agentic-workflows-v2/ui/` | web | React 19 SPA — live DAG visualization, run history, WebSocket streaming |
| `eval` | `agentic-v2-eval/` | data/library | Offline evaluation framework — rubrics, LLM-as-judge, batch runners, reporters |
| `tools` | `tools/` (`agentic-tools`) | library | Shared LLM client (10+ providers), benchmarks, Windows AI bridge |

---

## Runtime Package — Key Subdirectories

```
agentic-workflows-v2/agentic_v2/
├── engine/          Native DAG executor (Kahn's algorithm, asyncio fan-out)
├── langchain/       LangGraph engine adapter (optional extras)
├── adapters/        AdapterRegistry singleton mapping names to ExecutionEngine
├── agents/          BaseAgent[TInput,TOutput] + 5 specialized agents
│   ├── orchestrator.py            OrchestratorAgent (delegation + DAG dispatch)
│   ├── orchestrator_models.py     SubTask, I/O schemas, system prompts
│   ├── orchestrator_planning.py   Pure planning helpers (no-LLM path)
│   └── orchestrator_factories.py  TaskInput factories per agent type
├── server/          FastAPI app, routes, auth, execution, streaming
│   ├── execution.py               Background task lifecycle, LangGraph streaming
│   ├── _step_events.py            Step-event builders (extracted from execution.py)
│   └── _stream_merge.py           Pure stream-state merge helpers
├── scoring/         Scoring/judge domain (extracted from server/ per ADR-032)
│   ├── evaluation_scoring.py      Aggregation, grade bands (A/B/C/D/F)
│   ├── judge.py                   LLM-as-judge with Likert rubric
│   ├── scoring_criteria.py        Per-criterion 0-100 scorers
│   ├── scoring_profiles.py        Named weight profiles (default/strict/lenient)
│   ├── multidimensional_scoring.py  Multi-axis: correctness/quality/efficiency/docs
│   ├── step_scoring.py            Per-step score from StepResult
│   ├── dataset_matching.py        Heuristic sample-to-schema field mapping
│   └── eval_config.py             Config loader with import-time root resolution
├── models/          SmartModelRouter, circuit breaker, 8+ provider backends
├── rag/             Full RAG pipeline (13 modules: load/chunk/embed/retrieve/assemble)
├── contracts/       Pydantic v2 additive-only wire-format models
├── security/        URL guard, detectors, policy, response sanitizer, middleware
├── workflows/       YAML workflow definitions + loaders
└── integrations/    OpenTelemetry, MCP adapters
```

---

## Key Entry Points

| Entry point | Path | Purpose |
|---|---|---|
| FastAPI app factory | `agentic_v2/server/app.py:create_app()` | Server startup |
| uvicorn target | `agentic_v2.server.app:app` | Production/dev server |
| CLI | `agentic_v2/cli/` (Typer, 7 commands) | `agentic run`, `agentic serve`, `agentic compare` |
| Workflow YAML definitions | `agentic_v2/workflows/definitions/*.yaml` | 6 production workflows |
| DAG executor | `agentic_v2/engine/dag_executor.py` | Native execution |
| Adapter registry | `agentic_v2/adapters/registry.py` | Engine selection |
| SmartModelRouter | `agentic_v2/models/smart_router.py` | Tier-based LLM dispatch |

---

## Agent Inventory

| Agent | Capabilities |
|---|---|
| `CoderAgent` | CodeGeneration, SelfReflection |
| `ReviewerAgent` | CodeReview |
| `ArchitectAgent` | SystemsDesign |
| `TestAgent` | TestGeneration |
| `OrchestratorAgent` | TaskDecomposition, AgentMatching |
| `ClaudeAgent` (impl) | Anthropic Messages API backend |
| `ClaudeSDKAgent` (impl) | claude-agent-sdk backend (standalone) |

---

## LLM Providers (8+)

OpenAI, Anthropic, Google Gemini, Azure OpenAI, Azure AI Foundry, GitHub Models, Ollama, Local ONNX/Windows AI (Phi Silica)

---

## Testing Approach

| Aspect | Detail |
|---|---|
| Framework | pytest 7+ with `asyncio_mode = "auto"` |
| Test count | 150+ test files across runtime + eval |
| Coverage gate | 80% on `agentic_v2/` (runtime), 80% on `agentic_v2_eval/` |
| No-credential baseline | `AGENTIC_NO_LLM=1` installs deterministic `PlaceholderChatModel` |
| Markers | `@pytest.mark.integration`, `@pytest.mark.slow`, `@pytest.mark.e2e` |
| Golden tests | `tests/golden/` — LLM calls mocked, volatile keys stripped before compare |
| Security tests | `tests/security/` — AST sandbox escape-vector tests |

---

## CI/CD Summary

| Job | Trigger | What it does |
|---|---|---|
| `ci.yml` | PR + push | Lint (ruff), type-check (mypy --strict), unit tests, coverage gate (80%), wire-format drift check |
| `eval-package-ci.yml` | PR + push | Eval package unit tests + mypy strict |
| `nightly.yml` | Nightly | Load p99/throughput regression gate, deterministic eval gate |
| `codeql.yml` | PR + push | GitHub CodeQL SAST |
| `dependency-audit.yml` | PR + push | `pip-audit` for dependency CVEs |
| `windows-workflows-ci.yml` | PR + push | Windows-specific workflow validation |
| `docs.yml` | PR + push | MkDocs link/fence check |

---

## Architecture Decision Records

31 ADRs total (ADR-001 through ADR-035; gaps 004-006, 013 intentional). Key recent ADRs:

| ADR | Title | Status |
|---|---|---|
| 024 | AST Expression Interpreter — eliminates `eval()` | Accepted |
| 030 | Unconditional SSRF connection pinning | Accepted |
| 031 | Native DAG single-engine proposal (NOT adopted; LangGraph retained) | Superseded |
| 032 | Extract scoring/judge domain into `agentic_v2.scoring` | Accepted |
| 033 | Import-time project-root resolution in eval-config loader | Accepted |
| 034 | Path-First File I/O Contracts for multi-step workflows | Proposed |
| 035 | RAG Pipeline Architecture (LanceDB + Voyage 4 Hybrid Search) | Accepted |

---

## Recent Significant Changes (2026-06)

- **Scoring package extracted** (`agentic_v2/scoring/`) — 9 modules moved out of `server/` per ADR-032; `server/evaluation.py` is now a thin orchestration wrapper.
- **Orchestrator decomposed** — `agents/orchestrator.py` (was >800 lines) split into `orchestrator.py` + `orchestrator_models.py` + `orchestrator_planning.py` + `orchestrator_factories.py`.
- **Server execution split** — `server/execution.py` split into `execution.py` + `_step_events.py` + `_stream_merge.py`.
- **AST sandbox** — expression evaluator replaced `eval()` with AST interpreter (ADR-024); 128 escape-vector tests added.
- **LangChain upgraded** to 1.x (cleared 8 CVEs).
- **CI: load regression gate** — nightly job gates p99 latency and throughput.
- **RAG pipeline** — 13-module `agentic_v2/rag/` fully implemented (ADR-035).
