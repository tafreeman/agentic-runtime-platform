# ADR-011: A/B Evaluation Harness — API & Interface Design

---

| Field          | Value |
|----------------|-------|
| **ID**         | ADR-011 |
| **Status**     | 🟡 Proposed |
| **Date**       | 2026-03-06 |
| **System**     | tools/commit_eval · agentic-workflows-v2/server · agentic-workflows-v2/ui |
| **Authors**    | Platform Engineering |
| **Reviewers**  | Backend, Frontend, Security |
| **Extends**    | ADR-010 (Eval Harness Methodology) |

---

## 1. TL;DR

> **The harness is exposed via two adapters sharing one core: a typer CLI (`agentic-eval
> compare`) for scripting and CI use, and a FastAPI REST + WebSocket API for the React
> dashboard. Both call the same `Comparator.run()` method — hexagonal architecture with
> the application core decoupled from its entry points. WebSocket is chosen over SSE for
> real-time streaming because it reuses the proven `connectExecutionStream()` infrastructure
> already deployed in LivePage with zero new client code. Data contracts are Pydantic models
> with additive-only schema evolution.**

---

## 2. Status History

| Date | Status | Note |
|------|--------|------|
| 2026-03-06 | 🟡 Proposed | Initial design |

---

## 3. Context & Problem Statement

The `Comparator.run()` core (ADR-010) must be reachable from two distinct usage contexts
with fundamentally different requirements:

```
┌────────────────────────────────────────────────────────────────┐
│  TWO INTERFACE CONTEXTS                                        │
├────────────────────────────────────────────────────────────────┤
│  CLI context (scripting / CI):                                 │
│    - Local terminal, bash scripts, scheduled CI pipelines      │
│    - Needs: inline args OR declarative YAML config file        │
│    - Output: file (HTML/MD report) + terminal summary          │
│    - Real-time: stdout progress lines, optional --quiet        │
│                                                                │
│  Web API context (React dashboard):                            │
│    - Browser-initiated async background job                    │
│    - Needs: REST POST to start, WebSocket for live progress    │
│    - Output: JSON (ComparisonResult) + downloadable reports    │
│    - Real-time: push events from server to client              │
└────────────────────────────────────────────────────────────────┘
```

The failure mode to avoid: building two separate evaluation pipelines. If CLI and API
contain duplicated evaluation logic, every bug requires two fixes and every new feature
requires two implementations. The solution is a single `Comparator.run()` core with two
thin adapter shells — hexagonal architecture (Cockburn, 2005).

### 3.1 Existing WebSocket Infrastructure

The project already has a battle-tested WebSocket pattern for real-time streaming:

```
api/websocket.ts:connectExecutionStream()
  - Auto-reconnects on disconnect (5 retries)
  - Exponential backoff: retryDelayMs × 2^(retryCount-1) (produces 1s, 2s, 4s, 8s, 16s)
  - Deployed and stable in LivePage.tsx since initial release
  - URL parameterized via `pathPrefix?: string = "execution"` option —
    eval reuse passes `pathPrefix: "eval"` to reach `/ws/eval/${runId}`.
    No new function or wrapper required; one caller (LivePage) is unaffected.

hooks/useWorkflowStream.ts
  - React hook mapping raw WebSocket events to typed state
  - Handles: workflow_start, workflow_end, step_start, step_complete,
    step_error, evaluation_*, error, keepalive, connection_established
  - Proven in production for 30-60 minute workflow runs
```

Any new real-time feature must justify diverging from this infrastructure. The evaluation
harness has no such justification — its streaming requirements are identical: one-way server
→ client progress updates for a long-running asynchronous operation.

### 3.2 YAML Config Precedent — Promptfoo

Promptfoo (github.com/promptfoo/promptfoo) established the declarative YAML config as the
standard pattern for LLM A/B evaluation. Its configuration model — prompts, providers, and
test cases defined in YAML — enables reproducible, version-controlled evaluations. The
`eval.yaml` format adopted here borrows this declarative approach while adapting it to the
commit-driven use case (repo path, commit SHA, contestant definitions, rubric selection).

