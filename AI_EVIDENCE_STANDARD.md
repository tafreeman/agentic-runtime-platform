# AI Implementation Evidence Standard — Scorecard

**Repo:** `agentic-runtime-platform`
**Method:** Evidence-only review. 18 agents fanned out over the repo; 10 pattern/dimension claims were re-checked by independent adversarial verifiers who opened the cited files and *ran the tests*. Labels below reflect what was verified, not what the README asserts.

---

## Verdict: **A− · Production-credible, pin-worthy with caveats**

This is a genuinely implemented multi-agent runtime, not a narrative repo. The headline subsystems — provider abstraction, tiered routing with circuit breakers, the Kahn's-algorithm DAG executor, structured-output parsing, tool dispatch, OpenTelemetry observability, and the evaluation/judge stack — are all **STRONG**: real code, wired into hot paths, and backed by *behavioral* tests that the verifiers executed and watched pass (router 57 + redis 29, DAG 28, backends 77, eval 256, observability 85, tool calling 74). All six `examples/` run end-to-end under `AGENTIC_NO_LLM=1`, and CI enforces an 80% coverage gate credential-free.

What keeps it from an unqualified A is a thin but real layer of **narrative-vs-code drift** and two patterns that look stronger in the README than in the test suite. None of it is fatal; all of it is honestly fixable.

---

## Pattern labels (evidence-graded)

| Pattern | Label | Basis |
|---|---|---|
| Provider abstraction | **STRONG** | ABC + 6 cloud + 2 local backends, real per-provider format translation; 77 tests ran green |
| Routing | **STRONG** | Health-weighted scoring, adaptive cooldowns, circuit breaker state machine, cross-tier degradation, Redis CAS; 57 tests |
| DAG / workflow orchestration | **STRONG** | Event-driven `asyncio.wait(FIRST_COMPLETED)`, cascade-skip, timeout watchdog w/ structural cancel; 28 tests |
| Structured output | **STRONG** | 422-line parser w/ salvage + sentinel `<<<ARTIFACT>>>` blocks, Pydantic discriminated event union; 106 tests |
| Tool calling | **STRONG** | Schema-gen + multi-round dispatch loop, 12 builtin tools (3.5k lines), fail-closed shell allowlist; 74 tests |
| Observability | **STRONG** | OTEL traces/metrics wired into engine+agent+router hot paths, parent/child span propagation test; 85 tests |
| Eval-driven development | **STRONG** | LLM-judge w/ positional-bias mitigation + MAE calibration, hard gates, A–E profiles; 256 tests |
| Planning / orchestration | **IMPLEMENTED** | Real capability-scored assignment + fallback chains in code, but assignment correctness / dependency ordering / fallback recovery are **untested** (happy-path shape tests only) |
| Token budgeting | **IMPLEMENTED** | `TokenBudget` enforced before cache, raises on overflow; tested |
| ReAct | **PARTIAL** ⬇ | `base.py` loop exists but its tool→observe→continue branch is **untested**; the *tested* ReAct lives in a different module (`engine/tool_execution.py`) the agent loop doesn't call; `ClaudeAgent._is_task_complete` hardcodes `True` so the one real-LLM agent never iterates |
| Refinement / iterative review | **PARTIAL** ⬇ | Shipped `iterative_review.yaml` is a self-labeled **demo** no test loads; cited engine loop resolves inputs **once before** the retry loop, so `coalesce()` feedback is stale on re-iteration — the convergence mechanism is broken on the cited path |
| Consensus / voting | **NONE** | No ensemble/majority-vote/self-consistency anywhere (grep-confirmed) |
| Human approval gates | **NONE** | No `wait_for_human`/`require_approval`; tools execute the instant the LLM emits a call |

⬇ = adversarial verifier **downgraded** the finder's original `IMPLEMENTED` label.

---

## Dimension verdicts

- **AI / Deterministic boundary — STRONG (unusually disciplined).** Deterministic code owns parsing, structure recovery, enum normalization, path containment, and branch evaluation; the LLM owns only free-form content and *proposed* tool-call/status values, all re-derived before action. Fail-safe by design: any unparseable reviewer output is forced to `NEEDS_FIXES` — bad output can only trigger *more* review, never fake an approval. **Residual gap:** file/artifact *content* is written verbatim with no payload validation (path is sandboxed, contents are not), and non-review agent outputs stay untyped `dict[str, Any]`.

