## 8. Documentation & architecture decision records

Source of truth: clean `origin/main` worktree at `../arp-main-inventory`, revision `c3b2d328`. Ages are days since last commit, measured against 2026-10-12. Line counts are from `docs/inventory/data/meta_inventory.json`. Read-only audit; nothing in the worktree was modified.

Status legend: **Current** (no contrary evidence found), **Aging** (75-90 days, fast-moving area), **Stale >90d** (age over 90 days), **Stale content** (text contradicts code, CI or an ADR regardless of age), **Duplicate** (copy or mirror of another doc), **Stub** (redirect or pointer only), **Broken link**, **Working note** (agent or process artifact, not reference material), **Orphan** (builds under mkdocs but is not in `nav`).

### 8.1 Documentation map

Counts: 205 markdown files are in the tree (excluding `node_modules`, `.venv`, `_audit`). Excluded from this map: `agentic_v2/prompts/*.md` (LLM prompt payloads, not docs), `.claude/rules/*.md` (agent rules, listed under process), and `docs/adr/` (covered in 8.5).

#### Getting started

| File | Lines | Last commit | Purpose | Status |
|---|---:|---|---|---|
| `README.md` | 332 | 2026-10-10 | Root landing: product summary, quick start, providers, docs index | Current; provider list is accurate for code paths reviewed |
| `agentic-workflows-v2/README.md` | 220 | 2026-10-01 | Package README: install, first workflow, package scope | Current |
| `docs/index.md` | 185 | 2026-10-12 | MkDocs home page | Current |
| `docs/getting-started/index.md` | 89 | 2026-07-29 | Getting-started overview | Aging |
| `docs/getting-started/installation.md` | 252 | 2026-10-10 | Install steps and env var table | Stale content: line 168 lists GitHub Models (`GITHUB_TOKEN`) as a provider; GitHub Models retired upstream 2026-07-30 (ADR-016, `agentic-workflows-v2/docs/MODEL_LAYER.md:64`) |
| `docs/getting-started/quickstart.md` | 185 | 2026-07-29 | Quick start | Aging |
| `docs/getting-started/first-workflow.md` | 233 | 2026-07-29 | First YAML workflow walkthrough | Aging; overlaps `agentic-workflows-v2/docs/tutorials/getting_started.md` |
| `docs/DEMO.md` | 113 | 2026-07-29 | Five-minute local demo | Aging |
| `docs/NO_LLM_MODE.md` | 137 | 2026-09-03 | `AGENTIC_NO_LLM=1` deterministic mode | Current |
| `docs/ONBOARDING.md` | 272 | 2026-08-31 | Contributor onboarding, clean checkout to verified workflow | Current |
| `docs/development-guide.md` | 281 | 2026-08-31 | Edit, run, test loop | Current |
| `agentic-workflows-v2/docs/DEVELOPMENT.md` | 118 | 2026-07-29 | Package development notes; defers to `docs/development-guide.md` | Aging; overlaps |
| `agentic-workflows-v2/docs/tutorials/getting_started.md` | 63 | 2026-07-29 | "First native DAG" tutorial | Aging; overlaps `docs/getting-started/first-workflow.md` |
| `agentic-workflows-v2/docs/tutorials/building_workflow.md` | 57 | 2026-07-29 | Two-step deterministic workflow | Aging |
| `agentic-workflows-v2/docs/tutorials/creating_agent.md` | 121 | 2026-07-29 | Creating a `BaseAgent` | Aging |
| `examples/README.md` | 98 | 2026-08-29 | Python API examples | Current |
| `agentic-workflows-v2/examples/README.md` | 71 | 2026-07-29 | Runtime examples (second examples README) | Aging; overlaps root `examples/README.md` |

#### Architecture

