# AI Implementation Evidence Standard — Scorecard

**Repo:** `agentic-runtime-platform`
**Method:** Evidence-only review. Original assessment (2026-06-10): 18 agents fanned out over the repo; 10 pattern/dimension claims re-checked by independent adversarial verifiers who opened the cited files and *ran the tests*. Regenerated 2026-07-03 from live code, then **refutation-verified later the same day** by a full 22-agent adversarial re-run: independent verifiers executed the suites (60/60 parsing, 205/207 router, 134 observability, 26/26 consensus, 26 approval-gate tests green) and ran the platform four independent keyless ways (two `examples/`, `agentic run code_review --adapter native`, pytest subsets). Every changed row below is now second-verifier confirmed — the earlier interim † markers are retired. Labels reflect what was verified, not what the README asserts.

---

## Verdict: **A− · Production-credible, pin-worthy**

This is a genuinely implemented multi-agent runtime, not a narrative repo. The headline subsystems — provider abstraction, tiered routing with circuit breakers, the Kahn's-algorithm DAG executor, structured-output parsing, tool dispatch, OpenTelemetry observability, and the evaluation/judge stack — are all **STRONG**: real code, wired into hot paths, and backed by *behavioral* tests. All six `examples/` run end-to-end under `AGENTIC_NO_LLM=1`, and CI enforces an 80% coverage gate credential-free.

The caveats that justified the minus at the original assessment — narrative-vs-code drift, two over-labeled patterns, missing approval gates, no consensus primitive, SSRF guard defaulting off — **have closed and are now refutation-verified** (remediation section below). The 2026-07-03 adversarial re-run graded the repo **maturity Level 4 (cap 5) and pin-worthy**, noting the code is stronger than its narrative in places. The minus now rests on a *new*, verifier-confirmed set of defects — three security gaps that contradict the fail-closed-governance headline, plus a fail-open consensus edge and an inert runtime budget path (see "Fix before featuring" below). All are assessed as fixable in days; none undermines the core capability labels.

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
| Human approval gates | **STRONG** ⬆ | Was **NONE**. `agentic_v2/governance/approval.py` (337 lines) + `escalation.py`; consulted *before* validation/execution in `engine/tool_execution.py` (`evaluate_tool_approval`); **fails closed** — gated tool w/ no registered provider is DENIED; hung provider fails closed within a bounded timeout (ADR-041); 19 tests in `tests/test_approval_gates.py` |
| Consensus / voting | **IMPLEMENTED** ⬆ | Was **NONE**. `agentic_v2/engine/consensus.py` (255 lines: ensemble + self-consistency primitives); 20 tests in `tests/engine/test_consensus.py` |
| ReAct | **IMPLEMENTED** ⬆ | Was **PARTIAL** (loop branch untested, `_is_task_complete` hardcoded). The agent loop's tool→observe→continue branch is now covered by `tests/test_agent_react_loop.py` (14 tests); `_is_task_complete` is a real overridable hook (e.g. `agents/architect.py`) |
| Planning / orchestration | **IMPLEMENTED** ⬆ | Behavioral orchestrator suites now exist (`tests/test_orchestrator_behavior.py`, `test_orchestrator_adaptive.py`, `test_agents_orchestrator.py`) — the original "shape tests only" caveat no longer holds |
| Token budgeting | **IMPLEMENTED** | `TokenBudget` enforced before cache, raises on overflow; tested |
| Refinement / iterative review | **IMPLEMENTED** | Original defect (inputs resolved once *before* the retry loop, staling `coalesce()` feedback) fixed in PR #70: `loop_until` inputs re-resolve each round |

⬆ = label changed in the 2026-07-03 refresh; independently confirmed by the same-day adversarial re-run (see Method).

---

## Dimension verdicts

- **AI / Deterministic boundary — STRONG (unusually disciplined).** Deterministic code owns parsing, structure recovery, enum normalization, path containment, and branch evaluation; the LLM owns only free-form content and *proposed* tool-call/status values, all re-derived before action. Fail-safe by design: any unparseable reviewer output is forced to `NEEDS_FIXES` — bad output can only trigger *more* review, never fake an approval.

