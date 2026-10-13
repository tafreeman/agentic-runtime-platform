## 9. Work status — ongoing, stalled, and future

> Snapshot taken 2026-10-12/13 against `origin/main` = `c3b2d328` (tafreeman/agentic-runtime-platform#387, ADR-062). Git/PR state moves hourly in this repo (several concurrent sessions); counts below were re-read from `git`/`gh` at write time and several differ from the pre-extracted JSON. Where they differ, the live value is used and the difference is called out.

### 9.0 Headline numbers

| Metric | Value | Source |
|---|---|---|
| Open PRs | 6 (#382, #383, #384, #388, #389, #390) | `gh pr list -R tafreeman/agentic-runtime-platform` |
| Of which feature/UI work | 3 (#388, #389, #390) | same |
| Of which Dependabot | 3 (#382, #383, #384) | same |
| Open GitHub issues | 0 | `meta_inventory.json` `git.open_issues` |
| Pushed feature branches with no PR | 2 (`feature/criterion_aggregation`, `feature/el_screen_restyle`) | `git ls-remote --heads origin` vs open PRs |
| Local worktrees (incl. this inventory's) | 9 | `git worktree list` |
| Stashes | 3 | `git stash list` |
| Real code-level TODO/FIXME/HACK/XXX markers | 1 (`TODO(ADR-001)`) | grep over main worktree, §9.4 |
| Open-ended "Proposed" ADRs | 5 (007, 010, 011, 012, 034) | `docs/adr/ADR-INDEX.md` |
| Merged PRs since 2026-09-25 | 33 commits on main | `git log origin/main --since=2026-09-25` |

---

### 9.1 Ongoing work

| Item | Branch / PR | Size | State | Next step |
|---|---|---|---|---|
| Evidence Ledger UI redesign — tokens, primitives, DataTable, FilterBar (ADR-054 follow-on) | `feature/evidence_ledger_port` / tafreeman/agentic-runtime-platform#388 | +3,152 / -123, 17 files | OPEN, `mergeable: MERGEABLE`, `mergeStateStatus: BLOCKED`, 0 failing checks, 1 pending, no review decision. Local checkout is `ahead 3, behind 14` of `origin/main` (head `3dbfae10`, 2026-10-10); origin copy `74123cb4` already merged main | Wait for checks, get the single review (global rule: one approval, PRs <~400 lines — this one is ~8x over), then merge. Consider splitting tokens vs components if review stalls |
| Evidence Ledger screen restyle (existing screens re-themed) | `feature/el_screen_restyle` @ `1d28dce3`, no PR | +466 / -551, 36 files; 15 commits behind main | Pushed, worktree `C:/Users/tandf/.codex/worktrees/evidence-ledger-ui/agentic-runtime-platform`. Stacked on #388 (carries its commits `a9ba66a3`, `9ad6bca3`, `1572d32a`) | Hold until #388 merges, rebase, open PR |
| Local ignore rules for design-tool scratch under `docs/ui/` | `chore/ignore_docs_ui_scratch` / #389 | +18, 1 file | OPEN, BLOCKED (1 check pending) | Merge as soon as checks go green; it is what stops the ~350 untracked `docs/ui` files from polluting `git status` |
| `app_improvement_review` workflow (evidence-based app review) | `feature/app_improvement_review` / #390 | +639 / -2, 8 files; 3 commits (`65890f36`, `57a8c879`, `adddb23f`) | OPEN, BLOCKED; branch is 0 behind main. Worktree `C:/tmp/arp-appreview` | Review + merge; confirm shipped-workflow gate registration (commit `57a8c879`) |
| Criterion aggregation + independent eval gate (G1 of tech-debt plan) | `feature/criterion_aggregation` (no PR) | local `a6ee2520`: +854 / -141, 12 files; origin copy `32180ede`: +1,373 / -201, 16 files | Local branch was **rebased onto main during this session** (0 behind main) but is `ahead 63, behind 1` of its own origin copy — push needed (force-with-lease, owner's call) | See §9.2: effectively stalled until pushed and a PR opened |
| Dependabot `pip-root-llm` (15 updates) | `dependabot/pip/pip-root-llm-06dfaa602f` / #382 | +18 / -18, 3 files | OPEN, `reviewDecision: APPROVED`, 0 failing, 1 pending, BLOCKED on pending check. Relocked in `eba4f777` (local branch `relock-382`) | Merge when the last check lands (needs explicit authorization per global rule) |
| Tech-debt delivery plan G0–G7 | `docs/tech_debt_plans` @ `8e61318c` in `C:/tmp/arp-plans`, 1 commit ahead of main, unpushed, no PR | +460, 4 docs (`docs/plans/2026-09-10-tech-debt-workflow.md` + 3 addenda) | Planning docs only; the plan itself says "does not assert that the planned changes ... have completed" | Push + PR the docs (small), then start G0 baseline reconciliation |
| Probe-tooling edits (uncommitted) | live checkout, no branch of its own | +47 / -1: `tools/llm/probe_config.py` (+28), `tools/llm/probe_discovery_providers.py` (+13), `.env.example`, `.gitignore` | Uncommitted tracked modifications on `feature/evidence_ledger_port` — unrelated to the UI branch they sit on | Move to a `chore/` branch or stash before the next `git checkout`; do not let them ride into #388 |
| Untracked Evidence Ledger components (live checkout) | live checkout, untracked | `agentic-workflows-v2/ui/src/components/el/{ApprovalGate,EventLog,LiveSteps,ModelChain,ReRunSheet,TierLanes,Waterfall}.tsx`, `el/timeScale.ts`, `ui/src/lib/runSentence.ts` (~2.1k lines per brief) | Not committed anywhere; exists only on this machine | Commit to a branch (follow-up to #388) or it is one `git clean` from loss |
| Model-pack builder follow-ups (ADR-054) | merged #373, #374 | — | Shipped 2026-10-10/11; no open follow-up PR found | None open |

---

### 9.2 Stalled work

| Item | Why stalled | Age | Recommended action |
|---|---|---|---|
| Dependabot `pip-root-rest` (38 updates) — #384 | 26 failing checks (every `test (os, py)` leg, `lint`, `type-check`, `Mypy (strict engine + contracts)`, `wire-format-drift`, `e2e-streaming`, `eval-golden-gate`, `no-llm-smoke`, `python-smoke`, `EK step-delegation`, `EvalKit bridge`, `Claude subscription backend tests`, `tools/ tests`, `test-coverage`, `Build release assets`, `Build and test devcontainer`, `ci-constraints.txt in sync`) — real breakage from the bulk bump, not just a stale lock | Opened 2026-10-12 16:32Z | **Close and let Dependabot regroup**, or relock then bisect: apply the 38 bumps in 3-4 batches (memory: `deps-land-via-manual-batches`). Do not rebase it blind |
| Dependabot `pip-root-tooling` (4 updates) — #383 | Exactly one failure: `ci-constraints.txt in sync with uv.lock` (GITHUB_TOKEN-pushed relocks start no CI; Dependabot does not touch `uv.lock`) | 2026-10-12 16:24Z | **Relock** with `uvx uv@0.11.2` (CI pins 0.11.2), export constraints, push from a user account (audit lesson: `remediation-progress-2026-09-23.md` §Lessons). Then merge |
| `feature/criterion_aggregation` (F5/F6 → G1) | No PR; origin copy `32180ede` is 62 commits behind `origin/main`; the rebased local copy `a6ee2520` is unpushed. Touches `scripts/eval_gate.py`, `scoring/evalkit_bridge.py`, `.github/workflows/{ci,eval-package-ci}.yml`, ADR-042 — high conflict surface with the 62 main commits it missed | Origin copy: 2026-10-12 (commit date) but based on a main from before 2026-09-25 | **Rebase (already done locally), push, open PR.** Required gate must be proven green with neither legacy eval nor EvalKit installed (plan G1 done-when) before touching G2 (legacy removal) |
| ADR-042 cutover (`step_scoring.py` still imports in-tree `agentic_v2_eval`) | Accepted/partially implemented since 2026-07; only the additive `evalkit_bridge` landed (docs/ROADMAP.md §3c) | ~3 months | Same PR as above (G1/G2). Land or explicitly re-scope |
| `docs/HANDOFF.md` (proof handoff 2026-09-26) | Stale: names PR #354 and #353 as open/in-flight; both merged 2026-09-26 (#353 `fix(engine): make DAG.validate's cycle check iterative`, #354 `feat(proofs): prove timeout cleanup always fails closed`). Its Scope-lock says "SOLID queue is empty" | 17 days | Rewrite or delete; it also tells future sessions to ignore other work |
| `docs/ROADMAP.md` / `docs/KNOWN_LIMITATIONS.md` | "Last verified" 2026-07-28; no entry for the Sept–Oct 2026 work (Lean proofs ADR-060, plan_tribunal, Evidence Ledger, model packs, NIM/GH-Models retirements) | 76 days | Refresh next time `just docs` scope is touched; note memory `docs-refs-check-scope` — `check_docs_refs.py` only scans a fixed file list, so these rot silently |
| 3 git stashes | `stash@{0}` `On feature/study-telemetry: epitaxy: pre-switch ...`; `stash@{1}` `On wip_sweep: uncommitted uv.lock + band_cases.py + build_rebench_cases.py ...`; `stash@{2}` `On adr_016: WIP adr_016: bug fixes, tier-0 steps, websocket compat, new tests (Aug 3)` | stash@{2} dated Aug 3 (~70 days) | Owner triage only; memory `user-keeps-wip-in-git-stash` says never `git stash` during validation. Inspect with `git stash show -p`; ADR-016 work may now be on main |

---

### 9.3 Cleanup backlog

#### Branches

Local branches (9) and remote heads (11). Origin `gh-pages` and `slo-data` are bot-owned.

| Branch | Where | State | Verdict |
|---|---|---|---|
| `main` | local | `behind 1` of origin (local `d0c07a13`, origin `c3b2d328`) | fast-forward |
| `fix/langgraph_fanin_join` | local + origin + worktree `C:/tmp/arp-fanin` | content merged as #387 (squash; branch still shows `ahead 1` of main by SHA) | **delete** branch + worktree |
| `relock-382` | local | tracks `origin/dependabot/pip/pip-root-llm-06dfaa602f` (relock `eba4f777`) | keep until #382 merges, then delete |
| `chore/ignore_docs_ui_scratch` | local + origin + worktree `C:/tmp/arp-chore` | #389 open | keep until merged |
| `feature/app_improvement_review` | local + origin + worktree `C:/tmp/arp-appreview` | #390 open | keep until merged |
| `feature/el_screen_restyle` | local + origin + codex worktree | no PR | keep, open PR after #388 |
| `feature/criterion_aggregation` | local + origin + worktree `C:/Users/tandf/source/agentic-runtime-platform-f5-f6` | see §9.2 | keep |
| `docs/tech_debt_plans` | local + worktree `C:/tmp/arp-plans` | unpushed | push or discard |
| `feature/evidence_ledger_port` | local (checked out in live checkout) + origin | #388 open | keep |
| `origin/dependabot/pip/pip-root-{llm,rest,tooling}-*` | origin | #382/#383/#384 | closed by merge/close of PRs |
| `origin/gh-pages` | origin | 94 commits; mkdocs deploy | leave |
| `origin/slo-data` | origin | nightly bot commits `[skip ci]` | leave |

Already cleaned during this session (listed in the brief, no longer present): local branches and worktrees for `fix/secret_mask_json` (#380), `fix/review_report_extraction` (#377), `fix/fullstack_rework` (#379), `fix/retire-github-models` (#378), `fix/nvidia-deepseek-v4-eol` (#376), `fix/nvidia-llama-31-8b-eol` (#375), and `.claude/worktrees/{deepseek-v4-eol,epic-yonath-0c6f8e}`, `C:/Users/tandf/source/arp-model-pack-builder`, copilot worktrees — `git worktree list` at write time shows none of them. Verified with `git branch --list` (empty for the three `fix/*` names checked).

#### Worktrees (9 live)

| Path | Branch | Disposition |
|---|---|---|
| `C:/Users/tandf/source/agentic-runtime-platform` | `feature/evidence_ledger_port` | primary checkout; dirty (see below) |
| `C:/tmp/arp-appreview` | `feature/app_improvement_review` | keep until #390 merges |
| `C:/tmp/arp-chore` | `chore/ignore_docs_ui_scratch` | keep until #389 merges |
| `C:/tmp/arp-el-port` | detached `74123cb4` (merge of main into #388 head) | **remove** — redundant with the live checkout |
| `C:/tmp/arp-fanin` | `fix/langgraph_fanin_join` | **remove** — #387 merged |
| `C:/tmp/arp-main-inventory` | detached `c3b2d328` | remove after the inventory is finished |
| `C:/tmp/arp-plans` | `docs/tech_debt_plans` | keep (unpushed work) |
| `C:/Users/tandf/.codex/worktrees/evidence-ledger-ui/agentic-runtime-platform` | `feature/el_screen_restyle` | keep; owned by Codex |
| `C:/Users/tandf/source/agentic-runtime-platform-f5-f6` | `feature/criterion_aggregation` | keep |

Note (memory `nested-worktree-loads-real-env`): none of these is under `.claude/worktrees` any more, so the live-`.env`-at-import hazard does not apply to the current set.

#### Local-only artifacts (uncommitted, in the live checkout)

| Artifact | Size / count | Risk | Action |
|---|---|---|---|
| Modified tracked: `.env.example`, `.gitignore`, `tools/llm/probe_config.py`, `tools/llm/probe_discovery_providers.py` | +47 / -1 | Mixed into the #388 branch checkout | Commit to a `chore/` branch |
| Untracked `agentic-workflows-v2/ui/src/components/el/*` (8 files) + `ui/src/lib/runSentence.ts` | ~2.1k lines | Lost on `git clean` | Commit |
| `docs/ui/` untracked design HTML (Dispatch, Dossier, Rewind, Run Inspector 1–7, Live execution x3, `designd`–`designg`, `superdesign-local/`, `_impeccable/`, `design-system/`, `_design-system.tgz`) | 353 entries by `git status --short -uall docs/ui`; 9.8 MB on disk (`du`); only 6 files under `docs/ui/` are tracked on main | Pollutes status; #389 ignores them but does not archive them | Merge #389; move the winning mockups under `docs/ui/` tracked or into `_archive/` |
| `evidence-ledger-design-system/` directory at repo root (also a `.zip` per the brief; none matched `*.zip` at repo root at write time) | n/a | Exported bundle | Covered by #389 ignore rule |
| `docs/inventory/`, `scripts/inventory/` | this inventory | Untracked | Commit when the inventory lands |

#### Stashes: 3 (see §9.2).

---

### 9.4 Code-level debt markers

Method: `grep -rnE "\b(TODO|FIXME|XXX|HACK|DEPRECATED)\b"` over `py/ts/tsx/yaml/yml/lean` in `C:/tmp/arp-main-inventory` (excluding `node_modules`, `.venv`, `docs/`, `*.generated.*`). `py_inventory.json` `modules[].markers` reports only the one TODO; the grep widened the scope to YAML, TSX and string literals and found the rest — all but one are not actionable debt.

#### Summary

| Package | TODO | FIXME | HACK | XXX | DEPRECATED | Actionable |
|---|---|---|---|---|---|---|
| `agentic-workflows-v2/agentic_v2` | 1 | 0 | 0 | 0 | 3 | 1 TODO + 2 route deprecations |
| `agentic-v2-eval` | 0 | 0 | 0 | 0 | 0 | 0 (1 regex literal) |
| `agentic-workflows-v2/ui` (TS/TSX) | 0 | 0 | 0 | 0 | 0 | 0 |
| `tools/`, `scripts/`, `proofs/` | 0 | 0 | 0 | 0 | 0 | 0 (`sorry`/`admit` hits in `proofs/Scheduler.lean:2537-2538` are prose; `warningAsError` rejects real `sorry`) |
| **Total** | **1** | **0** | **0** | **0** | **3** | **3** |

#### agentic-workflows-v2 (runtime)

| file:line | Tag | Text | Class |
|---|---|---|---|
| `agentic-workflows-v2/agentic_v2/workflows/runner.py:416` | TODO(ADR-001) | "When a custom step_executor is provided we must construct DAGExecutor directly because NativeEngine does not accept a step_executor parameter and the registry returns a shared singleton. Full unification requires NativeEngine to support per-call step_executor injection or a factory pattern." | **Real debt** (engine-unification, tied to ADR-031 single-engine direction; plan goal G3) |
| `agentic-workflows-v2/agentic_v2/server/routes/evaluation_routes.py:411` | DEPRECATED | "(Sprint B SB-1): Use path-based URL instead" (route docstring) | Real: deprecated route still served |
| `agentic-workflows-v2/agentic_v2/server/routes/evaluation_routes.py:438` | DEPRECATED | same, second route | Real: remove after confirming UI uses path-based URL |
| `agentic-workflows-v2/agentic_v2/config/defaults/agents.yaml:62` | DEPRECATED | "prompt files removed in d921ba0f" (commented-out researcher/writer agents) | Dead commented YAML — delete |
| `agentic-workflows-v2/agentic_v2/engine/prompt_assembly.py:63` | TODO | "no TODO stubs" | Prompt text, not debt |
| `agentic-workflows-v2/agentic_v2/agents/implementations/claude_sdk_agent.py:37` | TODO | docstring example | Not debt |
| `agentic-workflows-v2/agentic_v2/tools/builtin/search_ops.py:376` | TODO | tool help example | Not debt |

#### agentic-v2-eval

| file:line | Tag | Text | Class |
|---|---|---|---|
| `agentic-v2-eval/src/agentic_v2_eval/metrics/quality.py:92-94` | TODO/FIXME/XXX/HACK | regex that *detects* markers in scored code | Not debt |

Inference: a repo this size carrying one real TODO means debt is tracked elsewhere (KNOWN_LIMITATIONS, ADRs, the plan in §9.1), not in-code.

Skips/xfail: 15 test files under `agentic-workflows-v2/tests`, `agentic-v2-eval/tests`, `tests/` contain `pytest.mark.skip` or `xfail` (count of files, not cases); the 11 deselected `tools/tests` cases are enumerated in `.github/workflows/ci.yml:655-687`.

---

### 9.5 Documented future work

Each row is verified against main (`c3b2d328`) unless noted.

| Item | Source | Status on main |
|---|---|---|
| Epic 9 — Multi-Run Comparison (candidate) | `docs/ROADMAP.md` §4 | **Open.** Only "Proposed" roadmap entry; depends on ADR-012 (Proposed) |
| ADR-042 slices: switch `step_scoring.py` to EvalKit, remove `agentic_v2_eval` | `docs/ROADMAP.md` §3c; `docs/adr/ADR-042-agentic-evalkit-adoption.md` | **Partial.** `evalkit_bridge` present, pin `agentic-evalkit>=0.4.1,<0.5.0` (`agentic-workflows-v2/pyproject.toml:52`); cutover is in `feature/criterion_aggregation` (unmerged) |
| ADR-034 path-first workflow I/O contracts | `docs/adr/ADR-INDEX.md` L172: "Proposed, 0% (pilot on fullstack_generation pending)" | **Open**, though ADR-052 typed step artifact contracts and #379 fullstack rework landed adjacent work; index row not updated |
| ADR-007 classification matrix & stop policy | ADR-INDEX L24 "Proposed" | Open, no implementation |
| ADR-010 commit-driven A/B eval harness | ADR-INDEX L27, L156: Proposed, ~10% (primitives) | Open |
| ADR-011 eval harness API & interface | ADR-INDEX L28, L157: Proposed, ~15% | Open |
| ADR-012 UI evaluation hub & A/B comparison | ADR-INDEX L29, L158: Proposed, ~10% | Open; UI hub partially advanced by #388 line of work but not this ADR |
| ADR-031 native DAG single engine | ADR file: Superseded, not adopted in this repo | Closed (non-goal); contradicts the tech-debt plan's "retain both engines" — consistent |
| Parked ADR numbers 049 (noncompensatory gates draft in a stash) and 053 (memoryctl, PR #205) | `docs/adr/ADR-INDEX.md` L77 | **Contradicted:** `CHANGELOG.md` 2026-09-03 entry says "removed accepted ADR-054 and ADR-057 from the parked-number note"; 049/053 still reserved. Verify before reusing |
| Next free ADR number | ADR-062 is the last file (`docs/adr/ADR-062-langgraph-join-once-semantics.md`) | ADR-063 free unless INDEX says otherwise |
| Wire-format gate covers 8 shapes; remaining endpoints hand-mirrored | `docs/KNOWN_LIMITATIONS.md` §1.1 (Status L34-35) | Open: "future sprint" |
| Optional provider surfaces outside the 80% coverage gate | KNOWN_LIMITATIONS §1.2 | Intentional |
| CLI `--adapter langchain` pre-flight check | KNOWN_LIMITATIONS §2.1 (L68) | Open (server path done by S1-6) |
| Redis backend for `slowapi` rate limit and `AuthThrottle` | KNOWN_LIMITATIONS §4.1/§4.2, ADR-018 | **Open** — Redis exists only for the circuit breaker (T1-2) |
| Human approval gate UI pause/resume + server approval queue | KNOWN_LIMITATIONS §4.3 | Open. Note untracked `ApprovalGate.tsx` in `ui/src/components/el/` is the likely UI half |
| SSRF DNS rebinding needs network-layer egress | KNOWN_LIMITATIONS §4.4 | Accepted, no app fix planned |
| `X-Tenant-ID` spoofable without OIDC | KNOWN_LIMITATIONS §4.5 | Accepted |
| `python -m tools.llm.model_inventory` fails from repo root | KNOWN_LIMITATIONS §4.12 | **Still open on main**: `tools/llm/model_inventory.py:504` `from llm_client import LLMClient` |
| `onnx:` IDs exposed in catalog but unusable by exact-model chat | KNOWN_LIMITATIONS §4.13 | Open (no change found) |
| Strict ONNX weight verification not in every loader | KNOWN_LIMITATIONS §4.14; ROADMAP E8-4 | Open |
| 11 stale `tools/tests` cases | KNOWN_LIMITATIONS §4.15 | **Partly superseded:** CI now has a `tools/ tests` job that runs `tools/tests` with 11 `--deselect`s (`ci.yml:655-687`); memory `tools-tests-never-run-by-ci` is out of date. The 11 cases themselves remain stale |
| Live-provider behavior not proven by blocking CI | KNOWN_LIMITATIONS §3.1 | Intentional; opt-in live lanes |
| Multi-tenant billing/quotas; polyglot workers | ROADMAP §5 | Explicitly out of scope for v0.3.x |
| v0.4.0-rc.1 release engineering | CHANGELOG "Release engineering for v0.4.0-rc.1 (2026-07-14)" | Manifest `release-manifest.toml` present; no `rc.1` tag verification done here — mark UNVERIFIED |
| Tech-debt goals G0–G7 | `docs/plans/2026-09-10-tech-debt-workflow.md` (branch `docs/tech_debt_plans`, unmerged) | Not started on main except F5/F6 (#315, #316) and scoring Slice C |
| Native-lane NIM reasoning-model empty content | CHANGELOG 2026-08-29 "Not fixed here" (`NvidiaBackend` inherits `OpenAIBackend.complete_chat`) | Open |
| DigitalOcean provider has no native backend/discovery/registry entry | CHANGELOG 2026-09-01 | Open by design |
| Expression-interpreter dispatch changes | tech-debt plan: "deferred until a real grammar change" | Deferred |
| Proof ledger: whole-trace consumed-timeout statement, fairness/cancellation assumptions | `docs/HANDOFF.md` "UNCLEAR" list | Open research; handoff itself stale |
| `AI_EVIDENCE_STANDARD.md` gaps | `AI_EVIDENCE_STANDARD.md` L244 defers to KNOWN_LIMITATIONS; L21/L34/L259 mandate **UNVERIFIED** labels rather than listing gaps | No separate gap list exists; limitations of record are KNOWN_LIMITATIONS above |

#### CHANGELOG "Unreleased" state

`CHANGELOG.md` has **seven consecutive `## Unreleased - ...` headings** (L3-L176): secret masks (#380), GitHub Models retirement (#378), DeepSeek V4 retirement (#376), reviewer reports (#377), fullstack rework (#379), NIM tier-1 retirement (#375), Mistral provider, UI design guardrails. There is no `[Unreleased]` section header; the file's 0.3.0 → 0.4.0-rc.1 cut has not been made since 2026-07-14. A release-cut task is implicit: collapse these into a version heading.

---

### 9.6 Cross-repo follow-ups (open items touching ARP)

Sources: `C:/Users/tandf/source/_audit/remediation-progress-2026-09-23.md` (newest remediation file; `remediation-progress-2026-08-04.md` and `-07-25.md` older), `net-new-triage-revalidation-2026-08-09.md`, `net-new-sweep-2026-07-25.md`. The newest net-new file is the 2026-08-09 revalidation; no newer dated file exists.

| Item | Source | Status at 2026-10-12 |
|---|---|---|
| T05: add `ci-constraints.txt in sync with uv.lock` to ARP's **classic** branch protection (ruleset `base` is disabled; 12 required checks live in classic protection) | remediation-progress-2026-09-23 §3 item 2 | Owner action; not verifiable by this inventory (no admin API read). #383 failing only that check suggests it is still not blocking merge ordering |
| T19: restart CI on Dependabot PRs by close/reopen because a `GITHUB_TOKEN` push starts no CI (#323, #311, #301, #322 at that date) | same, §3 item 4 & §Lessons | Those PRs are now merged/closed (#367, #366, #357). Hazard persists: #382/#383 need user-account pushes |
| T11 verification: 2026-09-24 12:00 UTC scheduled relock run should pass | same | **UNVERIFIED** here; #382's relock (`eba4f777`) was done by hand this session, suggesting the workflow may still not cover the case |
| T51: root `CLAUDE.md` §7 documents `_TrackedProvider` coupling | same §3 item 5 | Done (§7 present in workspace root file) |
| T50: stale worktrees back merged PRs | same | Superseded by §9.3 |
| M8 EK `_TrackedProvider` coupling — consumer canary (`ek-delegation-tests`, ARP#329) | same §2 | Closed; remaining hazard: EK 0.4.x range and blanket-`ImportError`-skip lesson |
| M7/N2 ARP caps EK/EVK below 0.4 | same §2 | Closed by ARP#330: constraints resolve `executionkit==0.4.0`, `agentic-evalkit==0.4.1` |
| H5 LangChain path unredacted | ARP#326 | Closed |
| Net-new triage (2026-08-09): 2 confirmed HIGHs on ARP (both size S) | net-new-triage-revalidation-2026-08-09.md "The two confirmed HIGHs on ARP" | Likely addressed by later work (#325-#330); **UNVERIFIED** item-by-item |
| `agentic-workflows-v2` dependency pins for `ek` extra range | workspace `CLAUDE.md` §7 | Hazard stands: EK 0.5/0.4 major outside range silently stops exercising path |
| Releasing EK/EVK requires hub bump | workspace `CLAUDE.md` §7 | Not ARP-owned; no ARP action |

---

### 9.7 Recent velocity (last ~40 merged PRs, newest first)

| Theme | PRs | Dates (UTC) | Notes |
|---|---|---|---|
| **Engine / middleware fixes** | #387 LangGraph run-once join (ADR-062); #380 JSON-safe secret masks (ADR-061); #377 keep `review_report` when reviewer JSON damaged; #379 fullstack rework ships and re-reviews; #353 iterative DAG cycle check; #348 cancellation survives observer masking; #340 observer failures kept out of scheduling | 2026-09-25 → 2026-10-13 | Highest-value 3 days: #375-#380 + #387 landed 2026-10-11/13 |
| **Models / providers churn** | #375 retired NIM tier-1 model + 410 as retired; #376 retired NIM DeepSeek V4 rungs; #378 drop retired GitHub Models rungs; #373 drag-and-drop model-pack builder; #374 typed model ids in pack builder | 2026-10-10 → 2026-10-12 | Three EOL fixes in 24h — provider volatility (memory `provider-env-reality`); consider a retirement-detection CI probe |
| **UI / design** | #370 critique/audit remediation; #371 design rules enforced in CI; #372 font shorthand / transition guard; open #388, #389 | 2026-10-08 → 2026-10-10 | Pivot to Evidence Ledger design system (ADR-054) |
| **Lean proofs / scheduler** | #347 land ADR-060 stack; #351, #352, #354, #361 proofs; #362/#364 differential test; #341, #343 | 2026-09-25 → 2026-10-01 | Burst on scheduler verification |
| **New workflows / features** | #363 `plan_tribunal` multi-judge; #365 follow-up; #349/#350 study telemetry + SWE-AB ledger | 2026-09-25 → 2026-10-01 | `plan_tribunal.yaml` present on main; `app_improvement_review` (#390) next |
| **Dependencies** | #386 node 26.11; #385 ui-npm (14); #381 setup-uv 10.3.0; #369, #368, #367 (24 pip-root-rest), #366, #359, #360, #357 (14 pip-root-llm) | 2026-09-28 → 2026-10-12 | Pip-group PRs routinely land days late via manual relock; npm/docker/actions auto-merge |
| **Docs / chores** | #355 derived test count; #345 pre-commit `--all-files` green | 2026-09-25 → 2026-09-27 | — |

Pace: 33 commits to main in 18 days, 20 of them in the final 5 (`git log origin/main --since=2026-09-25`). 0 open issues means work is tracked in PRs and docs only.

---

### 9.8 Prioritized next actions

| # | Action | Rationale |
|---|---|---|
| 1 | **Commit the untracked `el/*` components and `runSentence.ts` and the probe-tooling edits to their own branches** | ~2.1k lines + 47 lines exist only in the live checkout on a branch they do not belong to; the cheapest and most irreversible-if-lost item |
| 2 | **Land #388 (Evidence Ledger), then rebase and PR `feature/el_screen_restyle`** | 3,152-line PR is the long pole; `el_screen_restyle` and the untracked components stack on it; MERGEABLE, 0 failing checks |
| 3 | **Merge #389 (docs/ui ignore) and archive or track the 353 design files** | 18-line PR; removes noise that hides real untracked work in `git status` |
| 4 | **Push the rebased `feature/criterion_aggregation` (a6ee2520) and open the PR** | Rebase work is done locally; origin copy is 62 commits stale; gates ADR-042 cutover and plan G2 |
| 5 | **Relock and merge #383; finish #382 (approved, awaiting last check)** | Both are mechanical; #383 fails only on `uv.lock` sync; use `uvx uv@0.11.2` and push as a user |
| 6 | **Close #384 and re-stage the 38 bumps in batches** | 26 failing checks = real breakage; a blind rebase wastes CI minutes; unblocks Dependabot's group |
| 7 | **Review/merge #390 (`app_improvement_review`)** | 0 behind main, 639 lines, small review surface; ships a new workflow |
| 8 | **Remove stale worktrees and branches (`arp-fanin`, `arp-el-port`, `fix/langgraph_fanin_join`) and fast-forward `main`** | Worktrees pin branches and caused the multi-session collisions recorded in memory (`concurrent-sessions-same-branch`) |
| 9 | **Refresh docs: delete/rewrite `docs/HANDOFF.md`, update ROADMAP/KNOWN_LIMITATIONS "last verified", fold seven `Unreleased` CHANGELOG headings, update ADR-INDEX for ADR-034 and the tools-tests CI job** | Docs are 17-76 days stale, include false claims (PR #354 "open"), and `just docs` does not scan them (memory `docs-refs-check-scope`) |
| 10 | **Fix `tools/llm/model_inventory.py:504` import and push/PR the tech-debt plan (`8e61318c`)** | One-line known defect with a documented fix (KNOWN_LIMITATIONS §4.12); the plan commit is the only record of G0-G7 and is unpushed |

Authorization reminder (global rule): merging any of these PRs, creating releases/tags, and force-pushing the rebased `feature/criterion_aggregation` each need explicit, separate user approval.