---

## 4. Decision

### 4.1 Hexagonal Architecture — One Core, Two Adapters

```
┌───────────────────────────────────────────────────────────────────┐
│                                                                   │
│    PRIMARY PORTS (entry points)                                   │
│                                                                   │
│    CLI Adapter               REST/WS Adapter                      │
│    tools/commit_eval/cli.py  server/routes/eval.py               │
│         │                         │                              │
│         └──────────┬──────────────┘                              │
│                    │                                              │
│           SECONDARY PORT (application core)                       │
│                    │                                              │
│            Comparator.run()                                       │
│            tools/commit_eval/comparator.py                       │
│                    │                                              │
│         ┌──────────┴──────────┐                                  │
│         │                     │                                  │
│   CommitExtractor        SandboxManager                          │
│   ContestantRunner       PatchExtractor                          │
│   EvalHarness            ComparisonReporter                      │
│                                                                   │
│    SECONDARY ADAPTERS (driven services)                           │
│    LLMClient, WorkflowRunner*, ClaudeAgent, Scorer               │
│                                                                   │
│    * Two WorkflowRunner implementations exist:                    │
│      - Native: agentic_v2/workflows/runner.py                    │
│      - LangChain: agentic_v2/langchain/runner.py                 │
│      Both implement ExecutionEngine protocol. Comparator          │
│      dispatches via AdapterRegistry (see §4.1.1 below).          │
└───────────────────────────────────────────────────────────────────┘
```

Alistair Cockburn's hexagonal architecture (2005, alistair.cockburn.us/hexagonal-architecture)
states: "the goal is to allow an application to equally be driven by users, programs,
automated test or batch scripts, and to be developed and tested in isolation from its
eventual run-time devices." This is exactly the requirement: `Comparator.run()` must be
callable from both CLI and HTTP API without modification.

#### 4.1.1 WorkflowRunner Dispatch — AdapterRegistry

`Comparator` must run a contestant of `type: "workflow"` through the same execution
infrastructure used by the server. The correct mechanism is `AdapterRegistry`, the
thread-safe singleton that maps engine names to `ExecutionEngine` protocol implementations:

```python
from agentic_v2.adapters.registry import get_registry

registry = get_registry()
# Default to "langchain" — matches server behavior in routes/workflows.py
engine = registry.get_adapter(config.get("engine", "langchain"))
result = await engine.execute(dag, ctx)
```

Both `native` and `langchain` adapters implement the `ExecutionEngine` protocol
(`core/protocols.py`). Contestants can opt into either backend via the `eval.yaml`
config or the CLI `--engine` flag — the `Comparator` is agnostic to which is chosen.
This ensures eval runs exercise the same code paths as production workflow runs.

> **Registry initialization:** `get_registry()` returns the singleton; both built-in
> adapters are registered at import time. No additional setup is required in
> `Comparator.__init__`.

### 4.2 CLI Design (`cli.py`)

**Framework: typer** — built on top of click (the most widely used Python CLI framework),
typer adds Python type hint–driven
argument parsing with zero boilerplate. It auto-generates `--help` from function signatures,
provides shell auto-completion out of the box, and integrates natively with Pydantic models.

**Inline invocation:**
```bash
agentic-eval compare \
  --repo /path/to/repo \
  --commit abc123 \
  --contestant-a "workflow:code_review" \
  --contestant-b "prompt:prompts/experimental.md" \
  --rubric coding_standards \
  --output-format html \
  --output report.html
```

**Contestant type shorthand**: `"type:ref"` — parsed into `Contestant(type=type, ref=ref)`.

**Config file invocation** (declarative, version-controllable):
```bash
agentic-eval compare --config eval.yaml
```