| File | Lines | Last commit | Purpose | Status |
|---|---:|---|---|---|
| `docs/ARCHITECTURE.md` | 189 | 2026-08-31 | Repo-level architecture overview; links to deep dives | Current (drift-checked: all 8 protocols documented, see 8.4) |
| `docs/architecture-runtime.md` | 711 | 2026-10-12 | Runtime engine deep dive | Current |
| `agentic-workflows-v2/docs/ARCHITECTURE.md` | 98 | 2026-09-04 | Package-level architecture | Current; second architecture overview, see 8.2 |
| `agentic-workflows-v2/docs/REPO_MAP.md` | 63 | 2026-09-04 | Which owner to edit for a change | Current |
| `agentic-workflows-v2/docs/MODEL_LAYER.md` | 212 | 2026-10-12 | Model routing, discovery, retired providers | Current |
| `agentic-workflows-v2/docs/NODE_CONFIG_OVERLAY.md` | 90 | 2026-07-29 | Per-step config overlay; describes an "unfinished UI prototype" | Aging; status of the prototype unverified |
| `docs/architecture-ui.md` | 163 | 2026-07-29 | UI architecture (Evidence Ledger) | Aging; UI moves fast |
| `docs/architecture-eval.md` | 453 | 2026-09-10 | `agentic-v2-eval` architecture | Current |
| `docs/architecture-tools.md` | 400 | 2026-08-31 | `agentic-tools` architecture | Stale content: line 65 says GitHub Models requires `GITHUB_TOKEN` via `gh` subprocess |
| `docs/integration-architecture.md` | 317 | 2026-08-31 | Cross-package boundaries, ports, contracts | Current |
| `docs/project-overview.md` | 139 | 2026-08-31 | Monorepo purpose and packages | Current; overlaps `README.md` and `docs/index.md` |
| `docs/project-context.md` | 163 | 2026-08-31 | Compact repo map for tool users | Current; overlaps `agentic-workflows-v2/docs/REPO_MAP.md` |
| `docs/PATTERN_CATALOG.md` | 181 | 2026-08-31 | Pattern to implementation pointers | Current |
| `docs/WORKFLOW_AUTHORING.md` | 903 | 2026-10-12 | How to write, validate and run YAML workflows | Current; largest doc |
| `docs/workflows/index.md` | 219 | 2026-10-12 | Built-in workflow reference | Current |
| `agentic-workflows-v2/docs/WORKFLOWS.md` | 48 | 2026-10-01 | Built-in workflow loading | Current |
| `docs/deep-dive-server.md` | 597 | 2026-07-29 | FastAPI server internals | Aging |
| `docs/deep-dive-agents.md` | 221 | 2026-07-29 | Agent classes | Aging |
| `docs/deep-dive-agentic-v2-eval.md` | 410 | 2026-07-29 | Eval package deep dive | Aging; overlaps `docs/architecture-eval.md` |
| `docs/api-contracts-runtime.md` | 811 | 2026-07-29 | REST and WebSocket route reference | Aging; fast-moving (routes changed by ADR-050, ADR-043) |
| `docs/data-models-runtime.md` | 191 | 2026-08-31 | Pydantic contracts and wire models | Current |
| `docs/cli-reference.md` | 250 | 2026-08-31 | CLI commands | Current |
| `docs/configuration.md` | 379 | 2026-10-10 | Env vars and settings | Stale content: line 63 lists GitHub Models (`GITHUB_TOKEN` or `GH_TOKEN`) as a provider |
| `docs/component-inventory-ui.md` | 136 | 2026-09-27 | UI component boundaries | Current |
| `agentic-workflows-v2/docs/API_REFERENCE.md` | 98 | 2026-09-04 | Map of public Python, CLI and server interfaces | Current |
| `agentic-workflows-v2/docs/DOCS_BEST_PRACTICES.md` | 88 | 2026-07-29 | Documentation rules for the package | Aging |
| `proofs/README.md` | 334 | 2026-09-30 | Lean model of `DAGExecutor` (ADR-060) | Current |

#### Operations

| File | Lines | Last commit | Purpose | Status |
|---|---:|---|---|---|
| `docs/operations/index.md` | 47 | 2026-08-31 | Operations landing | Current |
| `docs/operations/troubleshooting.md` | 332 | 2026-08-31 | Symptom-first troubleshooting | Current |
| `docs/operations/security-hardening.md` | 302 | 2026-07-29 | Server security controls | Aging |
| `docs/deployment-guide.md` | 257 | 2026-07-29 | CI/CD, Docker, prod env vars | Stale content: line 13 says `ci.yml` "contains fourteen jobs"; `.github/workflows/ci.yml` on main defines 20 jobs |
| `docs/SUPPLY_CHAIN.md` | 116 | 2026-07-29 | Local model SHA-256 verifier | Aging |
| `docs/load-report.md` | 73 | 2026-07-18 | Load proof, generated from `load/results/` | Aging (86d); regenerate from source |
| `docs/flagship.md` | 23 | 2026-07-29 | Load and shared-state evidence summary | Aging |
| `load/README.md` | 112 | 2026-07-29 | Local k6 load harness | Aging |
| `infra/azure/README.md` | 52 | 2026-07-29 | Azure Bicep reference (described as a possible deployment) | Aging |

#### Reference

| File | Lines | Last commit | Purpose | Status |
|---|---:|---|---|---|
| `docs/GLOSSARY.md` | 244 | 2026-08-31 | Term definitions | Current |
| `docs/CODING_STANDARDS.md` | 137 | 2026-07-29 | Coding rules and enforcement sources | Aging |
| `docs/KNOWN_LIMITATIONS.md` | 283 | 2026-09-04 | Confirmed limitations | Current; checked by `check_docs_refs.py` (workspace list) |
| `docs/MIGRATIONS.md` | 165 | 2026-07-29 | Breaking changes since v0.3.0 | Aging; likely missing post-v0.3.0 breaks (unverified) |
| `docs/AI_RISK_MANAGEMENT.md` | 231 | 2026-08-31 | NIST AI RMF mapping | Current |
| `docs/tools/index.md` | 78 | 2026-07-29 | `agentic-tools` package overview | Aging |
| `docs/tools/llm-client.md` | 174 | 2026-07-29 | Shared LLM client; documents `gh:` prefix | Aging; stale content (GitHub Models section) |
| `docs/tools/local-models.md` | 167 | 2026-07-29 | Local ONNX models | Aging |
| `docs/tools/windows-ai.md` | 135 | 2026-07-29 | Phi Silica bridge | Aging |
| `docs/tools/model-probing.md` | 170 | 2026-07-29 | Model probing; examples use `gh:openai/gpt-4o-mini` | Stale content (retired provider in examples) |
| `docs/tools/provider-limits.md` | 143 | 2026-07-29 | Provider quota checks; table row "GitHub Models 70" | Stale content (retired provider) |
| `docs/tools/benchmarks.md` | 164 | 2026-07-29 | Model and agent benchmarks | Aging |
| `agentic-workflows-v2/tests/fixtures/backend_responses/README.md` | 63 | 2026-06-22 | Synthetic regression oracles for backend responses | Stale >90d (112d) |
| `docs/404.md` | 31 | 2026-07-29 | Site 404 page | Current (site asset) |

#### Evaluation

