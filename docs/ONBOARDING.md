# Contributor onboarding

This guide gets a new contributor from a clean checkout to a verified workflow
run and a working development environment.

Last verified: 2026-07-28.

## What is in this repository

| Path | Purpose |
|---|---|
| repository root and `tools/` | Shared `agentic-tools` Python package |
| `agentic-workflows-v2/` | Workflow runtime, CLI, FastAPI server, and RAG components |
| `agentic-workflows-v2/ui/` | React dashboard |
| `agentic-v2-eval/` | Rubrics, evaluators, runners, and reports |
| `tests/e2e/` | Checks that cross package boundaries |
| `docs/` | Maintained guides, reference material, and ADRs |

The runtime has two execution engines:

- `native` implements the platform-specific DAG behavior;
- `langchain` compiles compatible workflows to LangGraph and is the default
  for `agentic run`.

Use `agentic compare` when you need to check whether both engines produce
compatible results. Do not assume every native-only feature is supported by
the LangGraph adapter.

## Prerequisites

- Python 3.11 or newer
- Node.js 20 or newer
- Git
- PowerShell for the repository's `just` recipes and development scripts

Provider keys are optional. The first workflow below is deterministic and does
not call a model.

## 1. Install the workspace

On Windows, from the repository root:

```text
just setup
```

This creates `.venv`, installs the three Python packages in editable mode, and
installs the dashboard dependencies.