- **Evaluation evidence — STRONG.** Three-stage gating (weighted hybrid → grade map → hard-gate force-to-F), non-compensatory multidimensional gate, immutable A–E profiles, a committed 274-line golden fixture w/ refresh path. 53 + 262 tests ran green. **Gaps:** no on-disk human-labeled calibration corpus, golden regression covers only 1 of 6 workflows, judge tests use mock providers (live-model judge quality unverified — by design for credential-free CI).

- **Production readiness (resilience + observability) — STRONG.** Classified jittered retries, DAG timeout watchdog, circuit breakers/bulkheads, token budgeting, TTL+LRU cache, opt-in OTEL. Secret-safety is deliberate: `api_key` fields are `repr=False`, prompt/response capture redacted-by-default. 143 + 21 tests green. **One fabricated claim:** README's `result.cost → TokenUsage(...)` — no such attribute/type on the actual `WorkflowResult` (`TokenUsage` is an external `executionkit` type).

- **Execution-path verification — STRONG.** All six examples executed under `AGENTIC_NO_LLM=1`; 21/21 no-LLM tests pass. **Narrative drift:** `researcher` role documented but no agent/persona exists; README `run_workflow` signature wrong (`inputs=dict` vs `**inputs`); timeout OTEL attr is `workflow.…`, not README's `dag.timeout_exceeded`.

- **Security & governance — MIXED (strong primitives, weak wiring).** Real and tested: shell-free exec w/ metacharacter rejection + fail-closed allowlist, file ops fail-closed on unset sandbox root w/ `resolve()` traversal+symlink containment, secret-stripped subprocess env, rlimit'd Python sandbox, RAG indirect-injection defenses. **But governance lags the "production-grade / regulated" branding:** inbound/outbound sanitization is wired only at the HTTP boundary — inside the agent loop `get_client()` returns `sanitization=None`, so tool outputs and retrieved content fed back to per-step LLM calls (the classic indirect-injection vector) are **unguarded**; **no human approval gates** on any high-impact action; SSRF private/loopback blocking defaults **off** and doesn't resolve DNS or guard redirects; auth throttle is in-process-only (multi-replica bypass, per the repo's own `KNOWN_LIMITATIONS`).

---

## If you fix three things before pinning

1. **Wire `with_sanitization()` into the agent loop** (not just the HTTP boundary) — closes the indirect-prompt-injection vector that most undercuts the regulated-environment claim.
2. **Repair or relabel refinement** — re-resolve step inputs inside the `loop_until` body so `coalesce()` feedback actually flows, and add a convergence test; or label `iterative_review.yaml` as the example it is.
3. **Correct the README** — fix the `run_workflow` signature, drop/implement the `researcher` role, fix the `result.cost`/`TokenUsage` example and the OTEL attribute name. These are the only places the repo over-claims.

---

## Honest scope caveats (verifier-disclosed)

- Strength ratings for the security dimension rest on *reading* test files, not a green run; the eval/router/DAG/tooling ratings were confirmed by actually executing the suites.
- LanceDB ANN, cross-encoder reranking, and the `agentic rag` CLI exist as code but were **not executed** (optional deps).
- The Windows AI / Phi Silica path is real code (Python + a C# bridge) but sits outside the CI-gated `agentic_v2` package and couldn't run here.

---

## Remediation status (maintainer-tracked)

- **P0 (items 1–3 above): DONE** — landed via PR #70 (`44a1d7d`, merged 2026-06-10): sanitization wired into `complete_chat` default-on/fail-closed, `loop_until` inputs re-resolved each round, README over-claims corrected. Known residual: `ClaudeAgent`/`claude_sdk_agent` call the Anthropic SDK directly and bypass the sanitization wrapper (tracked under P1 #9).
- **P1 (open):** #9 ReAct iteration wiring · #10 planning/orchestration behavioral tests · #11 consensus/voting · #12 human approval gates · #13 SSRF default-on + DNS + redirect re-validation.