| File | Lines | Last commit | Purpose | Status |
|---|---:|---|---|---|
| `docs/evaluation/rubrics.md` | 165 | 2026-07-29 | Rubric definitions | Aging |
| `docs/evaluation/judge.md` | 182 | 2026-07-29 | Model-backed judges | Aging; stale content: example at line 151 uses `model="gh:gpt-4o"` |
| `docs/evaluation/gating.md` | 182 | 2026-07-29 | Runtime evaluation gates | Aging |
| `docs/evaluation/runners.md` | 174 | 2026-07-29 | Evaluation runners | Aging |
| `docs/evaluation/datasets.md` | 151 | 2026-07-29 | Dataset format | Aging |
| `agentic-v2-eval/README.md` | 197 | 2026-07-29 | Package README for `agentic-v2-eval` | Aging; package is being replaced per ADR-042 |
| `agentic-v2-eval/src/agentic_v2_eval/README.md` | 37 | 2026-07-29 | Package internals | Broken link: `../../../docs/evaluation/index.md` (no such file) |
| `datasets/default/README.md` | 120 | 2026-07-29 | Committed golden dataset | Aging |
| `docs/superpowers/specs/2026-07-02-evaluation-framework-design.md` | 714 | 2026-07-02 | Design analysis (HF discovery, benchmarks, provenance) | Stale >90d (77d, not >90); self-declared "Superseded as decision-of-record by ADR-042"; in site build but not in `nav` (Orphan) |

#### Governance & security

| File | Lines | Last commit | Purpose | Status |
|---|---:|---|---|---|
| `AI_EVIDENCE_STANDARD.md` | 259 | 2026-09-04 | Evidence standard for describing the repo | Current; checked by `check_docs_refs.py` (workspace list) |
| `SECURITY.md` | 53 | 2026-09-23 | Root vulnerability reporting policy | Current |
| `agentic-workflows-v2/SECURITY.md` | 8 | 2026-09-23 | Pointer to root `SECURITY.md` | Stub (duplicate pointer) |
| `docs/OWASP_LLM_THREAT_MODEL.md` | 145 | 2026-08-31 | OWASP LLM threat mapping | Current; excluded from mkdocs build (`mkdocs.yml` `exclude_docs`) |
| `docs/operations/security-hardening.md` | 302 | 2026-07-29 | Server security controls | Aging |
| `docs/SUPPLY_CHAIN.md` | 116 | 2026-07-29 | Model file integrity | Aging |
| `agentic-workflows-v2/CODE_OF_CONDUCT.md` | 39 | 2026-05-27 | Code of conduct (package) | Stale >90d (138d); no root equivalent |

#### UI & design

| File | Lines | Last commit | Purpose | Status |
|---|---:|---|---|---|
| `DESIGN.md` | 210 | 2026-10-09 | Dashboard design system (Impeccable context) | Current |
| `PRODUCT.md` | 34 | 2026-10-09 | Product context for design work | Current |
| `docs/ui/evidence-ledger-design-system.md` | 769 | 2026-10-08 | Evidence Ledger design system rules | Current; overlaps `DESIGN.md` (rules vs context) |
| `docs/ui/impeccable-context-changes.md` | 13 | 2026-10-09 | Records move of design context to root | Current; not in `nav` (Orphan) |
| `docs/ui/pages.md` | 150 | 2026-07-29 | Page-by-page UI guide, "as of 2026-07-28" | Aging; UI churn high |
| `docs/ui/api-integration.md` | 143 | 2026-07-29 | Browser to `/api` contract | Aging |
| `docs/ui/evidence-ledger-migration.md` | 108 | 2026-07-18 | Capability-preservation and migration map | Aging (86d); completed migration record |
| `docs/ui/evidence-ledger-full-rewrite-goal-prompt.md` | 859 | 2026-07-27 | Copy-paste prompt for an external Codex/GPT task | Working note (prompt artifact, not reference); not in `nav` (Orphan) |
| `agentic-workflows-v2/ui/README.md` | 112 | 2026-07-29 | React 19 dashboard README | Aging |
| `agentic-workflows-v2/ui/e2e/README.md` | 73 | 2026-07-29 | Playwright E2E for the dashboard | Aging |
| `.claude/rules/ui-design.md` | 51 | 2026-10-09 (age 3) | Agent rules for UI work | Current |

#### Process, contribution & planning

