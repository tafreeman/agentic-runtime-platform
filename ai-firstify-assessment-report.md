# AI-Firstify Assessment Report

**Project:** agentic-runtime-platform
**Original assessment date:** 2026-07-13
**Current refresh date:** 2026-07-16
**Mode:** Audit + release verification (report artifact updated; product files unchanged)
**Current commit audited:** `0c84f74d4dedf3208ec37c9ab9697ca42cc256da`
(`feature/evidence-ledger-model-packs`)

> **Framing note.** This repo's *product* is an agentic runtime platform — LLM
> orchestration is the deliverable, not an accident. The AI-Firstify rubric was
> written to catch *personal tools that over-grew into chatbots*, so two
> dimensions are re-interpreted here: "Agent Architecture" is scored as
> *"is the agent code disciplined and bounded?"* (not *"are there any LLM calls?"*),
> and "Skill Usage" / "Context Hygiene" are scored against how well the repo is
> set up **as a codebase developed with Claude Code** (CLAUDE.md, rules,
> progressive disclosure), which is the layer AI-Firstify actually governs.

## Release-Readiness Refresh — 2026-07-16

### Current verdict: HOLD `v0.4.0-rc.1`

The July 14 release-engineering work is implemented and the local artifact path
is healthy, but the repository is **not ready to publish today**. The current
feature branch is synchronized with `origin/main`, is four commits ahead and
zero behind, and is pushed to GitHub. It has no pull request and no branch CI
runs. Public `main` has no GitHub release and its latest dependency-audit run is
red.

| Priority | Blocker | Current evidence | Exit condition |
|---|---|---|---|
| P0 | Branch dependency surface | `pip-audit --skip-editable --local` reports three advisories in locked `mcp 1.27.0`: CVE-2026-52870, CVE-2026-52869, and CVE-2026-59950. The complete fix floor is `mcp>=1.28.1`. | Refresh the affected dependency/lock, regenerate `ci-constraints.txt`, and obtain a clean all-extras audit. |
| P0 | Public dependency-audit workflow | The latest `main` run fails on `setuptools 79.0.1`, PYSEC-2026-3447 / CVE-2026-59890; the published fix is `83.0.0`. This is runner/bootstrap state rather than a declared application dependency, but the configured workflow still treats it as release-blocking. | Upgrade or isolate the audited bootstrap environment and prove the workflow green on a PR and then `main`. |
| P0 | Generated documentation drift | `check_docs_refs.py` passes, but `generate_doc_stats.py --check` fails. Current source-derived values are 48 ADRs, 6 production workflows, and 3,883 backend tests. | Regenerate `docs/index.md` and rerun both documentation gates. |
| P0 | No integration evidence | The branch has no open PR and GitHub reports no workflow runs for it. Public `main` therefore does not contain the release manifest, artifact verifier, production-image repairs, or Evidence Ledger work. | Open a PR, run all required checks, merge, and verify the post-merge SHA before tagging. |

The four moderate OpenTelemetry UI advisories remain non-blocking under the
repository's `npm audit --audit-level=high` policy. They require a breaking
2.9.x upgrade and should remain an explicit follow-up rather than being hidden.

### Green evidence on the current branch

- `git pull --ff-only origin main`: already up to date; local untracked report
  and model-ranking files were preserved.
- Targeted current-head Python checks: **30 passed** (`test_model_override.py`
  plus root cross-package E2E).
- UI: **443 tests passed** and the Vite production build completed.
- All three sdists and three wheels built and passed Twine validation.
- The isolated release verifier installed the wheels outside the checkout,
  imported all three packages, exercised both CLIs, and accepted bundle
  `v0.4.0-rc.1`.
- Public `main` CI, CodeQL, documentation deployment, and the latest nightly E2E
  reliability run are green; only Dependency Audit is red among the examined
  current release-relevant runs.

The complete 4,000+ runtime suite and both production-container health probes
were last proven during the July 14 Phase 1 run, not at current HEAD. They must
be repeated after the P0 dependency and documentation fixes.

### Repository changes since the original assessment

The feature branch contains four commits beyond current `main`:

1. `437275e` — Evidence Ledger UI, model packs, multimodal/tier chat, LM Studio
   discovery/load support, release manifest, isolated artifact verifier,
   dependency refresh, deterministic load report, and production image repairs.