```yaml
# eval.yaml
repo: /path/to/repo        # or https://github.com/owner/repo
commit: abc123
rubric: coding_standards   # or path to custom rubric.yaml
contestants:
  a:
    type: workflow
    ref: code_review
  b:
    type: prompt
    text: |                # inline prompt text — no file path needed
      You are an expert Python developer. Implement the following:
      {requirements}
    model: claude:claude-sonnet-4-6
    temperature: 0.3
output:
  format: html
  path: report.html
```

The YAML config enables eval runs to be pinned in the repository alongside the code they
evaluate — reproducible, auditable, committable.

### 4.3 REST + WebSocket API (`server/routes/eval.py`)

**Endpoints:**
```
POST /eval/compare          → { run_id: str }
GET  /eval/runs             → list[ComparisonRunSummary]
GET  /eval/runs/{run_id}    → ComparisonResult
WS   /ws/eval/{run_id}      → event stream (see §4.4)  [NEW route required]
```

**POST /eval/compare** body:
```json
{
  "repo": "/path/to/repo",
  "commit": "abc123",
  "rubric": "coding_standards",
  "contestants": {
    "a": { "label": "A", "type": "workflow", "ref": "code_review" },
    "b": { "label": "B", "type": "prompt",   "ref": null,
           "prompt_text": "You are...", "model": "claude:claude-sonnet-4-6",
           "temperature": 0.3 }
  }
}
```

The server starts `Comparator.run()` as a background task (FastAPI `BackgroundTasks`),
returns `run_id` immediately, and emits phase events over the WebSocket connection.

> **Implementation note:** The server currently only has a WebSocket handler at
> `/ws/execution/{run_id}` (in `server/websocket.py:189`). A **new** backend route handler
> for `/ws/eval/{run_id}` must be written — it does not exist today.

### 4.4 WebSocket Event Stream

```
client connects: ws://host/ws/eval/{run_id}
  ← { "type": "eval_start",  "run_id": "..." }
  ← { "type": "phase_start", "phase": "extract" }
  ← { "type": "phase_end",   "phase": "extract",  "status": "done", "elapsed_ms": 3200 }
  ← { "type": "phase_start", "phase": "run_a" }
  ← { "type": "phase_end",   "phase": "run_a",    "status": "done", "elapsed_ms": 47000 }
  ← { "type": "phase_start", "phase": "run_b" }
  ← { "type": "phase_end",   "phase": "run_b",    "status": "done", "elapsed_ms": 53000 }
  ← { "type": "phase_start", "phase": "score" }
  ← { "type": "phase_end",   "phase": "score",    "status": "done", "elapsed_ms": 8100 }
  ← { "type": "eval_complete", "winner": "A", "score_a": 7.8,
      "score_b": 6.4, "result": { ... ComparisonResult ... } }
```

**Minimal event vocabulary** — four event types (`phase_start`, `phase_end`,
`eval_complete`, `error`) plus `eval_start` — matches the granularity of the existing
workflow event taxonomy and avoids over-engineering the streaming protocol.

> **Replay buffer:** The `ConnectionManager` in `server/websocket.py` maintains a 500-event
> circular replay buffer (lines 57-69) that sends buffered events to late-connecting clients.
> This is relevant for eval clients that connect after a run has already started — they will
> receive up to 500 prior events on connection, reducing the risk of missed phase transitions.

### 4.5 Data Contracts (Pydantic v2, additive-only)

**`Contestant`** — unified type with discriminator field (not three separate classes):
```python
class Contestant(BaseModel):
    label: str
    type: Literal["workflow", "prompt", "agent"]
    ref: str | None = None         # workflow name, file path, or agent class
    model: str | None = None       # model override
    prompt_text: str | None = None # type="prompt": inline text
    temperature: float = 0.7       # type="prompt": generation temperature
    system_prompt: str | None = None  # type="agent": system prompt override
```

