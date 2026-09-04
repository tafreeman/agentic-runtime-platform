# Known Limitations

> **Audience:** Operators, auditors, and contributors reading failing CI or trying to understand why something "works but not quite."
> **Outcome:** After reading, you know what is intentionally unfinished and what the next sprint is expected to address.
> **Last verified:** 2026-07-28

This page records limitations confirmed in the current checkout. Some describe
accepted design boundaries; others describe work that is not complete. Check
the linked source and tests when a branch has moved beyond the date above.

Each item includes a **Status** (reflecting how we're treating it today) and an **Upstream fix** field pointing at the relevant ticket, workaround, or follow-up.

> **Note on item IDs:** entries below cite the Sprint 1 story IDs (`S1-n`) they shipped under. [`ROADMAP.md`](ROADMAP.md) tracks the same work under the two-sprint plan's T-series IDs — e.g. S1-1 = T1-1 (wire-format gate extension), S1-2 = T1-4 (rate limiting + auth throttle), S1-6 = T3-2 (eager adapter validation).

---

## 1. Typed gates that are not fully enforced

### 1.1 Python ↔ TypeScript wire format is manually mirrored (partial)

Python models remain the source for frontend wire contracts, but only selected
shapes are generated and checked automatically.

The current drift gate covers eight shapes: `ExecutionEvent`,
`StepResultRecord`, `DAGResponse`, `WorkflowInputSchemaResponse`,
`WorkflowEditorStep`, `RunsSummaryResponse`, `ChatRequest`, and
`ChatStreamEvent`. Their JSON schema snapshots are under `tests/schemas/`, and
the generated TypeScript files are under `ui/src/api/`. Other endpoint
payloads remain manually maintained.

- **Surface:** Any new event field in the uncovered endpoints requires an edit in both files.
- **Risk:** Silent shape mismatches between backend emit and frontend decode for endpoints not yet covered by the drift gate.
- **Workaround:** When editing `contracts/events.py` or `server/models.py`, grep `ui/src/api/types.ts` for the type name and update in the same PR.
- **Status:** Partially resolved (eight shapes are gated). The remaining manual boundary is recorded in [ADR-014](adr/ADR-014-pydantic-wire-format.md).
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
python -m pip install \
  -e "./agentic-workflows-v2[dev,server,langchain]" \
  -c ci-constraints.txt
```

A runtime install without the `langchain` extra succeeds, but
`--adapter langchain` cannot resolve the adapter.

- **Surface:** `agentic_v2/langchain/` imports are guarded with `try/except ImportError`.
- **Risk:** Confusing first-run failure if a contributor installed minimal extras.
- **Workaround:** Install with `langchain` extras (included in `just setup`), or pass `--adapter native` explicitly.
- **Status:** The _late_ error has been resolved by S1-6: `AdapterRegistry.validate_selected()` now runs at FastAPI lifespan startup and raises `ConfigurationError` with an install hint before any request is processed. The optional-extras design is still correct; only the error timing improved. See [ADR-020](adr/ADR-020-langchain-adapter-eager-validation.md).
- **Upstream fix:** None further needed for the server path. CLI `agentic run --adapter langchain` surfaces the error at adapter resolution time (outside the FastAPI lifespan); may benefit from an explicit pre-flight check in a future sprint.

---

## 3. CI and environment dependencies

### 3.1 The blocking CI path does not prove live provider behavior

The regular CI path uses deterministic tests and `AGENTIC_NO_LLM=1` for its
no-credential smoke coverage. The evaluation workflow has an opt-in or
scheduled live gate, but it skips cleanly when no provider secrets are
configured.

- **Surface:** `.github/workflows/ci.yml` and
  `.github/workflows/eval-package-ci.yml`.
- **Risk:** A green pull request does not prove that every provider accepts the
  current request shape, streams correctly, honors tool choice, or handles
  current quota behavior.
- **Workaround:** Run targeted integration tests with each provider used by the
  deployment. Record the provider, model, endpoint, and date with the result.
- **Status:** Intentional. The default pull-request path remains deterministic
  and does not spend provider quota.
- **Upstream fix:** Keep opt-in live lanes and add provider-specific coverage
  only where credentials and cost controls are available.

### 3.2 Windows is a supported target but has specific gotchas

Known residual friction:

- use PowerShell for the shipped `.ps1` lifecycle scripts;
- use `npm --prefix agentic-workflows-v2/ui ...` from the repository root so
  the working directory is explicit;
- use Windows paths or resolved `Path` objects when invoking Python file tools;
  and
- avoid passing PowerShell expressions containing `$` through another shell,
  which can expand them before PowerShell receives the command.

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

### 4.6–4.11 Retired with the retrieval package

The six retrieval limitations previously recorded here are no longer current
ARP behavior because the package and command surface were removed. The removal,
migration boundary, and historical defects remain recorded in
[ADR-057](adr/ADR-057-remove-rag-package.md) and the changelog.

### 4.12 The model inventory command fails from the repository root

`python -m tools.llm.model_inventory` imports `llm_client` as a top-level
module. In the installed repository package, that module is
`tools.llm.llm_client`, so the command exits with
`No module named 'llm_client'`.

- **Surface:** `tools/llm/model_inventory.py`.
- **Risk:** A model discovery run fails before checking any provider.
- **Workaround:** Use `python -m tools.llm.model_probe` for live discovery.
- **Status:** Known command defect.
- **Upstream fix:** Change the command to package-relative imports and add a
  repository-root CLI smoke test.

### 4.13 The model catalog exposes `onnx:` IDs that exact-model chat cannot use

ONNX discovery emits `onnx:<relative-path>` IDs and the native model backend
supports that prefix. The LangChain model builder uses `local:` for its ONNX
path and has no `onnx:` prefix builder. `POST /api/chat` uses the LangChain
builder, so selecting a discovered `onnx:` entry there produces an unsupported
provider error.

- **Surface:** `agentic_v2/models/local_discovery.py`,
  `agentic_v2/models/backends.py`, `agentic_v2/langchain/models.py`, and
  `agentic_v2/server/routes/chat.py`.
- **Risk:** The model page can list a local model that its chat playground
  cannot test.
- **Workaround:** Use the native backend for `onnx:` models. Use `local:` only
  where the LangChain ONNX builder's path contract is appropriate.
- **Status:** Known cross-adapter mismatch.
- **Upstream fix:** Normalize the prefix contract across discovery and both
  execution paths, then add an end-to-end discovered-model chat test.

### 4.14 Strict model-weight verification is not wired into every model loader

The SHA-256 verifier and strict-mode behavior are implemented in
`agentic_v2/models/weight_integrity.py`. The shared-tools local provider calls
it before loading a local model. The runtime's native `OnnxBackend` and
LangChain local ONNX builder do not call it.

- **Surface:** `tools/llm/provider_adapters.py`,
  `agentic_v2/models/backends_local.py`, and
  `agentic_v2/langchain/model_builders.py`.
- **Risk:** `AGENTIC_STRICT_MODEL_VERIFY=1` can be set while a runtime ONNX
  load still proceeds without consulting the trusted hash file.
- **Workaround:** Call `verify_model_weights()` explicitly before starting the
  runtime and restrict the model directory against later changes.
- **Status:** Partial enforcement.
- **Upstream fix:** Put verification in the common runtime load boundary and
  add strict-mode tests for every local model backend.

---

### 4.15 Eleven `tools/tests` cases assert an API that no longer exists

`tools/tests` holds 17 test files that **no CI job had ever collected**. The whole-repo
coverage step measures `--cov=tools` but only collects `agentic-workflows-v2/tests` and
`agentic-v2-eval/tests`, so `tools/` was *measured* but never *exercised* — its coverage
number was whatever the workflow suites happened to import.

The `tools-tests` job in `ci.yml` now collects them. Running them for the first time
surfaced 11 failures. They are not flaky; they are stale, and they are stale precisely
because nothing ever ran them:

- `test_errors.py::TestClassifyError::test_return_code_param_accepted` calls
  `classify_error(..., return_code=124)`; the parameter no longer exists.
- Ten cases across `test_benchmark_pipeline.py` and `test_evaluation_pipeline.py`
  (`TestEvaluateTaskOutputLlm`) patch `evaluation_pipeline.print_evaluation_report`,
  a symbol the module no longer defines.

- **Surface:** `tools/tests/test_errors.py`, `tools/tests/test_benchmark_pipeline.py`,
  `tools/tests/test_evaluation_pipeline.py`; the `tools-tests` job in `.github/workflows/ci.yml`.
- **Risk:** Low for runtime behaviour — the implementations are current and the other 410
  cases pass. The real cost is that these three files' intent is now unverified, so a
  regression in the surrounding code would not be caught by them.
- **Workaround:** None needed; the 11 are deselected by node id in the CI job, so the
  remaining cases in those same files still gate.
- **Status:** Accepted, short-term. Deselecting by node id rather than by file is
  deliberate — it keeps the debt greppable and keeps the rest of each file enforcing.
- **Upstream fix:** Decide per case whether the test or the API is right, then either
  update the assertions or delete the case. Once the list is empty, drop the `--deselect`
  flags so the whole suite gates unconditionally.

## 5. Documentation and process

### 5.1 Implementation plans for Epics 3, 5, and 6 are retrospective

Epics 1 and 2 have proper pre-implementation plan docs. Epics 3, 5, and 6 shipped without prospective plan docs — decision history for those epics is reconstructed from commit messages and ADRs rather than dedicated planning artifacts.

- **Risk:** Decision rationale may be under-documented compared to prospective plans.
- **Mitigation:** Load-bearing decisions are captured in ADRs (`docs/adr/`).
- **Status:** Accepted; new epics are expected to ship with prospective plans going forward.

### 5.2 Historical documents describe the version that created them

ADRs, design plans, audit reports, prompts, and changelog entries are retained
as records. They may describe files, commands, or behavior that no longer
exist.

- **Status:** Intentional. Current engineer guidance lives outside the
  historical directories and is checked against the active code.
- **Upstream fix:** None. Add a new ADR, migration entry, or changelog entry
  instead of rewriting an older decision record.

---

## 6. How this list is maintained

- Any limitation discovered in the wild should be added here with a Status and a workaround. Do not hide limitations in issue trackers.
- When a limitation is fixed, remove the entry and link the fix from `CHANGELOG.md` under the release it shipped in.
- The "Last verified" date at the top of this document is refreshed whenever an entry is added, resolved, or materially changed.