2. `b3c2ac8` — regenerated derived documentation statistics after rebasing onto
   the post-PR-207 mainline; later source changes have already made those values
   stale again.
3. `47c97a3` — removed the unused shadcn CLI runtime dependency and substantially
   reduced the UI lockfile.
4. `0c84f74` — stopped ambient model packs from affecting non-LangChain adapters
   and added regression coverage.

The branch-wide delta is large: approximately 150 files, 13,738 insertions, and
3,640 deletions. That increases the importance of PR-hosted CI and a clean
post-merge release gate; targeted local checks alone are insufficient release
provenance.

### Progress toward the AI-Firstify Phase 2 plan

The earlier report's phase names describe contributor-workflow automation, not
the separate July 14 release-engineering phase. Against that original plan:

| Plan area | Status | Evidence |
|---|---|---|
| Phase 1: instruction integrity | **Partial** | Published ADR guidance points at `ADR-INDEX.md`, but root `CONTRIBUTING.md` still hard-codes “next free 017,” the two contributor guides still diverge, and the documented `--update-golden` option remains unimplemented. |
| Phase 2: deterministic automation | **Not started** | No canonical `regen-wire`, `update-golden`, or new-ADR entry point exists in the root `justfile` or scripts. |
| Phase 3: project skills | **Not started** | No project-owned `.claude/skills`, `.claude/commands`, or tracked `SKILL.md` exists. `AGENTS.md` improves contributor context but is not an executable workflow. |
| Associated eval project | **Healthy separate boundary** | `tafreeman/agentic-evalkit` is public with release `v0.1.1`; its current remediation PR CI runs are green. It remains a separately released associated project, not a component of this repository's `release-manifest.toml`. |

### Updated execution order

1. Clear the `mcp` and `setuptools` audit failures and regenerate documentation
   statistics.
2. Rerun the full local gate: runtime/eval/E2E/UI tests, docs, both dependency
   audits, all artifacts, and backend/frontend production-container health.
3. Open the feature branch as a PR, require green CI/CodeQL/dependency review,
   merge, and verify the post-merge `main` SHA.
4. Cut `v0.4.0-rc.1` only from that verified `main` SHA and validate the public
   release assets and images.
5. Begin the original AI-Firstify Phase 2 only after closing its instruction-
   integrity prerequisites: canonical contributor guidance and a real,
   test-backed golden-update contract.

## Original AI-Firstify Score (2026-07-13 snapshot)

| Dimension | Score | Summary |
|-----------|-------|---------|
| 1. Project Structure | GREEN | Organized uv-workspace monorepo; 50-line CLAUDE.md; remote + active git (46 commits/7d) |
| 2. Agent Architecture | GREEN | Embedded agents are the product and are ADR-disciplined (native DAG engine, retained LangGraph adapter, shared router) |
| 3. Skill Usage | YELLOW | Excellent `.claude/rules/` + `justfile`, but **zero committed project skills/commands**; repeated multi-step workflows live as prose |
| 4. Scope & Complexity | GREEN | Large surface (623 py files) but every major capability is ADR-justified; watch maintenance surface |
| 5. Context Hygiene | YELLOW | Strong progressive disclosure, but an imported golden-update command and root contributor guidance are stale |
| 6. Safety | GREEN | Clean secret scan, detect-secrets baseline, approval gates, AST sandbox, CodeQL/SBOM |
| 7. Workflow Design | GREEN | 46 ADRs, CI gates, sub-agent review, wire-format drift check, conventional commits |

**Verified net: 5 GREEN / 2 YELLOW / 0 RED — a healthy, well-run repository.**
The two improvement levers are restoring the accuracy of AI-facing instructions
and then skill-ifying the repo's genuinely repeated Claude-Code workflows. See
the Codex verification appendix for corrections and the authoritative priority
order.

## Original Audit Recommendations

> These recommendations are preserved from the original audit. The verified,
> authoritative order is in **Additional prioritized todos** below; instruction
> integrity must be repaired before new skills automate the current prose.

1. **[MEDIUM]** Capture the repo's repeated multi-step workflows as committed
   project skills or slash-commands — wire-format regeneration, golden-file
   regeneration, and new-ADR scaffolding are the top three. Prerequisite: a
   `.gitignore` carve-out so a project skill dir is tracked (see D3). *Effort: ~half day.*