**`ComparisonResult`** — additive-only, follows the `contracts/` project policy:
```python
class ComparisonResult(BaseModel):
    run_id: str
    task: TaskInstance
    trial_a: Trial
    trial_b: Trial
    score_a: dict[str, Any]     # EvaluationResult serialized
    score_b: dict[str, Any]
    rubric_score_a: float
    rubric_score_b: float
    patch_delta: str            # unified diff of patch_a vs patch_b
    winner: Literal["A", "B", "tie"]
    margin: float               # abs(score_a_weighted - score_b_weighted)
    created_at: str             # ISO 8601 timestamp
```

Schema evolution policy: fields are never removed or renamed. New optional fields are
added with defaults. This ensures stored run results remain readable as the harness
evolves — consistent with the `contracts/` additive-only convention.

---

## 5. Files Changed

| File | Change |
|------|--------|
| `tools/commit_eval/cli.py` | New — typer CLI, inline args + YAML config |
| `tools/commit_eval/models.py` | New — `Contestant`, `ComparisonResult`, `Trial`, `TaskInstance` |
| `agentic_v2/server/routes/eval.py` | New — FastAPI router with POST/GET/WS endpoints |
| `agentic_v2/server/app.py` | Register eval router: `app.include_router(eval_router)` |
| `pyproject.toml` (root) | Add `typer>=0.12`, `pytest-json-report>=1.5` to `[project.optional-dependencies]` |

---

## 6. Rationale

### 6.1 typer over argparse and click

| Factor | typer | click | argparse |
|--------|-------|-------|----------|
| Type hint-driven (no decorators per arg) | Yes | No — explicit `@click.option` per arg | No |
| Auto-generates `--help` from docstrings | Yes | Partial | Manual |
| Shell auto-completion | Built-in | Plugin (`click-completion`) | Manual |
| Pydantic v2 integration | Native (requires typer 0.12+; codebase currently pins `typer>=0.9,<1`) | Manual serialization | Manual |
| Built on top of | click | — | stdlib |
| Lines of CLI code for this use case | ~100 | ~160 | ~200 |

typer is click with type hints. Since click is the most widely used Python CLI framework,
typer inherits its stability and ecosystem while
reducing boilerplate by ~40% through type-hint inference. For a tool where the primary
users are developers who value discoverability (`--help`, auto-complete), typer is the
right choice.

### 6.2 WebSocket over SSE for Real-Time Streaming

> **Note:** The server already has an SSE endpoint at `GET /api/runs/{run_id}/stream`
> (lines 660-682 of `server/routes/workflows.py`, using `StreamingResponse` with
> `media_type="text/event-stream"`). The argument for WebSocket here is therefore not
> about server-side novelty but about **client-side reuse** of the proven
> `connectExecutionStream()` infrastructure already deployed in LivePage.

| Factor | WebSocket | Server-Sent Events (SSE) |
|--------|-----------|--------------------------|
| Direction | Bidirectional (could support cancel) | Server → client only |
| Existing client infrastructure | `connectExecutionStream()` + `useWorkflowStream.ts` — proven, deployed | Would require new hook and reconnect logic (the existing SSE endpoint has no corresponding client-side reconnect wrapper) |
| Auto-reconnect | Implemented in `connectExecutionStream()` (5 retries, exponential backoff) | Must implement from scratch on the client side |
| Binary data support | Yes | Text only |
| HTTP/2 multiplexing | Not native | Yes |
| Performance difference | Negligible for this use case — both are TCP push | Negligible |
| Protocol alignment with LivePage | Direct reuse | New divergent pattern |

The performance characteristics of WebSocket and SSE are similar for simple server-to-client
streaming (Ably Engineering, 2024; Timeplus benchmark, 2024). WebSocket is chosen here not
for inherent performance superiority but for **client-side infrastructure reuse**: the
`connectExecutionStream()` function with its 5-retry exponential backoff (`pathPrefix`-parameterized
to reach `/ws/eval/{run_id}` without any new client code) has been running in
production in LivePage without issues for long-duration workflow runs. While the server
already supports SSE via the `/api/runs/{run_id}/stream` endpoint, the React client has no
corresponding SSE reconnect wrapper or hook. Creating a parallel SSE client infrastructure
would require:

1. A new browser EventSource reconnect wrapper
2. A new React hook
3. Parallel maintenance of two real-time client patterns

This cost is unjustified when WebSocket covers the use case identically.

### 6.3 Unified `Contestant` Type vs. Three Separate Classes

A discriminated union with a `type: Literal[...]` field over three separate
`WorkflowContestant`, `PromptContestant`, `AgentContestant` classes because:

- The UI serializes a single JSON object to `POST /eval/compare` regardless of type
- The CLI YAML config has a single `contestants.a/b` shape regardless of type
- `ContestantRunner` dispatches on `contestant.type` — it does not need polymorphic dispatch
- Three separate classes create a union type (`WorkflowContestant | PromptContestant | AgentContestant`) everywhere downstream, doubling the annotation surface
- Optional fields with `None` defaults have no runtime cost

### 6.4 Additive-Only Schema Evolution

`ComparisonResult` follows the `contracts/` project policy established in the codebase.
Fields are never removed or renamed because:

1. Eval run results are stored as JSON files in the run store
2. The UI reads results from the API; older stored results must remain parseable
3. The CLI report renderer uses the same model; serialization must stay stable

New capabilities (e.g., adding `rubric_dimension_breakdown: list[dict] | None = None`)
can always be added as optional fields with `None` defaults without breaking existing
consumers.

### 6.5 Production Precedents for This Architecture

| System | Pattern | Analog in This ADR |
|--------|---------|---------------------|
| **Temporal.io** | Workflow core (`Workflow`) + separate CLI + API SDKs | `Comparator.run()` + CLI adapter + REST adapter |
| **GitHub Actions** | REST API to start workflow + WebSocket log stream | `POST /eval/compare` + `WS /ws/eval/{id}` |
| **Promptfoo** | YAML config + CLI + optional server sharing the same eval core | `eval.yaml` format + `agentic-eval` CLI + FastAPI server |
| **Celery** | Worker core + beat scheduler + flower web UI as separate adapters | `Comparator` + CLI + web API |
| **Buildkite** | Sequential build steps with real-time log streaming to web | Sequential A→B execution + WebSocket phase events |

---

## 7. Consequences

### 7.1 Positive Outcomes

| Outcome | Mechanism |
|---------|-----------|
| No duplicated evaluation logic | Single `Comparator.run()` core — CLI and API are thin adapters |
| CLI usable in CI without a running server | Direct Python import, no HTTP or WebSocket required |
| Real-time UI out of the box | Zero new WebSocket client code — reuses `connectExecutionStream()` via `pathPrefix: "eval"` option |
| Config file enables reproducible evals | `eval.yaml` pinned in repo alongside code being evaluated |
| Type-safe contracts at both boundaries | Pydantic models validated at CLI input and API request body |

### 7.2 Trade-offs and Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| Long-running eval (30–120 min) needs persistent WebSocket | Medium | Server stores `ComparisonResult` to disk; client can poll `GET /eval/runs/{id}` if WS drops and doesn't reconnect within 5 retries |
| Run persistence across server restarts | Low | Store `ComparisonResult` as JSON in run store (consistent with existing workflow run storage) |
| Concurrent eval runs compete for worktree disk space | Low | Each run uses unique `/tmp/eval-{uuid}` path; auto-cleaned on completion |
| `prompt_text` field may contain sensitive prompt IP | Low | Never log full `Contestant` model; log only `label + type + ref` at INFO level |
| typer + Pydantic v2 compatibility | Low | Verified: typer 0.12+ supports Pydantic v2 model parameters natively |

---

## 8. Alternatives Considered

