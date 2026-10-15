## 7. Folder-by-folder inventory

**Basis.** Committed facts come from the clean `origin/main` worktree (`C:/tmp/arp-main-inventory`, rev `c3b2d328`) via `data/fs_inventory.json`. Local-only facts come from the live checkout (branch `relock-382`) via `data/fs_local_checkout.json`. Sizes are KB on disk. "Stale" means last commit older than 90 days, and it describes age, not disuse. Nothing under `node_modules/`, `.venv/`, `.git/`, `.mypy_cache/` or `.cache/` was recursed into. Where the JSON reports no size for those, the cell says "not measured".

### 7.1 Top-level map (committed and local-only)

Committed rows show origin/main sizes. Local-only rows show live-checkout sizes. The live `tools/`, `agentic-workflows-v2/`, `docs/` and `proofs/` rows are larger than origin because ignored or untracked subtrees sit inside tracked folders (see 7.3).

| Entry | Tracked files | Size | What it contains | Why it is needed | Status | Recommended action |
|---|---|---|---|---|---|---|
| `agentic-workflows-v2/` | 1,033 (origin) | 35.4 MB origin | The runtime package: `agentic_v2/`, `ui/`, `evals/`, `tests/`, `docs/`, `scripts/`, `examples/` | Core product | Active | Keep |
| `agentic-v2-eval/` | 57 | 273 KB | In-repo evaluation package `agentic_v2_eval` (rubrics, metrics, evaluators) | Scores structured results; ARP's eval harness | Active | Keep. `scripts/` and `tests/` are stale |
| `tools/` | 82 | 791 KB origin | Shared `agentic-tools` package: `core/`, `llm/` (provider probing, bakeoffs), `agents/benchmarks/`, `tests/` | Shared utilities for runtime, eval and maintenance commands | Active | Keep. `core/` and `agents/repo_analyzer/` are stale |
| `docs/` | 143 | 1.8 MB origin | ADRs (56), guides, evaluation and operations docs, mkdocs source | Documentation source; feeds `mkdocs.yml` | Active | Keep. `docs/assets/`, `docs/screenshots/`, `docs/stylesheets/` are stale |
| `scripts/` | 12 | 124 KB | `eval_gate.py`, `check-doc-drift.py`, `build_load_report.py`, `validate-workflows.py`, release verification, trace tools | Repo-level CI and maintenance scripts | Active | Keep |
| `tests/` | 2 | 23 KB | Only `tests/e2e/` (cross-package E2E) | Cross-package integration tests | Active | Keep |
| `examples/` | 9 | 60 KB | Python API demos (01 through 06, resume, tool choice, SDK orchestrator) plus README | Runnable usage examples | Active | Keep. README says not all run without a provider |
| `datasets/` | 6 | 33 KB | `default/` golden evaluation dataset (committed workflow outputs, `golden_cases.json`) | Deterministic eval gate input | Active | Keep |
| `proofs/` | 7 | 168 KB origin | Lean 4 model of the DAG scheduler (ADR-060): `Scheduler.lean`, `Main.lean`, lakefile | Formal model of the scheduler; `lean-proofs.yml` CI | Active | Keep. Live `proofs/.lake/` build cache is local-only |
| `load/` | 15 | 49 KB | k6 scripts, Compose and nginx load harness, `baseline.json`, results | Local load and Redis CAS checks | Active (results stale) | Keep. Results are 120 days old |
| `infra/` | 3 | 13 KB | `infra/azure/` Bicep reference template (not deployed by CI) | Reference for a managed Azure deploy | Unused (reference only) | Keep as reference or move out of tree |
| `otel/` | 1 | 0.4 KB | `otel-collector-config.yaml` | Collector config for OpenTelemetry | Config (stale, 138 days) | Keep if the compose stack uses it; otherwise delete |
| `.github/` | 24 | 135 KB | 18 workflows (`ci.yml`, `eval-package-ci.yml`, `lean-proofs.yml`, `deploy.yml`, ...) and issue templates | CI, CD, Dependabot and security scanning | Active (`ISSUE_TEMPLATE/` stale) | Keep |
| `.devcontainer/` | 1 | 1.3 KB | `devcontainer.json` building `../Dockerfile` | Dev container; CI validates it | Config (stale, 121 days) | Keep |
| `.claude/` | 4 (`rules/*.md`) | 15 KB | Tracked rule files: `ci.md`, `portfolio-context.md`, `testing.md`, `ui-design.md` | Imported by `CLAUDE.md` | Active | Keep. Live `.claude/` also holds ignored local settings (see 7.3) |
| `.impeccable/` | 1 | 9 KB | `design.json` design context | Design-system context for the UI tooling | Active | Keep |
| `.secrets.baseline` | 1 | 78 KB | `detect-secrets` baseline | Pre-commit secret scan baseline | Config | Keep. Re-baseline when findings change |
| `.env.example` | 1 | 8.5 KB | Every env key name, no values | Documents config; required by security rules | Config | Keep in sync with code |
| `.gitattributes`, `.gitignore`, `.mailmap`, `.nvmrc`, `.python-version`, `.pre-commit-config.yaml`, `.dockerignore` | 1 each | under 10 KB each | Git, Docker, pre-commit and toolchain pins | Repo hygiene and toolchain | Config | Keep |
| `Dockerfile`, `Dockerfile.ui`, `docker-compose.yml` | 1 each | 2.9 KB, 1.0 KB, 2.0 KB | Backend image, UI image, compose stack | Container build and local stack | Active | Keep |
| `ci-constraints.txt` | 1 | 13.8 KB | Pins generated from `uv.lock` | Used by `just setup` and CI constraints gate | Generated | Regenerate with `just relock`; never hand-edit |
| `uv.lock` | 1 | 1.1 MB | uv lockfile for the workspace | Reproducible installs | Generated (large) | Keep |
| `pyproject.toml` | 1 | 2.7 KB | Root workspace project config | Build and tool config | Config | Keep |
| `justfile` | 1 | 3.7 KB | Task runner recipes (`setup`, `test`, `docs`) | Canonical local commands | Active | Keep |
| `package.json`, `package-lock.json` | 1 each | under 3 KB | Root npm stub whose `npm test` fails on purpose | Only satisfies the root `node_modules` requirement | Stub | Keep (workspace rule), or document as intentional |
| `mkdocs.yml` | 1 | 5.8 KB | Docs site config | Builds `site/` | Config | Keep |
| `sonar-project.properties` | 1 | 1 KB | SonarQube project config | Static analysis | Config | Keep |
| `release-manifest.toml` | 1 | 1 KB | Release manifest | Read by `verify_release_artifacts.py` | Config | Keep |
| `eval_pipeline.png` | 1 | 27 KB | Image of the eval pipeline | No tracked file references it (`git grep` is empty; only a local Playwright log mentions it) | Unused | Confirm with the owner, then reference it from docs or remove it |
| `CHANGELOG.md`, `CONTRIBUTING.md`, `SECURITY.md`, `README.md`, `LICENSE`, `CLAUDE.md`, `AGENTS.md`, `DESIGN.md`, `PRODUCT.md`, `AI_EVIDENCE_STANDARD.md` | 1 each | 1 KB to 74 KB | Root documentation and agent context | Contributor, security and agent guidance | Active | Keep |
| `.git/` | not tracked | not measured | Git metadata | Repository | Local-only | Keep |
| `.env` | not tracked | 10 KB | Live provider API keys (not read in this inventory) | Runtime secrets for local runs | Local-only (secret) | Keep. Never commit. Rotate if exposed |
| `.venv/` | not tracked | not measured | Python virtualenv for the root workspace | `just` recipes and PowerShell calls use `.venv/Scripts/python.exe` | Local-only cache | Keep while in use. Recreate with `just setup` if needed |
| `node_modules/` | not tracked | not measured | Root stub dependencies | Satisfies root `npm test` | Local-only cache | Regenerable with `npm install` |
| `.mypy_cache/` | not tracked | 620 MB (30,396 files) | mypy incremental cache | Speeds up type checks only | Local-only cache | Safe to delete (largest single item) |
| `.cache/` | not tracked | 134 MB (21,132 files) | `docs-site/` build cache and `doc-command-audit.txt` | Doc build cache | Local-only cache | Safe to delete |
| `.pytest_cache/`, `.ruff_cache/`, `.hypothesis/` | not tracked | 0.5 MB, 0.1 MB, 0.1 MB | Pytest, Ruff and Hypothesis caches | Speed only | Local-only cache | Safe to delete |
| `.playwright-mcp/`, `.playwright-cli/` | not tracked | 0.4 MB, 0.2 MB | Browser console and page snapshot logs from automation runs | Debugging artifacts | Local-only artifact | Safe to delete |
| `.sonar/` | not tracked | 0 KB | Empty SonarQube scanner cache directory | None | Local-only cache | Safe to delete |
| `.vscode/` | not tracked | 0.2 KB | Local editor settings | Personal IDE setup | Local-only config | Keep |
| `.agentic_replay.db` | not tracked | 1.4 MB | SQLite replay store (`replay_store.py`, `REPLAY_DB_FILENAME`). A second copy sits in `agentic-workflows-v2/` (614 KB, Jul 6) | Stores run replays; user data | Local-only data | Keep. Do not delete without asking. Consider archiving |
| `.agentic_ui_settings.json` | not tracked | 5.6 KB | Local dashboard settings | User preferences | Local-only data | Keep |
| `runs/` | not tracked | 23 MB (3,054 files) | Per-run JSON logs in `runs/default/` written by `run_logger.py` (`/runs/` is gitignored) | Run history; `rescoring` mutates these in place | Local-only data | Keep. Ask before deleting. Archive old runs if disk is needed |
| `site/` | not tracked | 16.8 MB (306 files) | `mkdocs build` output (HTML) | Generated docs site | Generated (local) | Safe to delete; rebuild with mkdocs |
| `dist/` | not tracked | 3.4 MB | Built wheel and sdist for `agentic_tools 0.1.0` | Build output for the root `tools` package | Local-only artifact | Safe to delete; rebuild when needed |
| `output/` | not tracked | 1.1 MB | `output/playwright/` UI screenshots (control room, evidence ledger) | Visual check captures | Local-only artifact | Safe to delete after review |
| `artifacts/` | not tracked | 6 KB | `wf-bug_resolution/` (`code_file.py`, `test_clamp_fix.py`) from a workflow run | Workflow output sample | Local-only artifact | Safe to delete |
| `coverage.xml`, `.coverage` | not tracked | 1.1 MB, 52 KB | Coverage outputs (Jun 6 and Jul 28) | Stale; regenerated by test runs | Local-only artifact (stale) | Safe to delete |
| `.adversarial-review/` | not tracked | 0.7 MB | Codex adversarial review run (`code_review_v1.md`, diff, prompt, script) | One-off review record | Local-only artifact | Safe to delete once the review is closed |
| `evidence-ledger-design-system/` | not tracked | 11.3 MB (80 files) | Design-system export: `index.html`, `tokens.css`, `tokens.json`, `components/`, `assets/`, README. Gitignored at root (`/evidence-ledger-design-system/`) | Design reference for the Evidence Ledger UI | Local-only artifact | Keep until the UI design is settled. Then move to `docs/` or remove |
| `_bmad/`, `_bmad-output/` | not tracked | 85 KB, 21 KB | BMAD method scaffolding (`config.toml`, bmm workflows) and BMAD planning output (`deferred-work.md`, specs) | Agent workflow tooling | Local-only tool | Regenerable from the BMAD installer; keep if used |
| `.agents/` | not tracked | 1.3 MB (227 files) | BMAD skill mirror (`skills/bmad-*`) | Agent skill tooling | Local-only tool | Regenerable; safe to delete if unused |
| `agentic-workflows-v2/New folder (2)/` | not tracked | not measured | Contains only `node_modules/` (no source) | Accidental folder | Orphan | Safe to delete |