2. **[LOW]** If skills feel heavyweight, add one `.claude/rules/workflows.md`
   documenting the regen/ADR flows step-by-step and `@import` it from CLAUDE.md —
   converts the prose in CONTRIBUTING/ci.md into an always-loaded prescriptive checklist. *Effort: ~1 hour.*
3. **[LOW]** Decide whether shared team harness config (permissions/hooks in
   `.claude/settings.json`) should be committed. It is currently gitignored
   (local-only); the committed-rules / local-settings split is defensible, so this
   is a conscious-choice item, not a defect. *Effort: 30 min.*
4. **[LOW]** Watch-item, not an action: periodically re-justify the breadth of
  experimental provider-discovery backends (ollama / lmstudio / onnx / cloud /
  OpenRouter — ADR-036..040 and ADR-050..051 — plus
  `tools/windows_ai_bridge/`). Each is ADR-backed today; the
   risk is maintenance surface for a solo maintainer, not scope creep. *Effort: ongoing.*

## Detailed Findings

### Dimension 1: Project Structure — GREEN
- **CLAUDE.md**: exists, **50 lines** (rubric GREEN threshold is <200). Deliberately
  thin; delegates detail to `@import`ed rule files.
- **.gitignore**: comprehensive (VS-template base + a large project-specific tail).
  Correctly excludes `.env`, `.env.*` with `!.env.example`, `secrets.txt`,
  `**/hardware_override.yaml`, `.gemini/oauth_creds.json`, run artifacts, coverage.
- **Git**: remote configured (`origin` → `github.com/tafreeman/agentic-runtime-platform`);
  **46 commits in the last 7 days**; conventional-commit subjects throughout recent log.
- **Layout**: 29 root entries — a coherent **uv-workspace monorepo** (`agentic-workflows-v2`
  runtime + `agentic-v2-eval` harness + repo-root `agentic-tools`), plus `datasets/`,
  `docs/`, `infra/`, `otel/`, `load/`, `examples/`. Code + data + docs + eval live
  together. Not disorganized.

