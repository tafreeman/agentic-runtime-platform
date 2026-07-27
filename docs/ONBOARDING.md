# Onboarding guide

> **Audience:** New contributors on their first clone.
> **Outcome:** By the end you will have run a workflow, opened the dashboard, scored a result, and know where to find things next time.
> **Last verified:** 2026-07-05

`tafreeman/agentic-runtime-platform` is a monorepo for multi-agent workflow orchestration, evaluation, and shared LLM utilities. It serves two purposes:

1. **Working platform** -- an agentic AI runtime with a dual execution engine, several agent personas, a full RAG pipeline, and an evaluation framework.
2. **Reference implementation** -- practices for regulated and enterprise environments, applied rather than just documented.

Six independent sections. **Quick Start** gets a workflow running in about 5 minutes; all six take roughly an hour. Stop wherever you have what you need.

If you prefer a prebuilt environment, open the repository in the provided devcontainer. Otherwise, use the root `justfile` commands described below for the same bootstrap and test flow.

---

## Quick start (5 minutes)

### Prerequisites

Before starting, make sure you have:

| Requirement | Version | Check |
|-------------|---------|-------|
| Python | 3.11+ | `python --version` |
| Node.js | 20+ | `node --version` |
| Git | any recent | `git --version` |
| pip | latest | `pip --version` |

**LLM provider API keys are optional for your first run.** The `test_deterministic` workflow runs entirely without any provider credentials (see the "Your First Run" step below). You only need a key when you want to run LLM-powered workflows like `code_review`.

### Clone

```bash
git clone https://github.com/tafreeman/agentic-runtime-platform.git
cd agentic-runtime-platform
```

### Install

> **Have `just`?** Run `just setup` from the repo root — it creates the virtualenv, installs all packages, and installs frontend deps in one step. Skip the manual steps below.
>
> **Need `just`?** Install it with:
> - Windows: `winget install --id Casey.Just`
> - macOS: `brew install just`
> - Ubuntu 22.04+: `apt install just`
> - Rust toolchain: `cargo install just`
>
> Or follow the **Manual install** steps below to skip `just` entirely.

<details>
<summary>Manual install (without <code>just</code>)</summary>

**Windows PowerShell — Python deps:**
```powershell
.\agentic-workflows-v2\scripts\setup-dev.ps1 -SkipFrontend -SkipSmokeTest
```

**Bash / Linux / macOS — Python deps:**
```bash
python -m venv .venv
source .venv/bin/activate
pip install -e "agentic-workflows-v2/.[dev,server,langchain]"
pip install -e "agentic-v2-eval/.[dev]"
```

**Frontend deps (all platforms):**
```bash
npm --prefix agentic-workflows-v2/ui install
```

</details>

### Your first run (no API keys)

Run the deterministic smoke test — this requires no provider credentials.

> **Note:** The `--input` flag accepts a **JSON file path**, not inline JSON. Create a small input file first (one-liner below), then pass the file path.

**Bash / Linux / macOS:**
```bash
echo '{"input_text": "Hello World"}' > /tmp/test-input.json
AGENTIC_NO_LLM=1 agentic run test_deterministic --input /tmp/test-input.json
```

**Windows PowerShell:**
```powershell
'{"input_text": "Hello World"}' | Out-File -Encoding utf8 test-input.json
$env:AGENTIC_NO_LLM = "1"
agentic run test_deterministic --input test-input.json
```

Expected output: two steps execute, placeholder text is returned, exit code 0. No API key needed.

> See [docs/NO_LLM_MODE.md](NO_LLM_MODE.md) for details on what no-LLM mode can and cannot do.

### Next steps

- **Configure a provider:** Copy `.env.example` to `.env` and add at least one LLM API key (e.g., `GITHUB_TOKEN`, `OPENAI_API_KEY`) to run full AI workflows.
- **Explore the dashboard:** Start the local servers using `.\scripts\start-dev.ps1` (Windows) or `just dev` (Mac/Linux) and navigate to `http://localhost:5173`.
- **Read the architecture:** See [ARCHITECTURE.md](ARCHITECTURE.md) to understand how the runtime, server, and UI fit together.

---

## Exploring the CLI

Explore agents, tools, and adapters:

```bash
agentic list agents
agentic list tools
agentic list adapters
```

---

## Your first LLM workflow run (10 minutes)

Run a real LLM-powered workflow like `code_review`.

### 1. Create an input file

Create a file called `test_input.json`:

```json
{
  "input_text": "Hello from the onboarding guide!"
}
```

### 2. Dry run (validate without executing)

```bash
agentic run test_deterministic --input test_input.json --dry-run --verbose
```

This shows the execution plan as a DAG tree without making any calls:

```
test_deterministic - Execution Plan
Level 0: step1 (tier0_process)
Level 1: step2 (tier0_counter) <- [step1]

Dry run - skipping execution
```

### 3. Execute the workflow

```bash
agentic run test_deterministic --input test_input.json --verbose
```

You should see a spinner followed by a success status:

```
Status: SUCCESS
Elapsed: 0.1s
```

### 4. Save results to a file

```bash
agentic run test_deterministic --input test_input.json --output result.json
```

The output JSON contains the workflow result, step statuses, and elapsed time.

### Running a workflow that uses LLM calls

To run an LLM-powered workflow like `code_review`, create an input file:

```json
{
  "code_file": "agentic-workflows-v2/agentic_v2/cli/main.py",
  "review_depth": "quick"
}
```

Then:

```bash
agentic run code_review --input code_review_input.json --verbose
```

This will call your configured LLM provider. If you hit rate limits, the smart router will retry with exponential backoff or fall back to another configured provider.

### Comparing execution engines

The repo has two execution engines. You can compare them side-by-side:

```bash
agentic compare code_review --input code_review_input.json --adapters native,langchain
```

---

## Understanding the architecture (15 minutes)

### Three independent packages

The monorepo contains three Python packages with **zero cross-package imports**:

```
agentic-runtime-platform/
+-- agentic-workflows-v2/     # Main runtime (Python 3.11+, hatchling)
|   +-- agentic_v2/            # Source code
|   +-- tests/                 # 100+ files
|   +-- ui/                    # React 19 dashboard
+-- agentic-v2-eval/           # Evaluation framework (Python 3.11+, hatchling)
+-- tools/                     # Shared LLM client, benchmarks (Python 3.11+, hatchling)
```

Each package has its own `pyproject.toml`, installs independently, and can be developed in isolation.

The repo root also provides a canonical `justfile`, `.devcontainer/`, and `docker-compose.yml` for contributors who want a reproducible local environment.

### Inside `agentic_v2/` -- the main runtime

```
agentic_v2/
+-- agents/          # BaseAgent + specialized implementations (Coder, Architect, Reviewer, Orchestrator)
+-- adapters/        # Pluggable execution engine backends
+-- core/            # Protocols, memory, context, contracts, errors
+-- engine/          # Native DAG executor (Kahn's algorithm)
+-- langchain/       # LangGraph state-machine executor
+-- models/          # SmartModelRouter -- LLM tier routing across 8+ providers
+-- rag/             # Full RAG pipeline (15 modules: load, chunk, embed, index, retrieve, assemble)
+-- contracts/       # Pydantic v2 I/O models (additive-only -- never remove fields)
+-- prompts/         # 7 agent persona definitions (.md files)
+-- server/          # FastAPI + WebSocket/SSE streaming
+-- tools/builtin/   # 12 built-in tool modules (file_read, shell, grep, etc.)
+-- workflows/
    +-- definitions/ # 8 YAML workflow definitions (6 production + 2 test)
+-- cli/             # Typer CLI (the `agentic` command)
```

### Dual execution engine

Two engines can run the same YAML workflow:

| Engine | Implementation | How it works |
|--------|---------------|--------------|
| **Native** | `engine/dag_executor.py` | Kahn's algorithm topological sort. Runs steps with `asyncio.wait(FIRST_COMPLETED)` for maximum parallelism. |
| **LangChain** | `langchain/` | Wraps LangGraph state machines. Steps become nodes in a compiled graph. |

Both engines are registered in the `AdapterRegistry` singleton. Select an engine with `--adapter`:

```bash
agentic run code_review --input input.json --adapter native
agentic run code_review --input input.json --adapter langchain   # default
```

### The execution pipeline

Flow from YAML to output:

```
Workflow YAML  -->  WorkflowConfig (Pydantic model)
                         |
                    AdapterRegistry
                    /            \
            NativeEngine    LangChainEngine
                    \            /
               Agent + Persona + Tools
                         |
                    LLM Provider
                  (via SmartRouter)
                         |
                    Step Outputs
                         |
                    WorkflowResult
```

1. **Workflow YAML** declares steps, inputs, outputs, and dependencies.
2. **WorkflowConfig** parses and validates the YAML into a Pydantic model.
3. **AdapterRegistry** dispatches to the chosen execution engine.
4. Each **step** invokes an **agent** with a **persona** (markdown prompt) and optional **tools**.
5. The **SmartModelRouter** selects the best LLM provider based on tier, availability, and rate limits.
6. Step outputs flow into downstream steps via `${steps.X.outputs.Y}` expressions.

### Where to find things