| File | Lines | Last commit | Purpose | Status |
|---|---:|---|---|---|
| `CONTRIBUTING.md` | 309 | 2026-09-04 | Root contributor guide (source for `docs/CONTRIBUTING.md`) | Current; see 8.2 |
| `docs/CONTRIBUTING.md` | 313 | 2026-08-31 | Published mirror of root guide with rewritten links | Duplicate (see 8.2) |
| `agentic-workflows-v2/CONTRIBUTING.md` | 117 | 2026-09-04 | Package-specific addendum | Current; addendum, not a duplicate |
| `CHANGELOG.md` | 712 | 2026-10-12 | Canonical changelog | Current |
| `docs/CHANGELOG.md` | 30 | 2026-07-05 | Published summary pointing to root changelog | Stale >90d content (99d); "Unreleased highlights" lags root; see 8.2 |
| `docs/ROADMAP.md` | 162 | 2026-09-23 | In-repo multi-week backlog | Current |
| `docs/MIGRATIONS.md` | 165 | 2026-07-29 | Breaking-change log | Aging |
| `docs/HANDOFF.md` | 66 | 2026-09-26 | "Proof handoff 2026-09-26", scope lock for Lean work | Working note; not in `nav`; not reference material |
| `docs/PROOF_LEDGER.md` | 97 | 2026-09-26 | Scope lock and ledger for proof work | Working note; not in `nav` |
| `AGENTS.md` | 32 | 2026-09-02 | Repo guidelines for agents | Current |
| `CLAUDE.md` | 57 | 2026-08-02 | Claude Code guidance for the repo | Current |
| `.claude/rules/ci.md` | 84 | 2026-08-02 | CI gates and local validation | Current (not in `nav`; agent rule) |
| `.claude/rules/portfolio-context.md` | 51 | 2026-08-02 | Portfolio context and CI gotchas | Current; states ci.yml has "17 blocking jobs" in portfolio notes, but the file defines 20 (see 8.6) |
| `.claude/rules/testing.md` | 68 | 2026-08-02 | Test conventions | Current |
| `agentic-workflows-v2/SUPPORT.md` | 36 | 2026-07-29 | Support channels | Aging |
| `.github/PULL_REQUEST_TEMPLATE.md` | 25 | 2026-05-27 | PR template | Stale >90d (138d) |
| `.github/ISSUE_TEMPLATE/bug_report.md` | 34 | 2026-05-27 | Bug template | Stale >90d (138d) |
| `.github/ISSUE_TEMPLATE/feature_request.md` | 32 | 2026-05-27 | Feature template | Stale >90d (138d) |
| `agentic-workflows-v2/.github/PULL_REQUEST_TEMPLATE.md` | 46 | 2026-07-29 | Package PR template | Aging; second PR template (see 8.2) |
| `proofs/README.md` | 334 | 2026-09-30 | Lean proofs scope and status (ADR-060) | Current |

#### Package & subtree READMEs

| File | Lines | Last commit | Purpose | Status |
|---|---:|---|---|---|
| `agentic-workflows-v2/agentic_v2/integrations/mcp/README.md` | 173 | 2026-07-29 | MCP client library | Aging |
| `agentic-workflows-v2/tests/integrations/mcp/README.md` | 45 | 2026-07-29 | MCP test layout | Aging |
| `agentic-workflows-v2/fixtures/README.md` | 32 | 2026-07-29 | Committed fixtures | Aging |
| `agentic-workflows-v2/tests/fixtures/backend_responses/README.md` | 63 | 2026-06-22 | Backend response oracles | Stale >90d (112d) |
| `tools/README.md` | 53 | 2026-07-29 | `agentic-tools` package README | Aging; overlaps `docs/tools/index.md` |
| `tools/agents/benchmarks/README.md` | 97 | 2026-07-29 | Agent benchmark runner | Aging |
| `tools/llm/windows_ai_bridge/PHI_SILICA_STATUS.md` | 122 | 2026-07-29 | Phi Silica bridge status | Aging; status document, may be dated |

#### Subtree docs not covered above (counted, not itemised)

- `agentic-workflows-v2/evals/swe_ab/docs/*.md` and `agentic-workflows-v2/evals/swe_ab/README.md` (campaign evidence, results, provider notes). Several mention GitHub Models or `gh:` ids; not audited line by line (unverified). Note the tree also contains `docs/results/*` with dated campaign outputs.
- `agentic-workflows-v2/ui/src` and `ui/public` docs: none beyond the README above.

### 8.2 Duplicates & overlaps

