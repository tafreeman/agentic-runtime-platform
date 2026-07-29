# Security hardening

This guide covers the security controls built into the FastAPI server and its
tools. It does not replace a deployment threat model, network policy, secret
manager, or incident-response plan.

See [Configuration](../configuration.md) for every setting and
[Known limitations](../KNOWN_LIMITATIONS.md) for remaining gaps.

## Before exposing the server

At minimum:

1. Enable API-key or OIDC authentication.
2. Put TLS and an ingress or API gateway in front of the server.
3. Restrict CORS to the deployed frontend origins.
4. Set a dedicated file-tool root.
5. Keep shell commands disabled unless a reviewed workflow needs them.
6. Register an approval provider before enabling tools with side effects.
7. Keep private-address blocking enabled for HTTP tools.
8. Add gateway-level rate limits for multi-replica deployments.
9. Choose durable, access-controlled storage for runs, replay events, and
   audit records.
10. Decide which prompt, output, trace, and audit fields may be retained.

The defaults support local development. They are not a complete
internet-facing deployment policy.

## Authentication

### API key

Set `AGENTIC_API_KEY` to protect `/api/*` routes:

```dotenv
AGENTIC_API_KEY=<secret-from-your-secret-manager>
```

Clients can send either header:

```http
Authorization: Bearer <key>
```

```http
X-API-Key: <key>
```

The server uses constant-time comparison. When no key is configured and OIDC
is disabled, API routes are open.

The following remain public:

- `/api/health` and paths below it, including `/api/health/ready`
- `/docs`
- `/openapi.json`
- `/redoc`
- `/metrics`, when enabled
- non-API static UI paths

The WebSocket endpoint validates the browser origin and uses the same API key.
Send the key in a header. Query-string WebSocket tokens are rejected.

The key lookup occurs for each request, but changing a running process's
environment is deployment-platform specific. Use a secret provider or restart
strategy that you have tested before relying on live rotation.

### OIDC

OIDC mode validates JWT signatures, issuer, audience, expiry, subject, and the
configured signing-algorithm allowlist.

```dotenv
AGENTIC_OIDC_ENABLED=1
AGENTIC_OIDC_ISSUER=https://identity.example.com/
AGENTIC_OIDC_AUDIENCE=agentic-runtime
AGENTIC_OIDC_JWKS_URL=https://identity.example.com/.well-known/jwks.json
AGENTIC_OIDC_ALGORITHMS=RS256
```

Startup fails if OIDC is enabled without issuer, audience, or JWKS URL.
`AGENTIC_API_KEY` remains a compatibility fallback in OIDC mode.

Keep the signing-algorithm list narrow. Test key rotation, JWKS outage, expired
tokens, incorrect audiences, and clock skew.

## Tenant scope

OIDC-authenticated requests can derive tenant scope from validated tenant or
organization claims. Without OIDC, the compatibility header `X-Tenant-ID`
selects the run and dataset directory.

`X-Tenant-ID` is client supplied. It is not an authorization boundary. Do not
use header-based tenant scope as isolation between untrusted customers.

For multi-tenant deployments:

- derive tenant identity from validated credentials;
- enforce authorization before reading or writing tenant data;
- isolate storage and encryption keys as required;
- test cross-tenant filenames and dataset IDs; and
- include tenant-aware audit review.

## Rate limits and failed-login lockout

The default global limit is `60/minute` per client IP:

```dotenv
AGENTIC_RATE_LIMIT_DEFAULT=60/minute
```

The counter is in-process. Several replicas do not share one limit, and the
address seen by the application may be a proxy unless forwarding is configured
correctly. Enforce the authoritative limit at the ingress or API gateway.

These test and exception flags remove the application limit:

```dotenv
AGENTIC_RATE_LIMIT_DISABLED=1
AGENTIC_DISABLE_RATE_LIMITING=1
```

Do not set them in a normal production deployment. The first disables the
middleware. The second explicitly accepts startup without the optional rate
limit dependency.

Failed API-key authentication is also tracked per IP:

| Setting | Default |
| --- | ---: |
| `AGENTIC_AUTH_LOCKOUT_WINDOW_SECONDS` | `60` |
| `AGENTIC_AUTH_LOCKOUT_THRESHOLD` | `5` |
| `AGENTIC_AUTH_LOCKOUT_DURATION_SECONDS` | `300` |

The threshold-triggering request and later locked requests receive HTTP 429
with `Retry-After`. A successful authentication clears that IP's failure
history. This state is also in-process.

## Request and model-loop sanitization

JSON request bodies pass through sanitization middleware. It can classify
content as clean, requiring approval, redacted, or blocked. Blocked input
returns HTTP 422.

