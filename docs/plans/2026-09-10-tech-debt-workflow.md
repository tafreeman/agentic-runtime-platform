# Remaining technical-debt delivery workflow

Status: implementation plan, 2026-09-10. This document does not assert that the
planned changes or their validation have completed.

## Baseline and decisions

The audit covered ARP and EvalKit. The focused F5/F6 changes shipped through
PRs #315 and #316; #316 merged as `9e77f797`. This plan was authored against
the clean completion worktree at `473a5162`, the source commit for #316.
The separate `feature/study-telemetry` checkout contains unrelated work and
must not be used as an implementation base. Revalidate remote main before
starting each goal; do not replay already-merged changes.

Completed work to retain: adapter validation hooks; execution of supplied
LangChain definitions; real progress callbacks; shared CLI/native-server
adapter execution; shared step-result conversion; and `StepResultRecord` in
contracts. Slice C is wired into runtime scoring, and the nonempty-output 0.7
fallback has been removed. These are not outstanding implementation tasks.
The upstream compatibility workflow exists, but the earlier inspection found
no runs: its operational effectiveness still needs evidence.

Two end-state decisions were selected for this plan:

* Retain both native and LangGraph engines. Share orchestration and lifecycle;
  do not replace either engine with the other.
* ARP owns its required deterministic gate without an EvalKit or legacy-package
  dependency. EvalKit retains its abstention-aware grading semantics. Runtime
  step evidence remains advisory unless an independently authorized policy
  grants gating authority.

## Goals, order, and model ownership

H means Opus or Sol class, responsible for design, difficult implementation,
and integration review. L means Haiku or Luna class, responsible for bounded
work under an explicit contract. These are task assignments, not benchmark
claims about particular model versions.

| Goal | Outcome and task allocation | Prerequisites | Completion evidence |
| --- | --- | --- | --- |
| G0 | L reconciles the audit ledger against current main, records base SHAs and exact CI commands; H reviews remaining scope. L verifies the existing upstream lane can resolve and execute both contract suites. | None | Baseline gates; actual compatibility run with both suites executed, installed versions recorded, no all-skipped success |
| G1 | H fixes the scoring contract and ports the required gate; L adds prescribed differential fixtures and migrates the bridge call site. | G0 | Gate passes with neither legacy evaluation nor EvalKit installed; expected semantic differences are explicit tests |
| G2 | L removes legacy consumers, package and configuration in bounded patches; H validates packaging and cutover. | G1 merged and required gate green on main | No live legacy imports; clean wheel-install gate and runtime smoke tests; required check preserved |
| G3 | H implements application-owned execution service, tracing/checkpoint ownership and stream-failure behavior; L migrates prescribed callers. | G0 | CLI/API adapter parity; no failure-triggered rerun; exactly-once finalization and lifecycle tests |
| G4 | H defines request policy and lifecycle stages; L extracts helpers; H verifies error and persistence behavior. | G3 | Existing API behavior, tenant boundaries, model-pack policy and run-record shape preserved |
| G5A/G5B | EvalKit H specifies digest/storage invariants; L migrates one proven equivalence at a time; H owns fault/concurrency review. | G0; G5B after G5A | Byte-identical identities and old cache entries readable; fault matrix passes |
| G6 | H defines enforceable dependency boundaries; L migrates imports and adds hermetic coverage per subsystem. | G2 and G4 | Forbidden edges rejected; compatibility aliases work; omissions removed only with coverage evidence |
| G7 | L performs small, independent cleanup patches; H reviews any semantic decision. | G0 and disjoint file ownership | Focused behavior preserved and repository gates pass |

G1/G2, G3/G4, and EvalKit G5 can run in parallel in isolated worktrees.
G7 must not overlap files owned by active goals. Serialize integration within
each repository. There is no automatic multi-PR merge or release step.

Architectural implementation contracts:

* [Scoring and legacy retirement](tech-debt/scoring-and-retirement-addendum.md)
* [Execution lifecycle and server decomposition](tech-debt/execution-addendum.md)
* [Dependency boundaries and bounded cleanup](tech-debt/boundaries-and-cleanup-addendum.md)

EvalKit's companion entry point is
`docs/plans/2026-09-10-tech-debt-workflow.md` in that repository. Cross-repo
paths here are identifiers, not imports or links dependent on local layout.

## Executable task envelope

Each goal owner starts by recording the exact base SHA, prerequisite PR/run
evidence, allowed files, exclusions, applicable addendum, and gate commands.
Each delegated task receives one bounded patch objective, prescribed interface,
fixtures to preserve, acceptance checks, and the exact return format below.

Reusable goal instruction:

> Complete goal Gx using its linked architectural addendum. Reconcile current
> main before editing, preserve unrelated work, and record the baseline checks.
> Delegate only bounded L tasks after H resolves the contract. Implement and
> integrate all tasks within this goal; run the affected checks and full
> repository gates. Return changed files, contract decisions, test counts,
> skips/failures, remaining risks and prerequisite evidence for the next goal.
> Stop before merges, releases or paid provider runs requiring authorization.

L must escalate changes to public APIs, grading policy, durable formats,
dependency direction, or the assigned file set. After two unsuccessful repair
attempts, return the minimal reproduction and current diff to H. Do not hide a
failure by weakening tests, coverage, typing, or suppression ratchets.

Small fixes whose implementation is no larger than their specification belong
in G7 as direct patches. Do not write a new architecture document for each
helper extraction. Expression-interpreter dispatch changes remain deferred
until a real grammar change warrants them.

## Validation and ADR handoff

Before and after implementation, run the repository's current lint, type and
full hermetic test gates using its CI configuration. Record pass/fail/skip
counts, coverage and commands. Run documentation checks for these addenda;
do not describe proposed test names as existing evidence. G0 captures exact
commands because workspace layout and CI invocations can change.

Keep local test success, remote CI success, push, merge, and release as separate
states in the ledger. A dependency lane that only retests locked versions is
not evidence of newer-version compatibility. Test newest allowed versions
without the exact constraints, and separately test newer excluded releases in
an experimental environment that explicitly overrides only the two upstream
requirements. Keep shipping requirements unchanged until reviewed evidence
supports a bump. Report resolution failure separately from contract failure.

G1/G2 append dated decisions and cutover evidence to ADR-042. G3/G4 append the
execution-lifecycle contract to the combined ADR-001/002/003 document. G6
records the facade/layer policy in the architecture documentation and relevant
ADR. Preserve historical decisions and explicitly state what is superseded.
Documentation creation alone does not close any audit finding.