| Pair | Relationship | Verdict |
|---|---|---|
| `CHANGELOG.md` (712 lines, 2026-10-12) vs `docs/CHANGELOG.md` (30 lines, 2026-07-05) | Root is canonical and carries an `Unreleased` entry (ADR-061). `docs/CHANGELOG.md` is a pointer plus an "Unreleased highlights" summary "since v0.3.0", 99 days old. `mkdocs.yml` nav "Changelog" points at the docs copy, so the site shows the stale summary. | Stub with diverged content |
| `CONTRIBUTING.md` (root, 309) vs `docs/CONTRIBUTING.md` (313) | `docs/CONTRIBUTING.md` is a committed copy regenerated at deploy by `.github/workflows/docs.yml` step "Sync CONTRIBUTING.md into docs/ (rewrite repo-root paths)". The diff is link rewriting only. The committed copy is not checked for sync in PRs (unverified: no sync check found in `ci.yml`). | Generated mirror, identical apart from links |
| `agentic-workflows-v2/CONTRIBUTING.md` (117) vs root `CONTRIBUTING.md` | Package addendum. Defers branch, commit, PR and validation policy to the root guide. | Not a duplicate |
| `SECURITY.md` (root, 53) vs `agentic-workflows-v2/SECURITY.md` (8) | Package file is a pointer to root. | Stub redirect |
| `docs/ARCHITECTURE.md` (189) vs `agentic-workflows-v2/docs/ARCHITECTURE.md` (98) | Different scope: repo boundaries and request flow vs package layout. Same filename and role. `scripts/check-doc-drift.py` checks only the `docs/ARCHITECTURE.md` copy. | Diverged by design, easy to confuse |
| `docs/architecture-runtime.md` (711), `docs/ARCHITECTURE.md` (189), `docs/integration-architecture.md` (317) | Three overlapping architecture overviews plus deep dives. | Overlap |
| `README.md` (332), `docs/index.md` (185), `docs/project-overview.md` (139), `agentic-workflows-v2/README.md` (220) | Four landing-level overviews of the same product. | Overlap |
| `docs/getting-started/first-workflow.md` (233) vs `agentic-workflows-v2/docs/tutorials/getting_started.md` (63) and `building_workflow.md` (57) | Three first-workflow tutorials. | Overlap |
| `examples/README.md` (98) vs `agentic-workflows-v2/examples/README.md` (71) | Two examples READMEs for overlapping example sets. | Overlap |
| `docs/development-guide.md` (281) vs `agentic-workflows-v2/docs/DEVELOPMENT.md` (118) | Package doc defers to the repo guide. | Partial pointer |
| `.github/PULL_REQUEST_TEMPLATE.md` (25, 138d) vs `agentic-workflows-v2/.github/PULL_REQUEST_TEMPLATE.md` (46, 75d) | GitHub reads PR templates from the repository root `.github/` (GitHub convention, not verified in this session), so the package copy is likely inert. | Duplicate; package copy likely dead |
| `agentic-workflows-v2/docs/adr/0001, 0002, 0003, 0007` vs `docs/adr/` | Legacy, separate ADR numbering: four files, all `Status: Accepted`. `0007-extract-scoring-package.md` records the same decision as `docs/adr/ADR-032-extract-scoring-package.md` (both Accepted). Not listed in `ADR-INDEX.md`. | Duplicate decision record, orphaned numbering |
| `docs/adr/ADR-001-002-003-architecture-decisions.md` vs `RAG-pipeline-blueprint.md` vs `ADR-035` | One file holds three ADRs; the file has no `**Status:**` line and its ADR-003 section is marked superseded by ADR-007. `RAG-pipeline-blueprint.md` is the research basis for ADR-035, itself superseded by ADR-057. | Retained by design |
| `docs/adr/drafts/ADR-023-*.md` (5 notes) and `drafts/README.md` | Superseded working notes for ADR-023. The README says not to cite them as authoritative. | Intentional archive |
| `docs/superpowers/specs/2026-07-02-evaluation-framework-design.md` vs `docs/adr/ADR-042-agentic-evalkit-adoption.md` | The spec declares itself superseded as decision-of-record by ADR-042. | Superseded, kept for analysis |
| `DESIGN.md` + `PRODUCT.md` (root) vs `docs/ui/evidence-ledger-design-system.md` (769) | Root files are design context; the Evidence Ledger doc holds the rules. `docs/ui/impeccable-context-changes.md` says `tokens.css` wins on conflict. | Complementary |
| `docs/ui/evidence-ledger-full-rewrite-goal-prompt.md` (859) vs `docs/ui/evidence-ledger-migration.md` (108) | Prompt for an external rewrite task vs completed migration record. | Working artifacts |
| `docs/tools/index.md` (78) vs `tools/README.md` (53) | Same package described twice. | Overlap |
| `docs/architecture-eval.md` (453), `docs/deep-dive-agentic-v2-eval.md` (410), `agentic-v2-eval/README.md` (197), `docs/evaluation/*.md` | Four overlapping descriptions of one package that ADR-042 is replacing. | Overlap; will age with the migration |

### 8.3 Broken relative links

A scan of 205 markdown files (relative links only, fenced code excluded) found 2 broken targets. Both match `meta_inventory.json`.

| Source file | Link | Problem |
|---|---|---|
| `agentic-v2-eval/src/agentic_v2_eval/README.md` | `../../../docs/evaluation/index.md` | No `docs/evaluation/index.md`. The evaluation folder has `datasets`, `gating`, `judge`, `rubrics` and `runners` only. Intended target unverified. |
| `agentic-workflows-v2/docs/README.md` | `../DEVELOPMENT.md` | Resolves to `agentic-workflows-v2/DEVELOPMENT.md`, which does not exist. The file is `agentic-workflows-v2/docs/DEVELOPMENT.md`, so the link should be `./DEVELOPMENT.md`. |

Not checked: absolute GitHub URLs, anchors, and reference-style links.

### 8.4 Docs checker coverage and mkdocs gaps

**Checkers wired into `just docs` and CI.** The justfile `docs` recipe runs three scripts. In `.github/workflows/ci.yml`, job `check-doc-drift` (line 529) runs `scripts/check-doc-drift.py` and `agentic-workflows-v2/scripts/check_docs_refs.py`, and job `doc-stats-drift` (line 560) runs `generate_doc_stats.py --check`. The mkdocs build runs separately in `.github/workflows/docs.yml`.

| Script | Scope | Result on c3b2d328 |
|---|---|---|
| `agentic-workflows-v2/scripts/check_docs_refs.py` | Fixed `TARGET_FILES` (15 entries, relative to `agentic-workflows-v2/`) plus `WORKSPACE_TARGET_FILES` (4 entries, relative to ARP root). Note: the script lives in `agentic-workflows-v2/scripts/`, not root `scripts/`. | OK: no broken local paths, no retired RAG references |
| `scripts/check-doc-drift.py` | `docs/ARCHITECTURE.md` vs `agentic_v2/core/protocols.py`; ADR `**Status:**` body lines vs `ADR-INDEX.md` | OK: 8 protocols documented; 46 explicit ADR statuses match the index; ADR-042 pinned Accepted; no claimed number reclaimed |
| `scripts/generate_doc_stats.py --check` | Generated doc statistics | Not run (unverified) |

**Files NOT covered by `check_docs_refs.py` (link and path checks):**