The `justfile` currently selects `powershell.exe` as its shell. On Linux and
macOS, or on Windows without `just`, follow the
[manual installation commands](getting-started/installation.md#manual-setup).

Verify the installed entry points:

```text
agentic version
agentic list workflows
agentic-v2-eval --version
```

If the virtual environment is not activated, call the executable directly in
PowerShell:

```powershell
.\.venv\Scripts\agentic.exe version
```

## 2. Run a workflow without a provider

The repository includes a valid input fixture:

```powershell
$env:AGENTIC_NO_LLM = "1"
.\.venv\Scripts\agentic.exe run test_deterministic `
  --input agentic-workflows-v2\tests\fixtures\deterministic_input.json
```

Expected result:

```text
Status: SUCCESS
```

This confirms workflow discovery, JSON input loading, dependency ordering, and
result construction. It does not test a provider.

Inspect the plan without running it:

```text
agentic run code_review --dry-run
```

Write a result to disk:

```text
agentic run test_deterministic --input <input.json> --output result.json
```

`--input` always expects a JSON file path. See the
[quick start](getting-started/quickstart.md) for an explanation of the result
fields and the [CLI reference](cli-reference.md) for every command.

## 3. Start the backend and dashboard

On Windows:

```text
just dev
```

Open:

| Service | URL |
|---|---|
| Dashboard | `http://127.0.0.1:5173` |
| Backend health | `http://127.0.0.1:8010/api/health` |
| Backend readiness | `http://127.0.0.1:8010/api/health/ready` |
| Swagger UI | `http://127.0.0.1:8010/docs` |

Useful lifecycle commands:

```text
just dev-status
just dev-stop
just dev-reload
```

For manual startup or a different operating system, use two terminals:

```text
python -m uvicorn agentic_v2.server.app:app --host 127.0.0.1 --port 8010
npm --prefix agentic-workflows-v2/ui run dev
```

The standalone `agentic serve` command defaults to port `8000`. Use
`agentic serve --port 8010` when pairing it with the dashboard's default proxy.

## 4. Understand one workflow

Start with
`agentic-workflows-v2/agentic_v2/workflows/definitions/test_deterministic.yaml`.
It contains two tier-0 agent steps. In no-LLM mode, the current native path
returns placeholder values without contacting an external provider.

Then inspect `code_review.yaml`:

1. the workflow declares an input schema;
2. each step names an agent and its dependencies;
3. the loader validates the graph;
4. the selected engine schedules ready steps;
5. agents return typed step results;
6. the runtime combines them into a `WorkflowResult`.

For syntax and feature support, use:

- [Workflow authoring](WORKFLOW_AUTHORING.md)
- [First workflow tutorial](getting-started/first-workflow.md)
- [Runtime architecture](architecture-runtime.md)
- [Architecture decisions](adr/ADR-INDEX.md)

## 5. Configure a provider only when needed

Copy `.env.example` to `.env` and set the credential for the provider you
intend to use. Do not fill every variable.

```powershell
Copy-Item .env.example .env
```

With the backend running, probe the current routing:

```powershell
Invoke-RestMethod http://127.0.0.1:8010/api/models/probe
```

Model availability can change between environments. Treat a successful
deterministic run as a runtime smoke test, not proof that live inference works.
Use [Configuration](configuration.md) for provider names, model overrides,
authentication, tracing, persistence, and RAG settings.

## 6. Run an evaluation

The evaluation package consumes structured scores. It does not run a workflow
for you.

Create `results.json`:

```json
[
  {
    "Accuracy": 0.9,
    "Completeness": 0.8,
    "Efficiency": 0.75
  }
]
```

Score it with the bundled default rubric:

```text
agentic-v2-eval evaluate results.json --output scored.json
agentic-v2-eval report scored.json --format markdown --output report.md
```

Use `--fail-under <0.0-1.0>` when a script or CI job should fail below a
threshold. See the
[evaluation package README](https://github.com/tafreeman/agentic-runtime-platform/blob/main/agentic-v2-eval/README.md)
for its exit codes and Python API.

## 7. Make a change

Keep changes within their package unless the architecture explicitly requires
a cross-package dependency.

Paths in this table are relative to `agentic-workflows-v2/` unless stated
otherwise.

| Change | Start here |
|---|---|
| Workflow YAML | `agentic_v2/workflows/definitions/` |
| Runtime execution | `agentic_v2/engine/` |
| Model routing | `agentic_v2/models/` |
| API route | `agentic_v2/server/routes/` |
| Dashboard page | `ui/src/pages/` |
| Evaluation logic | `agentic-v2-eval/src/agentic_v2_eval/` |
| Shared provider or benchmark code | `tools/` |
| Persona prompt | `agentic_v2/prompts/` |

Add a focused regression test beside the package you change. If a Pydantic
wire contract changes, regenerate its JSON Schema and TypeScript types as
described in [Contributing](CONTRIBUTING.md#change-generated-contracts).

## 8. Validate before review

Use narrow checks while editing:

```text
python -m pytest agentic-workflows-v2/tests -q
python -m pytest agentic-v2-eval/tests -q
npm --prefix agentic-workflows-v2/ui test
npm --prefix agentic-workflows-v2/ui run build
```

Run the repository checks before requesting review:

```text
just test
just docs
pre-commit run --all-files
```

`just docs` checks internal documentation references and generated repository
statistics. The published site is also built with MkDocs in CI.

## Common problems

| Problem | Check |
|---|---|
| `agentic` is not found | Activate `.venv` or call its executable directly |
| A named workflow is missing | Run `agentic list workflows`; pass a YAML path for a custom file |
| `--input` fails to parse | Pass a file path containing valid JSON |
| The dashboard has network errors | Confirm the backend is listening on `8010` |
| A model-backed step fails | Check its provider variable and use the dashboard Models page or `/api/models/probe` |
| Native works but LangGraph fails | Inspect workflow capabilities and adapter support |
| RAG search returns nothing in a second shell | The current RAG CLI index is process-local; see [Known limitations](KNOWN_LIMITATIONS.md) |

For security reports, follow the
[security policy](https://github.com/tafreeman/agentic-runtime-platform/blob/main/agentic-workflows-v2/SECURITY.md).
For usage questions, use
[support](https://github.com/tafreeman/agentic-runtime-platform/blob/main/agentic-workflows-v2/SUPPORT.md).
For contribution rules and the complete
verification matrix, use [CONTRIBUTING.md](CONTRIBUTING.md).