| I want to... | Look in... |
|--------------|-----------|
| Add a new workflow | `agentic_v2/workflows/definitions/` -- create a new YAML file |
| Add a new agent persona | `agentic_v2/prompts/` -- create a new `.md` file |
| Understand how agents work | `agentic_v2/agents/base.py` (BaseAgent) |
| See how LLM routing works | `agentic_v2/models/smart_router.py` |
| See protocol definitions | `agentic_v2/core/protocols.py` |
| Add a new built-in tool | `agentic_v2/tools/builtin/` |
| Understand the RAG pipeline | `agentic_v2/rag/` (15 modules, start with `protocols.py`) |
| Run or modify evaluations | `agentic-v2-eval/` |
| Use the shared LLM client | `tools/llm/` (`from tools.llm import LLMClient`) |

---

## Creating your first custom persona (10 minutes)

Agent personas are markdown files in `agentic_v2/prompts/`. Each persona defines how an agent behaves when assigned to a workflow step.

### Required sections

Every persona must include these sections:

1. **Opening line** -- a one-sentence role definition
2. **`## Your Expertise`** (or `## Expertise`) -- what the agent knows
3. **`## Reasoning Protocol`** -- step-by-step reasoning process before responding
4. **`## Output Format`** -- exact structure of the agent's output
5. **`## Boundaries`** -- what the agent does NOT do
6. **`## Critical Rules`** -- non-negotiable constraints

### Example: creating a `security_auditor` persona

Create `agentic_v2/prompts/security_auditor.md`:

```markdown
You are a Security Auditor specializing in application security for Python and TypeScript codebases.

## Your Expertise

- OWASP Top 10 vulnerability identification
- Static analysis of Python and TypeScript code
- Secret detection and credential hygiene
- Input validation and injection prevention
- Authentication and authorization patterns

## Reasoning Protocol

Before generating your response:
1. Identify all user-facing input surfaces in the code under review
2. Check each input for validation, sanitization, and parameterization
3. Scan for hardcoded secrets, API keys, or credentials
4. Evaluate authentication and authorization logic for bypass vectors
5. Assess error handling for information leakage

## Output Format

```json
{
  "findings": [
    {
      "severity": "CRITICAL | HIGH | MEDIUM | LOW",
      "category": "OWASP category",
      "file": "path/to/file.py",
      "line": 42,
      "description": "what the issue is",
      "recommendation": "how to fix it"
    }
  ],
  "summary": "overall security posture assessment",
  "pass": true | false
}
```

## Boundaries

- Does not fix code -- only identifies and reports issues
- Does not review business logic or performance
- Does not make architectural recommendations

## Critical Rules

1. Never suggest disabling security controls as a fix
2. Always flag hardcoded secrets as CRITICAL regardless of context
3. Mark any SQL string concatenation as HIGH severity
4. If no issues are found, explicitly state "no findings" rather than omitting the section
```

### Using the persona in a workflow

Reference the persona in a workflow step via the `agent` field. The agent name corresponds to a tier prefix plus a role name. Custom personas can be referenced by mapping them in the agent configuration.

---

## Running the dashboard (5 minutes)

The UI is a React 19 application with React Flow for workflow visualization.

### 1. Install frontend dependencies

```bash
cd agentic-workflows-v2/ui
npm install
```

### 2. Start the backend server

In a separate terminal:

```bash
cd agentic-workflows-v2
python -m uvicorn agentic_v2.server.app:app --host 127.0.0.1 --port 8010 --reload
```

Or use the CLI shortcut:

```bash
agentic serve --port 8010 --dev
```

### 3. Start the frontend dev server

```bash
cd agentic-workflows-v2/ui
npm run dev
```