- Of `agentic-workflows-v2/docs/`, only `README`, `ARCHITECTURE`, `WORKFLOWS`, `DEVELOPMENT`, `REPO_MAP`, `DOCS_BEST_PRACTICES`, `API_REFERENCE` and `MODEL_LAYER` are listed. Not covered: `NODE_CONFIG_OVERLAY.md`, `tutorials/*`, `adr/*`.
- `docs/reports/ACTIVE_VS_LEGACY_TOOLING_MAP.md` is in `TARGET_FILES` but `agentic-workflows-v2/docs/reports/` does not exist. The `.exists()` guard skips it silently, so the entry is dead.
- Root `docs/**` (128 markdown files in total, of which most are unscanned): only `docs/KNOWN_LIMITATIONS.md` and `docs/ROADMAP.md` are scanned, via the workspace list.
- Root `README.md`, `docs/api-contracts-runtime.md`, `docs/configuration.md`, `docs/deployment-guide.md`, `docs/tools/*`, `docs/evaluation/*`, `docs/ui/*`, and all ADRs are not scanned. That is why the two broken links in 8.3 survived.
- The retired-RAG pattern check runs over the same lists. No checker matches the stale GitHub Models or "fourteen jobs" claims in 8.1.
- `check-doc-drift.py` ADR check uses `^\*\*Status:\*\*` only. ADRs 007-012 and 054 use a table `| **Status** |` and are not governed (see 8.5).

**mkdocs (`mkdocs.yml`, built `--strict` in `.github/workflows/docs.yml`):**

- Nav entries: 60. Every nav target exists under `docs/`. No nav entry points at a missing file.
- `Changelog` nav entry resolves to `docs/CHANGELOG.md`, the stale stub, not the root changelog.
- `OWASP_LLM_THREAT_MODEL.md` is in `exclude_docs`. The comment says its `docs/`-prefixed links break strict builds.
- `exclude_docs` names `archive/`, `analysis/`, `reports/` and `pr-checklists/`. None exist under `docs/` in this revision, so those entries are dead config.
- Built but not in nav (orphan pages): 62 files, namely 54 ADR files (all except `ADR-INDEX.md`), `adr/RAG-pipeline-blueprint.md`, `HANDOFF.md`, `PROOF_LEDGER.md`, `404.md` (site asset, expected), and four `docs/ui/` files. Also built but not excluded: 6 `adr/drafts/*` files and `superpowers/specs/2026-07-02-evaluation-framework-design.md`. Total orphan pages: 69.
- Fix options: add the working notes (`HANDOFF.md`, `PROOF_LEDGER.md`, `adr/drafts/`, `superpowers/`) to `exclude_docs`, and add ADRs deliberately (for example one nav entry per ADR, or leave them as orphans with the index as entry point).

### 8.5 Architecture decision records

Files: 54 ADR files in `docs/adr/` (numbers 001-062 with gaps 004-006, 013, 049, 053). `ADR-INDEX.md` is the index. The "Status" column is the **file** status, checked by reading each file. "Index" is the quick-access deck in `ADR-INDEX.md`. Last commit is from `meta_inventory.json`.