The middleware fails closed when it is unavailable or raises unexpectedly.
`AGENTIC_SANITIZER_FAIL_OPEN=1` bypasses that behavior and should be limited to
isolated diagnosis.

Model-client sanitization is enabled by default:

```dotenv
AGENTIC_SANITIZE_AGENT_LOOP=1
```

This also checks content returned by tools or retrieval before it is sent back
to supported model-client paths. Sanitization reduces risk; it cannot prove
that an instruction is safe or true.

## File, Git, and shell tools

File and Git tools refuse operations until a sandbox root is configured:

```dotenv
AGENTIC_FILE_BASE_DIR=C:\agentic-data
```

Use a dedicated directory that contains no application source, credentials, or
system files. Apply operating-system permissions in addition to the
application path check.

Shell commands are disabled when the allowlist is empty:

```dotenv
AGENTIC_SHELL_ALLOWED_COMMANDS=
```

If a workflow requires shell access, list executable basenames:

```dotenv
AGENTIC_SHELL_ALLOWED_COMMANDS=python,git
```

An allowlist entry permits the executable, not a safe subset of its arguments.
Interpreters and Git can still read, write, execute, or contact remote systems.
Run the server with a restricted OS account and container or host controls.

## HTTP tool and SSRF controls

Private, loopback, link-local, reserved, and known cloud-metadata addresses are
blocked by default:

```dotenv
AGENTIC_BLOCK_PRIVATE_IPS=1
```

The HTTP tools validate DNS results and redirect targets. Metadata addresses
remain blocked even when private-address blocking is disabled.

Application checks cannot replace egress controls. Restrict outbound network
destinations at the firewall, container network, service mesh, or cloud policy.
Set `AGENTIC_BLOCK_PRIVATE_IPS=0` only when a reviewed workflow must contact
internal services and compensating controls are in place.

## Approval gates

A tool call requires approval when any of these is true:

- the tool declares `requires_approval=True`;
- `AGENTIC_REQUIRE_TOOL_APPROVAL=1`; or
- the tool name appears in `AGENTIC_APPROVAL_REQUIRED_TOOLS`.

High-impact built-ins such as command execution, file mutation, and
state-changing HTTP operations require approval by default.

If a gated tool has no registered provider, the call is denied. The default
approval timeout is 1,800 seconds:

```dotenv
AGENTIC_APPROVAL_TIMEOUT_SECONDS=1800
```

The current gate is programmatic. The dashboard does not provide a complete
pause, approve, and resume workflow. Register an `ApprovalProvider` during
application startup and test deny, timeout, provider failure, and duplicate
request behavior.

Do not use `AutoApproveProvider` as a substitute for reviewing whether a tool
needs a gate.

## CORS and browser access

Set only the deployed browser origins:

```dotenv
AGENTIC_CORS_ORIGINS=https://app.example.com
```

Multiple origins are comma-separated. The local defaults include development
ports and should not be reused as a production policy.

CORS controls which browser pages can read responses. It is not authentication,
and it does not restrict non-browser clients.

## Audit, tracing, and metrics

Audit logging is off by default:

```dotenv
AUDIT_LOG_ENABLED=1
AUDIT_LOG_BACKEND=file
AUDIT_LOG_FILE_PATH=C:\agentic-data\audit.jsonl
```

The supported backends are `file` and `redis`. File records are append-only
from the application's perspective, but filesystem administrators can still
change or delete them. Protect, ship, retain, and verify audit records outside
the process.

Tracing and metrics are also opt-in:

```dotenv
AGENTIC_TRACING=1
AGENTIC_TRACE_SENSITIVE=0
AGENTIC_METRICS=1
```

`/metrics` is public so a scraper can reach it. Protect it at the network layer
if metric names or labels are sensitive. Keep sensitive trace content disabled
unless collection and retention have been approved.

## Middleware order

Inbound HTTP requests pass through:

1. CORS
2. global rate limiting
3. request metrics
4. trace-context handling
5. sanitization
6. OIDC or API-key authentication

Some public paths bypass authentication and application rate limiting as
described above. Network controls still apply.

## Verification

Before release, verify the deployed instance rather than only the source
configuration:

- unauthenticated protected route returns 401;
- invalid tokens trigger lockout and `Retry-After`;
- liveness and readiness probes have the intended network exposure;
- unapproved file, shell, and HTTP mutations are denied;
- file traversal and private-address requests are rejected;
- a tenant cannot read another tenant's runs or datasets;
- audit events arrive in durable storage;
- traces omit disallowed content;
- ingress rate limits work across replicas; and
- provider, Redis, and approval-service failures produce the intended response.

Use [Troubleshooting](troubleshooting.md) for diagnostics and
[Deployment](../deployment-guide.md) for the runtime setup.