- **Evaluation evidence — STRONG.** Three-stage gating (weighted hybrid → grade map → hard-gate force-to-F), non-compensatory multidimensional gate, immutable A–E profiles, committed golden fixture w/ refresh path. Judge bias controls are real: seeded criterion shuffle (`sha256(candidate || expected || prompt_version)`), swapped-order consistency flagging, `evaluate_calibration_set` MAE drift detection. **Gaps:** golden regression covers a subset of workflows; judge tests use mock providers (live-model judge quality unverified — by design for credential-free CI).

- **Production readiness (resilience + observability) — STRONG.** Classified jittered retries, DAG timeout watchdog, circuit breakers/bulkheads, token budgeting, TTL+LRU cache, opt-in OTEL. Secret-safety is deliberate: `api_key` fields are `repr=False`, prompt/response capture redacted-by-default.

- **Execution-path verification — STRONG.** All six examples executed under `AGENTIC_NO_LLM=1` at the original assessment; the no-LLM baseline is a maintained CI job (`no-llm-smoke`). The original README drift items (`run_workflow` signature, `researcher` role, OTEL attribute name, `result.cost` example) were corrected in PR #70 and re-checked in the Phase-1 docs pass (PR #147).

- **Security & governance — MIXED (strong primitives, three verifier-confirmed gaps).** Real and tested: shell-free exec w/ metacharacter rejection + fail-closed allowlist, file ops fail-closed on unset sandbox root w/ `resolve()` traversal+symlink containment, secret-stripped subprocess env, rlimit'd Python sandbox, RAG indirect-injection defenses, agent-loop sanitization default-on incl. the Claude/SDK agents, fail-closed approval gates in the dispatch path, SSRF blocking default-ON with DNS-rebinding pinning. The original wiring gaps are closed and refutation-verified. What keeps the dimension MIXED is a **new trio of verifier-confirmed defects** that contradict the fail-closed headline: (1) `tools/builtin/build_ops.py:120-164` — `build_app` executes install/build/test commands with **no approval gate and a bypassable substring denylist**, including a `create_subprocess_shell` path outside the shell allowlist; (2) `middleware/response_sanitizer.py:79-97` — findings classified "REDACTED" are **not actually scrubbed** from returned text (only Unicode is mutated); (3) `workflows/artifact_extractor.py:55-92` — a Windows **drive-letter path escapes** the `artifacts/<run_id>/` sandbox (only `..` traversal is covered), with extraction default-on. **Update (2026-07-08): all three are now fixed and tested** — `build_app` is gated (ADR-045); response secrets are masked with `[REDACTED:<category>]`; and `_safe_rel_path` rejects drive/UNC/root-absolute paths with a resolved containment check on write. The consensus fail-open is fail-closed on malformed config (its `None`-vote/golden half remains). See Remediation status below. Residuals: auth throttle in-process-only (`KNOWN_LIMITATIONS`); git write ops (`git_ops.py:74-96`) run without approval or cwd containment.

---

## Fix before featuring (2026-07-03 refutation findings — P2)

Verifier-confirmed; each contradicts a headline claim until fixed. All assessed fixable in days.