Note: `_bmad*`, `.agents/`, `.impeccable/live/` and `.claude/*` (except the tracked rules) are gitignored on purpose. They hold tool state, not source.

### 7.2 Second and third level, committed tree (origin/main)

Files are tracked counts. "Last commit" shows date and age in days. "Stale" means older than 90 days. Purposes come from folder names, package docstrings, and READMEs where present.

**Repo root and tooling**

| Dir | Files | Dominant types | Last commit | Stale | Purpose |
|---|---|---|---|---|---|
| `.` (root files) | 32 | md 9, no-ext 9, yml 2, json 2 | 2026-10-12 (0) | No | Root configs and docs |
| `.claude/rules` | 4 | md | 2026-10-09 (3) | No | Rules imported by `CLAUDE.md` |
| `.devcontainer` | 1 | json | 2026-06-13 (121) | Yes | Dev container definition |
| `.github` | 3 | md, yml | 2026-09-23 (18) | No | Top-level GitHub files |
| `.github/ISSUE_TEMPLATE` | 3 | md, yml | 2026-05-27 (138) | Yes | Issue forms |
| `.github/workflows` | 18 | yml | 2026-10-12 (0) | No | CI, CD, Dependabot, CodeQL, SBOM, Lean, docs |
| `.impeccable` | 1 | json | 2026-10-09 (3) | No | Design context (`design.json`) |

