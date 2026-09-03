# Changelog

All notable changes to this project are documented here.

---

## [Unreleased]

### ARP public-truth and ADR governance drift controls (2026-09-03)

- Removed current-facing references to the retrieval package and command surface deleted by ADR-057, and pointed migration guidance at the standalone groundkit repository.
- Marked ADR-042 Accepted while retaining the implementation tracker's honest partial-slice status; removed accepted ADR-054 and ADR-057 from the parked-number note.
- Expanded the documentation drift gates to reject retired runtime surfaces, ADR body/index status disagreements, and accepted ADR numbers still described as parked or in flight.

### SWE-bench A/B campaign evidence lands on main; `swe-ab` extra (2026-09-02)

- **`evals/swe_ab/reports/` is now tracked** (42 reports, ~9 MB): the per-sample verdicts are the evidence the campaign exists to produce, and they previously lived only on whichever machine last ran a wave. `artifacts/`, `sandbox/` and the case trees stay ignored. `docs/EVIDENCE.md` §1.6 is regenerated from the corpus and carries the trust caveats per slice; nothing is deleted (WAVE-RUNBOOK rule 3).
- **New `swe-ab` extra carries `pandas`**, which only `evals/swe_ab/tools/build_swebench_cases.py` imports (to read the SWE-bench Verified parquet). It was briefly a core runtime dependency on the campaign branch; it is not one on `main`. The kit's runbook commands pass `--extra swe-ab` because a plain exact `uv sync` drops extras it was not asked for (EVIDENCE.md §2.12).
- Campaign harness fixes since the PR #282 squash: WAVE_MIX rebalanced onto the buckets with remaining pool depth, a failed Ollama call can no longer silently fall through to the operator's paid Claude subscription, and a provider under test keeps its own credential while every other paid credential is blanked (`NVIDIA_API_KEY`, `OPENROUTER_API_KEY`, `DIGITALOCEAN_TOKEN`).

### DigitalOcean Serverless Inference joins as a LangChain-path provider (2026-09-01)

- **New `digitalocean:` prefix and `build_digitalocean_model`.** A `ChatOpenAI` base-URL swap to `https://inference.do-ai.run/v1`, the same shape as the OpenRouter builder: DigitalOcean fronts DeepSeek, GLM, Kimi, Qwen and Nemotron behind one OpenAI-compatible surface. Ids are the bare catalog id (`digitalocean:deepseek-v4-flash-0731`), gated on `DIGITALOCEAN_TOKEN` (`PROVIDER_ENV_KEYS`, `.env.example`). Verified end-to-end against `deepseek-v4-flash-0731`.
- **LangChain engine only.** No native `MultiBackend` backend, no discovery probe and no `model_registry.yaml` entry — invoke it by explicit id, as with OpenRouter before ADR-050 formalized it.

### NVIDIA NIM reasoning models no longer return empty content (2026-08-29)

- **`build_nvidia_model` now disables NIM's internal reasoning phase.** Several NIM-hosted models (`deepseek-ai/deepseek-v4-flash-0731`, the `nvidia/nemotron-3` family, `nvidia/nemotron-3.5-lightning-30b-a3b`, `moonshotai/kimi-k3`) spend their output token budget on chain-of-thought before emitting an answer, so a call with a modest `max_tokens` returned `content=''` — indistinguishable from "the model failed". Requests now carry `extra_body={"chat_template_kwargs": {"thinking": False}}`. Applied unconditionally: probed model by model against the cloud endpoint, no model returned a 4xx for the field and none answered differently *because of* it — it was silently ignored by `meta/muse-glimmer-30b` and `openai/gpt-oss-{20b,120b}` (which gate reasoning on `reasoning_effort` instead) and by the non-reasoning `nvidia/ising-calibration-1.5-31b`, whose output was byte-identical either way.
- **New `NVIDIA_DISABLE_THINKING` escape hatch** (`0`/`false`/`no`/`off`), for a self-hosted NIM whose chat template rejects the field. Unset means the field is sent.
- **Empty content now degrades to the model's reasoning rather than to `""`.** `ChatOpenAI` documents that non-standard provider fields such as `reasoning_content` are not extracted or preserved, so there was previously nothing to fall back to; `build_nvidia_model` now returns the provider-specific subclass that warning points at, which preserves the field in `additional_kwargs`. `extract_agent_response_text` falls back to it — and to Ollama's `thinking` — when content is blank, logging a `WARNING`, mirroring `OllamaBackend`'s existing `response.thinking` fallback. This matters for the default registry, which already routes tier chains and `judge_default` at `nvidia:deepseek-ai/deepseek-v4-{flash,pro}`.
- **Not fixed here:** the native (non-LangChain) lane has the same defect — `NvidiaBackend` inherits `OpenAIBackend.complete_chat`, which reads `message["content"]` with no thinking-disable and no fallback.

### Curated cost-lane ceiling and five new discovery paths — ADR-059 (2026-08-28)

