# Security Hardening

This page is for **production operators** deploying the Agentic Workflows V2 FastAPI server.
It describes every in-process security control, its environment-variable knobs, its default
behavior, and practical recipes for tuning it to your environment.

**This page is NOT** an ADR, a code specification, or a threat model. For decision rationale
see the linked ADRs; for the formal threat model see
[`docs/OWASP_LLM_THREAT_MODEL.md`](../OWASP_LLM_THREAT_MODEL.md). For the complete env-var
index see the [Configuration Reference](../configuration.md).

---

## At a glance

| Control | Environment variable(s) | Default | Sprint 1 reference |
|---------|------------------------|---------|-------------------|
| API key authentication | `AGENTIC_API_KEY` | Not set — all routes open | ADR-018 |
| Global rate limiting | `AGENTIC_RATE_LIMIT_DEFAULT`, `AGENTIC_RATE_LIMIT_DISABLED` | `60/minute` per IP | ADR-018 |
| 401 brute-force throttle — window | `AGENTIC_AUTH_LOCKOUT_WINDOW_SECONDS` | `60` seconds | ADR-018 |
| 401 brute-force throttle — threshold | `AGENTIC_AUTH_LOCKOUT_THRESHOLD` | `5` failures | ADR-018 |
| 401 brute-force throttle — lockout | `AGENTIC_AUTH_LOCKOUT_DURATION_SECONDS` | `300` seconds | ADR-018 |
| DAG workflow timeout | No env var — set per call via `timeout` kwarg | None (unlimited) | ADR-019 |
| Adapter eager validation | `AGENTIC_DEFAULT_ADAPTER` | `langchain` | ADR-020 |
| Filesystem sandbox | `AGENTIC_FILE_BASE_DIR` | Not set — file tools refuse all operations | — |
| Shell tool allowlist | `AGENTIC_SHELL_ALLOWED_COMMANDS` | Not set — all shell commands disabled | — |
| Sanitization fail-closed | `AGENTIC_SANITIZER_FAIL_OPEN` | Not set — 503 returned when layer unavailable | — |
| CORS origins | `AGENTIC_CORS_ORIGINS` | localhost dev ports (5173, 8000, 8010) | — |
| Block private IPs in HTTP tool | `AGENTIC_BLOCK_PRIVATE_IPS` | Not set — private IPs allowed | — |

---

## 1. API key authentication

### How it works

When `AGENTIC_API_KEY` is set in the environment, the `APIKeyMiddleware` (layer 3 in the
middleware stack, see §Middleware order below) gates every request whose path starts with
`/api/`. The key must be supplied via one of two headers:

```http
Authorization: Bearer <key>
```
```http
X-API-Key: <key>
```

Token comparison uses `secrets.compare_digest()` to prevent timing side-channel attacks.
The key is **re-read from the environment on every request** (via `_get_api_key()` →
`get_secret("AGENTIC_API_KEY")`). This means you can rotate the key without restarting the
server — new requests will immediately use the updated value.

When `AGENTIC_API_KEY` is **not set**, the middleware is a no-op and all routes are publicly
accessible. The server logs a warning at startup:

```
WARNING: AGENTIC_API_KEY is not set — all API routes are publicly accessible.
```

!!! warning "Never run without a key in internet-exposed environments"
    A server without `AGENTIC_API_KEY` accepts unauthenticated workflow runs, which may
    execute arbitrary LLM calls against your provider quotas.

### Public path exemptions

The following paths bypass authentication regardless of whether a key is set:

- `/api/health`
- `/docs`
- `/openapi.json`
- `/redoc`

All other paths under `/api/` require a valid key. Non-API routes (UI static files, WebSocket
upgrade) also bypass authentication so the React frontend can load without credentials.

### WebSocket origin validation

WebSocket connections go through a separate origin check (`is_websocket_origin_allowed()`).
A connection is allowed when any of the following is true:

- The `Origin` header is absent (non-browser clients such as curl or SDK calls).
- The origin matches the HTTP `Host` header of the request exactly.
- The origin hostname is `localhost`, `127.0.0.1`, or `::1` (any port — Vite dev server uses
  dynamic ports).
- The origin appears in the `AGENTIC_CORS_ORIGINS` allowlist (see §9).

### Recipe: rotate the key without a restart

```bash
# Update the secret in your environment manager (e.g., Kubernetes secret, AWS Secrets Manager)
# then export in the server's process environment.  No restart needed — auth.py reads the
# env var on every request.
export AGENTIC_API_KEY="$(openssl rand -hex 32)"
```

Because the key is re-read per request, the old key stops working the moment the environment
variable changes. Brief request-level races (in-flight requests that already read the old key
at header extraction) complete normally; the new key is enforced on the next request.

---

## 2. Global rate limiting

### How it works

The server uses [slowapi](https://github.com/laurentS/slowapi) for per-IP global rate limiting.
`slowapi` is built on the `limits` library and is applied at the **outermost middleware layer**
(layer 1), before auth and sanitization, so abusive clients are rejected before any auth work
is done.

The key function is `remote_address` — the client's IP as seen by the server process. Every
unique IP is tracked independently in an in-process memory store.

**Default limit:** `60/minute` per IP. Configurable via `AGENTIC_RATE_LIMIT_DEFAULT`.

**Response on breach:**

```http
HTTP/1.1 429 Too Many Requests
Retry-After: <seconds-to-next-window>
Content-Type: application/json

{"detail": "Rate limit exceeded: <detail>"}
```

**Public paths are exempt.** `/api/health`, `/docs`, `/openapi.json`, and `/redoc` return
`None` from the key function, which instructs slowapi to skip enforcement.

### Disabling for tests

```bash
AGENTIC_RATE_LIMIT_DISABLED=1 python -m uvicorn agentic_v2.server.app:app ...
```

!!! warning "Do not disable in production"
    `AGENTIC_RATE_LIMIT_DISABLED=1` removes all per-IP rate gating. Use only in isolated
    test environments.

### Middleware order

The server middleware stack (outermost to innermost, i.e., the order in which an inbound
request passes through each layer) is:

```
1. SlowAPIMiddleware        — global per-IP rate limit
2. SanitizationASGIMiddleware — prompt-injection / secret redaction
3. APIKeyMiddleware         — bearer-token auth + per-IP 401 throttle
4. CORSMiddleware           — CORS preflight / header injection
```

`app.add_middleware` prepends each layer, so the first `add_middleware` call (CORS) becomes
the innermost layer and the last call (SlowAPI) becomes the outermost.

### Tuning recipes

**Low-traffic development environment:**

```bash
AGENTIC_RATE_LIMIT_DEFAULT=200/minute
```

Relaxes the cap to avoid friction during development while still exercising the rate-limit
code path.

**High-traffic production behind a load balancer:**

```bash
AGENTIC_RATE_LIMIT_DEFAULT=120/minute
```

!!! warning "Multi-replica caveat"
    The rate-limit counter is in-process. In a multi-replica deployment behind a load
    balancer, each replica tracks only the requests it receives. The effective per-IP rate
    cap is `N × configured_limit` where `N` is the number of replicas. A caller can bypass
    the limit by distributing requests across replicas.

    The planned Sprint 2 Redis migration will replace the in-process store with a shared
    counter, making the limit cluster-wide. Until then, enforce rate limiting at the ingress
    / API-gateway layer for multi-replica deployments.

    See [KNOWN_LIMITATIONS.md §4.3](../KNOWN_LIMITATIONS.md#41-rate-limiting-is-in-process-only).

!!! note "Reference"
    See [ADR-018](../adr/ADR-018-api-rate-limiting-and-auth-throttle.md) for the design
    rationale and the Sprint 2 Redis migration plan.

---

## 3. 401 brute-force throttle (AuthThrottle)

### How it works

`AuthThrottle` (in `server/auth.py`) tracks failed authentication attempts per client IP
using monotonic timestamps. It is integrated into `APIKeyMiddleware` and runs at layer 3.

**Sliding window:** Only failures within the last `AGENTIC_AUTH_LOCKOUT_WINDOW_SECONDS`
seconds count toward the threshold. Failures older than the window are evicted on the next
request from that IP.

**Defaults (verified against `server/auth.py`):**

| Parameter | Default | Override |
|-----------|---------|----------|
| Sliding window | `60` seconds | `AGENTIC_AUTH_LOCKOUT_WINDOW_SECONDS` |
| Failure threshold | `5` failures | `AGENTIC_AUTH_LOCKOUT_THRESHOLD` |
| Lockout duration | `300` seconds | `AGENTIC_AUTH_LOCKOUT_DURATION_SECONDS` |

### Lockout semantics

When an IP reaches the threshold, the `AuthThrottle` sets a `locked_until` timestamp. Every
subsequent request from that IP — including the threshold-triggering request — receives:

```http
HTTP/1.1 429 Too Many Requests
Retry-After: <remaining-lockout-seconds>
Content-Type: application/json

{
  "detail": "Too many failed authentication attempts. Please retry later.",
  "retry_after": <remaining-lockout-seconds>
}
```

The lockout is checked **before** credential verification. Locked IPs are rejected before
the server even reads the `Authorization` or `X-API-Key` header, so lockout cannot be
cleared by supplying a correct key during the lockout period.

**Successful authentication clears the failure counter.** A valid key from a previously
failing IP resets its failure history entirely.

### Eviction

The `_evict_expired()` method cleans up state entries lazily on each request — no background
task is needed. An IP's entry is removed when its lockout has expired **and** its failure
window has also expired.

### In-process limitation

!!! warning "Multi-replica caveat"
    `AuthThrottle` state is per-process. In a multi-replica deployment, a distributed
    attacker who spreads probes across replicas can stay under each replica's threshold while
    collectively exceeding the intended lockout threshold.

    See [KNOWN_LIMITATIONS.md §4.4](../KNOWN_LIMITATIONS.md#42-per-ip-auth-throttle-shares-the-same-multi-replica-caveat).
    Sprint 2 will migrate to a Redis-backed shared store.

### Recipe: investigate a locked-out client

The server logs a warning for every lockout event and every rejected locked-IP request:

```
WARNING: Auth throttle: IP 203.0.113.42 locked out for 300 seconds after 5 failures
WARNING: Auth throttle: rejecting locked IP 203.0.113.42 (retry after 287s)
```

To find lockout events for a specific IP:

```bash
# journalctl / docker logs / file log depending on your deployment
grep "locked out\|locked IP" server.log | grep "203.0.113.42"
```

Authentication failures (before lockout) are also logged:

```
WARNING: Authentication failed for /api/workflows/run from 203.0.113.42
```

### Recipe: lowering thresholds for high-value endpoints

The threshold and lockout duration currently apply globally across all endpoints. If you
need tighter thresholds, lower the environment variables:

```bash
AGENTIC_AUTH_LOCKOUT_WINDOW_SECONDS=30
AGENTIC_AUTH_LOCKOUT_THRESHOLD=3
AGENTIC_AUTH_LOCKOUT_DURATION_SECONDS=900
```

!!! note
    Per-endpoint throttle granularity is listed as future work in
    [ADR-018](../adr/ADR-018-api-rate-limiting-and-auth-throttle.md). Today the
    configuration is global.

---

## 4. DAG workflow timeout

### Where it applies

`DAGExecutor.execute(workflow, ..., timeout=N)` accepts an optional `timeout` parameter
(seconds, float). When set, the entire scheduling loop is wrapped with
`asyncio.wait_for(scheduling_loop(), timeout=N)`.

There is **no environment variable** for the default timeout. The value is set per call by
the server route layer. Today this means you configure it by adjusting the route-level
call site — it is not a startup configuration knob.

### What happens on timeout

When the timeout elapses:

1. All in-flight `asyncio.Task` objects for running steps are cancelled
   (`task.cancel()`) and awaited to prevent "Task was destroyed but it is pending" warnings.
2. Every step still in `RUNNING` state is transitioned to `FAILED` with `error_type:
   "TimeoutError"` and a descriptive message.
3. All transitive dependents of those failed steps are cascade-skipped via BFS (the same
   propagation used for step-level failures).
4. Steps that never started are also skipped.
5. The returned `WorkflowResult` has `overall_status=FAILED`.
6. `result.metadata` contains:
   ```python
   {"timeout_exceeded": True, "timeout_seconds": <N>, "error": "<message>"}
   ```

**OTEL attributes** emitted on the active span:

```
workflow.timeout_exceeded = True
workflow.timeout_seconds = <N>   # on the span event "workflow.timeout"
```

These attributes are queryable in Jaeger/Tempo dashboards to identify timed-out runs.

### Relationship to per-step timeouts

The workflow-level timeout and per-step timeouts in `StepExecutor` are **additive, not
mutually exclusive**. Both can be active simultaneously:

- A step's individual timeout fires if that step alone runs too long.
- The workflow timeout fires if the cumulative execution across all steps (including
  dependencies and waiting time) exceeds the ceiling.

Set a tight per-step budget for individual agent calls and a looser workflow ceiling as a
backstop.

### Tuning guidance

A reasonable starting point:

```
workflow_timeout = longest_legitimate_single_workflow_duration × 1.5
```

For example, if your most complex workflow takes about 4 minutes under normal conditions,
set a 6-minute (360 second) timeout. This gives headroom for provider latency spikes while
still bounding runaway workflows.

!!! note
    Cooperative cancellation via `asyncio.wait_for` depends on `await` points in step
    bodies. A tightly-looping synchronous step may not cancel promptly. If you have steps
    with synchronous-heavy bodies, consider adding explicit cancellation checkpoints.

!!! note "Reference"
    See [ADR-019](../adr/ADR-019-dag-executor-top-level-timeout.md) for the design rationale
    and the follow-on task to expose `timeout` as a first-class `execution_profile` HTTP field.

---

## 5. Adapter eager validation

### How it works

`AGENTIC_DEFAULT_ADAPTER` selects which execution engine the server validates at startup.
The default is `langchain`.

During the FastAPI lifespan startup sequence, `AdapterRegistry.validate_selected(name)` is
called. For the `langchain` adapter, this immediately attempts to import `langchain` and
`langgraph`. If either import fails (the optional extras are not installed), a
`ConfigurationError` is raised:

```
ConfigurationError: LangChain engine selected but extras not installed.
Install with: pip install -e '.[langchain]'
```

uvicorn logs the error and **exits with a non-zero code**. The server does not start, and
no requests are served. This fail-fast behavior is intentional — a misconfigured deployment
fails at boot rather than mid-workflow.

For `AGENTIC_DEFAULT_ADAPTER=native` (and any other adapter value that is not `langchain`),
`validate_selected()` is a no-op.

### Recipe: deploy with native engine only (no LangChain extras)

```bash
AGENTIC_DEFAULT_ADAPTER=native
```

Set this when:

- You have not installed the `[langchain]` extras.
- You want to minimize the dependency footprint.
- All workflows in your deployment explicitly specify `adapter: native`.

!!! warning
    Setting `AGENTIC_DEFAULT_ADAPTER=native` bypasses the LangChain check but does not
    prevent workflows from requesting the `langchain` adapter at run time. If a workflow
    request specifies `adapter: langchain` and the extras are absent, the error surfaces at
    request time rather than boot time.

!!! note "Reference"
    See [ADR-020](../adr/ADR-020-langchain-adapter-eager-validation.md) for the rationale
    and the CLI pre-flight check planned as a follow-on.

---

## 6. Filesystem sandboxing

### AGENTIC_FILE_BASE_DIR

The `file_ops` built-in tool uses this variable to establish a sandbox root. All file
operations are resolved relative to this directory, and any attempt to traverse outside it
(e.g., via `../`) is rejected at the validator boundary.

!!! warning "Fail-closed"
    When `AGENTIC_FILE_BASE_DIR` is **not set**, all file tool operations are refused. File
    tools will return an error on every call until this variable is configured.

    Operators who need file operations **must** set this variable. Leaving it unset is the
    safe default — no accidental file access can occur.

**Recommended value:** a dedicated, isolated directory that the server process can write to
and that does not contain sensitive system files or application secrets.

```bash
# Container deployments
AGENTIC_FILE_BASE_DIR=/app/data

# Bare-metal / VM deployments
AGENTIC_FILE_BASE_DIR=/var/lib/agentic/data
```

Ensure the directory:

- Exists and is writable by the server process user.
- Does not overlap with application code, secrets, or system directories.
- Has appropriate filesystem-level permissions (mode `700` or `750` for the server user).

---

## 7. Shell tool allowlist

### AGENTIC_SHELL_ALLOWED_COMMANDS

The `shell_ops` built-in tool executes shell commands inside the server process. By default
(when the variable is not set or is empty), **all shell commands are disabled**.

!!! warning "Fail-closed"
    An empty or missing `AGENTIC_SHELL_ALLOWED_COMMANDS` means no shell commands can run.
    This is the safe default.

When set, the value is a comma-separated list of command **basenames** (the executable name
without path). Only commands whose basename appears in this list are allowed to execute.

```bash
# Disable entirely (default — omit the variable or set it to empty)
AGENTIC_SHELL_ALLOWED_COMMANDS=

# Allow only specific commands
AGENTIC_SHELL_ALLOWED_COMMANDS=ls,cat,python,git
```

!!! tip "Minimum set for code-execution workflows"
    The following covers most code-execution workflow patterns while keeping the attack
    surface narrow:
    ```bash
    AGENTIC_SHELL_ALLOWED_COMMANDS=ls,cat,python,git
    ```
    Add additional commands only when a specific workflow requires them. Never include
    interpreters (`bash`, `sh`, `zsh`) unless the workflow explicitly requires a shell
    runner and you have reviewed the associated risk.

---

## 8. Sanitization middleware

### How it works

`SanitizationASGIMiddleware` (layer 2 in the middleware stack) inspects the JSON body of
every inbound request. It applies the `SanitizationMiddleware` instance stored in
`app.state.sanitization` (initialized in the FastAPI lifespan with `dry_run=False`).

Classification outcomes:

| Classification | Action |
|---------------|--------|
| `clean` | Request passes through unmodified. |
| `requires_approval` | Request passes through unmodified (advisory only in current release). |
| `redacted` | Request body replaced with sanitized text before passing downstream. |
| `blocked` | `422 Unprocessable Entity` returned immediately. |

### Fail-closed behavior

!!! warning "Fail-closed by default"
    When the sanitization layer fails to initialize (or is explicitly `None`), the middleware
    returns `503 Service Unavailable` unless `AGENTIC_SANITIZER_FAIL_OPEN=1` is set.

    On any unexpected exception during sanitization processing, the middleware returns
    `500 Internal Server Error` rather than passing the request through unsanitized.

    Only JSON bodies (`Content-Type: application/json`) are inspected. All other content
    types pass through unchanged.

### AGENTIC_SANITIZER_FAIL_OPEN

!!! warning "BREAKING CHANGE (2026-05-09)"
    Only the string `"1"` is recognized as enabling fail-open. Previous versions accepted
    `"true"`, `"yes"`, and other truthy strings. If your deployment scripts set
    `AGENTIC_SANITIZER_FAIL_OPEN=true`, update them to `AGENTIC_SANITIZER_FAIL_OPEN=1`.

Setting `AGENTIC_SANITIZER_FAIL_OPEN=1` causes the middleware to pass requests through
when the sanitization layer is unavailable or encounters an error, rather than returning
`503`/`500`.

!!! warning "Not for production"
    `AGENTIC_SANITIZER_FAIL_OPEN=1` disables the prompt-injection and secret-redaction
    safety net when the sanitization layer is unavailable. Use only for debugging in
    isolated environments. **Do not set this in production.**

### Recipe: legacy debugging mode

```bash
# Temporarily enable fail-open to diagnose sanitization startup failures
AGENTIC_SANITIZER_FAIL_OPEN=1 python -m uvicorn agentic_v2.server.app:app ...
# After diagnosing, remove the variable and fix the root cause.
```

---

## 9. CORS

### AGENTIC_CORS_ORIGINS

Controls which browser origins the server includes in `Access-Control-Allow-Origin` response
headers (via FastAPI's `CORSMiddleware`, the innermost middleware layer).

**Default origins (when `AGENTIC_CORS_ORIGINS` is not set):**

```
http://localhost:5173
http://127.0.0.1:5173
http://localhost:8000
http://127.0.0.1:8000
http://localhost:8010
http://127.0.0.1:8010
```

These defaults cover the local Vite dev server and common local API ports. They are not
appropriate for production.

!!! warning "Production deployments must restrict CORS origins"
    Set `AGENTIC_CORS_ORIGINS` to the actual frontend origin(s) in every production
    deployment. Leaving the default allows any localhost browser session to make
    credentialed cross-origin requests.

```bash
# Single frontend origin
AGENTIC_CORS_ORIGINS=https://app.example.com

# Multiple origins (comma-separated, no spaces)
AGENTIC_CORS_ORIGINS=https://app.example.com,https://admin.example.com
```

### WebSocket origin validation

WebSocket origin validation reuses the same `AGENTIC_CORS_ORIGINS` allowlist via
`get_allowed_origins()`. Additionally, any `localhost` or `127.0.0.1` origin (any port) is
always allowed for WebSocket connections — the Vite dev server starts on dynamic ports
(5173, 5174, …) so they cannot be enumerated statically.

Non-browser clients that omit the `Origin` header are always allowed for WebSocket
connections.

---

## 10. HTTP tool SSRF protection

### AGENTIC_BLOCK_PRIVATE_IPS

The `http_ops` built-in tool (and `langchain/tools.py`) make outbound HTTP requests
during workflow execution. As of P1 #13, **SSRF protection is enabled by default** and
covers:

- Private/loopback/link-local/reserved IP literals (RFC 1918, RFC 4193, etc.)
- DNS names: all returned addresses are resolved and checked — a hostname that resolves to
  a private address is blocked even if it looks public.
- Cloud metadata endpoints: `169.254.169.254`, `fd00:ec2::254`, `100.100.100.200`,
  `metadata.google.internal` are always blocked regardless of the flag.
- Redirect re-validation: each redirect hop is validated before following (max 5 hops).
- IPv4-mapped IPv6 (`::ffff:127.0.0.1`) is normalised before checking.

!!! warning "SSRF defense"
    In environments where the server process has network access to internal services
    (databases, metadata APIs, internal dashboards), an unauthenticated or malicious
    workflow could exploit the HTTP tool to make requests to those services. The SSRF guard
    is **on by default** — this is a security-critical default. Do not disable it without
    applying compensating controls.

```bash
# On by default — opt out only with explicit justification
# AGENTIC_BLOCK_PRIVATE_IPS=0  # disables private-IP blocking (NOT recommended)
```

Set `AGENTIC_BLOCK_PRIVATE_IPS=0` only when workflows legitimately need to reach internal
network endpoints and you have applied other controls (network policy, service mesh
authorization) to restrict which internal addresses the server can reach. Note that
cloud metadata endpoints (`169.254.169.254` etc.) remain blocked even when the flag
is set to `0`.

---

## Reference deployment posture

The following block represents the minimum recommended configuration for a hardened,
internet-exposed production instance. Copy and adapt it to your environment.

```bash
# ── Authentication ────────────────────────────────────────────────────────────
# Generate with: openssl rand -hex 32
AGENTIC_API_KEY=<32-byte-random-hex>

# ── CORS ─────────────────────────────────────────────────────────────────────
AGENTIC_CORS_ORIGINS=https://app.example.com

# ── Filesystem sandbox ────────────────────────────────────────────────────────
AGENTIC_FILE_BASE_DIR=/app/data

# ── Shell tool ────────────────────────────────────────────────────────────────
# Empty = all shell commands disabled (recommended unless workflows require shell)
AGENTIC_SHELL_ALLOWED_COMMANDS=

# ── Engine ───────────────────────────────────────────────────────────────────
# Use native engine to avoid LangChain extras requirement.
# Remove or set to langchain if LangChain extras are installed.
AGENTIC_DEFAULT_ADAPTER=native

# ── SSRF defense (default ON — no action required for production) ────────────
# AGENTIC_BLOCK_PRIVATE_IPS is True by default. Unset or set to 1 to keep the
# default. Set to 0 only if workflows must reach internal services and
# compensating network controls are in place.
# AGENTIC_BLOCK_PRIVATE_IPS=0  # opt-out — not recommended

# ── Rate limiting ─────────────────────────────────────────────────────────────
# Tune based on expected traffic. Lower for higher-security, lower-traffic
# environments. Raise with caution — in-process only, see §2.
AGENTIC_RATE_LIMIT_DEFAULT=30/minute

# ── Auth brute-force throttle ─────────────────────────────────────────────────
# Window (seconds), threshold (failures), lockout (seconds)
# Defaults are 60 / 5 / 300; values below are more aggressive for production.
AGENTIC_AUTH_LOCKOUT_WINDOW_SECONDS=60
AGENTIC_AUTH_LOCKOUT_THRESHOLD=5
AGENTIC_AUTH_LOCKOUT_DURATION_SECONDS=600

# ── Sanitization ──────────────────────────────────────────────────────────────
# Leave AGENTIC_SANITIZER_FAIL_OPEN unset (fail-closed is the safe default).
# AGENTIC_SANITIZER_FAIL_OPEN=   # do not set

# ── Observability ─────────────────────────────────────────────────────────────
AGENTIC_TRACING=1
OTEL_EXPORTER_OTLP_ENDPOINT=http://otel-collector:4317
```

!!! tip "Secret generation"
    Use a cryptographically strong random value for `AGENTIC_API_KEY`:
    ```bash
    openssl rand -hex 32
    ```
    Store it in your secret manager (AWS Secrets Manager, Vault, Kubernetes Secret) and
    inject it at runtime — never commit it to the repository.

---

## See also

- [Configuration Reference](../configuration.md) — full environment variable index with types,
  defaults, and accepted values
- [ADR-018](../adr/ADR-018-api-rate-limiting-and-auth-throttle.md) — rate limiting and auth
  throttle design rationale, Sprint 2 Redis migration plan
- [ADR-019](../adr/ADR-019-dag-executor-top-level-timeout.md) — DAG executor top-level timeout
  watchdog design
- [ADR-020](../adr/ADR-020-langchain-adapter-eager-validation.md) — LangChain adapter eager
  validation at startup
- [KNOWN_LIMITATIONS.md](../KNOWN_LIMITATIONS.md) — in-process caveats, multi-replica
  behavior (§4.3, §4.4), and deferred Sprint 2 work
- [Troubleshooting](troubleshooting.md) — common failure modes and diagnostic recipes
- [Deployment Guide](../deployment-guide.md) — CI/CD pipeline, Docker, environment setup,
  and production observability checklist