1. **Gate `build_app`** — **FIXED (2026-07-08):** `BuildAppTool.requires_approval` now returns `True`, so every `build_app` call is routed through `evaluate_tool_approval` before any phase runs; no provider → DENIED (fail-closed). See `tools/builtin/build_ops.py` (`requires_approval`), ADR-045, and the gate tests in `tests/test_approval_gates.py` (`test_build_app_gate_fires_before_execute`, `test_build_app_no_provider_fails_closed`, and the exhaustive `test_destructive_builtins_require_approval`). The bypassable substring denylist is retained only as defense-in-depth.
2. **Make "REDACTED" redact** — **FIXED (2026-07-08):** `SecretDetector.scan_and_mask` replaces each matched span with `[REDACTED:<category>]`, and `ResponseSanitizer` adopts the masked text whenever secret findings exist (`middleware/detectors/secrets.py`, `middleware/response_sanitizer.py`); CLEAN input still round-trips byte-identically. Test: `tests/test_response_sanitizer_redaction.py`. Scope note: the response path runs SecretDetector + UnicodeSanitizer only; PII redaction stays an inbound-`SanitizationMiddleware` concern.
3. **Close the drive-letter artifact escape** — **FIXED (2026-07-08):** `_safe_rel_path` now rejects any path absolute under either convention (Windows drive/UNC via `PureWindowsPath`, POSIX root), and `_write_files` re-verifies each destination resolves inside `run_dir` before writing (`workflows/artifact_extractor.py`). Test: `tests/test_artifact_extractor.py::TestDriveAnchorEscape` asserts nothing is written outside `run_dir`.
4. **Close the consensus fail-open** — **PARTIALLY FIXED (2026-07-08):** a missing/`None` `min_agreement` keeps the documented `0.0` default, but a present-but-unparseable or out-of-range value now raises `ConfigurationError` (fail-closed) instead of silently coercing to 0.0 (`engine/agent_resolver.py` `_coerce_min_agreement`; tests in `tests/engine/test_consensus_step.py`). **Still open:** `None` votes counting as valid consensus candidates, and regenerating `datasets/default/consensus_review_output.json`.
5. **Make the runtime budget real** — no production path calls `set_budget` (tests only), so `TokenBudget` is inert at runtime; install a settings-driven default and act on `consume()` returning False.
6. **Fix the nightly live-eval install** — **FIXED (2026-07-08, companion CI change):** the `eval-live-gate` install now uses the `[server]` extra (`.github/workflows/eval-package-ci.yml`), and `workflow_dispatch` + an extended live-gate `if:` make it verifiable on demand instead of only on the nightly. **Still open:** making `eval-golden-gate` a required status check (a branch-protection setting).
7. **Wire `loop_max` expression resolution** so the shipped `iterative_review.yaml` refines on the native path (`loader.py:681-688` converts `${inputs.max_review_rounds}` to sentinel 0; `engine/step.py` never reads `loop_max_expr`).
8. **Purge doc drift** — the `docs/index.md` stat strip is wrong on all three numbers; auto-compute or delete; remove the PDF/DOCX RAG-loader claim (`rag/loaders.py` is Markdown/Text only).

---

## Honest scope caveats

- LanceDB ANN, cross-encoder reranking, and the `agentic rag` CLI exist as code but were **not executed** (optional deps).
- The Windows AI / Phi Silica path is real code (Python + a C# bridge) but sits outside the CI-gated `agentic_v2` package.
- Test *counts* and coverage *percentages* are deliberately not restated here — they drift. The enforced floors live in CI (80% on `agentic_v2`, credential-free) and the suites cited above are the evidence.

---

## Remediation status (maintainer-tracked)

- **P0 (original "fix three things"): DONE** — PR #70 (merged 2026-06-10): sanitization wired into `complete_chat` default-on/fail-closed, `loop_until` inputs re-resolved each round, README over-claims corrected.
- **P1: CLOSED and refutation-verified** — ReAct iteration wiring (#9 → `tests/test_agent_react_loop.py`), planning/orchestration behavioral tests (#10 → orchestrator suites), consensus/voting (#11 → `engine/consensus.py`, verifier label IMPLEMENTED), human approval gates (#12 → `governance/approval.py` + ADR-041), SSRF default-on (#13 → `settings.py` default=True + `.env.example`).
- **P2: PARTIALLY CLOSED (2026-07-08)** — the three HIGH security defects (items 1-3: `build_app` gate, response-path redaction, artifact drive-letter escape) are fixed and tested; the consensus fail-open (item 4) is now fail-closed on malformed/out-of-range config (its `None`-vote + golden-regen half remains); and the eval-live-gate `[server]` install (item 6) is fixed via a companion CI change. Items 5, 7, 8 and the noted residuals remain OPEN.
- **Standing residuals:** in-process-only auth throttle (multi-replica deployments need a shared store); live-model judge calibration corpus (mock-judged in CI by design).
