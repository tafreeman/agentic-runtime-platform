# Known Limitations

> **Audience:** Operators, auditors, and contributors reading failing CI or trying to understand why something "works but not quite."
> **Outcome:** After reading, you know what is intentionally unfinished and what the next sprint is expected to address.
> **Last verified:** 2026-07-18

This is an honest accounting. Every item here is real, reproducible, and has shipped into the current release. Nothing here is a guess. If you find a new limitation, add it — do not paper over it elsewhere.

Each item includes a **Status** (reflecting how we're treating it today) and an **Upstream fix** field pointing at the relevant ticket, workaround, or follow-up.

> **Note on item IDs:** entries below cite the Sprint 1 story IDs (`S1-n`) they shipped under. [`ROADMAP.md`](ROADMAP.md) tracks the same work under the two-sprint plan's T-series IDs — e.g. S1-1 = T1-1 (wire-format gate extension), S1-2 = T1-4 (rate limiting + auth throttle), S1-6 = T3-2 (eager adapter validation).

---

## 1. Typed gates that are not fully enforced

### 1.1 Python ↔ TypeScript wire format is manually mirrored (partial)

`agentic_v2/contracts/events.py` defines the execution-event discriminated union in Python; `ui/src/api/types.ts` mirrors it by hand. Drift is caught by reviewer eyeball, not by automation.

Sprint 1 (S1-1 / ROADMAP T1-1) added four HTTP response shapes to the schema-drift CI gate — `DAGResponse`, `WorkflowInputSchemaResponse`, `WorkflowEditorStep`, and `RunsSummaryResponse` — joining the previously covered `ExecutionEvent` and `StepResultRecord` for six gated shapes in total. These six shapes have committed JSON schema snapshots under `tests/schemas/` and the gate regenerates them in CI. Other endpoint payloads (beyond these six) remain hand-mirrored without an automated drift check.

- **Surface:** Any new event field in the uncovered endpoints requires an edit in both files.
- **Risk:** Silent shape mismatches between backend emit and frontend decode for endpoints not yet covered by the drift gate.
- **Workaround:** When editing `contracts/events.py` or `server/models.py`, grep `ui/src/api/types.ts` for the type name and update in the same PR.
- **Status:** Partially resolved by S1-1 (six shapes now gated). Remainder ratified as manual in [ADR-014](adr/ADR-014-pydantic-wire-format.md).
- **Upstream fix:** Future sprint — extend gate coverage to remaining endpoint payloads.

### 1.2 The 80% coverage gate scopes out optional provider/plugin surfaces

The `--cov-fail-under=80` gate measures the core runtime only. By design, `[tool.coverage.run] omit` in `agentic-workflows-v2/pyproject.toml` excludes optional provider and plugin surfaces from the gated number — notably the **LangChain adapter** (`agentic_v2/langchain/*`), the **model backends/router** (`agentic_v2/models/*`), MCP integrations, and CLI/prompt scaffolding.

- **Why:** These surfaces require external services or extras installs and are exercised by their own targeted suites rather than the core unit run, so folding them into the gated percentage would make the number reflect provider availability rather than core-code health.
- **Surface:** The "coverage gate 80%+" badge therefore reflects core coverage, not whole-repo coverage. The LangChain adapter and model router are tested, but not inside the gated figure — explicitly, `agentic_v2/langchain/tools.py` (the LangChain adapter's own approval-gate re-implementation, see §4.3) and `agentic_v2/models/backends_base.py` / `backends_cloud.py` / `backends_local.py` (per-provider format translation) are listed individually by name in the coverage `omit` array (not merely swept in by a glob) and covered only by their own targeted suites, not the gated 80% figure.
- **Status:** Intentional. Documented here so the badge is not read as a whole-repo claim.
- **Visibility:** CI now publishes a separate ungated `whole-repo-coverage` artifact across the runtime, eval package, and shared tools using the same fast test selection without the core-only coverage omit list.
- **Upstream fix:** Future sprint — decide whether any optional surface should move from visibility-only reporting into a blocking gate.

---

## 2. API quirks

### 2.1 LangChain adapter requires a separate extras install

Running `agentic run <workflow> --adapter langchain` requires that the package was installed with the `[langchain]` extras:

```bash
pip install -e ".[dev,server,langchain]"
```

A bare `pip install -e ".[dev,server]"` will succeed, but any `--adapter langchain` call fails at import time.

- **Surface:** `agentic_v2/langchain/` imports are guarded with `try/except ImportError`.
- **Risk:** Confusing first-run failure if a contributor installed minimal extras.
- **Workaround:** Install with `langchain` extras (included in `just setup`), or pass `--adapter native` explicitly.
- **Status:** The _late_ error has been resolved by S1-6: `AdapterRegistry.validate_selected()` now runs at FastAPI lifespan startup and raises `ConfigurationError` with an install hint before any request is processed. The optional-extras design is still correct; only the error timing improved. See [ADR-020](adr/ADR-020-langchain-adapter-eager-validation.md).
- **Upstream fix:** None further needed for the server path. CLI `agentic run --adapter langchain` surfaces the error at adapter resolution time (outside the FastAPI lifespan); may benefit from an explicit pre-flight check in a future sprint.

---

## 3. CI and environment dependencies

### 3.1 Placeholder mode exists but CI still validates provider integration

The runtime supports `AGENTIC_NO_LLM=1` for deterministic placeholder execution across both native and LangChain engines (committed in `c2aff71`, documented in [`docs/NO_LLM_MODE.md`](NO_LLM_MODE.md)). However, some end-to-end CI gates intentionally exercise GitHub Models through `GITHUB_TOKEN` to validate provider integration itself. The trade-off is ratified in [ADR-016](adr/ADR-016-github-token-as-default-e2e-llm.md).

- **Surface:** `ci.yml`, `nightly.yml`, `performance-benchmark.yml` (which require live provider credentials).
- **Zero-config alternative:** Set `AGENTIC_NO_LLM=1` to run workflows without any LLM provider. See [`docs/NO_LLM_MODE.md`](NO_LLM_MODE.md) for scope and limitations.
- **Risk:** A GitHub Models outage or rate-limit event fails the provider-integration CI jobs, but `AGENTIC_NO_LLM=1` jobs remain unaffected.
- **Workaround:** `agentic run test_deterministic` or `AGENTIC_NO_LLM=1 agentic run <workflow>` runs entirely without LLM calls — use for shape and flow testing.
- **Status:** Accepted for v0.3.0. Free LLM access in CI vs. provider dependency trade-off is explicit in ADR-016.
- **Upstream fix:** None — placeholder mode is live. Future work: extend mode to evaluation/rubric scoring.

### 3.2 Windows is a first-class target but has specific gotchas

Epic 3 hardened the Windows bring-up story. Known residual friction:

- `npx` is unreliable on Windows PATH; always use `npm` for running scripts.
- `jq` is not available; JSON parsing in scripts uses `python -c` or `grep`.
- `pnpm` fails with EPERM on mounted / shared drives; fall back to `npm`.
- PowerShell run from Git Bash mangles `$_` and `$_.Property` — wrap with `powershell.exe -NoProfile -Command '…'` and single quotes.

- **Surface:** Developer workflow scripts.
- **Status:** Documented here and in onboarding guidance. No single fix — all require awareness.

---

## 4. Operational gaps

### 4.1 Rate limiting is in-process only

The `slowapi` global rate limiter and the `AuthThrottle` per-IP auth throttle (both introduced in S1-2) store all counters in the server process's memory. In a multi-replica deployment (load balancer distributing across N instances), each replica maintains an independent counter, so the effective per-IP limits are multiplied by N.

- **Surface:** `agentic_v2/server/app.py` (slowapi setup), `agentic_v2/server/auth.py` (AuthThrottle).
- **Risk:** A determined caller can exceed the intended rate cap by distributing requests across replicas.
- **Workaround:** Run a single server replica, or enforce rate limits at the reverse proxy / API-gateway tier.
- **Status:** Accepted for Sprint 1. Sprint 2's T1-2 shipped the circuit-breaker Redis backend only; `slowapi` and `AuthThrottle` counters remain in-process.
- **Upstream fix:** Future sprint — add Redis backend for `slowapi` and `AuthThrottle`. See [ADR-018](adr/ADR-018-api-rate-limiting-and-auth-throttle.md).

### 4.2 Per-IP auth throttle shares the same multi-replica caveat

`AuthThrottle`'s per-IP 401-failure window is in-process for the same reason as §4.1. A distributed attacker who splits authentication-probe requests across replicas can stay under each replica's threshold while collectively exceeding the intended lockout threshold.

- **Surface:** `agentic_v2/server/auth.py` (`AuthThrottle` class).
- **Risk:** Brute-force auth attempts from a distributed source can evade per-replica lockout.
- **Workaround:** Same as §4.1 — single replica or ingress-level throttling.
- **Status:** Accepted for Sprint 1. Sprint 2's T1-2 covered the circuit-breaker Redis backend only; `AuthThrottle` remains in-process.
- **Upstream fix:** Future sprint — shared Redis store for `AuthThrottle`. See [ADR-018](adr/ADR-018-api-rate-limiting-and-auth-throttle.md).

### 4.3 Human approval gates are programmatic only (no UI pause/resume yet)

P1 #12 added real, tested human-approval gates on the tool-execution hot path: an injectable `ApprovalProvider` (`agentic_v2/governance/approval.py`) is consulted at **both** dispatch points before any high-impact tool runs, and the gate **fails closed** (a gated tool with no provider registered is denied, never executed). High-impact builtins (`shell`/`shell_exec`/`execute_python`, `file_write`/`file_delete`/`file_move`/`file_copy`/`directory_create`, `http`/`http_post`) are gated by default.

What is **not** built yet is the full UI-driven *pause-and-resume* flow — suspending a run, surfacing an approval prompt to a human operator in the web UI, and resuming on their click.

- **Surface:** `agentic_v2/governance/approval.py` (gate + providers), `agentic_v2/engine/tool_execution.py` and `agentic_v2/agents/base.py` (dispatch-point wiring), `agentic_v2/contracts/events.py` (`approval_required` / `approval_decision` events).
- **Current behavior:** approval is decided synchronously by the registered provider. The agent loop emits the contract events on its event bus; the engine tool loop surfaces approval request/decision via the logger (WARNING for request, INFO for decision) and in the serialized result metadata rather than streaming the new events — the engine dispatch point has no clean event channel without threading an emitter through the tool loop.
- **Risk:** Operators must wire a provider programmatically (`set_approval_provider(...)`) at process start; there is no web-UI approval queue. Gated tools fail closed until a provider is registered, which is the intended safe default but will block runs that expected those tools to execute unattended.
- **Workaround:** Register an `ApprovalProvider` at startup (`AutoApproveProvider` for trusted environments, `CallbackApprovalProvider`/`PolicyApprovalProvider` for selective approval), or disable the requirement per tool/globally. See [security-hardening.md §11](operations/security-hardening.md).
- **Status:** Programmatic gate shipped and tested (`tests/test_approval_gates.py`). UI pause/resume is an explicit follow-on; the wire events exist so the server/UI can build on them.
- **Upstream fix:** Future sprint — server-side approval queue + WebSocket-driven pause/resume in the UI, streaming the `approval_required`/`approval_decision` events from the engine path.

### 4.4 SSRF guard cannot fully close DNS rebinding without network-layer egress control

The SSRF guard (`agentic_v2/security/url_guard.py`) validates a URL's resolved addresses before each request and re-validates every redirect hop. To resist DNS rebinding it also **pins the connection** to a validated address: the aiohttp path wraps the connector in a `GuardedResolver` that re-checks each address at connect time, and the httpx (LangChain) path rewrites the request URL to the validated IP while carrying the real hostname in the `Host` header / `sni_hostname` extension.

- **Surface:** `agentic_v2/security/url_guard.py` (`validate_url_pinned`, `check_resolved_address`), `agentic_v2/tools/builtin/http_ops.py` (`GuardedResolver`), `agentic_v2/langchain/tools.py` (`_pin_request_target`).
- **Residual risk:** Pinning relies on the resolver returning the same answer the guard validated, and OS-level resolver caching is outside the application's control. A hostile authoritative DNS server with a near-zero TTL is a real threat model that application-layer checks alone cannot fully defeat. The guard is **defense-in-depth**, not a complete boundary.
- **Risk:** In an environment where the server has network reachability to internal services, an attacker controlling DNS for a hostname a workflow fetches could, in principle, steer a connection to a private/metadata address on any code path not covered by pinning.
- **Workaround:** For hostile-DNS threat models, add a **network-layer egress control** — an egress firewall, service-mesh authorization policy, or Kubernetes `NetworkPolicy` — restricting which addresses the server process may reach. Keep `AGENTIC_BLOCK_PRIVATE_IPS` on (the default).
- **Status:** Accepted. Application-layer guard + connection pinning shipped and tested (`tests/test_ssrf_guard.py`); network-layer egress control is an operator responsibility documented in [security-hardening.md §10](operations/security-hardening.md).
- **Upstream fix:** None planned at the application layer — this is an inherent limitation of resolving names in userspace. Operators must apply network controls for hostile-DNS threat models.

### 4.5 `X-Tenant-ID` is client-supplied and spoofable in the default configuration

Tenant scoping ([ADR-022](adr/ADR-022-tenant-isolation.md)) resolves a tenant from OIDC claims first, then falls back to the `X-Tenant-ID` request header when OIDC is inactive, then to the `default` tenant. In the shipped default configuration — OIDC disabled (`agentic_oidc_enabled` defaults to `False`) and no `AGENTIC_API_KEY` set (`server/auth.py`: "all requests pass through unchanged"; `server/lifespan.py` warns "all API routes are publicly accessible") — nothing authenticates the caller, so `X-Tenant-ID` is entirely client-supplied and any caller can select any tenant's scope by setting the header. Per ADR-022 this header is a *compatibility* mechanism, not a hard trust boundary.

- **Surface:** `agentic_v2/core/tenant.py` (`get_tenant_context`), `agentic_v2/server/auth.py` (`APIKeyMiddleware`, reads `AGENTIC_API_KEY`), `agentic_v2/settings.py` (`agentic_oidc_enabled`).
- **Risk:** With OIDC off and no API key, a caller can read or write another tenant's runs/datasets by choosing its `X-Tenant-ID`. Path-traversal checks still confine access to the *selected* tenant's directory, but nothing binds the request to the caller's *own* tenant.
- **Workaround:** Enable OIDC (`AGENTIC_OIDC_ENABLED=1`) so tenant/org claims — not the header — drive scoping, and/or set `AGENTIC_API_KEY`; or place the server behind an authenticating gateway that strips or validates `X-Tenant-ID`.
- **Status:** Accepted. `X-Tenant-ID` is a documented compatibility path for local/dev and API-key deployments (ADR-022), not a per-tenant security boundary in the unauthenticated default. [ROADMAP.md](ROADMAP.md) E8-2 is worded to match.
- **Upstream fix:** None at the header layer — tenant enforcement requires an authenticated identity ([ADR-021](adr/ADR-021-jwt-oidc-authentication.md)) or a gateway.

---

## 5. Documentation and process

### 5.1 Implementation plans for Epics 3, 5, and 6 are retrospective

Epics 1 and 2 have proper pre-implementation plan docs. Epics 3, 5, and 6 shipped without prospective plan docs — decision history for those epics is reconstructed from commit messages and ADRs rather than dedicated planning artifacts.

- **Risk:** Decision rationale may be under-documented compared to prospective plans.
- **Mitigation:** Load-bearing decisions are captured in ADRs (`docs/adr/`).
- **Status:** Accepted; new epics are expected to ship with prospective plans going forward.

### 5.2 `Generated:` and `Last Updated:` dates in docs may lag

Per-package deep-dive docs under `docs/architecture-*.md` carry generation dates that were set during an initial documentation pass (2026-04-16 to 2026-04-18). Subsequent epic work may have moved details under them without updating the dates.

- **Status:** Accepted. Trust the current code over the doc when the date is older than 2 weeks; file an issue.
- **Upstream fix:** Future sprint — audit and either refresh or re-date.

---

## 6. How this list is maintained

- Any limitation discovered in the wild should be added here with a Status and a workaround. Do not hide limitations in issue trackers.
- When a limitation is fixed, remove the entry and link the fix from `CHANGELOG.md` under the release it shipped in.
- The "Last verified" date at the top of this document is refreshed whenever an entry is added, resolved, or materially changed.
