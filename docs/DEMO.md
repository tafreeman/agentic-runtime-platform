# Five-minute local demo

This demo proves that the runtime, API, WebSocket stream, and dashboard work
together. It does not require a provider credential.

Complete [Installation](getting-started/installation.md) first.

## 1. Run the deterministic workflow

From the repository root in PowerShell:

```powershell
$env:AGENTIC_NO_LLM = "1"
.\.venv\Scripts\agentic.exe run test_deterministic `
  --input agentic-workflows-v2\tests\fixtures\deterministic_input.json `
  --verbose
```

The command should end with:

```text
Status: SUCCESS
```

This checks the CLI, workflow loader, input validation, and dependency order.
It does not test provider access.

## 2. Start the development services

Keep `AGENTIC_NO_LLM=1` in the same environment, then run:

```text
just dev
```

Check the services:

| Service | Address |
|---|---|
| Dashboard | `http://127.0.0.1:5173` |
| Backend health | `http://127.0.0.1:8010/api/health` |
| Backend readiness | `http://127.0.0.1:8010/api/health/ready` |
| API documentation | `http://127.0.0.1:8010/docs` |

On a system that cannot run the PowerShell-based `just` recipe, start the
services in separate terminals:

```text
python -m uvicorn agentic_v2.server.app:app --host 127.0.0.1 --port 8010
npm --prefix agentic-workflows-v2/ui run dev
```

## 3. Run from the dashboard

1. Open `http://127.0.0.1:5173`.
2. Open **Workflows**.
3. Select `test_deterministic`.
4. Enter the required `input_text`.
5. Start the run.
6. Open the live view and watch each step change state.
7. Open the saved run after it completes and inspect its step results.

The deterministic workflow has two tier-0 steps. A successful live run confirms
that the HTTP request, execution event stream, and saved result reached the
dashboard.

## 4. Optional provider-backed run

To demonstrate model routing:

1. stop the development services with `just dev-stop`;
2. run `Remove-Item Env:AGENTIC_NO_LLM` in PowerShell;
3. copy `.env.example` to `.env`;
4. configure one supported provider;
5. restart with `just dev`; and
6. run `code_review` from the dashboard or CLI.

CLI example:

```powershell
.\.venv\Scripts\agentic.exe run code_review `
  --input agentic-workflows-v2\tests\fixtures\code_review_input.json `
  --verbose
```

Provider response time, availability, and cost depend on the selected account
and model. A provider-backed failure does not invalidate the deterministic
runtime test; inspect the provider probe and the failed step separately.

## What each step verifies

| Check | Evidence |
|---|---|
| Deterministic CLI run | Workflow discovery and local engine execution |
| Health and readiness | Server process and configured dependencies |
| Dashboard workflow list | REST API and UI data loading |
| Live run page | WebSocket execution events |
| Saved run page | Result serialization and run retrieval |
| Optional `code_review` | Provider routing and model-backed steps |

## Troubleshooting

| Symptom | Check |
|---|---|
| `agentic` is not found | Activate `.venv` or use `.\.venv\Scripts\agentic.exe` |
| Port conflict | Run `agentic devex port-guard --backend-port 8010 --frontend-port 5173` |
| Dashboard cannot reach the API | Open `/api/health` and confirm backend port `8010` |
| Live view cannot connect | Confirm the backend is running and the dashboard origin is allowed |
| Provider-backed step fails | Inspect `/api/models/probe`, the run result, and the provider variable |

For more detail, see [Troubleshooting](operations/troubleshooting.md),
[Runtime architecture](architecture-runtime.md), and the
[Runtime API](api-contracts-runtime.md).
