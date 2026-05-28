# Troubleshooting

Symptoms and fixes for the most common failure modes when running the platform locally or in production. Organized by component — search for the HTTP status code, exception class, or symptom you're seeing.

For systemic limitations rather than transient failures, see [Known Limitations](../KNOWN_LIMITATIONS.md). For tuning knobs, see [Security Hardening](security-hardening.md) and [Configuration Reference](../configuration.md).

If your symptom isn't here, file an issue at <https://github.com/tafreeman/agentic-runtime-platform/issues>.

---

## Startup failures

### `ConfigurationError: LangChain engine selected but extras not installed`

- **Symptom.** FastAPI server fails to start during lifespan startup; a critical log line names the missing extras and the install hint.
- **Cause.** `AGENTIC_DEFAULT_ADAPTER=langchain` (the default) but `pip install -e ".[langchain]"` was not run in the active environment.
- **Fix.** Either install the extras:
  ```bash
  cd agentic-workflows-v2
  pip install -e ".[langchain]"
  ```
  Or switch to the native engine, which has no optional-deps gate:
  ```bash
  export AGENTIC_DEFAULT_ADAPTER=native
  ```
- **Reference.** [ADR-020](../adr/ADR-020-langchain-adapter-eager-validation.md).

### Server starts but every request returns 503 "sanitization layer not initialized"

