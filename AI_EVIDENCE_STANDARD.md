# AI Implementation Evidence Standard — Scorecard

**Repo:** `agentic-runtime-platform`
**Method:** Evidence-only review. Original assessment (2026-06-10): 18 agents fanned out over the repo; 10 pattern/dimension claims re-checked by independent adversarial verifiers who opened the cited files and *ran the tests*. **Regenerated 2026-07-03:** a fresh evidence sweep (claims inventory, code map, pattern + dimension scans) re-collected the basis below; every row that *changed* since the original run was re-verified directly against live code and carries a file-level citation. The refresh's independent adversarial-refutation stage was cut short by an infrastructure budget limit — changed rows therefore rest on direct code citation rather than a second blind verifier, and are marked †. Labels reflect what was verified, not what the README asserts.

---

## Verdict: **A− · Production-credible, pin-worthy**

This is a genuinely implemented multi-agent runtime, not a narrative repo. The headline subsystems — provider abstraction, tiered routing with circuit breakers, the Kahn's-algorithm DAG executor, structured-output parsing, tool dispatch, OpenTelemetry observability, and the evaluation/judge stack — are all **STRONG**: real code, wired into hot paths, and backed by *behavioral* tests. All six `examples/` run end-to-end under `AGENTIC_NO_LLM=1`, and CI enforces an 80% coverage gate credential-free.

The caveats that justified the minus at the original assessment — narrative-vs-code drift, two over-labeled patterns, missing approval gates, no consensus primitive, SSRF guard defaulting off — **have since closed** (evidence in the remediation section below). The grade is held at A− pending a full adversarial re-run of the refreshed evidence; the pin-worthy verdict no longer carries the original caveats.

---

## Pattern labels (evidence-graded)

| Pattern | Label | Basis |
|---|---|---|
| Provider abstraction | **STRONG** | ABC + 6 cloud + 2 local backends, real per-provider format translation; behavioral suite ran green at original assessment |
| Routing | **STRONG** | Health-weighted scoring, adaptive cooldowns, circuit breaker state machine, cross-tier degradation, Redis CAS |
| DAG / workflow orchestration | **STRONG** | Event-driven `asyncio.wait(FIRST_COMPLETED)`, cascade-skip, timeout watchdog w/ structural cancel |
| Structured output | **STRONG** | Parser w/ salvage + sentinel `<<<ARTIFACT>>>` blocks, Pydantic discriminated event union |
| Tool calling | **STRONG** | Schema-gen + multi-round dispatch loop, builtin tools, fail-closed shell allowlist |
| Observability | **STRONG** | OTEL traces/metrics wired into engine+agent+router hot paths, parent/child span propagation test |
| Eval-driven development | **STRONG** | LLM-judge w/ seeded criterion-shuffle positional-bias mitigation, swapped-order consistency checks, MAE calibration (`docs/evaluation/judge.md`); three-stage gating w/ six hard gates and `enforce_hard_gates=True` production default (`docs/evaluation/gating.md`) |
| Human approval gates | **STRONG** †⬆ | Was **NONE**. `agentic_v2/governance/approval.py` (337 lines) + `escalation.py`; consulted *before* validation/execution in `engine/tool_execution.py` (`evaluate_tool_approval`); **fails closed** — gated tool w/ no registered provider is DENIED; hung provider fails closed within a bounded timeout (ADR-041); 19 tests in `tests/test_approval_gates.py` |
| Consensus / voting | **IMPLEMENTED** †⬆ | Was **NONE**. `agentic_v2/engine/consensus.py` (255 lines: ensemble + self-consistency primitives); 20 tests in `tests/engine/test_consensus.py` |
| ReAct | **IMPLEMENTED** †⬆ | Was **PARTIAL** (loop branch untested, `_is_task_complete` hardcoded). The agent loop's tool→observe→continue branch is now covered by `tests/test_agent_react_loop.py` (14 tests); `_is_task_complete` is a real overridable hook (e.g. `agents/architect.py`) |
| Planning / orchestration | **IMPLEMENTED** †⬆ | Behavioral orchestrator suites now exist (`tests/test_orchestrator_behavior.py`, `test_orchestrator_adaptive.py`, `test_agents_orchestrator.py`) — the original "shape tests only" caveat no longer holds |
| Token budgeting | **IMPLEMENTED** | `TokenBudget` enforced before cache, raises on overflow; tested |
| Refinement / iterative review | **IMPLEMENTED** | Original defect (inputs resolved once *before* the retry loop, staling `coalesce()` feedback) fixed in PR #70: `loop_until` inputs re-resolve each round |