### Dimension 2: Agent Architecture — GREEN (reframed for a platform)
- Provider/agent libraries by tracked-file mention count (files referencing the
  name — same method for all): **openai 107, langchain 85, ollama 71, anthropic 67,
  langgraph 39**. A naive rubric read flags this RED ("LLM calls for core
  functionality"); that is a false positive here — **agent orchestration is the
  product.**
- The correct question — *is the agent layer disciplined?* — is answered by the ADRs
  and shared primitives the codebase reuses instead of re-implementing:
  `SmartModelRouter` (tier/model selection), `ExecutionContext` (run state/checkpoints),
  `ConversationMemory`, the native DAG engine plus the retained LangGraph adapter,
  forced tool choice (ADR-027), a process-wide token budget (ADR-048), and eager
  LangChain adapter validation (ADR-020). ADR-031's single-engine proposal is
  superseded and was not adopted.
- No evidence of *accidental* embedded agents in dev tooling (scripts/devex are
  deterministic). Verdict: disciplined → GREEN.

### Dimension 3: Skill Usage — YELLOW
- **No committed project skills or slash-commands.** `git ls-files` finds no
  `SKILL.md` and nothing under a tracked `.claude/skills|commands|agents`. The
  `bmad-*` / `speckit-*` dirs present on disk are **locally-installed tool packs,
  gitignored by design** (`.claude/*` is ignored except `!.claude/rules/`, and
  `_bmad*` / `**/bmad-*/` are ignored again explicitly).
- What the repo *does* have is strong: committed **`.claude/rules/ci.md` + `testing.md`**
  (`@import`ed into CLAUDE.md), a **`justfile`** (`just test`, `just docs`) capturing
  deterministic commands, and a thorough `CONTRIBUTING.md`.
- **The gap:** genuinely repeated *multi-step* workflows are documented as prose but
  not invokable as one prescriptive unit — e.g. wire-format regeneration
  (`python -m scripts.generate_ts_types` → `npm run generate:types` → commit, per
  ADR-014), golden-file regeneration, and new-ADR scaffolding (numbering, 004-006
  skipped). These are exactly the "repeated workflow → skill" candidates the rubric
  rewards.
- Why YELLOW not RED: `.claude/` exists and is used well; rules + justfile + CONTRIBUTING
  are strong prescriptive substitutes. Why not GREEN: the multi-step flows aren't
  skill-ified, and committing a project skill today requires a `.gitignore` carve-out
  (`!.claude/skills/` + `!.claude/skills/**`) that doesn't exist yet.

### Dimension 4: Scope & Complexity — GREEN (with a watch-item)
- **623 Python files**, 46 ADRs, 15 CI workflows, auth (ADR-021), tenant isolation
  (ADR-022), RAG (ADR-035), a React `ui/`, and load testing. For a *personal tool*
  this would be textbook over-engineering.
- It is not a personal tool. Every heavyweight capability is **ADR-justified**: the UI
  is a real product surface (ADR-012 evaluation hub, ADR-043 configurable workflow UI,
  ADR-050 chat playground); auth/tenancy/rate-limiting target deployed multi-tenant use.
- Mission is focused: *tier-based multi-model workflow orchestration* + an *offline eval
  harness*. The two packages are cohesive; supporting dirs (`infra/`, `otel/`, `load/`,
  `tools/`) are platform infrastructure, not unrelated features.
- **Watch-item:** the experimental local-model-discovery backends (ADR-036..040) and
  `tools/windows_ai_bridge/` are the parts most likely to become maintenance surface
  for a solo maintainer. Justified today; worth periodic re-justification.

### Dimension 5: Context Hygiene — YELLOW (strong structure, stale instructions)
- CLAUDE.md is **50 lines** and offloads all detail via `@.claude/rules/ci.md` and
  `@.claude/rules/testing.md` — the canonical progressive-disclosure pattern.
- `testing.md` is **path-scoped** (`paths: ["**/*_test.py", "tests/**/*.py"]`) so it
  auto-loads only when a test file is in context — avoiding context pollution.
- Large reference material (CI gates, coverage policy, wire-format drift, test
  conventions) lives in the rule files, never inlined into CLAUDE.md.
- However, `.claude/rules/testing.md` documents an unsupported
  `--update-golden` pytest option, and root `CONTRIBUTING.md` has stale ADR
  numbering while the published contributor guide has newer guidance. These
  truth-integrity defects prevent a GREEN rating until reconciled.

### Dimension 6: Safety — GREEN
- **Hardcoded-secret scan: clean** (no key-like literal assignments outside
  tests/fixtures/examples). `.env` gitignored; only `.env.example` (empty values)
  tracked.
- Defense in depth: **`.secrets.baseline`** (679 lines, detect-secrets) + a
  **detect-secrets pre-commit hook**; user-level env-access hook.
- Human-in-the-loop: **55 tracked files** reference approval/HITL; dedicated ADRs
  (041 approval-gate timeout, 045 build-app gate, 047 structural-tool gate). An
  expression evaluator runs in an **AST sandbox** (ADR-024).
- Supply-chain / SAST: `codeql.yml`, `dependency-review.yml`, `sbom.yml`,
  `dependency-audit.yml` workflows.

### Dimension 7: Workflow Design — GREEN
- **Prescriptive & validated:** CI rules (`ci.md`), a `justfile`, an 80% coverage gate
  enforced in a dedicated step, and a **wire-format-drift** job that fails on
  contract/schema mismatch.
- **Creation/review separation:** the audit procedure itself mandates a fresh-eyes
  sub-agent review (used below); the repo history shows a bot review flow and
  adversarial review passes.
- **Decision discipline:** **46 ADRs** (`docs/adr/`, numbering with 004-006 intentionally
  skipped, an `ADR-INDEX.md`, and drafts) — well above typical for a solo repo.
- **Git discipline:** conventional-commit subjects, pre-commit (black, isort via ruff,
  mypy, docformatter, detect-secrets) and a **`strip-ai-coauthors`** hook enforcing the
  no-AI-attribution policy.

## Still Needs Human Decision

- [ ] Adopt committed project **skills** vs. a single `.claude/rules/workflows.md` for
      the repeated regen/ADR flows (Recommendations 1 vs. 2).
- [ ] Whether to track `.claude/settings.json` shared harness config (Recommendation 3).

## Original Recommended Next Steps

1. Pick the D3 path (skill vs. rules file) and, if skills: add the `.gitignore`
   carve-out, then scaffold `regenerate-wire-format` and `new-adr` first — they are the
   highest-frequency, most error-prone flows.
2. Leave Dimensions 1/5/6/7 as-is; they are reference-quality and shouldn't be churned.
3. Add the provider-backend surface-area review to a recurring maintenance cadence
   (e.g. a quarterly ADR re-justification pass) rather than acting now.

---

## Codex Verification and Revised Todo Plan

**Original verification date:** 2026-07-13
**Verified checkout:** `main` at `3c31c48bb7c8c2a1880efc2e7072a59b59e11b9a`

### Review ruling

The audit's main conclusion is directionally sound: this is a disciplined AI
runtime repository, and the absence of committed project skills is an
improvement opportunity rather than an architectural failure. The exact score
should be revised from **6 GREEN / 1 YELLOW** to **5 GREEN / 2 YELLOW** until the
AI-facing instructions are internally consistent. Dimension 5 (Context Hygiene)
is **YELLOW**, not GREEN, because two instructions a new contributor or coding
agent is likely to trust are currently stale or non-executable.

### Original claim verification (2026-07-13 snapshot)

| Claim | Result | Verified evidence / correction |
|---|---|---|
| Audited commit | **Verified** | At the original verification, `main` HEAD was the full reported SHA `3c31c48bb7c8c2a1880efc2e7072a59b59e11b9a`. |
| Thin, progressively disclosed Claude context | **Verified with caveat** | `CLAUDE.md` is exactly 50 physical lines and imports the two committed rule files. One imported rule contains a broken golden-update command, so the structure is good but the content is not fully trustworthy. |
| 623 Python files | **Verified** | `git ls-files '*.py'` returns 623 tracked Python files. |
| 15 CI workflows | **Verified** | Fifteen tracked YAML workflows are present under `.github/workflows/`. |
| No committed project skills or commands | **Verified** | No tracked `SKILL.md` or tracked file under `.claude/skills`, `.claude/commands`, or `.claude/agents` exists. Locally installed ignored tool packs do not change this conclusion. |
| `.claude/` requires a carve-out for skills | **Verified** | `.gitignore` ignores `.claude/*` and re-includes only `.claude/rules/`; a committed skills directory needs an explicit re-include rule. |
| 47 ADRs | **Corrected** | Source-derived documentation reports **46 individual ADRs**. There are 44 numbered ADR files because one file contains ADR-001, ADR-002, and ADR-003. |
| Single native DAG engine / ADR-031 | **Incorrect** | ADR-031 is superseded and explicitly says the single-engine proposal was not adopted. The native engine and LangGraph adapter are both retained. This does not change the GREEN architecture verdict, but it changes the rationale. |
| Wire-format regeneration is a repeated multi-step flow | **Verified** | CI runs Python schema generation followed by UI TypeScript generation and fails on drift. The workflow is documented but has no single root task. |
| Golden regeneration uses `--update-golden` | **Incorrect** | Pytest rejects `--update-golden` as an unknown argument. The test currently regenerates only when the JSON golden is deleted and the test is rerun without that flag. |
| ADR authoring guidance is current | **Incorrect** | Root `CONTRIBUTING.md` still says the next ADR is 017 and omits reserved gap 013. The published `docs/CONTRIBUTING.md` correctly tells readers to consult the index, demonstrating drift between two contributor guides. ADR-051 already exists, and ADR-049's omission is not explained in the index. |
| Safety controls exist | **Verified** | The 679-line detect-secrets baseline, detect-secrets hook, response/tool approval controls, AST expression interpreter, and CodeQL/dependency-review/SBOM/dependency-audit workflows are present. The audit's specific “clean scan” result is not independently reproducible from the report because it does not record the command and scan scope. |
| Documentation checks are green | **Verified with coverage gap** | Both direct commands behind `just docs` pass. They do not detect root-vs-published `CONTRIBUTING.md` drift or validate the documented pytest flags. |
| 46 commits in seven days | **Snapshot-only** | This rolling count changes with the verification time and should not be treated as a durable quality claim. It does not affect the verdict. |

### Additional prioritized todos

#### P0 — Restore instruction integrity before automating it

- [ ] **Choose one canonical contributor guide.** Prefer root
  `CONTRIBUTING.md` as the source and generate/copy the published version, or
  replace `docs/CONTRIBUTING.md` with a thin link. Add a docs check that fails
  when the two surfaces disagree if both must remain.
- [ ] **Fix ADR numbering guidance.** Remove the hard-coded “next free 017,”
  direct authors to `ADR-INDEX.md`, include all reserved/withdrawn gaps, and
  explicitly decide whether ADR-049 is reserved, withdrawn, or available.
- [ ] **Make the golden regeneration contract real.** Either implement a tested
  `--update-golden` pytest option or remove the flag everywhere and document the
  actual delete-and-rerun behavior. Prefer an explicit opt-in update flag that
  cannot rewrite goldens during an ordinary test run.
- [ ] **Correct the audit's architecture and count language.** Use “native DAG
  engine plus retained LangGraph adapter,” 46 ADRs, and include ADR-051 in the
  provider-maintenance watch list.

#### P1 — Create deterministic workflow entry points

- [ ] Add a root `just regen-wire` recipe that runs both schema and TypeScript
  generation steps from the correct working directories.
- [ ] Add a root `just update-golden` recipe backed by the explicit, reviewed
  golden-update mechanism selected in P0.
- [ ] Add a small `scripts/new_adr.py` (or equivalent) that reads the ADR index,
  rejects collisions/reserved identifiers, creates the standard template, and
  reminds the author to update the index.
- [ ] Add tests for these entry points and include them in `just docs` or a
  dedicated lightweight `just verify-workflows` gate.

#### P2 — Add thin project skills after the commands are reliable

- [ ] Re-include `.claude/skills/` in `.gitignore` without exposing local
  settings, caches, worktrees, or third-party tool packs.
- [ ] Add focused skills for `regenerate-wire-format`, `update-golden`, and
  `new-adr`. Each skill should call the deterministic task/script rather than
  duplicating shell commands or policy text.
- [ ] Keep the skills progressively disclosed. Do not import a large workflows
  rule into every Claude session when the workflow is only occasionally used.

#### P3 — Close governance decisions and maintenance watch items

- [ ] Decide whether to commit a minimal `.claude/settings.json`. If adopted,
  commit only safe shared hooks/permissions; keep credentials and per-user
  grants in the already ignored local settings file.
- [ ] Review ADR-036 through ADR-040, ADR-050, ADR-051, and
  `tools/windows_ai_bridge/` against a quarterly matrix: current user path,
  last successful CI/runtime exercise, dependency cost, overlap, and keep/
  deprecate decision.
- [ ] Add a short reproducibility appendix to future audits containing exact
  commands, globs/exclusions, timestamps, and commit SHA for quantitative claims
  such as secret scans, file counts, and recent-commit activity.

### Prioritized implementation plan

#### Phase 1 — Documentation truth and guardrails (P0, first PR)

1. Reconcile the two contributor guides and establish the canonical source.
2. Correct ADR numbering/gap guidance and complete the ADR index's implementation
   status table through ADR-051.
3. Implement or remove `--update-golden`, then update the test docstring and
   `.claude/rules/testing.md` to match.
4. Add regression checks for contributor-guide drift, ADR-index completeness,
   and the golden-update CLI contract.

**Exit criteria:** direct docs checks pass; the contributor surfaces agree; the
documented golden command is accepted by pytest; the index accounts for every
formal ADR and every intentional gap.

#### Phase 2 — Deterministic automation (P1, second PR)

1. Add and test `regen-wire`, `update-golden`, and ADR-scaffolding entry points.
2. Ensure each command is idempotent or explicitly opt-in when it rewrites a
   reviewed artifact.
3. Run the commands in CI in check-only mode where practical so documentation
   cannot drift from executable behavior.

**Exit criteria:** each workflow has one canonical command, produces an
actionable failure, and is exercised by an automated gate.

#### Phase 3 — AI workflow layer (P2, third PR)

1. Add the narrow `.gitignore` carve-out for project-owned skills.
2. Create the three thin skills as discoverable wrappers over Phase 2 commands.
3. Test the skills from a clean checkout with no local Claude tool packs.

**Exit criteria:** a fresh contributor can discover and run each workflow, while
the authoritative mechanics remain in versioned scripts/tasks usable by humans
and CI without Claude.

#### Phase 4 — Policy and maintenance (P3, separate decisions)

1. Record the shared-settings decision and its security boundary.
2. Establish the provider/backend review matrix and first review date.
3. Adopt the reproducible-audit evidence template for the next assessment.

**Exit criteria:** settings ownership is explicit, every experimental backend
has a current keep/deprecate rationale, and future audit counts can be rerun
exactly.