**agentic-workflows-v2 (runtime package)**

| Dir | Files | Dominant types | Last commit | Stale | Purpose |
|---|---|---|---|---|---|
| `agentic-workflows-v2` | 10 | md 5, no-ext 2, json, sh | 2026-10-10 (1) | No | Package root: README, pyproject, `dev.sh` |
| `agentic-workflows-v2/.github` | 1 | md | 2026-07-29 (75) | No | Package-level contributor doc |
| `agentic-workflows-v2/.github/ISSUE_TEMPLATE` | 3 | yml | 2026-05-27 (138) | Yes | Issue forms |
| `agentic_v2` | 6 | py | 2026-10-12 (0) | No | Package init and top-level modules |
| `agentic_v2/adapters` | 8 | py | 2026-09-25 (17) | No | Execution-engine adapters and registry |
| `agentic_v2/agents` | 18 | py | 2026-09-24 (18) | No | Specialized agent classes |
| `agentic_v2/cli` | 4 | py | 2026-09-10 (32) | No | `agentic_v2` command-line interface |
| `agentic_v2/config` | 6 | yaml 5, py | 2026-10-12 (0) | No | YAML runtime configuration |
| `agentic_v2/contracts` | 8 | py | 2026-09-25 (17) | No | Pydantic contracts (wire-format source of truth) |
| `agentic_v2/core` | 5 | py | 2026-10-11 (0) | No | Engine-agnostic protocols and context |
| `agentic_v2/devex` | 5 | py | 2026-07-12 (92) | Yes | Developer-experience utilities |
| `agentic_v2/engine` | 19 | py | 2026-10-12 (0) | No | DAG executor, execution context, step runners |
| `agentic_v2/evaluation` | 2 | py | 2026-05-27 (138) | Yes | Evaluation helpers shared by workflow and server |
| `agentic_v2/governance` | 3 | py | 2026-07-12 (92) | Yes | Human-approval gate primitives (HITL) |
| `agentic_v2/integrations` | 32 | py 31, md 1 | 2026-10-11 (0) | No | External framework and provider integrations |
| `agentic_v2/langchain` | 16 | py | 2026-10-12 (0) | No | LangChain and LangGraph engine |
| `agentic_v2/middleware` | 11 | py | 2026-10-12 (0) | No | Prompt sanitization and security pipeline |
| `agentic_v2/models` | 32 | py | 2026-10-12 (0) | No | Model routing (`SmartModelRouter`), circuit breakers |
| `agentic_v2/prompts` | 14 | md 12, py 2 | 2026-10-01 (12) | No | Agent prompt templates |
| `agentic_v2/scoring` | 14 | py 11, yaml 3 | 2026-10-12 (0) | No | Scoring, rubric and judge logic |
| `agentic_v2/security` | 2 | py | 2026-06-18 (116) | Yes | Runtime security helpers |
| `agentic_v2/server` | 34 | py | 2026-10-10 (1) | No | FastAPI app, routes, replay store |
| `agentic_v2/tools` | 17 | py | 2026-07-22 (82) | No | Tool system |
| `agentic_v2/utils` | 2 | py | 2026-08-09 (64) | No | Shared helpers |
| `agentic_v2/workflows` | 16 | yaml 9, py 7 | 2026-10-12 (0) | No | Named YAML workflows and run logger |
| `agentic-workflows-v2/backend/src` | 1 | py | 2026-05-27 (138) | Yes | `main.py` only; no live consumer found in this pass |
| `agentic-workflows-v2/shared/src` | 1 | py | 2026-05-27 (138) | Yes | `utils.py` only; no live consumer found in this pass |
| `agentic-workflows-v2/docs` | 9 | md | 2026-10-12 (0) | No | Package docs (index, guides) |
| `agentic-workflows-v2/docs/adr` | 4 | md | 2026-07-27 (77) | No | Package-level ADRs |
| `agentic-workflows-v2/docs/tutorials` | 3 | md | 2026-07-29 (75) | No | Tutorials |
| `agentic-workflows-v2/evals/swe_ab` | 152 | json 47, jsonl 44, py 37, md 18 | 2026-09-25 (17) | No | SWE-bench A/B harness: runner, graders, reports, ledger |
| `agentic-workflows-v2/examples` | 7 | py 5, md, json | 2026-07-29 (75) | No | Runtime examples (see its README) |
| `agentic-workflows-v2/fixtures` | 3 | json 2, md | 2026-07-29 (75) | No | Committed sample run envelope and inputs |
| `agentic-workflows-v2/schemas` | 2 | json | 2026-05-27 (138) | Yes | Workflow and trusted-model-hash JSON schemas |
| `agentic-workflows-v2/scripts` | 15 | ps1 8, py 6, sh | 2026-09-10 (32) | No | Dev, test, coverage and restart scripts |
| `agentic-workflows-v2/scripts/fixtures` | 1 | json | 2026-05-27 (138) | Yes | Script fixture |
| `agentic-workflows-v2/tests` | 164 | py | 2026-10-12 (0) | No | Unit and integration suite |
| `agentic-workflows-v2/tests/contract` | 2 | py | 2026-08-09 (64) | No | Contract tests |
| `agentic-workflows-v2/tests/devex` | 4 | py | 2026-07-12 (92) | Yes | Devex tests |
| `agentic-workflows-v2/tests/engine` | 11 | py | 2026-10-01 (11) | No | Engine tests |
| `agentic-workflows-v2/tests/fixtures` | 27 | json 21, py 5, md | 2026-10-12 (0) | No | Test fixtures |
| `agentic-workflows-v2/tests/golden` | 2 | json | 2026-07-18 (86) | No | Golden outputs |
| `agentic-workflows-v2/tests/integrations` | 9 | py 8, md | 2026-10-11 (0) | No | Integration tests |
| `agentic-workflows-v2/tests/langchain` | 2 | py | 2026-07-12 (92) | Yes | LangChain tests |
| `agentic-workflows-v2/tests/models` | 31 | py | 2026-10-12 (0) | No | Model routing tests |
| `agentic-workflows-v2/tests/schemas` | 32 | json | 2026-09-10 (32) | No | Generated schemas checked by the drift job |
| `agentic-workflows-v2/tests/server` | 18 | py | 2026-10-11 (0) | No | API tests |
| `agentic-workflows-v2/tests/slo` | 4 | py 2, json 2 | 2026-07-18 (86) | No | SLO checks |
| `agentic-workflows-v2/tests/tools` | 5 | py | 2026-07-22 (82) | No | Tool tests |
| `agentic-workflows-v2/ui` | 11 | json 4, ts 3, md, html | 2026-10-12 (0) | No | Dashboard package config and entry |
| `agentic-workflows-v2/ui/e2e` | 16 | ts 15, md | 2026-10-12 (0) | No | Playwright E2E tests |
| `agentic-workflows-v2/ui/scripts` | 2 | mjs | 2026-09-10 (32) | No | UI build helpers |
| `agentic-workflows-v2/ui/src` | 207 | tsx 141, ts 62, css 3, snap 1 | 2026-10-11 (1) | No | React 19 dashboard source |