†⬆ = label changed in the 2026-07-03 refresh, verified by direct file citation (see Method).

---

## Dimension verdicts

- **AI / Deterministic boundary — STRONG (unusually disciplined).** Deterministic code owns parsing, structure recovery, enum normalization, path containment, and branch evaluation; the LLM owns only free-form content and *proposed* tool-call/status values, all re-derived before action. Fail-safe by design: any unparseable reviewer output is forced to `NEEDS_FIXES` — bad output can only trigger *more* review, never fake an approval.

- **Evaluation evidence — STRONG.** Three-stage gating (weighted hybrid → grade map → hard-gate force-to-F), non-compensatory multidimensional gate, immutable A–E profiles, committed golden fixture w/ refresh path. Judge bias controls are real: seeded criterion shuffle (`sha256(candidate || expected || prompt_version)`), swapped-order consistency flagging, `evaluate_calibration_set` MAE drift detection. **Gaps:** golden regression covers a subset of workflows; judge tests use mock providers (live-model judge quality unverified — by design for credential-free CI).

- **Production readiness (resilience + observability) — STRONG.** Classified jittered retries, DAG timeout watchdog, circuit breakers/bulkheads, token budgeting, TTL+LRU cache, opt-in OTEL. Secret-safety is deliberate: `api_key` fields are `repr=False`, prompt/response capture redacted-by-default.

- **Execution-path verification — STRONG.** All six examples executed under `AGENTIC_NO_LLM=1` at the original assessment; the no-LLM baseline is a maintained CI job (`no-llm-smoke`). The original README drift items (`run_workflow` signature, `researcher` role, OTEL attribute name, `result.cost` example) were corrected in PR #70 and re-checked in the Phase-1 docs pass (PR #147).

- **Security & governance — STRONG (was MIXED).** † Real and tested: shell-free exec w/ metacharacter rejection + fail-closed allowlist, file ops fail-closed on unset sandbox root w/ `resolve()` traversal+symlink containment, secret-stripped subprocess env, rlimit'd Python sandbox, RAG indirect-injection defenses. The three wiring gaps that made this MIXED have closed: sanitization is wired into the agent loop default-on/fail-closed (PR #70) and the Claude/SDK agent bypass was subsequently closed (`agents/implementations/claude_agent.py`, `claude_sdk_agent.py` now route through sanitization); **human approval gates** exist, fail closed, and sit in the tool-dispatch path (see pattern row); **SSRF private/loopback blocking defaults ON** (`agentic_v2/settings.py` `agentic_block_private_ips: default=True`; `.env.example` ships `AGENTIC_BLOCK_PRIVATE_IPS=1`; `security/url_guard.py`). Residual: auth throttle remains in-process-only (multi-replica bypass, per the repo's own `KNOWN_LIMITATIONS`).

---

## Honest scope caveats

- The 2026-07-03 refresh re-verified *changed* rows by direct code/test citation; the independent adversarial-refutation stage did not complete (infrastructure budget limit). Unchanged STRONG rows carry over from the original verifier-executed run.
- Rows marked † were verified by the maintainer's orchestrator opening the cited files, not by a second blind agent. A full adversarial re-run is the trigger for reconsidering the A− grade.
- LanceDB ANN, cross-encoder reranking, and the `agentic rag` CLI exist as code but were **not executed** (optional deps).
- The Windows AI / Phi Silica path is real code (Python + a C# bridge) but sits outside the CI-gated `agentic_v2` package.
- Test *counts* and coverage *percentages* are deliberately not restated here — they drift. The enforced floors live in CI (80% on `agentic_v2`, credential-free) and the suites cited above are the evidence.

---

## Remediation status (maintainer-tracked)

- **P0 (original "fix three things"): DONE** — PR #70 (merged 2026-06-10): sanitization wired into `complete_chat` default-on/fail-closed, `loop_until` inputs re-resolved each round, README over-claims corrected.
- **P1: CLOSED** as of this refresh, each with live-code evidence cited in the pattern table above — ReAct iteration wiring (#9 → `tests/test_agent_react_loop.py`), planning/orchestration behavioral tests (#10 → orchestrator suites), consensus/voting (#11 → `engine/consensus.py`), human approval gates (#12 → `governance/approval.py` + ADR-041), SSRF default-on (#13 → `settings.py` default=True + `.env.example`).
- **Open residuals:** in-process-only auth throttle (multi-replica deployments need a shared store); live-model judge calibration corpus (mock-judged in CI by design).