- **New `AGENTIC_MAX_COST_LANE` operator control (`local`/`free`/`paid`, default `paid` — unset, no behavior change).** Every registry entry now carries a curated `cost_lane`; an uncurated model fails closed to `paid`. The ceiling filters the *full* candidate list in both engines — `langchain.models.get_model_candidates_for_tier`, the native `ModelRouter`/`SmartModelRouter`, and explicit-model call sites (`fallback_selector.run_with_fallback`, `EKProvider.complete`) that previously bypassed tier-based selection (and with it, any ceiling) entirely. A pinned `model_override`/explicit `model=` cannot bypass the ceiling either. If filtering would empty an otherwise non-empty candidate set, the call raises `CostLaneCeilingExceededError` naming the ceiling rather than silently returning nothing or falling through unfiltered. Ollama's `cost_lane` is dynamic, not merely curated: it downgrades from `local` when `OLLAMA_API_KEY` is set and the model isn't pulled locally (matching `build_ollama_model`'s ADR-051 reroute to the account-bound cloud endpoint), or when the configured `OLLAMA_BASE_URL` itself isn't loopback — an operator can point any locally-branded provider at a remote host, and the lane now reflects that.
- **A failover step that crosses into a strictly more expensive cost lane is now visible.** Logged at `WARNING` and recorded as a `lane_crossings` run event in the step's metadata (success and failure paths, including the contract-validation failure route), even when the default ceiling permits the crossing.
- **Three previously-unprobed local serving paths are now discovered:** Lemonade (Ryzen AI hybrid NPU), Docker Model Runner, and Foundry Local (`foundry-local:` prefix — distinct from Azure AI Foundry's `azure-foundry:`). A new `models.discovery_snapshot.discover_all_models()` facade returns one uniform record — id, provider, endpoint, cost lane, reachability — across all seven serving paths (the four above plus cloud, Ollama, LM Studio/ONNX), replacing five differently-shaped functions callers previously had to reconcile by hand. Every locally-branded provider's reported endpoint and lane account for a non-default, non-loopback configured host, not just Ollama's.
- NVIDIA NIM's curated free-endpoint models are now declared directly in `model_registry.yaml` (`tiers: []` — deliberately never promoted into a tier chain, per ADR-040).

### RAG package removed — superseded by groundkit (2026-08-10)

- **`agentic_v2.rag` is removed outright.** The 17-module package (`agentic_v2/rag/`), the `agentic rag` CLI group (`cli/rag_commands.py` plus the RAG helpers in `cli/helpers.py`), 14 dedicated test files plus the RAG sections of `tests/test_protocol_conformance.py`, the `[rag]` optional extra (`lancedb>=0.15,<1`, `litellm>=1.84,<2`), `docs/rag/`, `examples/02_rag_pipeline.py`, and the non-blocking `rag-extra-tests` CI job are all gone. See [ADR-057](docs/adr/ADR-057-remove-rag-package.md).
- **Superseded, not deprecated in place: the standalone groundkit repo replaces it.** groundkit's `ADR-0001-promote-vs-rewrite` (Accepted 2026-08-10) ran a 9-agent inventory over this package, confirmed every claimed production gap (no cross-process persistence, no directory-scale ingestion, unimplemented metadata filtering, Protocol-naming mismatches, and more), and recorded the owner decision explicitly: no cherry-pick of fixes back into ARP.
- **No deprecation shim.** A repo-wide import scan found zero non-test consumers of `agentic_v2.rag` outside its own CLI wiring, so there was no call site to protect with a warning period — this is a clean removal, not a phased migration.
- **Migration:** projects that need RAG functionality should target groundkit once it ships v0.1.0; there is no ARP-side replacement or compatibility layer in the interim, and `pip install agentic-workflows-v2[rag]` no longer resolves.

### agentic-evalkit pin moved to the published 0.3.x series (2026-08-09)

- **The `eval` extra now pins `agentic-evalkit>=0.3.0,<0.4.0`**, was `>=0.1.1,<0.2.0` — two minor series behind the published release. The constraints export no longer excludes the package (`--no-emit-package agentic-evalkit` dropped from `ci.yml` and both `justfile` targets), so the extra is actually constrained in CI rather than silently unpinned.
- **CI now installs and exercises the extra.** A new `evalkit-bridge-tests` job installs the `eval` extra plus `agentic-v2-eval`, asserts `agentic_evalkit` really imports (so a resolution failure cannot pass as a silent skip), and runs the bridge and boundary suites. Both previously `importorskip`ed in every job, so the ARP-to-EvalKit adapter had never actually run in CI.
- The boundary test's version assertion is now **derived from the pin in `pyproject.toml`** instead of a hardcoded `0.1.` prefix. The hardcoded literal is what silently rotted when the pin moved, and nothing caught it because no job installed the extra.

### Typed step artifact contracts — ADR-052 (2026-07-14)

- **Typed step artifact contracts (ADR-052).** A live `fullstack_generation` run reported 8/8 steps successful while every downstream consumer received an `api_code` placeholder ("see backend_code for implementation") instead of the real `backend_code` file map — `coalesce()` picks the first non-null value, and key presence was the only success criterion. New opt-in per-step `input_contracts`/`output_contracts` (first kind: `code_artifact`) validate artifact content through one shared validator in both execution engines: canonical-first alias promotion, placeholder/refusal-prose rejection, unsafe-path rejection, structured diagnostics. `fullstack_generation` adopts the contract for `backend_code`/`backend_tests` (`api_code`/`api_tests` remain parse-only migration aliases), and a placeholder-only `AGENTIC_NO_LLM=1` run now reports `failed` instead of a hollow success. String payloads are parsed with the canonical FILE/ENDFILE grammar from `engine/llm_output_parsing.py` — contract validation defines no grammar of its own.

### Workflow runs with empty required inputs rejected at submit (2026-07-14)

- **Empty required inputs now fail at submit with 422.** `POST /api/run` accepted runs whose required inputs were blank and let them die asynchronously — the console navigated to a live view that instantly showed "Input validation failed" with 0/8 steps. The runner's input validation is now a shared `validate_workflow_inputs` helper called at submit (after dataset-backed evaluation inputs resolve), returning 422 with the violation list; the run form blocks the same cases client-side, and dataset-backed evaluation runs skip the client check because their inputs resolve server-side.
### Release engineering for v0.4.0-rc.1 (2026-07-14)

- Added an explicit platform-bundle manifest that maps the GitHub prerelease tag
  to the independently versioned `agentic-tools`, `agentic-workflows-v2`, and
  `agentic-v2-eval` distributions.
- Added isolated wheel installation, import, CLI, metadata, and tag checks to the
  release pipeline and exposed the same artifact gate as `just release-check`.
- Repaired the release image contract: the backend uses its `production` stage
  with the default LangChain runtime extra, and the dashboard now has a non-root
  nginx production stage with SPA fallback and a health endpoint.
- Made the generated load report deterministic by deriving its displayed time
  from committed evidence instead of the CI runner clock.
- Refreshed vulnerable Python dependency locks and raised direct runtime floors
  to the first fixed releases reported by the release dependency audit.

### Evidence Ledger UI, Model Router, and multimodal playground — ADR-054 (2026-07-14)

- Replaced the production shell and semantic token system with the light-first
  Evidence Ledger design: warm-paper surfaces, editorial display typography,
  hairline structure, restrained orange focus/action treatment, responsive
  desktop/mobile navigation, owned shadcn/Radix primitives, and route-level
  code splitting. `/settings` now redirects into the consolidated Model Router
  and the mock-only `/prototypes` route is no longer shipped.
- Added provider editing, safe enable/disable and classified saved-provider
  probes; tier routing dry-run; and immutable named model packs with versioning,
  validation, activation, duplication, workflow binding, dependency-aware
  archive, and JSON import/export. Workflow launches can select an exact pack;
  context-local resolution prevents concurrent-run leakage and completed runs
  retain the source, immutable pack snapshot, requested override, and resolved
  model/provider per step.
- Promoted the existing SSE chat endpoint into a first-class Playground and
  added multimodal input/output. Messages accept bounded PNG/JPEG/WebP/GIF data
  URLs, image previews/removal, attachment-only turns, abortable streaming, and
  typed safe raster output events. Remote/SVG inputs and unsafe provider media
  blocks are rejected without exposing credentials.
- Added Pydantic/JSON/TypeScript drift coverage for multimodal chat contracts,
  backend lifecycle and precedence tests, UI lifecycle/payload/provenance tests,
  and updated the UI architecture, page, component, API, migration, and ADR
  documentation.
- Made workflow editing discoverable from the workflow catalog with a separate,
  feature-gated edit action on every definition while preserving the existing
  run-configuration/detail action.
- Updated live model discovery to LM Studio's native `/api/v1/models` contract
  with optional `LM_API_TOKEN`, retained legacy fallbacks, and replaced the
  capped OpenRouter allowlist with its complete text-output chat catalog via
  `output_modalities=all`. Ollama discovery remains on the official `/api/tags`.
- Added per-model LM Studio loading through native `POST /api/v1/models/load`.
  Downloaded but unloaded chat models now expose a bounded `load` action with
  progress, classified errors, idempotent already-loaded handling, and an
  automatic provider rescan when loading completes.
- Added overloaded HTTP chat requests: clients can provide either an exact
  `model` or a capability `tier` (1–5). Tier requests reuse the configured
  model-router candidate chain and emit the selected model as a typed `route`
  SSE event before completion output.
- Added a responsive all-provider status-card grid above the searchable model
  catalog. Providers with no detected models remain visible and use an explicit
  amber state instead of disappearing or implying liveness.

### No-LLM badge now server-reported (2026-07-09)

- **No-LLM badge now server-reported.** The dashboard's no-LLM indicator (`Sidebar`, `ConsoleHeader`, `ConsoleStatus`) read `isNoLlmModeEnabled()`, a client build-time flag baked in at `vite build` — it could silently disagree with how the server was started. `GET /api/health` now returns an additive `no_llm_mode` field read live from `AGENTIC_NO_LLM` each request (not the cached `Settings` singleton); all three surfaces derive the badge from it via the shared `["backend-health"]` query. The orphaned build-time flag (`isNoLlmModeEnabled()`, the `__AGENTIC_NO_LLM_MODE__` Vite/Vitest define, `VITE_AGENTIC_NO_LLM` plumbing) was removed as dead code.

### Process-wide token budget wired up — ADR-048 (2026-07-09)

- **Process-wide token budget wired up (ADR-048).** `LLMClientWrapper.set_budget()` and the `TokenBudget` enforcement it arms had zero production callers — `models.get_client()` never armed a budget, so the cap was dead code. New `AGENTIC_TOKEN_BUDGET` (env var, default unlimited) arms a cumulative `ProcessWideTokenBudget` on the shared client singleton via `_maybe_set_token_budget()`. It always accumulates spend (the post-dispatch accounting paths charge tokens already spent and ignore `consume()`'s return, so a plain reservation `TokenBudget` would drop an overrun unrecorded and let the cap be bypassed) — making it a real circuit breaker. Cumulative across the process (singleton, not per-run — see ADR-048), fails safe to disabled on a bad value (a blank env var is silently unset), skipped under `AGENTIC_NO_LLM`. Enforcement + accumulation tests included.

### Docs homepage stats derived from source (2026-07-09)

- **Docs homepage stats now derived, not hand-typed.** `docs/index.md`'s "By the numbers" strip (backend test count, ADR count, production workflow count) carried hand-maintained literals that had drifted (ADR count hard-typed 38 vs an actual 44). New `scripts/generate_doc_stats.py` recomputes each from source (AST-counted test functions, `docs/adr/ADR-*.md` filename parsing, non-`test_*` workflow YAML defs); `just docs` runs it in `--check` mode and a new `doc-stats-drift` CI job enforces it on push and PR. `docs/project-overview.md`'s ADR cell now defers to the ADR index without a numeral.

### Model registry drift detection (2026-06-25)

- Added probe-time drift detection (`detect_registry_drift`, ADR-040). On every provider probe (server startup and `/api/models/probe`) the curated registry is diffed against the live `discover_cloud_models()` listings; any pinned id a keyed provider no longer lists is **quarantined** (dropped from routing by both engines) and logged at WARNING — automatically catching the next retired model instead of discovering it as a runtime 404. A provider that returns no listing is treated as unknown (no false-positive mass-quarantine); newly discovered ids are never auto-promoted into a chain. No-op under `AGENTIC_NO_LLM`; `AGENTIC_REGISTRY_STRICT=1` raises instead of warning so a CI/probe job fails loudly. The `DriftReport` is surfaced as an additive `drift` key in the probe response.

### Curated model registry (2026-06-25)

- Added a single source-of-truth model registry (`config/defaults/model_registry.yaml` + `models/model_registry.py`). Tier fallback chains, the special-purpose model ids (judge default, NotebookLM fallback, ultimate fallback), and a per-token price table now live in one place that feeds both the native router (`DEFAULT_CHAINS`) and the LangChain engine (`_TIER_FALLBACK_CHAINS` / `_TIER_DEFAULTS`), plus the judge and NotebookLM call sites. Eliminates the triple-maintained model-id lists behind the retired-`gemini-2.0` 404 incident; a dangling id reference now fails loudly at load time.
- Reconciled the previously divergent native-router and LangChain tier chains into one canonical chain per tier (cloud-capability-first with a local Ollama tail; tiers 4–5 escalate to `gemini-2.5-pro` / `claude-opus-4-6`). See ADR-040.

### CI Test Fixes (2026-05-27)

- `test_path_safety_fallback_branch_without_is_relative_to`: replaced hardcoded Windows-style paths with `os.sep`-based paths so the fallback branch passes on Linux CI and Windows.
- `test_score_step_handles_eval_unavailable_and_missing_default`: added mid-test `pytest.skip` for the `load_rubric` monkeypatch section; `load_rubric` is only in the module namespace when `agentic_v2_eval` is installed.
- `test_score_step_falls_back_to_default_rubric`: added `@pytest.mark.skipif(not hasattr(step_scoring, "load_rubric"), ...)` for the same reason.

### Test Fixes (2026-05-26)

- Fixed `_agenerate` NameError in `agentic_v2/integrations/langchain.py` by adding router lookup for the model name (resolves 3 test failures).
- Regenerated stale golden file `tests/golden/code_review_output.json` after `agent_resolver.py` placeholder-key change.
- Marked 2 environment-sensitive `tools.llm` provider tests as skipped pending isolated venv execution.

### Epic 7: First-Run Experience (2026-05-21)

- **E7-1 — Onboarding docs + setup hardening** — `docs/ONBOARDING.md`, `README.md`, `agentic-workflows-v2/README.md`, and `scripts/setup-dev.ps1` updated to surface `agentic run test_deterministic` as the recommended zero-credential first step. All `--input` inline-JSON examples converted to the file-based form (`--input input.json`). `just` installation instructions added for contributors who prefer the task runner. Onboarding QA confirmed < 10 minutes on a fresh Windows clone.
- **E7-2 — `GettingStartedCard` dashboard component** — New React component rendered on `DashboardPage.tsx` for users who have no prior runs recorded. Cards are dismissible (close button) and the dismissed state is persisted in `localStorage` so the card does not reappear on reload. Component lives at `ui/src/components/GettingStartedCard.tsx`.
- **E7-3 — `NoProviderConfiguredError` + actionable CLI and server guidance** — `agentic_v2/core/errors.py` gains `NoProviderConfiguredError`. The CLI now catches this error and renders a Rich panel listing the required environment variables and pointing at `docs/ONBOARDING.md` instead of surfacing a traceback. The server returns HTTP 503 with a structured JSON body (`{"error": "no_provider_configured", "guidance": "…"}`) so API consumers can detect and display the condition. 7 new tests cover the CLI panel, the HTTP response shape, and the error class itself.
- **E7-4 — Devcontainer PR gate** — `.github/workflows/devcontainer-validate.yml` added. The workflow triggers on pull requests that touch `.devcontainer/**`, `Dockerfile*`, or `pyproject.toml`. It builds the devcontainer image and runs the `agentic run test_deterministic` smoke test inside the container, blocking merge if either step fails.
- **E7-5 — Onboarding QA audit** — Full timed walkthrough of `docs/ONBOARDING.md` Quick Start on a clean Windows clone confirmed end-to-end completion in under 10 minutes. All commands verified copy-pasteable (no shell expansion required, no inline JSON fragments).

### Epic 8: Production Readiness Pack
- **E8-1: OIDC Authentication** - Replaced opt-in API keys with mandatory OpenID Connect (OIDC) JWT validation. Closes the previous failed-open authentication gap. Added `OIDCAuthMiddleware` to `agentic_v2/server/auth_oidc.py`.
- **E8-2: Tenant Isolation** - Introduced hard tenant boundaries for runs and datasets, ensuring cross-tenant data leakage is structurally prevented. Added `agentic_v2/core/tenant.py` and scoped endpoints.
- **E8-3: Append-Only Audit Logging** - Deployed a durable, append-only audit ledger for all workflow executions, tool invocations, and system configuration changes (`agentic_v2/server/audit_log.py`).
- **E8-4: Supply-Chain Provenance** - Introduced hash manifest verification for local model weights via `agentic_v2/models/weight_integrity.py`.
- **E8-5: Security Gap Report** - Consolidated security posture and gap analysis created in `docs/audit/epic-8-security-posture.md` and updated existing threat models.

### Production Hardening (Sprint 1 — Quick Wins & Throttling, 2026-05-14)

- **S1-1 — Wire-format coverage extended to 4 additional HTTP shapes** — `DAGResponse`, `WorkflowInputSchemaResponse`, `WorkflowEditorStep`, and `RunsSummaryResponse` are now covered by the automated drift gate. Schema snapshots added under `tests/schemas/*.schema.json`; corresponding TypeScript interfaces emitted to `ui/src/api/*.generated.ts` by `scripts/generate_ts_types.py`. The `wire-format-drift` CI job in `.github/workflows/ci.yml` now regenerates and fails the PR on any mismatch across all six covered shapes. 30 new tests cover the schema round-trip.
- **S1-2 — API rate limiting + per-IP 401 throttle** — Global `slowapi` limiter applied at the FastAPI app level; default `60/minute` per IP (`AGENTIC_RATE_LIMIT_DEFAULT`; set `AGENTIC_RATE_LIMIT_DISABLED=1` to bypass in dev/test). A new `AuthThrottle` class in `agentic_v2/server/auth.py` maintains a per-IP sliding-window counter for failed authentication attempts: after `AGENTIC_AUTH_LOCKOUT_THRESHOLD` (default `5`) failures within `AGENTIC_AUTH_LOCKOUT_WINDOW_SECONDS` (default `60`) seconds, the IP is locked out for `AGENTIC_AUTH_LOCKOUT_DURATION_SECONDS` (default `300`) seconds and every subsequent request returns HTTP `429` with a `Retry-After` header. `agentic_v2/server/app.py` wires the throttle into the authentication middleware path. 36 new tests cover the global limiter, sliding-window accumulation, lockout boundary conditions, and `Retry-After` header values.
- **S1-3 — DAG executor top-level `timeout=` watchdog** — `agentic_v2/engine/dag_executor.py` accepts a `timeout` parameter (seconds, float). When the deadline is reached, all in-flight `asyncio` tasks are cancelled structurally (via `task.cancel()` + `asyncio.gather(..., return_exceptions=True)`), downstream steps are cascade-skipped rather than left in a pending state, and an OTEL span attribute `dag.timeout_exceeded=true` is emitted on the root span. The executor raises `DAGTimeoutError` so callers get a typed exception rather than a raw `asyncio.CancelledError`. 12 new tests cover: normal completion, exact-boundary timing, cascade-skip behaviour, OTEL attribute presence, and `DAGTimeoutError` propagation.
- **S1-4 — Global `pytest-timeout` of 30 s; slow tests tagged** — `pyproject.toml` `[tool.pytest.ini_options]` now sets `timeout = 30`. Three tests that legitimately exceed this budget (streaming replay, nightly reliability loop, and the full RAG ingest integration) are decorated `@pytest.mark.slow` and excluded from the default run via `-m 'not slow'`. No test in the standard suite can silently hang CI longer than 30 seconds.
- **S1-5 — 48 baselined F401 unused-import violations cleared** — 95 import sites across ~45 files (concentrated in `__init__.py` re-export modules and adapter stubs) were cleaned. `F401` is removed from the ruff `ignore` baseline in `pyproject.toml`, so the rule now enforces on every new commit. Zero F401 violations remain in the codebase.
- **S1-6 — Eager LangChain adapter validation at startup** — `agentic_v2/adapters/registry.py` gains a new `validate_selected()` method that confirms the selected adapter's dependencies are importable before the server begins accepting requests. `agentic_v2/server/app.py` calls `validate_selected()` inside the FastAPI lifespan context; if the `langchain` adapter is selected (controlled by `AGENTIC_DEFAULT_ADAPTER`, default `langchain`) but `langchain-core` is not installed, the process exits with a `ConfigurationError` that includes the full `pip install agentic-workflows-v2[langchain]` hint — replacing the previous behaviour where the traceback surfaced mid-workflow on first agent invocation. 11 new tests cover: valid adapter passes, missing-dependency path, correct error message content, and that the app refuses to start (not just log-and-continue) on validation failure.

### Security (Sprint 1 — Tool Safety & Silent Failures)

- **S1-01 — Sanitization middleware fail-closed** — `server/middleware/__init__.py` now returns HTTP 400 on sanitization errors instead of silently passing unvalidated input downstream. Any unhandled exception in the sanitization pipeline is treated as a block, not a pass-through.
- **S1-02 — File tools fail-closed without `AGENTIC_FILE_BASE_DIR`** — All six file tools (`FileReadTool`, `FileWriteTool`, `FileCopyTool`, `FileMoveTool`, `FileDeleteTool`, `DirectoryCreateTool`) reject operations with a clear error when `AGENTIC_FILE_BASE_DIR` is unset, preventing unintentional host filesystem access. `.env.example` updated with required operator guidance.
- **S1-03 — `run_id` traversal test corpus** — Added parametrized tests covering path traversal, null-byte injection, and unicode normalization bypass attempts against the existing `run_id` validator.
- **S1-04 — `_validate_ast` attribute-escape closed** — The expression evaluator's AST sandbox now rejects attribute access (`ast.Attribute` nodes) that could escape to `__class__.__mro__` chains or dunder traversal. Existing safe-expression corpus extended with adversarial fixtures.
- **S1-05 — `ShellTool` allowlist replaces substring blocklist** — `AGENTIC_SHELL_ALLOWED_COMMANDS` env var (comma-separated command names) controls which executables `ShellTool` may run. When unset, all shell commands are disabled (fail-closed). Defeats double-space, absolute-path, uppercase, and fullwidth-unicode blocklist bypasses. `.env.example` entry added. `_SHELL_METACHARS` + `_split_command` preserved as a second safety layer.
- **S1-06 — `CodeExecutionTool` sandbox hardened** — `__import__` replaced in the wrapper's `_safe_builtins` with a constrained importer that enforces the same `_DANGEROUS_IMPORTS` blocklist at runtime, closing `__import__('os')` bypass while preserving `import math` etc. `resource.setrlimit(RLIMIT_AS=512 MB, RLIMIT_NPROC=32)` added via `preexec_fn` on POSIX to prevent memory-bomb and fork-bomb DoS. Sandbox escape test corpus added.
- **S1-06 follow-up — loader-traversal escape closed** — `"sys.modules"` and `"__loader__"` added to `_DANGEROUS_PATTERNS`, blocking `sys.modules['builtins'].__loader__.load_module('os')` traversal on Windows. Regression tests added.
- **S1-07 — Sparse subprocess env across all tools** — New `agentic_v2/tools/subprocess_utils.py` with `minimal_subprocess_env()` helper. `GitTool` and `ShellTool` (including `ShellExecTool`) now pass `env=minimal_subprocess_env()` to all subprocess calls, preventing API key leakage to child processes. Test corpus verifies `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GITHUB_TOKEN`, etc. are excluded.

### Documentation

- **Architecture umbrella + roadmap + honesty docs** (commit `41bd0d8`) — new `docs/ARCHITECTURE.md` index linking the four existing `architecture-*.md` deep-dives (closes the broken `docs/README.md` reference); new `docs/ROADMAP.md` surfacing Epic 1/2/3/5/6 status, explicit Epic 4 tombstone, and proposed Epic 7 scope (closes the in-repo backlog gap flagged by the final review); new `docs/KNOWN_LIMITATIONS.md` documenting the 35 unresolved `agentic-v2-eval` mypy findings, the empty-window SLO trivial-pass, the schema-drift root-only blind spot, and the Python→TypeScript manual mirror; new `docs/MIGRATIONS.md` with first entries for the `presentation/` extraction, the `AgentProtocol.run` signature tightening, and the `langchain` adapter deprecation.
- **Epic retrospectives + three new ADRs** (commit `7b082fd`) — retrospective plan docs for Epics 3 (DevEx), 5 (UI Polish), and 6 (Eval Depth), covering stories, commits, load-bearing decisions, and process notes; **ADR-014** (Pydantic discriminated-union wire format for execution events), **ADR-015** (SLO rolling window stored in git as JSON artifacts — acknowledges the empty-window trivial-pass as open debt), **ADR-016** (GitHub Models via `GITHUB_TOKEN` as default E2E LLM provider — documents the zero-cost-vs-vendor-coupling trade-off); `ADR-INDEX.md` refreshed from 10 → 13 ADRs with updated lineage chains. Archive headers added to the Epic 1/2 prospective plan docs so unchecked boxes read as history rather than WIP.
- **Stale-artifact triage and count-drift fixes** (commit `205b314`) — deletes ~2,050 lines of orphaned content: `MCP_IMPLEMENTATION_{COMPLETE,PLAN,STATUS}.md`, `LANGCHAIN_MIGRATION_PLAN.md` (directly contradicted ADR-013), `chatlg.md` (1052-line raw conversation log at `agentic-v2-eval/`), `playwright-tester-training-prompt.md`, and several `handoff.md` stubs. Count drift corrected in `ONBOARDING.md` / `GLOSSARY.md` / `CLAUDE.md` (24 → 7 agent personas, 78+ → 100+ test files, 10 → 6 workflow definitions). Corrected a factual claim in `docs/MIGRATIONS.md`: `presentation/` is not fully gone — the top-level directory retains leftover theme-collection scripts and raw-themes data pending a follow-up cleanup.
- **Post-v0.3.0 doc cleanup** (commit `e7c2a69`) — drops superseded `IMPLEMENTATION_SUMMARY.md`, `MASTER_MANIFEST.md`, and `docs/contribution-guide.md` (all replaced by newer artifacts landed during the doc overhaul); relocates `docs/eval-harness/*` planning artifacts to `planning-artifacts/eval-harness/` so the user-facing `docs/` tree only contains user-facing content; adds a ⚠️ STALE banner to `ACTIVE_VS_LEGACY_TOOLING_MAP.md` linking to current sources of truth rather than rewriting it blind.

### Cleanup & Refactoring

- **UI build artifacts untracked** (commit `9522baf`) — `agentic-workflows-v2/ui/dist/index.html` and `agentic-workflows-v2/ui/tsconfig.tsbuildinfo` are now in `.gitignore`; they were showing up dirty after every `npm run build` and polluting every PR diff. Fulfills the spawned task filed during Sprint A triage.

### Stabilization (Sprint B)

- **SB-1 — Path-based dataset sample endpoints with deprecated redirect aliases** — Dataset sample browsing now uses `GET /eval/datasets/{source}/{dataset_id:path}/samples` and `GET /eval/datasets/{source}/{dataset_id:path}/samples/{sample_index}`. The previous query-param endpoints remain for one release cycle as deprecated `302` redirect aliases, and the UI dataset client now targets the path-based URLs while preserving slash-containing dataset identifiers.

- **SB-2 — No-LLM smoke CI job, deterministic fixture, and improved no-provider guidance** — `.github/workflows/ci.yml` now includes a `no-llm-smoke` job that validates deterministic placeholder execution with `AGENTIC_NO_LLM=1` and no provider secrets. Added `tests/fixtures/deterministic_input.json`, documented the no-key contributor workflow in `docs/CONTRIBUTING.md`, and surfaced clearer router/CLI guidance when no LLM provider is configured.

- **SLO p95 empty-window trivial-pass fixed** (commit `c9c4f33`, Sprint B #2) — `readP95` in `agentic-workflows-v2/ui/e2e/slo-storage.ts` previously returned `0` on an empty rolling window, which silently satisfied the `<= 2000ms` assertion and produced a permanently green gate after any `slo-data` branch reset. Now throws a new `InsufficientDataError` when the window has fewer than `DEFAULT_MIN_SAMPLES` (= 10) records, and the Playwright spec converts that to `test.skip(...)` during bootstrap. Bootstrap semantics: deferred, not passed. From the 11th nightly onward the p95 budget is a hard gate.
- **All 35 `agentic-v2-eval` mypy findings cleared** (commit `ed78ee2`, Sprint B #1) — dropped `continue-on-error: true` from `.github/workflows/eval-package-ci.yml` in the same commit. Workstream breakdown: `types-PyYAML` added (2 errors), `_eval_one` refactored to a discriminated union `tuple[Literal[True], R] | tuple[Literal[False], Exception]` (6 errors across `runners/streaming.py`), optional-import guards via `_require_*_module()` helpers in `datasets.py` (6 union-attr + 1 no-any-return), 10 missing annotations added, 10 `no-any-return` fixes via typed locals. 241 tests still pass. One new `# type: ignore[return-value]` at `runners/streaming.py:199` documented with justification (`inspect.isawaitable` narrowing limitation).
- **Wire-format drift gate** (commit `ae3878c`, Sprint B #3) — new automated Python ↔ TypeScript mirror for `agentic_v2.contracts.events.ExecutionEvent`. `agentic_v2/contracts/events.py` is the source of truth; `scripts/generate_ts_types.py` emits `tests/schemas/events.schema.json`; `ui/scripts/generate-ts-types.mjs` uses `json-schema-to-typescript` to emit `ui/src/api/events.generated.ts`. New `wire-format-drift` CI job regenerates and fails the PR on mismatch. The migration caught three latent client-type mismatches (`status: StepStatus` vs. the wire `string`, non-nullable `input`/`output` that are actually nullable, `criteria` shape drift on `EvaluationCompleteEvent`), now coerced at the `useWorkflowStream.ts` boundary. Client-only transport events (`error`, `keepalive`, `connection_established`) live in a hand-defined `ChannelEvent` union since they are not in the Python contract. Contributor docs updated.
- **Sprint B #5 — Placeholder / no-LLM mode.** `AGENTIC_NO_LLM=1` installs a deterministic placeholder at both engine chokepoints (`get_client()` → `MockBackend`; `get_chat_model()` → `PlaceholderChatModel`). Native and LangChain engines both run end-to-end without provider credentials. Not a simulator — structured parsers and evaluation runs still need real keys. (commit `c2aff71`)

---

## [0.3.0] — 2026-04-22

First tracked release of the `agentic-workflows-v2` platform. Bundles
**Epic 1** (Platform Foundation), **Epic 2** (Observable Execution),
**Epic 3** (DevEx / Windows), **Epic 5** (Console UI Polish), and
**Epic 6** (Evaluation & Data Depth). See **Known Limitations** below
for items shipped with caveats and **Migration Notes** for breaking
changes vs. the prior unversioned state.

> **Note on Epic 4.** Epic numbering jumps from 3 to 5. Epic 4 was
> never authored in this repository — the number was skipped during
> planning. Not a regression, just a tombstone for the record.

### New Features

- **Epic 1 — Platform Foundation (agentic-workflows-v2)**
  - **Typed core protocols** — `AgentProtocol.run` no longer accepts/returns `Any`; signature tightened to `object` so type checkers stop treating agent I/O as opaque. Companion `ToolProtocol` conformance test added.
  - **Consolidated `Settings`** — All environment variable reads routed through a single typed `pydantic-settings` class; scattered `os.environ` lookups removed so misconfigured deployments fail fast at startup instead of deep inside a run.
  - **Adapter registry test isolation** — Autouse fixture resets the `AdapterRegistry` singleton between tests, eliminating cross-test leakage and flakes when suites register alternate engine backends.
  - **Schema-drift CI gate** — New snapshot test on `contracts/` Pydantic models fails the build on any unreviewed wire-format change; `scripts/generate_schemas.py` refreshes the canonical snapshot.
  - **OTEL parent-child trace assertion** — Regression test verifies the engine → agent span chain is preserved end-to-end so distributed traces remain connected in Jaeger / Tempo.
  - **Golden-output regression test** — Deterministic fixture locks the `code_review` workflow's final output; any behavioral drift in the native engine trips the test.
  - **CI lint + coverage enforcement** — Ruff runs as a required job and the 80% coverage floor is now enforced in GitHub Actions rather than advisory.
  - **MCP results cleanup** — Ruff `UP006` / `S324` fixes across `mcp/results` remove legacy typing forms and insecure hash defaults.

- **Epic 2 — Observable Execution (agentic-workflows-v2)**
  - **Typed execution-event wire format** — New `contracts/events.py` Pydantic discriminated union covers `workflow_start`, `step_start`, `step_end`, `step_complete`, `step_error`, `workflow_end`, and `evaluation_*`. WebSocket and SSE broadcasts validate before emit; client union in `ui/src/api/types.ts` stays in lockstep.
  - **Live DAG animation** — `@xyflow/react` nodes and edges animate through queued → running → complete / error states as events arrive on `/ws/execution/{run_id}`, so users can watch a run progress without opening server logs.
  - **StepNode B2 redesign** — Each node now renders an ASCII status chip, LLM tier pill, token counter, and a streaming-progress bar driven by live events.
  - **Step drill-down panel** — Click a node to see a five-field detail pane (inputs, outputs, status, timing, errors) that handles partial state gracefully while a step is still running.
  - **Playwright streaming PR gate** — New E2E job runs the streaming flow 5× per PR using `data-testid` hooks added across the UI; any single failure blocks merge.
  - **WebSocket reconnect-replay test** — Fault-injection E2E kills the socket mid-run and asserts the server's 500-event replay buffer restores UI state on reconnect.
  - **Time-to-first-span SLO + p95 gate** — New measurement test records first-span latency and fails the build if the p95 regresses past the contract.
  - **Nightly 50× reliability job** — Streaming E2E runs 50× on a nightly cron with a rolling flake-rate gate; reconnect and p95 contracts hardened alongside.

- **Epic 3 — DevEx / Windows (agentic-workflows-v2)**
  - **Windows bring-up hardening** — `scripts/setup-dev.ps1` one-command bootstrap validated in CI so a fresh Windows clone installs deps, validates workflows, and runs a smoke test without manual intervention.
  - **`port-guard` devex tool** — Detects and reports processes holding dev ports (8010 / 5173 / 6006) before server startup so conflicts surface with an actionable message instead of a cryptic bind error.
  - **`workspace-test-runner` tool** — Single entry point to run the right test suite for whichever package you're in (backend pytest, eval pytest, UI vitest).
  - **`workflow-linter` tool** — Validates YAML workflow definitions against the required-fields contract (`name`, `agent`, `description`, `depends_on`, `inputs`, `outputs`) before they reach the runtime.
  - **Windows Unicode CLI fix** — `agentic` CLI no longer crashes on the Windows default codepage when rendering non-ASCII output; CLI verification added to CI to prevent regressions.

- **Epic 6 — Evaluation & Data Depth (agentic-workflows-v2)**
  - **Contracts** — Additive Pydantic v2 models (`EvaluationCriterionDetail`, `ScoreLayersModel`, `HardGatesModel`, `FloorViolationModel`, `RunEvaluationDetail`, `DatasetSampleSummary`, …) mirrored as TypeScript interfaces in `ui/src/api/types.ts`; `EvaluationCompleteEvent` expanded with `passed`, `pass_threshold`, `criteria`.
  - **Tokens-30d stat** — `RunsSummaryResponse` gains `tokens_30d`; `run_logger.summary()` aggregates tokens across all runs started in the last 30 days; Dashboard live stat wired to real data.
  - **`GET /runs/{filename}/evaluation`** — Returns full rubric breakdown for any stored run, including criteria scores, score layers, hard gates, and floor violations.
  - **Dataset sample endpoints** — `GET /eval/datasets/sample-list?dataset_id=…&limit=…` and `GET /eval/datasets/sample-detail?dataset_id=…&sample_index=…`; dataset IDs use query params to handle slash characters.
  - **Evaluations page** — `EvaluationRubricAccordion` with lazy `[+]`/`[-]` expansion: criterion table (normalized %, ASCII progress bar, `[FLOOR]` badge), score layers, hard gate `[OK]`/`[FAIL]` rows, floor violation list.
  - **Datasets page** — 3-pane browser: dataset catalog → `SampleIndexGrid` (paginated `[<]`/`[>]`) → `DatasetDetailPane` (collapsible `[meta +/-]`, field rendering, JSON viewer, workflow preview badge).

- **Epic 5 — Console UI Polish (agentic-workflows-v2/ui)**
  - `StatusBadge` migrated to ASCII bracket format: `[OK ]` `[RUN]` `[ERR]` `[WARN]` using `--b-*` CSS tokens; works across dark / paper / bolt themes.
  - `useHotkeys` hook — global keyboard shortcuts (n / f / / / j / k / Esc) with input-focus guard and unmount cleanup.
  - Dashboard filter — `/` and `f` focus the filter input; `Esc` clears and blurs; narrows runs by workflow name or run ID.
  - State pages — `EmptyState` (`$ no <entity> yet`), `ErrorBanner` (`[!] {msg}`), `NotFoundPage` (404 terminal-style), `AppErrorBoundary` (React error boundary).
  - Skip-to-main link — visually hidden, appears on first Tab; `<main id="main-content">` as target.
  - Focus ring audit — `focus:ring-1 focus:ring-b-clay/50` added to all interactive elements; audit notes at `docs/a11y-focus-ring-audit.md`.
  - Paper theme contrast QA — `--b-text-dim` on `--b-bg1` verified at 7.45:1 (passes AA); bolt 5.92:1; dark 3.80:1 (dim tier, intentional).
  - `BDagMini` — pure SVG static DAG thumbnail; reuses `layoutDAG` (Kahn topological sort); linear chains render as vertical, parallel branches center-aligned per rank; themed via CSS vars.

- **`skill-architect` agent** — New AI persona specialized in designing, extracting, and refactoring skills as reusable prompt programs. Added to the canonical agent roster with full documentation.
- **`verify-and-correct` skill** — Bounded self-correction loop: automatically runs tests, lint, and type checks after code changes, then retries fixes (up to a limit) before reporting back. Reduces back-and-forth on build failures.
- **`session-plan` skill** — Plan a focused session with 1–2 goals, explicit success criteria, and a TODO checklist. Prevents mega-sessions that hit rate limits by scoping work upfront.
- **Headless prompts** — New infrastructure for running agent prompts without an interactive session.
- **Adapter registry CLI wiring (ADR-001)** — Orchestrator, workflow runner, and CLI now route through the adapter registry, making engine backends (native DAG, LangGraph) fully swappable at runtime.
- **SmartModelRouter hardening (ADR-002)** — Added persistence across restarts, `Retry-After` header support, and degraded-mode fallback so the router stays operational when providers are rate-limited or unavailable.

### Improvements

- **CI pipeline upgrades** — Updated `actions/setup-python` from v4 → v5 across all workflows. Added cross-package E2E job, expanded security scanning with `pip-audit`, and tightened dependency review to fail on severity `moderate`.
- **Release pipeline** — New tag-triggered `deploy.yml` with build provenance for reproducible releases.
- **Performance regression detection** — Rewrote `performance-benchmark.yml` to compare against a stored baseline and fail on detected regressions.
- **Secret sanitization rule** — Always-on sanitization middleware now redacts API keys, tokens, and passwords before they reach LLM context. Covers all agent sessions by default.
- **Backlog tracking** — Added 11 new backlog tickets (rows 34–44) covering architectural debt, test gaps, and documentation tasks.

### Security

- **P0 tool-layer hardening** — `http_ops`, `search_ops`, and `shell_ops` received critical security fixes: SSRF URL validation, shell injection blocklist (20+ blocked patterns), `shlex.split` with `shell=False`, path traversal guards, and `__builtins__` restriction in the code execution sandbox.

### Bug Fixes & Documentation

- Fixed factual drift across monorepo documentation (CLAUDE.md, AGENTS.md, README files, ADRs).
- Corrected 40+ dangling references to deleted prompts and removed workflows.
- Removed 23 duplicate tests, fixed 2 broken tests as part of ADR-008 test coverage overhaul.
- Aligned stale agent config entries with the current agent roster.

### Test Coverage (ADR-008)

- Added tests for 12+ previously untested modules, including evaluation pipeline, workflow pipeline, server backends, LLM judge, and scoring.
- Hardened server test coverage for streaming backends and session handling.
- Overall test coverage for `agentic_v2` raised toward the 80% target.

### Cleanup & Refactoring

- **Presentation system extracted** — The presentation/deck builder has been moved to the standalone Architecture Deck System repository (`separate presentation-system repository`). 245 files removed from this repo; raw-themes data and scripts are preserved in the new repo.
- Removed deprecated agent prompts, workflow definitions, local assistant config, and stale GitHub Actions workflows.
- Removed dead prompt constants, obsolete artifact files, and cleaned up `.gitignore`.

### Migration Notes

- **`presentation/` system extracted to a standalone repo (`separate presentation-system repository`).** If you imported anything from `presentation/*` or ran its deck-builder / token-generation scripts, those paths no longer exist here. 245 files moved.
  - **What moved:** brutalist deck builder, JSX + PPTX slide generators, theme registry, raw-theme token configs, Storybook catalog, and the accompanying test suite.
  - **What stayed:** `decks-generated/` (the output artifacts from the old builder) remains in this repo until downstream consumers migrate.
  - **Action required:** Update imports of `presentation.*` or `src/tokens/*` to point at the new `separate presentation-system repository` repo, OR pin a pre-2026-04 commit of this repo if you are not ready to migrate.
- **`agentic_v2.core.protocols.AgentProtocol.run` signature tightened** from `Any` to `object`. Code that relied on implicit-`Any` call sites may now surface previously hidden `mypy` errors; update call sites to use the bounded `TypeVar`s (`TInput` / `TOutput`) from `agentic_v2.agents.base`.

### Known Limitations

This release ships with the following known issues. All are tracked for Sprint B or later; none block the primary workflows documented in `docs/ONBOARDING.md`.

- **35 mypy findings in `agentic-v2-eval/`** are now visible in CI (`continue-on-error: true`, not blocking merges). One of them (`agentic_v2_eval/runners/streaming.py:216-235`) raises an object that is not derived from `BaseException` and is a real bug worth fixing in Sprint B. Tracked as "Sprint B #7-followup" in `eval-package-ci.yml`.
- **SLO p95 gate can pass trivially on empty data.** `readP95({ windowDays: 7 })` in `ui/e2e/slo-storage.ts` returns `0` when the rolling window has no records, which silently satisfies the `<= 2000ms` assertion. Mitigated by the nightly workflow appending one sample per run, but the first night after an `slo-data` branch reset is a free pass.
- **Schema-drift guard is root-properties-only.** `tests/test_schema_drift.py` checks the top-level `properties` of covered Pydantic models; field removals on nested models referenced via `$defs`, as well as any type narrowing (e.g., `str` -> `Literal[...]`), pass silently. Tracked for extension in Sprint B.
- **No true placeholder / no-LLM mode.** Both local runs and CI require at least one configured LLM provider. In CI we use `GITHUB_TOKEN` + `models: read` to reach GitHub Models (zero-cost on public repos). The Epic 2 plan referenced a placeholder toggle, but the toggle was not implemented. See ADR-016 (planned) for the rationale.
- **Python -> TypeScript wire-format mirror is manual.** `agentic_v2/contracts/events.py` is hand-mirrored in `ui/src/api/types.ts`; there is no codegen or drift-detection gate. An intentional schema change must be made in both files; a missed edit ships as a silent frontend bug.
- **UI build artifacts are git-tracked.** `agentic-workflows-v2/ui/dist/index.html` and `agentic-workflows-v2/ui/tsconfig.tsbuildinfo` are historical tracked files that re-dirty after every `npm run build`. A follow-up task is filed; expect `git status` noise after building the UI locally.

---

## Earlier History

For changes prior to March 2026, see the git log:

```
git log --oneline --before="2026-03-01"
```

---

## Version Links

[Unreleased]: https://github.com/tafreeman/agentic-runtime-platform/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/tafreeman/agentic-runtime-platform/releases/tag/v0.3.0