**Eval package, shared tools, docs**

| Dir | Files | Dominant types | Last commit | Stale | Purpose |
|---|---|---|---|---|---|
| `agentic-v2-eval` | 3 | md, toml | 2026-07-29 (75) | No | Eval package root |
| `agentic-v2-eval/scripts` | 1 | sh | 2026-05-27 (138) | Yes | Eval helper script |
| `agentic-v2-eval/src/agentic_v2_eval` | 38 | py 29, yaml 8 | 2026-07-29 (75) | No | Evaluators and YAML rubrics |
| `agentic-v2-eval/tests` | 15 | py | 2026-07-12 (92) | Yes | Eval tests |
| `tools` | 2 | md, py | 2026-07-29 (75) | No | `agentic-tools` package root |
| `tools/agents` | 1 | py | 2026-05-27 (138) | Yes | Agent helper |
| `tools/agents/benchmarks` | 14 | py 12, md | 2026-07-29 (75) | No | Benchmark harness |
| `tools/agents/repo_analyzer` | 3 | py | 2026-07-12 (92) | Yes | Repo analysis tool |
| `tools/core` | 10 | py | 2026-07-12 (92) | Yes | Core utilities |
| `tools/llm` | 28 | py 27, ps1 | 2026-10-12 (0) | No | Provider probing, model registry, bakeoff, rankings |
| `tools/llm/windows_ai_bridge` | 6 | ps1 2, md, csproj, cs | 2026-07-29 (75) | No | C# Windows AI bridge (Phi Silica) |
| `tools/tests` | 18 | py | 2026-08-09 (64) | No | Tests for `tools` |
| `docs` | 39 | md | 2026-10-12 (0) | No | Docs top level (ops, getting started, workflows) |
| `docs/adr` | 56 | md | 2026-10-12 (0) | No | Architecture decision records |
| `docs/adr/drafts` | 6 | md | 2026-07-27 (77) | No | Draft ADRs |
| `docs/assets` | 2 | jpg, png | 2026-07-05 (99) | Yes | Doc images |
| `docs/assets/icons` | 8 | svg | 2026-07-05 (99) | Yes | Doc icons |
| `docs/evaluation` | 5 | md | 2026-07-29 (75) | No | Evaluation docs |
| `docs/getting-started` | 4 | md | 2026-10-10 (1) | No | Onboarding docs |
| `docs/operations` | 3 | md | 2026-08-31 (42) | No | Operations runbooks |
| `docs/screenshots` | 2 | html, png | 2026-06-08 (126) | Yes | Screenshots |
| `docs/stylesheets` | 3 | css | 2026-07-05 (99) | Yes | mkdocs stylesheets |
| `docs/superpowers/specs` | 1 | md | 2026-07-27 (77) | No | Spec document |
| `docs/tools` | 7 | md | 2026-07-29 (75) | No | Tooling docs |
| `docs/ui` | 6 | md | 2026-10-09 (3) | No | UI design docs (tracked subset) |
| `docs/workflows` | 1 | md | 2026-10-12 (0) | No | Workflow doc |