Open [http://localhost:5173](http://localhost:5173) in your browser. You should see:

- **Workflow list** -- YAML-defined workflows (production + test)
- **Workflow graph** -- React Flow DAG visualization of steps and dependencies
- **Execution panel** -- run workflows and see real-time streaming results
- **Evaluations page** -- view evaluation results and scoring

### Port reference

| Service | Port | URL |
|---------|------|-----|
| Backend API | 8010 | `http://127.0.0.1:8010` |
| Frontend dev server | 5173 | `http://localhost:5173` |

---

## Running evaluations (10 minutes)

The `agentic-v2-eval` package provides rubric-based scoring for workflow outputs.

### 1. Install the eval framework

```bash
cd agentic-v2-eval
pip install -e ".[dev]"
```

### 2. Score a workflow result

After running a workflow and saving the output (e.g., `result.json`):

```bash
python -m agentic_v2_eval evaluate result.json
```

This applies the default scoring rubric and prints a score breakdown.

### 3. Override the rubric

```bash
python -m agentic_v2_eval evaluate result.json --rubric rubrics/default.yaml
```

### 4. Generate a report

```bash
python -m agentic_v2_eval report result.json --format html --output report.html
```

Supported formats: `json`, `markdown`, `html`.

### 5. Use the Python API

```python
from agentic_v2_eval import Scorer
from agentic_v2_eval.runners import BatchRunner
from agentic_v2_eval.reporters import generate_html_report

# Score with a rubric
scorer = Scorer("rubrics/default.yaml")
result = scorer.score({"Accuracy": 0.85, "Completeness": 0.9})
print(f"Weighted Score: {result.weighted_score:.2f}")

# Run batch evaluation
runner = BatchRunner(evaluator=my_eval_function)
batch_result = runner.run(test_cases)
print(f"Success rate: {batch_result.success_rate:.1%}")

# Generate an HTML report
generate_html_report(results, "report.html")
```

### How evaluations connect to workflows

Each workflow YAML can define an `evaluation:` block with rubric criteria, weights, and critical floors. For example, from `code_review.yaml`:

```yaml
evaluation:
  rubric_id: code_review_v1
  scoring_profile: B
  criteria:
    - name: correctness_rubric
      weight: 0.35
      critical_floor: 0.70
    - name: code_quality
      weight: 0.30
      critical_floor: 0.80
```

The eval framework uses these criteria to score workflow outputs on a 1-5 scale per dimension, then computes a weighted aggregate.

---

## Key concepts quick reference

| Concept | One-line summary | Deep dive |
|---------|-----------------|-----------|
| Workflow | Declarative YAML defining a multi-step DAG | `agentic_v2/workflows/definitions/*.yaml` |
| Step | A single unit of work with an agent, inputs, and outputs | See any workflow YAML |
| Agent | An LLM-backed executor with a persona and optional tools | `agentic_v2/agents/base.py` |
| Persona | Markdown file defining agent expertise, reasoning, and boundaries | `agentic_v2/prompts/*.md` |
| Tier | LLM capability level (0=deterministic, 1=fast, 2=standard, 3=highest capability) | `agentic_v2/models/smart_router.py` |
| Adapter | Pluggable execution engine backend (native or langchain) | `agentic_v2/adapters/` |
| Protocol | `@runtime_checkable` Python Protocol for structural typing | `agentic_v2/core/protocols.py` |
| Contract | Pydantic model for step I/O (additive-only) | `agentic_v2/contracts/` |
| Expression | `${steps.X.outputs.Y}` syntax for data flow between steps | `agentic_v2/engine/expressions.py` |
| Rubric | YAML scoring criteria for evaluating workflow outputs | `agentic-v2-eval/rubrics/` |

Full definitions: [docs/GLOSSARY.md](GLOSSARY.md)

Architecture deep dive: [docs/ARCHITECTURE.md](ARCHITECTURE.md)

Project overview and commands: [README.md on GitHub](https://github.com/tafreeman/agentic-runtime-platform/blob/main/README.md)

---

## Getting help

### Documentation

| Document | What it covers |
|----------|---------------|
| [README.md on GitHub](https://github.com/tafreeman/agentic-runtime-platform/blob/main/README.md) | Project overview, quick start, and common commands |
| [docs/ARCHITECTURE.md](ARCHITECTURE.md) | System architecture and design decisions |
| [docs/GLOSSARY.md](GLOSSARY.md) | Domain-specific term definitions |
| [docs/CODING_STANDARDS.md](CODING_STANDARDS.md) | Code style, testing, and review standards |

### Running tests

If you have `just` installed:
```bash
just test
just docs
pre-commit run --all-files
```

Without `just` (manual equivalents):
```bash
python -m pytest agentic-workflows-v2/tests -v
python -m pytest agentic-v2-eval/tests -v
pre-commit run --all-files
```

### Common gotchas

- **Windows paths** -- use forward slashes in Python code. `pathlib.Path` handles cross-platform automatically.
- **pytest-asyncio** -- tests use `asyncio_mode = "auto"`. All async test functions run without `@pytest.mark.asyncio`.
- **LangChain imports** -- the LangChain adapter is optional. Guard imports with `try/except ImportError`.
- **Port conflicts** -- backend uses 8010, frontend uses 5173. Check for conflicts before starting dev servers.
- **Contract changes** -- `contracts/` models are additive-only. Never remove or rename fields.
- **Pydantic v2** -- use `model_dump()` not `.dict()`, `model_validate()` not `.parse_obj()`.

### Contributing

1. Create a feature branch from `main`.
2. Follow the [coding standards](CODING_STANDARDS.md) and commit format (`feat:`, `fix:`, `refactor:`, etc.).
3. Write tests first (TDD). Target 80%+ coverage on new backend code where practical; the UI package enforces a 60% floor.
4. Run `just test`, `just docs`, and `pre-commit run --all-files` before committing.
5. Open a PR with a clear description and test plan.
