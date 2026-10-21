# REVIEW.md
<!-- Read by the AI reviewer from the BASE branch only. Byte-stable. Owner: @tafreeman. Changes route to high_risk. -->

## What this repo is
Tier-routed multi-agent LLM runtime (Python 3.11, FastAPI, Pydantic v2, asyncio): YAML workflows compile to a DAG run by a native asyncio executor or a LangGraph adapter, with a React dashboard and a governance layer (human tool approval, SSRF guard). Packages: `agentic-workflows-v2/` (runtime), `agentic-v2-eval/` (eval harness), root `tools/`. Solo-maintained; CI evidence gates correctness.

## Invariants a change must not break
- With no `ApprovalProvider` registered, a tool call needing approval is DENIED, never run — `agentic_v2/governance/approval.py`. Checked: `tests/test_approval_gates.py`; `ek-delegation-tests` job.
- Every `BaseTool` subclass's `execute` is wrapped by the approval gate (ADR-047) — `agentic_v2/tools/base.py`. Checked: `tests/test_approval_gates.py`.
- `@tool` functions in `agentic_v2/langchain/tools.py` are outside that wrapper; each sensitive one must call `_check_tool_approval` first. Not checked by CI for new tools.
- Outbound HTTP uses the SSRF guard with connection pinning (ADR-030) — `agentic_v2/security/url_guard.py`. Checked: `tests/test_ssrf_guard.py`.
- Pydantic contracts drive committed JSON schemas and generated TypeScript (ADR-014) — `agentic_v2/contracts/`, `tests/schemas/`, `ui/src/api/*.generated.ts`. Checked: `wire-format-drift` job.
- `agentic_v2/engine` and `agentic_v2/contracts` stay strictly typed. Checked: `Mypy (strict engine + contracts)` job (`--follow-imports=skip`).
- No new lint or mypy suppressions — `agentic-workflows-v2/scripts/check_suppression_ratchet.py`. Checked: `lint` job.
- Coverage stays above `fail_under` in `agentic-workflows-v2/pyproject.toml`. Checked: `test-coverage` job. Unit tests pass without provider keys (`AGENTIC_NO_LLM=1`). Checked: `no-llm-smoke` job.
- Secrets never reach logs, responses or git; masking is in `agentic_v2/middleware/response_sanitizer.py` (ADR-046, ADR-061). Checked: `tests/test_response_sanitizer_redaction.py`. `detect-secrets` runs in pre-commit only.
- Required check names (list in the `ci.yml` header) are never renamed; no workflow-level `paths:`. Not checked by CI; a violation stalls every PR.
- The two workspace packages do not import each other. Not checked by CI.
- Scheduler guarantees are modelled in Lean (ADR-060) — `proofs/`. Checked: `lean-proofs.yml` (path-gated, not required). No `sorry`, no new axioms.

## High-risk areas and what to look for there
| Path | Look for |
|---|---|
| `agentic-workflows-v2/agentic_v2/governance/**` | A path where a gated tool runs without a decision; default-allow; swallowed provider errors; a timeout that approves. |
| `agentic_v2/security/**` | SSRF bypass: redirects, DNS rebinding, IPv4-mapped IPv6, allowed metadata hosts, unpinned connects. |
| `agentic_v2/server/auth*.py`, `server/middleware/**` | A new `/api/` route skipping auth; non-constant-time compare; weakened throttle or JWT/OIDC checks. |
| `agentic_v2/models/backends*.py`, `models/secrets.py` | Secrets logged or placed in exceptions; keys read outside `get_secret`; fallback silently switching keys. |
| `agentic_v2/langchain/tools.py` | `http_get` and `web_search` are NOT approval-gated (`http_get` has the SSRF guard). A new or changed `@tool` that writes, executes or reaches the network without `_check_tool_approval`. |
| `agentic_v2/tools/builtin/shell_ops.py` | Weakened metacharacter or dangerous-command checks, `shell=True`, wider subprocess env. |
| `agentic_v2/integrations/mcp/**` | `McpToolAdapter` is not a `BaseTool`, so the structural gate does not cover it; unsanitized remote output; removed timeout or budget. |
| `agentic_v2/scoring/**`, `agentic_v2/prompts/judges/**` | Rubric or judge-prompt changes that move scores without a golden update; scorer accepting missing criteria. |
| `scripts/eval_gate.py` | Gate made easier to pass: lower threshold, ignored `missing_criteria`, skipped cases, exit 0 on error. |
| `proofs/**` | `sorry`, new `axiom`, edited axiom guards, model drifting from the executor. |
| `.github/**` | Unpinned action refs, `${{ }}` of untrusted values in `run:`, broader `permissions:`, new triggers, auto-merge scope, renamed required jobs. |

## Conventions the reviewer should assume
- Steps name a capability tier, never a model; routing is `SmartModelRouter`.
- Ruff (line length 88) and Black are authoritative; rule set and ignores are in `agentic-workflows-v2/pyproject.toml`.
- Conventional Commits; material design changes get an ADR in `docs/adr/`.
- Golden files and `tests/schemas/` are regenerated, never hand-edited.
- Unit tests are key-free and deterministic; env changes go through `monkeypatch`.

## Do not flag (repo-specific)
- Auth middleware is a no-op when `AGENTIC_API_KEY` is unset: deliberate local-dev mode; startup logs a warning.
- The approval provider is a process-wide module global: documented in `governance/approval.py`.
- `AutoApproveProvider` exists for trusted use; flag only if registered by default.
- `async def` with no `await` on Protocol/ABC implementations and registered step functions: the interface needs it.
- ReactFlow `as unknown as X` casts in the UI: required to compile.
- `S101`/`S105`/`S106` in `tests/**`: configured ignores; fixtures hold fake secrets and redaction corpora.
- Modules under `[tool.coverage.run] omit` need live providers or the optional `executionkit` extra.
- Tracked evidence under `agentic-workflows-v2/evals/swe_ab/`; files listed in ADR-055 exceed the size guideline.

## Severity calibration for this repo
- CRITICAL: approval/auth/SSRF bypass, secret exposure, a CI gate weakened or skipped, unpinned or over-privileged workflow.
- HIGH: wrong results on the execution or scoring path, wire-contract change without regenerated artifacts, an ungated sensitive tool.
- MEDIUM: untested behavior change; error handling that hides failures.
- LOW: style and naming. Never raise what Ruff or Black already enforce.

## Out of scope for AI review
- Generated files: `uv.lock`, `ci-constraints.txt`, `*.generated.ts`, `tests/schemas/*.json`, `package-lock.json`.
- `docs/inventory/`, dated audit reports, `docs/adr/drafts/`, `datasets/` content.