**Other top-level areas**

| Dir | Files | Dominant types | Last commit | Stale | Purpose |
|---|---|---|---|---|---|
| `load` | 8 | py 2, load, md, json | 2026-07-29 (75) | No | Load-report generators and baseline |
| `load/k6` | 2 | js | 2026-06-14 (120) | Yes | k6 load scripts |
| `load/results` | 5 | json 4, txt | 2026-06-14 (120) | Yes | Committed load results |
| `scripts` | 12 | py 11, ps1 | 2026-09-25 (17) | No | Repo CI and maintenance scripts |
| `examples` | 9 | py 8, md | 2026-08-29 (44) | No | Python API demos |
| `proofs` | 6 | lean 2, md, json, toml | 2026-09-30 (12) | No | Lean model root and lake config |
| `proofs/Scheduler` | 1 | lean | 2026-09-26 (16) | No | Scheduler validation module |
| `datasets/default` | 6 | json 5, md | 2026-07-29 (75) | No | Golden evaluation dataset |
| `infra/azure` | 3 | md, bicep, example | 2026-07-29 (75) | No | Azure reference template |
| `otel` | 1 | yaml | 2026-05-27 (138) | Yes | OTel collector config |
| `tests/e2e` | 2 | py | 2026-07-18 (86) | No | Cross-package E2E tests |