| ADR | Title (short) | Status (file) | Index agrees? | Last commit |
|---|---|---|---|---|
| 001 (in combined file) | Dual execution engine (LangGraph vs native Kahn's DAG) | No Status line; decision record in combined file | Index: Accepted | 2026-09-10 |
| 002 (in combined file) | SmartModelRouter circuit-breaker hardening | No Status line; in combined file | Index: Accepted | 2026-09-10 |
| 003 (in combined file) | Deep research supervisor state machine and CI gating | Superseded by ADR-007 (blockquote) | Yes | 2026-09-10 |
| 007 | Multidimensional classification matrix and stop policy | Proposed | Yes | 2026-05-27 |
| 008 | Testing approach overhaul (value taxonomy) | **Proposed** (table Status, 2026-03-02 history) | **No: index says Accepted** | 2026-07-27 |
| 009 | Scoring enhancements (decay, lexicographic) | Accepted | Yes | 2026-07-27 |
| 010 | Commit-driven A/B eval harness methodology | Proposed | Yes | 2026-07-27 |
| 011 | Eval harness API and interface | Proposed | Yes | 2026-07-27 |
| 012 | UI evaluation hub and A/B comparison | Proposed | Yes | 2026-05-27 |
| 014 | Pydantic discriminated union as event wire format | Accepted | Yes | 2026-07-27 |
| 015 | SLO rolling window stored in git | Accepted | Yes | 2026-05-27 |
| 016 | GitHub Models via GITHUB_TOKEN as default E2E LLM | Superseded (upstream retirement 2026-07-30; no successor ADR) | Yes | 2026-10-12 |
| 017 | Dataset identifiers as query parameters | Accepted | Yes | 2026-07-27 |
| 018 | API rate limiting and per-IP auth throttle | Accepted | Yes | 2026-05-27 |
| 019 | DAG executor top-level timeout watchdog | Accepted | Yes | 2026-07-27 |
| 020 | LangChain adapter eager validation at startup | Accepted | Yes | 2026-05-27 |
| 021 | JWT OIDC authentication for API routes | Accepted | Yes | 2026-07-27 |
| 022 | Tenant-scoped run and dataset isolation | Accepted | Yes | 2026-05-27 |
| 023 | ExecutionKit runtime contract relationship (Option A') | Accepted | Yes | 2026-07-27 |
| 024 | Expression evaluation via AST interpreter | Accepted | Yes | 2026-06-14 |
| 025 | SDK-native `Task` orchestration | Accepted | Yes | 2026-07-27 |
| 026 | `--resume` and `fork_session` tradeoff | Accepted | Yes | 2026-07-27 |
| 027 | Forced / any / auto `tool_choice` | Accepted | Yes | 2026-06-14 |
| 028 | Tool descriptions as selection mechanism | Accepted | Yes | 2026-06-14 |
| 029 | Adaptive decomposition | Accepted | Yes | 2026-06-14 |
| 030 | SSRF guard pins connection target | Accepted | Yes | 2026-06-16 |
| 031 | Native DAG as single engine | Superseded; not adopted (no successor ADR) | Yes | 2026-06-16 |
| 032 | Extract scoring/judge domain | Accepted | Yes | 2026-06-24 |
| 033 | Import-time project-root resolution | Accepted | Yes | 2026-07-27 |
| 034 | Path-first file I/O contracts | Proposed | Yes | 2026-07-27 |
| 035 | RAG pipeline architecture (LanceDB + Voyage) | Superseded by ADR-057 | Yes | 2026-08-29 |
| 036 | OllamaBackend uses official client | Accepted | Yes | 2026-06-22 |
| 037 | Live Ollama model discovery | Accepted | Yes | 2026-06-22 |
| 038 | LM Studio and ONNX discovery | Accepted | Yes | 2026-07-18 |
| 039 | Cloud model discovery | Accepted | Yes | 2026-07-27 |
| 040 | Curated single-source model registry | Accepted | Yes | 2026-10-12 |
| 041 | Bounded approval gate timeout | Accepted | Yes | 2026-06-30 |
| 042 | Adopt agentic-evalkit (sliced migration) | Accepted | Yes | 2026-09-10 |
| 043 | Configurable workflow UI | Accepted | Yes | 2026-07-27 |
| 044 | Evaluation scoring visibility | Accepted | Yes | 2026-07-08 |
| 045 | BuildAppTool requires approval | Accepted | Yes | 2026-07-08 |
| 046 | Response-path entropy masking | Accepted | Yes | 2026-07-08 |
| 047 | Structural tool approval gate | Accepted | Yes | 2026-07-27 |
| 048 | Process-wide token budget | Accepted | Yes | 2026-07-09 |
| 050 | SSE chat playground and OpenRouter | Accepted | Yes | 2026-07-27 |
| 051 | Local-first Ollama cloud routing | Accepted | Yes | 2026-07-27 |
| 052 | Typed step artifact contracts | Accepted | Yes | 2026-07-16 |
| 054 | Evidence Ledger UI and versioned model packs | Accepted (table Status) | Yes | 2026-07-18 |
| 055 | File-size exception register | Accepted | Yes | 2026-07-18 |
| 056 | Prompt-versioning registry | Accepted | Yes | 2026-07-18 |
| 057 | Remove `agentic_v2.rag` package | Accepted | Yes | 2026-08-29 |
| 058 | Claude subscription backend | Accepted | Yes | 2026-08-20 |
| 059 | Curated cost lane and failover ceiling | Accepted | Yes | 2026-08-28 |
| 060 | Scheduler rules proved in Lean 4 | Accepted | Yes | 2026-09-30 |
| 061 | JSON-safe secret masks | Accepted | Yes | 2026-10-12 |
| 062 | LangGraph adapter join-once semantics | Accepted | Yes | 2026-10-12 |

"Index agrees?" compares the file status with the quick-access deck in `ADR-INDEX.md`. Every ADR except 008 appears in the deck with the same status. The index's "Implementation status" table covers only 001-024, 032-038 and 042 by design, so 025-031 and 039-041 have no audit entry.

**Index status mismatches and index gaps:**

- **ADR-008 mismatch (only one).** File status Proposed (`docs/adr/ADR-008-testing-approach-overhaul.md`, table at line 8, history 2026-03-02 "Proposed"). Index says Accepted. `check-doc-drift.py` cannot see it because the file uses a table, not `**Status:**`.
- **"?" status count.** `meta_inventory.json` reports 9 "?" statuses. These are `ADR-001-002-003`, `007`, `008`, `009`, `010`, `011`, `012`, `054` and `ADR-INDEX.md`. Real statuses from the files: 001-002-003 has no Status field (decisions are in sections, with 003 marked superseded); 007, 008, 010, 011, 012 are Proposed (008 contradicts the index); 009 is Accepted; 054 is Accepted; the index file has no status and is not an ADR.
- Index deck has 56 rows with 002 and 003 pointing into the combined file. The file list has 54 ADR files; 002 and 003 are not separate files, so the count is consistent.
- Intentional gaps: 004, 005, 006 and 013 (index says never created or withdrawn). Also 049 and 053, claimed by parked or in-flight work. The drift check enforces that no claimed number is marked Accepted.
- Next free number: index says the next free is not stated explicitly. Highest assigned is 062, so **063** is the next unclaimed number (unverified against open branches). 049 and 053 are reserved.
- Legacy `agentic-workflows-v2/docs/adr/0001-0003, 0007` are outside this index and use a separate numbering (see 8.2).

**Proposed ADRs (not accepted):** 007 (Multidimensional classification matrix; supersedes ADR-003 in intent, but ADR-003 is marked superseded by a Proposed record), 008 (testing overhaul; file says Proposed, index says Accepted), 010, 011, 012 (eval harness methodology, API, UI hub; the index notes only ~10-15% implementation at 2026-03-17), 034 (path-first I/O contracts; 0% implemented, pilot pending).

**Superseded ADRs and their successors:**

| ADR | Superseded by | Note |
|---|---|---|
| 003 (combined file) | ADR-007 | Composite CI gate replaced by classification matrix; CI scalar kept as tiebreaker |
| 016 | None (upstream retirement) | GitHub Models retired 2026-07-30; judge default moved to `nvidia:` per index lineage note. Code still has GITHUB_TOKEN wiring |
| 031 | None | Single-engine proposal not adopted; LangGraph adapter retained (ADR-001 engine stands) |
| 035 | ADR-057 | `agentic_v2/rag/` removed 2026-08-10; RAG moved to standalone groundkit repo |

Also superseded in content but still Accepted: `docs/superpowers/specs/2026-07-02-evaluation-framework-design.md` (declared superseded by ADR-042; not an ADR).

**Other ADR-level findings:**

- `ADR-INDEX.md` lineage chain and quick deck both show ADR-035 as superseded by 057 and ADR-042 as superseding `agentic-v2-eval`. ADR-042 text says in-tree package removal (slices D/E) is still pending, so "supersedes" is a decision, not yet executed (unverified against code).
- Implementation status table in `ADR-INDEX.md` lists "Last Audit" dates from 2026-03-17 to 2026-09-10. Entries for 001, 002, 010, 011, 012 cite these early dates and are not refreshed.
- ADR-016 index row and ADR file both say Superseded. The file's last commit is 2026-10-12, so the record was edited recently even though it describes a 2026-07-30 retirement.

### 8.6 Stale-content risk list (refresh first)

Ranked by the cost of a wrong answer for a reader. Ages from `meta_inventory.json`. Items 1-8 are provider or CI facts that have changed in code. Items 9-10 are fast-moving UI and changelog content.

| # | File | Age (days) | Why refresh |
|---|---|---:|---|
| 1 | `docs/configuration.md` | 1 | Env var table lists GitHub Models with `GITHUB_TOKEN`/`GH_TOKEN` (line 63). GitHub Models retired upstream 2026-07-30 (ADR-016; `agentic-workflows-v2/docs/MODEL_LAYER.md:64`). Fresh date hides the stale row. |
| 2 | `docs/getting-started/installation.md` | 1 | Same retired-provider row at line 168. New users will try to set a token for a dead provider. |
| 3 | `docs/deployment-guide.md` | 75 | Says `ci.yml` has "fourteen jobs" (line 13). `.github/workflows/ci.yml` on main defines 20 jobs, none `continue-on-error`. |
| 4 | `docs/tools/model-probing.md` | 75 | Examples use `gh:openai/gpt-4o-mini` (lines 11, 20, 73) and list GitHub Models (line 110). |
| 5 | `docs/tools/provider-limits.md` | 75 | Quota table row "GitHub Models 70" (line 86) and quota prose (line 58). |
| 6 | `docs/tools/llm-client.md` | 75 | Documents the `gh:<model>` subprocess provider (lines 33, 66-78). |
| 7 | `docs/evaluation/judge.md` | 75 | Example judge uses `model="gh:gpt-4o"` (line 151). ADR-016 says judge default moved to `nvidia:`. |
| 8 | `docs/architecture-tools.md` | 42 | Provider table row "GitHub Models ... `GITHUB_TOKEN` required" (line 65). Fresh age, stale row. |
| 9 | `docs/ui/pages.md` | 75 | "As of 2026-07-28" page guide. Evidence Ledger design-system doc changed 2026-10-08 (`docs/ui/evidence-ledger-design-system.md`), so the page guide likely lags the UI (unverified page by page). |
| 10 | `docs/CHANGELOG.md` | 99 | Published site changelog stub with an "Unreleased highlights" section from v0.3.0. Root `CHANGELOG.md` has moved on (ADR-061 entry). |

Also worth refreshing, below the top 10:

- `.claude/rules/portfolio-context.md` (age 71): says `ci.yml` defines **17** blocking jobs. The file on main defines 20 jobs. Agents read this rule every session, so the stale count propagates.
- `docs/api-contracts-runtime.md` (811 lines, age 75): REST and WebSocket reference predates ADR-050 (`POST /api/chat` SSE) and ADR-043 (`POST /api/eval/compare`) as far as the ADR dates show. Route list not checked against `server/` (unverified).
- `docs/WORKFLOW_AUTHORING.md` (903) and `docs/MODEL_LAYER.md` (212) are current (age 0) and are the best source for model routing and workflow authoring. Use them to correct items 1-8.

**Stale >90 days (not fast-moving, but flagged):** `agentic-workflows-v2/CODE_OF_CONDUCT.md` (138), `.github/PULL_REQUEST_TEMPLATE.md` (138), `.github/ISSUE_TEMPLATE/bug_report.md` (138), `.github/ISSUE_TEMPLATE/feature_request.md` (138), `agentic-workflows-v2/docs/adr/0002-evaluation-package.md` (138), `0003-server-optional.md` (138), `0007-extract-scoring-package.md` (118), `agentic-workflows-v2/tests/fixtures/backend_responses/README.md` (112), `docs/CHANGELOG.md` (99). The four legacy `agentic-workflows-v2/docs/adr/*` files are Accepted but outside `ADR-INDEX.md`; they should be retired into `docs/adr/` or removed.

**Top findings:**

1. Two live provider docs (`docs/configuration.md`, `docs/getting-started/installation.md`) still advertise GitHub Models, retired 2026-07-30, and no checker catches it.
2. The CI job count is wrong in `docs/deployment-guide.md` (14 vs 20). `.claude/rules/portfolio-context.md` says 17.
3. ADR-008 status conflict: file Proposed, index Accepted. The drift checker cannot see it because the file uses a table status line; ADRs 007-012 and 054 are ungoverned for the same reason.
4. The docs checker covers about 15 package files and 4 workspace files out of 205 markdown files. Two broken links were found and are not caught by CI.
5. The published site's "Changelog" and "Contributing" entries are generated or stale copies, and the site builds 69 orphan pages (54 ADRs included) that are not in nav.
