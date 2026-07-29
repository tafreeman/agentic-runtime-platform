# Runtime package development

Use the repository-level [development guide](../../docs/development-guide.md)
for workspace setup and broad checks. This page lists package-local commands.

## Install

From `agentic-workflows-v2`:

```text
python -m pip install -e ".[dev,server,langchain]"
```

The root `agentic-tools` package must already be installed. The normal
repository setup handles both:

```text
just setup
```

## Run the backend

From `agentic-workflows-v2`:

```text
python -m uvicorn agentic_v2.server.app:app `
  --host 127.0.0.1 `
  --port 8010 `
  --reload
```

Health routes:

- `http://127.0.0.1:8010/api/health`
- `http://127.0.0.1:8010/api/health/ready`

## Run the dashboard

From the repository root:

```text
npm --prefix agentic-workflows-v2/ui run dev
```

Vite starts on port `5173` and sends API requests to the backend on port
`8010`. Set `VITE_API_PROXY_TARGET` before startup to change that target.

## Run workflows

From either the repository root or this package directory:

```text
agentic list workflows
agentic validate code_review
agentic run code_review --dry-run
```

Deterministic smoke test from the repository root:

```powershell
$env:AGENTIC_NO_LLM = "1"
.\.venv\Scripts\agentic.exe run test_deterministic `
  --input agentic-workflows-v2\tests\fixtures\deterministic_input.json
```

## Test

From the repository root:

```text
python -m pytest agentic-workflows-v2/tests -q
```

Coverage:

```text
python -m pytest agentic-workflows-v2/tests `
  --cov=agentic_v2 `
  --cov-report=term-missing
```

UI:

```text
npm --prefix agentic-workflows-v2/ui test
npm --prefix agentic-workflows-v2/ui run test:coverage
npm --prefix agentic-workflows-v2/ui run build
```

## Validate package documentation and contracts

From the repository root:

```text
python agentic-workflows-v2/scripts/check_docs_refs.py
```

After changing a generated wire model, run from `agentic-workflows-v2`:

```text
python -m scripts.generate_ts_types
npm --prefix ui run generate:types
npm --prefix ui run build
```

## Local outputs

| Path | Contents |
|---|---|
| `.run-logs/` | Backend and dashboard development logs |
| `runs/` | Saved run output when configured to this location |
| `ui/dist/` | Production dashboard bundle |

These are generated outputs and normally should not be committed.

For environment variables, use the central
[configuration reference](../../docs/configuration.md). For failures, use
[troubleshooting](../../docs/operations/troubleshooting.md).