### 7.3 Local-only clutter summary

Measured totals:

- **Ignored or local-only root entries:** 24 measured entries, about 835,400 KB (about 816 MB). `.venv/`, `node_modules/` and `.git/` are not measured.
- **Local-only subtrees inside tracked folders** (`du` with `node_modules`, `.venv` and caches excluded): `agentic-workflows-v2/` about 198 MB, `proofs/` about 116 MB, `tools/` about 55 MB, `docs/` about 14 MB, `agentic-v2-eval/` about 2 MB, `scripts/` about 0.4 MB. In origin/main the same folders are 35.4 MB (`agentic-workflows-v2/`), 0.17 MB (`proofs/`), 0.79 MB (`tools/`), 1.8 MB (`docs/`), 0.27 MB (`agentic-v2-eval/`) and 0.12 MB (`scripts/`), so most of the gap is local-only.

Biggest local-only offenders, with their safety class:

| Path | Size | Class | Note |
|---|---|---|---|
| `.mypy_cache/` | 620 MB | Safe to delete | Type-check cache; largest item |
| `.cache/` | 134 MB | Safe to delete | `docs-site/` build cache |
| `proofs/.lake/` | about 116 MB | Safe to delete | Lean build output; `lake build` regenerates it |
| `tools/llm/windows_ai_bridge/bin/` | 50 MB (`obj/` 1.4 MB) | Safe to delete | Gitignored .NET build output; rebuild if needed |
| `agentic-workflows-v2/evals/swe_ab/artifacts/` | 63 MB | Ask first | Ignored run outputs of the SWE-AB harness |
| `agentic-workflows-v2/evals/swe_ab/ledger/campaign.db` | about 44 MB (inside `ledger/`) | Hold (data) | Ignored eval ledger database |
| `runs/` | 23 MB (3,054 files) | Hold (data) | Backend run history. Do not delete without asking |
| `site/` | 17 MB | Safe to delete | `mkdocs build` output |
| `evidence-ledger-design-system/` | 11 MB | Hold (work product) | Design export, not a cache |
| `dist/` | 3.4 MB | Safe to delete | Rebuildable wheels |
| `agentic-workflows-v2/ui/coverage/`, `ui/dist/` | 4.1 MB, 1.1 MB | Safe to delete | Vitest and Vite outputs |
| `output/` | 1.1 MB | Safe after review | Playwright screenshots |
| `coverage.xml`, `.coverage` (root, package copies) | about 2.4 MB in total | Safe to delete | Stale coverage outputs |
| `.agentic_replay.db` (root and in `agentic-workflows-v2/`) | 1.4 MB and 0.6 MB | Hold (data) | Replay store. Two copies exist |
| `.agentic_ui_settings.json`, `.claude/settings.local.json`, `.claude/launch.json` | small | Hold (config) | User settings |
| `.env` | 10 KB | Hold (secret) | Live keys. Gitignored. Not read in this inventory |