- **Symptom.** All `/api/*` responses are HTTP 503.
- **Cause.** The sanitization middleware is fail-closed by design; when its dependencies aren't wired (test app fixtures, partial init), it rejects requests.
- Fix. Production: ensure the sanitization layer is wired into the app factory. Local/test debugging only: AGENTIC_SANITIZER_FAIL_OPEN=1 (note the [2026-05-09 breaking change](../configuration.md#security-and-sandboxing) — only the literal value 1 is accepted now).

### Port already in use (8010 / 5173 / 6006)

- **Symptom.** `uvicorn`, Vite, or Storybook fails to bind with `EADDRINUSE` / `address already in use`.
- **Cause.** Another process is bound to the port.
- **Fix.**
  - PowerShell: `Get-NetTCPConnection -LocalPort 8010 | Select-Object -ExpandProperty OwningProcess | ForEach-Object { Stop-Process -Id $_ -Force }`
  - bash: `lsof -ti:8010 | xargs kill -9`
- **Prevention.** The `port-guard` devex tool detects holders before startup. See `scripts/setup-dev.ps1`.

### `.venv` not found / Python imports fail

- **Symptom.** `ModuleNotFoundError: No module named 'agentic_v2'` or similar.
- **Fix.**
  ```bash
  cd agentic-workflows-v2
  python -m venv .venv
  # PowerShell: .\.venv\Scripts\Activate.ps1
  # bash:       source .venv/bin/activate
  pip install -e ".[dev,server,langchain]"
  ```

---

## Authentication & rate limiting

### HTTP 401 "Invalid or missing API key"

- **Symptom.** Request to `/api/*` rejected with `{"detail": "Invalid or missing API key"}`.
- **Cause.** `AGENTIC_API_KEY` is set on the server, and the request did not include a matching `Authorization: Bearer <key>` or `X-API-Key: <key>` header.
- **Fix.** Send the header. The key value is re-read on every request, so rotating it does not require a restart.
- **Warning.** Each 401 increments a per-IP failure counter — sustained bad-key traffic triggers the lockout (next entry).

### HTTP 429 "Too Many Requests" with `Retry-After` header

Two distinct causes — distinguish by response body and server log.

**Cause A — global rate limit (slowapi).**

- **Identify.** Response body looks like `{"error":"Rate limit exceeded","detail":"60 per 1 minute"}`. No per-IP failure log.
- **Fix.** Reduce client request rate, OR raise `AGENTIC_RATE_LIMIT_DEFAULT` (e.g., `300/minute`). For tests: `AGENTIC_RATE_LIMIT_DISABLED=1`.

**Cause B — auth brute-force throttle.**

- **Identify.** Response body is `{"detail":"Too many authentication failures. Retry after <n> seconds."}` and the server log shows `Authentication failed for /api/... from <ip>` entries leading up to the lockout.
- **Fix.** Wait `AGENTIC_AUTH_LOCKOUT_DURATION_SECONDS` (default 300) or restart the server to clear in-process state. Then submit a successful request — that clears the IP's failure history.
- Tune. [AGENTIC_AUTH_LOCKOUT_* vars](../configuration.md#rate-limiting-and-auth-throttle).

### A legitimate client is locked out

- **Diagnose.** Search server logs: `grep "Authentication failed" logs/*.log | grep <client-ip>`. Confirm the requests were genuinely the locked-out client (not a script with a stale key).
- **Recovery.** Either:
  - Wait for the lockout window to expire, OR
  - Restart the server (lockout state is in-process), OR
  - For sustained operations: raise `AGENTIC_AUTH_LOCKOUT_THRESHOLD` or shorten `AGENTIC_AUTH_LOCKOUT_DURATION_SECONDS`.

### Rate limit feels uneven across replicas

- **Cause.** Rate-limit and lockout state are in-process — each replica counts independently. A client hitting two replicas via a load balancer effectively gets 2× the limit.
- **Fix.** Sprint 2 will introduce Redis-backed shared state. Until then, either pin sticky sessions at the load balancer or accept the multi-replica drift.

---

## WebSocket / streaming

### WebSocket connection rejected with HTTP 403 "origin not allowed"

- **Cause.** The browser sent an `Origin` header that isn't in `AGENTIC_CORS_ORIGINS` or recognized as a localhost loopback.
- **Fix.** Add the deploying frontend's origin to `AGENTIC_CORS_ORIGINS` (comma-separated, no trailing slash).

### WebSocket disconnects mid-run and UI loses state

- **Expected behavior.** The server's 500-event replay buffer should restore state on reconnect.
- **If it doesn't.** Check that the reconnect handshake uses the same `run_id`. Verify the buffer hasn't been evicted (long-running workflows on a low-memory deployment).

---

## Workflow execution

### Workflow stalls indefinitely

- **Expected.** Should not happen since the Sprint 1 timeout watchdog. If the call passes `timeout=N` (per call, not env var) the executor caps total wall time at N seconds.
- **If it stalls anyway.** The route is calling the executor without a `timeout=`. Add a default at the server layer.
- **Reference.** [ADR-019](../adr/ADR-019-dag-executor-top-level-timeout.md).

### Workflow returns `FAILED` with `metadata.timeout_exceeded=True`

- **Cause.** Total wall time exceeded the configured `timeout`.
- **Diagnose.** Inspect per-step durations in the run log — the slow step is the one that didn't finish before cancellation.
- **Fix.** Either raise the timeout for that workflow, or optimize the bottleneck step.

### Steps cascade-skipped after one failure

- **Expected behavior.** When a step fails, all transitive dependents are marked `SKIPPED` via BFS.
- **Find the root cause.** The first step with status `FAILED` in DAG topological order is the trigger. Everything `SKIPPED` downstream is collateral.

### `ValidationError: depends_on` field required

- **Cause.** Sprint 1 made `depends_on` required on `DAGNodeModel` and `WorkflowEditorStep` (was optional with `default=[]`).
- **Fix.** Callers constructing these models from raw dicts must pass `"depends_on": []` explicitly.
- **Reference.** Sprint 1 wire-format extension; see [api-contracts-runtime.md](../api-contracts-runtime.md) and [ADR-014 addendum](../adr/ADR-014-pydantic-wire-format.md).

---

## File and shell tools

### File tool fails with "AGENTIC_FILE_BASE_DIR is not set"

- **Cause.** File tools are fail-closed by design — without an explicit sandbox root, every file operation is rejected.
- **Fix.** Set `AGENTIC_FILE_BASE_DIR` to an absolute path before starting the server. Example: `AGENTIC_FILE_BASE_DIR=/app/data`.

### Shell tool refuses every command with "not in allowlist"

- **Cause.** `AGENTIC_SHELL_ALLOWED_COMMANDS` is empty or unset — all commands disabled.
- **Fix.** Whitelist exactly the basenames the workflow needs:
  ```bash
  export AGENTIC_SHELL_ALLOWED_COMMANDS=ls,cat,python,git
  ```
- **Note.** Absolute paths are resolved to their basename for comparison.

### `CodeExecutionTool` raises during `import os`-style traversal

- **Expected.** The sandbox blocks dangerous imports including `os`, `sys.modules`, `__loader__` traversal.
- **Workaround.** None — the block is intentional. If you genuinely need filesystem or shell access in a code step, use the dedicated file/shell tools with the appropriate allowlist instead.

---

## LLM provider failures

### `No model available for tier <X>` / smart router fails to route

- **Cause.** No provider key configured for the requested tier.
- **Fix.** Configure at least one provider key:
  - OpenAI: `OPENAI_API_KEY`
  - Anthropic: `ANTHROPIC_API_KEY`
  - Gemini: `GEMINI_API_KEY`
  - Azure OpenAI: `AZURE_OPENAI_API_KEY_0` + `AZURE_OPENAI_ENDPOINT_0`
  - GitHub Models (free tier): `GITHUB_TOKEN`
- **Zero-key dev.** `AGENTIC_NO_LLM=1` installs deterministic placeholders so the engine runs end-to-end without credentials. Structured parsers and evaluation still need real keys.

### Azure OpenAI returns 429 / quota exceeded

- **Cause.** Hit the configured slot's rate limit.
- **Fix.** Configure additional numbered slots — `AZURE_OPENAI_API_KEY_1`, `AZURE_OPENAI_ENDPOINT_1`, etc. The router falls back through them automatically.

### Anthropic / OpenAI returns 401

- **Fix.** Verify the key value (don't paste with leading/trailing whitespace). Confirm the key is active in the provider console. Check that the provider's organization/project allows the model you requested.

---

## Tracing and observability

### No spans appear in Jaeger / Tempo / your OTEL collector

- **Checklist.**
  1. `AGENTIC_TRACING=1` is set in the server process environment.
  2. `OTEL_EXPORTER_OTLP_ENDPOINT` points to a reachable collector. Default is `http://localhost:4317` (gRPC).
  3. If using HTTP, set `OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf` and the endpoint suffix `:4318/v1/traces`.
  4. Network: the collector port is reachable from the server (firewalls, K8s services).
- **Verify.** With `AGENTIC_TRACING=1`, the server emits "OTEL tracing enabled" at startup.

### Sensitive content missing from spans

- **Cause.** By default, prompts/outputs/tool args are excluded from spans.
- **Fix.** `AGENTIC_TRACE_SENSITIVE=1`. Only enable in trusted environments — those values can carry PII.

---

## Windows-specific

### `npx <command>` fails or hangs

- **Cause.** `npx` is unreliable on Windows PATH.
- **Fix.** Use `npm run <script>` or `npm exec -- <command>` instead. Pre-commit and project scripts have been adapted accordingly.

### Path errors with backslashes in Python tools

- **Fix.** Use forward slashes or `pathlib.Path` for cross-platform paths. The codebase already follows this convention — third-party code that doesn't is the usual culprit.

### `pnpm` fails with EPERM on a mounted/shared drive

- **Fix.** Fall back to `npm`. This is a well-known pnpm limitation on Windows network mounts.

### PowerShell scripts mangled in Git Bash

- **Cause.** `$_` and `$_.Property` interact badly with bash extglob.
- **Fix.** Invoke PowerShell with explicit profile/quoting: `powershell.exe -NoProfile -Command '...'` using single quotes.

---

## Frontend / UI

### `npm run build` fails with TypeScript errors after Pydantic changes

- **Cause.** The wire-format drift gate caught a Python/TypeScript mismatch.
- **Fix.** Regenerate the TypeScript mirrors:
  ```bash
  cd agentic-workflows-v2
  python -m scripts.generate_ts_types
  cd ui
  npm run generate:types
  npm run build
  ```
- **Reference.** [ADR-014](../adr/ADR-014-pydantic-wire-format.md) and the `wire-format-drift` CI job.

### Storybook fails with "Cannot find @storybook/addon-actions"

- **Cause.** Not installed by default in this project.
- **Fix.** Use the project's stand-in: `const action = (name) => (...args) => console.log(name, ...args)`. Don't add the addon unless the team agrees.

### Vite dev server resolves `.js` imports but the production build fails

- **Cause.** Rollup (production) doesn't auto-resolve `.js` to `.ts` like Vite dev does.
- **Fix.** When renaming `.js` → `.ts`, update every explicit `.js` import path or the production build will break.

---

## CI / pre-commit

### Pre-commit `detect-secrets` flags a file

- **Diagnose.** If the flagged content is a real secret: rotate it immediately, then sanitize history. If it's a false positive: review carefully, then add to the `.secrets.baseline` with `detect-secrets scan --baseline .secrets.baseline`.
- **Never** disable the hook to push past it.

### `ruff check` fails on changed files locally but green on main

- **Cause.** You may have a stale ruff cache or are running an older version.
- **Fix.** `pip install -U ruff` and re-run. Pre-commit hooks pin their own ruff version — `pre-commit autoupdate` syncs it.

### `mkdocs build --strict` fails in the docs CI job

- **Common causes.**
  - Broken intra-doc markdown link (target file moved/renamed without updating the link).
  - A new page added to nav but the file doesn't exist.
  - A new `.md` was committed that links to `../<file>.md` — mkdocs reads relative to the docs root, not the repo root.
- **Fix.** Re-run locally: `mkdocs build --strict`. Address each WARNING. The "first revision timestamp" warning from the git-revision plugin is benign for newly-committed files.

---

## See also

- [Configuration Reference](../configuration.md) — full env var catalog
- [Security Hardening](security-hardening.md) — production tuning knobs
- [Known Limitations](../KNOWN_LIMITATIONS.md) — caveats that aren't bugs
- [Architecture: Runtime](../architecture-runtime.md) — what's actually happening when a request hits the server
- File an issue: <https://github.com/tafreeman/agentic-runtime-platform/issues>