| Alternative | Rejected Because |
|-------------|-----------------|
| **REST polling only (no WebSocket)** | Eval runs last 30–120 minutes; polling wastes requests and provides no real-time feedback; poor UX for long operations |
| **SSE instead of WebSocket** | Creates a second streaming protocol diverging from the proven `connectExecutionStream()` infrastructure; net cost with no benefit |
| **gRPC streaming** | Requires proto compilation; no browser-native support without gRPC-Web proxy; overkill for internal tool |
| **File-based IPC (tail a log file)** | No browser integration; requires filesystem access from client |
| **argparse for CLI** | Verbose boilerplate; poor help output; no Pydantic integration; `sys.argv` parsing |
| **click for CLI** | Equivalent capability to typer but 40% more code; typer builds on click — no reason to use click directly |
| **Three separate Contestant classes** | Union type annotations everywhere downstream; single discriminated union is strictly simpler |
| **Breaking schema changes in ComparisonResult** | Invalidates stored run history; violates `contracts/` additive-only policy |

---

## 9. References

| Citation | Relevance |
|----------|-----------|
| Cockburn, A. — **Hexagonal Architecture** (alistair.cockburn.us, 2005) | Ports and adapters; single core, multiple entry point adapters |
| FastAPI — **WebSocket documentation** (fastapi.tiangolo.com) | WebSocket endpoint implementation with BackgroundTasks |
| typer — **Documentation** (typer.tiangolo.com) | CLI framework; click superstructure with type hints |
| Promptfoo — **Configuration reference** (promptfoo.dev/docs/configuration) | Declarative YAML A/B eval config; inspiration for `eval.yaml` format |
| Ably Engineering — **WebSockets vs SSE: Key differences** (ably.com/blog, 2024) | Performance comparison; confirms negligible difference for server-to-client streaming |
| Timeplus — **WebSocket vs SSE: A Performance Comparison** (timeplus.com, 2024) | Benchmark results; similar CPU utilization for streaming scenarios |
| `api/websocket.ts:connectExecutionStream()` | Existing WS client with 5-retry exponential backoff; `pathPrefix` option added — reused without forking |
| `hooks/useWorkflowStream.ts` | Existing WS React hook — mirrored for eval event types |
| `server/routes/workflows.py` | Existing FastAPI router structure — matched for consistency |
| `contracts/` directory — additive-only policy | Schema evolution constraint for `ComparisonResult` |

---

## 10. Decision Map

```
┌──────────────────────────────────────────────────────────────────────┐
│  ADR-011 DECISION MAP                                                │
│                                                                      │
│  CLI Framework                                                       │
│    ├── argparse ─────────────────────────────────────── REJECTED     │
│    ├── click ────────────────────────────────────────── REJECTED     │
│    └── typer ────────────────────────────────────────── CHOSEN       │
│                                                                      │
│  Real-Time Streaming Protocol                                        │
│    ├── REST polling ─────────────────────────────────── REJECTED     │
│    ├── Server-Sent Events (SSE) ─────────────────────── REJECTED     │
│    ├── gRPC streaming ───────────────────────────────── REJECTED     │
│    └── WebSocket (reuse connectExecutionStream()) ────── CHOSEN       │
│                                                                      │
│  Architecture                                                        │
│    ├── Two separate pipelines (CLI vs API) ──────────── REJECTED     │
│    └── Hexagonal: one Comparator, two adapters ─────── CHOSEN        │
│                                                                      │
│  Contestant Model                                                    │
│    ├── Three separate classes + union ───────────────── REJECTED     │
│    └── Unified Contestant with type discriminator ────── CHOSEN       │
│                                                                      │
│  Schema Evolution                                                    │
│    ├── Breaking changes allowed ─────────────────────── REJECTED     │
│    └── Additive-only (follows contracts/ policy) ─────── CHOSEN       │
└──────────────────────────────────────────────────────────────────────┘
```