Safe to delete now: `.mypy_cache/`, `.cache/`, `.pytest_cache/`, `.ruff_cache/`, `.hypothesis/`, `.sonar/` (empty), `.playwright-mcp/`, `.playwright-cli/`, `site/`, `dist/`, `coverage.xml`, `.coverage` files, `proofs/.lake/`, `tools/llm/windows_ai_bridge/bin|obj/`, `ui/dist|coverage|test-results`, and `agentic-workflows-v2/New folder (2)/`. Clear the pytest, ruff and mypy caches in every package, not only the root.

Hold, because they hold user data or work product: `runs/`, both `.agentic_replay.db` files, `evals/swe_ab/ledger/campaign.db`, `.env`, `.agentic_ui_settings.json`, `_bmad-output/` (planning and `deferred-work.md`), `evidence-ledger-design-system/`, and the untracked `docs/ui/` mockups.

### 7.4 Orphans, leftovers and large tracked files

| Item | Tracked? | Finding | Recommendation |
|---|---|---|---|
| `agentic-workflows-v2/agentic_v2/memoryctl/` | No | Contains only `__pycache__/` (about 30 `.pyc` files). No source. | Delete the directory |
| `agentic-workflows-v2/agentic_v2/rag/` | No | Contains only `__pycache__/`. Removed by ADR-057 (CHANGELOG entry). No tracked importers | Delete the directory |
| `agentic-workflows-v2/New folder (2)/` | No | Contains only `node_modules/`, created 2026-06-20 | Delete the folder |
| `agentic-workflows-v2/backend/src/main.py` | Yes (1 file, 0.3 KB, last commit 2026-05-27) | No references anywhere in the repo | Verify, then remove, or mark as a stub |
| `agentic-workflows-v2/shared/src/utils.py` | Yes (1 file, 0.1 KB, last commit 2026-05-27) | No references anywhere in the repo | Verify, then remove, or mark as a stub |
| `agentic-workflows-v2/fixtures/` | Yes (3 files) | Documented as committed examples in its README, used by docs and tests | Keep |
| `agentic-workflows-v2/schemas/` | Yes (2 JSON files, last commit 2026-05-27) | Workflow and trusted-model-hash schemas. Stale but plausibly referenced | Keep. Confirm consumers |
| `agentic-workflows-v2/dev.sh` | Yes (1 file, 1.9 KB) | Dev launcher. No other tracked reference | Keep if used on Git Bash; else remove |
| `agentic-workflows-v2/dist/` | No | Wheel and sdist for `agentic_workflows_v2 0.1.0` (Jul 16) | Safe to delete |
| `dist/` (root) | No | Wheel and sdist for `agentic_tools 0.1.0` | Safe to delete |
| `eval_pipeline.png` (root) | Yes | No tracked references | Reference it or remove it |
| `evidence-ledger-design-system.zip` | Not at repo root | Two copies sit in `C:/Users/tandf/Downloads/` (`evidence-ledger-design-system.zip` and `_1.zip`). The task brief expected a root copy, which does not exist | Keep one copy outside the repo, or delete the duplicates after review |
| `.coverage` duplicates | No | `.coverage` exists at root, `agentic-v2-eval/`, and `agentic-workflows-v2/` | Delete stale copies |

