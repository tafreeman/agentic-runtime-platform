# Troubleshooting

Start with the symptom, confirm the cause, and change one setting at a time.
For behavior that is intentionally unsupported, see
[Known limitations](../KNOWN_LIMITATIONS.md).

## Collect basic state

On Windows, the development scripts can report their process and port state:

```text
just dev-status
agentic devex port-guard --backend-port 8010 --frontend-port 5173
```

Check the backend separately:

```powershell
Invoke-RestMethod http://127.0.0.1:8010/api/health
Invoke-RestMethod http://127.0.0.1:8010/api/health/ready
```

`/api/health` confirms that the process is running. `/api/health/ready` also
checks configured required dependencies, including Redis when a Redis URL is
set.

When reporting a problem, include:

- the exact command;
- the complete error message and exit code;
- Python, Node, and package versions;
- the selected adapter;
- whether the workflow is deterministic or provider-backed; and
- the smallest input that reproduces the problem.

Remove credentials, prompts containing private data, and sensitive tool output.

## Installation and startup

### `agentic` is not found

Activate the repository environment:

```powershell
.\.venv\Scripts\Activate.ps1
```

Or call the executable directly:

```powershell
.\.venv\Scripts\agentic.exe version
```

If `.venv` does not exist, run `just setup` on Windows or follow the
[manual installation guide](../getting-started/installation.md#manual-setup).

### `ModuleNotFoundError: agentic_v2`

The runtime package is not installed in the active Python environment. From the
repository root:

```text
python -m pip install -e "./agentic-workflows-v2[dev,server,langchain]"
```

Install the root `agentic-tools` package first if the dependency cannot be
resolved:

```text
python -m pip install -e .
```

### LangGraph or LangChain extra is missing

The default `agentic run` adapter is `langchain`. Install the extra:

```text
python -m pip install -e "./agentic-workflows-v2[langchain]"
```

For a workflow that supports it, select the native engine instead:

```text
agentic run <workflow> --input <input.json> --adapter native
```

### Port 8010 or 5173 is in use

Identify the owner before stopping anything:

```powershell
Get-NetTCPConnection -State Listen -LocalPort 8010,5173 |
  Select-Object LocalPort, OwningProcess
Get-Process -Id <pid>
```

Stop the process only after confirming that it belongs to the development
environment:

```powershell
Stop-Process -Id <pid>
```

The standalone `agentic serve` command defaults to port `8000`, while
`just dev` uses backend port `8010` and dashboard port `5173`.

### Sanitization initialization fails

The server fails closed when the sanitization layer cannot initialize. Fix the
startup error or missing dependency. `AGENTIC_SANITIZER_FAIL_OPEN=1` bypasses
sanitization and is only suitable for isolated debugging; do not use it on an
exposed service.

## Authentication and request limits

### HTTP 401

When `AGENTIC_API_KEY` is set, send the same value with either:

```text
Authorization: Bearer <key>
X-API-Key: <key>
```

Health and API-documentation routes remain public. If OIDC is enabled, verify
the issuer, audience, and JWKS settings in
[Configuration](../configuration.md#http-authentication).

### HTTP 429

There are two independent limits:

- the normal per-IP request limit, configured by
  `AGENTIC_RATE_LIMIT_DEFAULT`; and
- the failed-authentication lockout, configured by the
  `AGENTIC_AUTH_LOCKOUT_*` variables.

Inspect the response body and server log to determine which limit rejected the
request. Honor `Retry-After` rather than retrying immediately. The disable
flags are for tests or an explicitly accepted deployment risk, not a normal
fix.

Authentication failure counters are in-process and are not shared across
replicas. There is currently no Redis-backed authentication lockout. Account
for that limit in the deployment design; Redis support elsewhere in the
runtime does not make this counter global.

## Workflow execution

### `--input` does not parse

`agentic run --input` expects a path to a JSON file:

```text
agentic run test_deterministic --input .\input.json
```

It does not accept inline JSON.

### Workflow is not found

List packaged workflows:

```text
agentic list workflows
```

For a custom workflow, pass its `.yaml` or `.yml` path directly. Validate it
before execution:

```text
agentic validate .\workflows\my_workflow.yaml
agentic devex workflow-linter .\workflows\my_workflow.yaml --strict
```

### A step is skipped after another step fails

Dependent steps are skipped when a prerequisite fails. Find the first `FAILED`
step in graph order; later `SKIPPED` results are usually consequences, not
independent failures.

### The native and LangGraph results differ

Check the workflow capability response or `agentic compare` output. Conditional
edges, retry policy, budgets, and other native features may not have matching
LangGraph behavior. Use the adapter required by the workflow rather than
assuming the engines are interchangeable.

### Execution reaches its timeout

Inspect per-step durations and provider retries in the saved run. Raise a
timeout only after confirming the expected worst-case duration; otherwise fix
the slow or retrying step.

## Model providers

### No model is available for a tier

Confirm that the process received the intended provider variable and that the
configured model exists for that account. With the backend running, inspect:

```powershell
Invoke-RestMethod http://127.0.0.1:8010/api/models/probe
```

Use `AGENTIC_NO_LLM=1` for deterministic development. It proves runtime flow,
not provider access or output quality.

### Provider returns 401 or 403

Check that the credential is active, has no surrounding whitespace, and is
allowed to use the requested model. Do not print the key while debugging.

### Provider returns 429

Honor the provider's retry guidance and inspect the router's fallback result.
Do not copy rate or quota values from documentation; provider limits depend on
the current account and can change.

## RAG

### Search in a new shell returns no results

The current `agentic rag ingest` and `agentic rag search` commands use separate
in-process stores. An index created by one command is not available to the next
process. The CLI also does not yet apply its collection option.

Use the Python RAG API with a durable vector store for real applications. See
the [RAG guide](../rag/index.md) and [Known limitations](../KNOWN_LIMITATIONS.md).

### Retrieval quality is unexpectedly poor

Check which embedder was constructed. `InMemoryEmbedder` is a deterministic
hash test double, not a semantic embedding model. Also confirm that stored and
query vectors came from the same provider, model, dimensions, and
normalization. Do not silently fall back to a different embedding space.

### LanceDB cannot be imported

Install the runtime's RAG extra:

```text
python -m pip install -e "./agentic-workflows-v2[rag]"
```

## File, shell, and code tools

### File or Git tool says `AGENTIC_FILE_BASE_DIR` is not set

Set `AGENTIC_FILE_BASE_DIR` to the absolute directory the tool may access.
File and Git tools reject operations when this boundary is missing.

### Shell command is not allowed

`AGENTIC_SHELL_ALLOWED_COMMANDS` is a comma-separated list of command
basenames. Keep it as small as possible:

```powershell
$env:AGENTIC_SHELL_ALLOWED_COMMANDS = "git,python"
```

### Code execution blocks an import

The local code sandbox intentionally blocks imports and traversal techniques
that could escape its boundary. Use the dedicated file or shell tool when the
workflow legitimately needs those capabilities.

## Dashboard

### The page loads but API calls fail

Confirm that FastAPI is on port `8010`. If it is elsewhere, set
`VITE_API_PROXY_TARGET` before starting Vite:

```powershell
$env:VITE_API_PROXY_TARGET = "http://127.0.0.1:9000"
npm --prefix agentic-workflows-v2/ui run dev
```

### WebSocket is rejected with 403

Add the dashboard's exact origin to `AGENTIC_CORS_ORIGINS`. Do not include a
trailing slash.

### TypeScript types no longer match Python

From `agentic-workflows-v2`:

```text
python -m scripts.generate_ts_types
npm --prefix ui run generate:types
npm --prefix ui run build
```

Review and commit the generated JSON Schemas and TypeScript together.

## Tracing

If no spans arrive:

1. confirm `AGENTIC_TRACING=true` in the server process;
2. confirm the `tracing` extra is installed;
3. confirm the OTLP protocol matches the endpoint;
4. check network access from the server to the collector; and
5. inspect startup logs for the tracing initialization result.

Prompts, outputs, and tool arguments are excluded by default. Only set
`AGENTIC_TRACE_SENSITIVE=true` in a trusted environment with an approved data
handling policy.

## Tests and documentation

### Generated contract check fails

Regenerate both sides as shown in the Dashboard section above. The committed
schemas are part of the API contract.

### Documentation reference check fails

Run:

```text
python agentic-workflows-v2/scripts/check_docs_refs.py
python scripts/generate_doc_stats.py --check
```

The first command reports missing local targets. The second reports stale
generated counts; run it without `--check` only when the repository facts have
changed and the documentation should be updated.

### MkDocs strict build fails

Install the dependencies used by `.github/workflows/docs.yml`, then run:

```text
mkdocs build --strict
```

Fix every missing page, broken link, invalid navigation entry, or plugin error.
Do not hide a content error by disabling strict mode.

## Windows notes

- Use `npm run <script>` or `npm exec -- <command>` instead of relying on
  `npx`.
- Use `pathlib.Path` in Python and quote paths that contain spaces.
- Run the PowerShell development scripts from PowerShell, not through Git Bash
  quoting.
- If script execution is blocked, review the organization's execution policy;
  do not weaken a managed security policy without approval.

## More help

- [Configuration](../configuration.md)
- [Security hardening](security-hardening.md)
- [Runtime API](../api-contracts-runtime.md)
- [Contributor guide](../CONTRIBUTING.md)
- [GitHub issues](https://github.com/tafreeman/agentic-runtime-platform/issues)