Large tracked files (origin/main, over 1 MB, 11 files, about 18.4 MB total):

- Ten of the eleven are in `agentic-workflows-v2/evals/swe_ab/` (reports and `ledger/export/trial.jsonl`, each 1.0 to 2.4 MB).
- `uv.lock` is 1.1 MB and generated.

There are no LFS filters in `.gitattributes`. Moving the eval reports out of the repo, or to Git LFS, would cut clone size. This is a recommendation only and needs owner review.

### 7.5 Untracked work in the live checkout

The live checkout has 372 untracked entries in `fs_local_checkout.json`. None are in origin/main.

| Folder | Untracked files | What they are | Examples |
|---|---|---|---|
| `docs/ui/` | 353 | Design exports and working files, about 10 MB. Mostly HTML mockups plus `design-system/`, `superdesign-local/`, `_impeccable/` and `_design-system.tgz` | `Run Inspector*.html` (6 variants), `Live execution*.html`, `Dispatch - Tier board.html`, `Dossier - Run record.html`, `designd.html` to `designg.html`, `.impeccable/critique/*.md` |
| `agentic-workflows-v2/ui/src/components/el/` and `lib/` | 9 | Evidence Ledger components, the in-progress UI work (relates to committed commits `13e5101f`, `1f0140a5`, `3dbfae10`) | `ApprovalGate.tsx`, `EventLog.tsx`, `LiveSteps.tsx`, `ModelChain.tsx`, `ReRunSheet.tsx`, `TierLanes.tsx`, `Waterfall.tsx`, `timeScale.ts`, `lib/runSentence.ts` |
| `scripts/inventory/` | 6 | Generators for this inventory (`_common.py`, `fs_inventory.py`, `meta_inventory.py`, and siblings) | `fs_inventory.py` |
| `docs/inventory/` | 4 plus this `sections/` directory | Inventory JSON data and the section drafts | `data/fs_inventory.json`, `data/fs_local_checkout.json` |

Ignored-but-present items inside tracked folders are covered in 7.3. The git status snapshot also lists four modified tracked files (`.env.example`, `.gitignore`, `tools/llm/probe_config.py`, `tools/llm/probe_discovery_providers.py`). Those are edits, not untracked work.
