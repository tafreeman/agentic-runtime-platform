## 6. Build, CI/CD, infrastructure & operations

Basis: clean worktree `C:/tmp/arp-main-inventory` at `c3b2d328` (origin/main). Workflow metadata cross-checked against `docs/inventory/data/meta_inventory.json`. "Blocks PRs" is inferred from triggers, job wiring and `continue-on-error`. Branch-protection and required-check settings are not stored in the repo, so any claim about them is marked (unverified).

### 6.1 CI workflows

18 files in `.github/workflows/` (paths are repo-relative).

| File | Triggers | Jobs (ids) | Purpose | Blocks PRs? |
|---|---|---|---|---|
| `ci.yml` | push, pull_request (no branch filter) | 20 (see 6.1.1) | Core Python, UI, docs and drift gate | Intended yes; required-check status (unverified) |
| `eval-package-ci.yml` | push (main, agenticv2, paths); pull_request (no paths, so the required golden gate always reports); cron 06:00 daily; dispatch | test, lint, type-check, build, eval-golden-gate, eval-live-gate | `agentic-v2-eval` package CI; golden gate at threshold 0.80 (line 170) | `eval-golden-gate` yes (header comment, lines 23-28, says required on main; live check unverified). `eval-live-gate` runs only on label `run-live-eval` or schedule |
| `windows-workflows-ci.yml` | push/PR on main, agenticv2; path-filtered | verify-workflows | Dry-run of the bundled workflows on Windows (`uv sync --frozen`) | Yes when paths match |
| `codeql.yml` | push/PR (main, agenticv2); cron Sun 02:00 | analyze (python, javascript-typescript) | CodeQL SAST | Unverified |
| `dependency-audit.yml` | push (main); cron Mon 06:00; dispatch | python-audit (pip-audit), npm-audit | Vulnerability scan, Python and npm | Unverified; has a justification-file path (around line 493) |
| `dependency-review.yml` | pull_request (main) | dependency-review | `actions/dependency-review-action@v5`, `fail-on-severity: high` | Yes (fails on high-severity introduced deps) |
| `dependency-drift-check.yml` | cron Mon 06:00; dispatch | ek-delegation-drift, evalkit-bridge-drift | Runs the EK and EVK bridge suites against unpinned extras to detect upstream drift | No (no `continue-on-error`; a failure is the finding) |
| `upstream-compatibility.yml` | cron Mon 08:23; dispatch | latest-stable (matrix) | Advisory run against latest upstream | No (file header: advisory only) |
| `dependabot-auto-merge.yml` | pull_request, actor `dependabot[bot]` | auto-merge | `gh pr merge --auto --squash` on Dependabot PRs | No (enables auto-merge; checks still gate) |
| `dependabot-relock.yml` | dispatch; cron 12:00 daily | discover-relock-candidates, relock, relock-scheduled | Re-locks `uv.lock` and `ci-constraints.txt` on Dependabot pip PRs | No |
| `docs.yml` | push main (docs/**, mkdocs.yml, CHANGELOG, CONTRIBUTING); dispatch | deploy | `mkdocs build --strict`, then `mkdocs gh-deploy --force` | No |
| `load-report-pages.yml` | push main (load/, build script); dispatch | render-and-deploy | `scripts/build_load_report.py`, mkdocs build, Pages deploy | No |
| `deploy.yml` | push tags `v*`; pull_request (path-filtered); dispatch | build-release-assets, attest-release-assets, publish-release | Release bundle: wheels, Docker images, provenance attestation, GitHub release (env `release`) | Publish is tag/env gated; exact PR behaviour (unverified) |
| `infra-deploy.yml` | dispatch only; deploy job runs only if input `confirm == 'DEPLOY'` (line 49) | validate, deploy | Bicep build and lint; gated what-if and deploy via OIDC (`azure/login@v3`). Name says "reference, never run" | No |
| `devcontainer-validate.yml` | pull_request, path-filtered to `.devcontainer/**`, Dockerfile, pyproject, UI package files | validate-devcontainer | Builds the devcontainer target | Path-filtered (step detail not read) |
| `nightly.yml` | cron 07:00 UTC daily; dispatch | streaming-50x, performance-regression | Flake-rate sensor and perf summary. Both steps `continue-on-error: true` (lines 67, 149) | No (comment, lines 61-62: not a release gate) |
| `sbom.yml` | release; cron Mon 06:00; dispatch | generate-sbom | CycloneDX SBOM for the Python env and npm tree | No |
| `lean-proofs.yml` | push/PR (main, agenticv2) with paths on `proofs/**` and scheduler/DAG code; cron 04:17; dispatch | lean-replay | Lean build, Python replay tests, axiom audit (see 6.6) | Path-filtered; yes when triggered (unverified as required) |

Other `.github/` files: `dependabot.yml`, `CODEOWNERS` (`*` and all subtrees owned by `@tafreeman`), `PULL_REQUEST_TEMPLATE.md` (checklist includes `pre-commit run --all-files`), `ISSUE_TEMPLATE/` (`bug_report.md`, `feature_request.md`, `config.yml`). There is no `.github/actions/` directory.

#### 6.1.1 `ci.yml` job map

| Job id | What it does (line refs in `.github/workflows/ci.yml`) |
|---|---|
| `python-smoke` | Python smoke install and checks (14-47) |
| `frontend-build` | UI build, Node 22 (48-63) |
| `frontend-test` | UI tests with coverage (64-85) |
| `lint` | Ruff check on `agentic_v2/` and `tests/` (86-112) |
| `suppression-ratchet` | `agentic-workflows-v2/scripts/check_suppression_ratchet.py` (113-132) |
| `typecheck-core-contracts` | Strict mypy on `agentic_v2/engine` and `contracts` (133-156) |
| `test-coverage` | `pytest tests/ --cov=agentic_v2`, then `coverage report --fail-under=80`; whole-repo visibility report; Codecov upload with `fail_ci_if_error: false` (157-218) |
| `claude-subscription-tests` | Claude backend and SDK tests under `agentic-workflows-v2/tests/` (219-262) |
| `ek-delegation-tests` | Installs the `ek` extra, asserts `executionkit` imports, runs the EK-gated suite (263-302) |
| `evalkit-bridge-tests` | Installs the `eval` extra, runs bridge and boundary tests (303-346) |
| `wire-format-drift` | Regenerates TS types and schema, then fails on `git diff` (347-411) |
| `e2e-streaming` | Streaming end-to-end; uploads UI Playwright artifacts on failure (412-463) |
| `no-llm-smoke` | Unit baseline with `AGENTIC_NO_LLM=1` (464-512) |
| `validate-workflows` | `python scripts/validate-workflows.py` (513-528) |
| `check-doc-drift` | `scripts/check-doc-drift.py` and `agentic-workflows-v2/scripts/check_docs_refs.py` (529-543) |
| `doc-stats-drift` | `python scripts/generate_doc_stats.py --check` (544-561) |
| `pydocstyle` | pydocstyle on core and contracts (562-590) |
| `lockfile-constraints` | Re-exports constraints with `uv==0.11.2`, fails on diff (591-618) |
| `dockerfile-constraints` | Every `pip install` line in `Dockerfile` must contain `-c ci-constraints.txt` (619-648) |
| `tools-tests` | `pytest tools/tests` (649 onward) |

The job count is 20 (observed). `.claude/rules/portfolio-context.md` in ARP says "17 blocking jobs", which is stale.

### 6.2 Quality gates

| Gate | Threshold or rule | Config source | Enforced by |
|---|---|---|---|
| Line coverage | `fail_under = 80`, `precision = 2` | `agentic-workflows-v2/pyproject.toml` 210-215 | `ci.yml` `test-coverage` (`coverage report --fail-under=80`) |
| Coverage omits | Modules that need live providers | `agentic-workflows-v2/pyproject.toml` 172-203 | same |
| Ruff | `E,F,W,I,N,UP,S,B,A,C4,SIM,TCH,RUF` | `agentic-workflows-v2/pyproject.toml` 241; per-file-ignores 365 | `ci.yml` `lint`; pre-commit ruff |
| Mypy | Strict on engine and contracts; overrides relax others | `agentic-workflows-v2/pyproject.toml` 382-412 | `ci.yml` `typecheck-core-contracts` |
| Suppression ratchet | Ruff ignores, per-file-ignores and mypy overrides may shrink, never grow | `agentic-workflows-v2/scripts/check_suppression_ratchet.py` | `ci.yml` `suppression-ratchet` |
| Wire-format drift | Pydantic to JSON schema to TS must regenerate with zero diff | `agentic-workflows-v2/scripts/generate_ts_types.py`, `generate_schemas.py` | `ci.yml` `wire-format-drift` |
| Lock to constraints | `ci-constraints.txt` equals `uv export` of `uv.lock` | `ci-constraints.txt` (636 lines) | `ci.yml` `lockfile-constraints` |
| Docker pins | Every `pip install` pins constraints | `Dockerfile` | `ci.yml` `dockerfile-constraints` |
| Eval golden gate | Threshold 0.80 | `.github/workflows/eval-package-ci.yml` 170 | `eval-golden-gate` |
| Doc drift | Path, retired-surface and stats checks | `scripts/check-doc-drift.py`, `scripts/generate_doc_stats.py`, `agentic-workflows-v2/scripts/check_docs_refs.py` | `ci.yml` `check-doc-drift`, `doc-stats-drift` |
| Pydocstyle | Core and contracts | `ci.yml` `pydocstyle` | `ci.yml` |
| Secrets | detect-secrets baseline v1.5.0: 27 plugins, 40 files, 279 recorded entries (observed) | `.secrets.baseline` | pre-commit `detect-secrets` v1.5.0 |
| Commit hygiene | Strips AI co-author trailers | `.pre-commit-config.yaml` 9-18 (local hook) | pre-commit |

Pre-commit hooks (`.pre-commit-config.yaml`): local `strip-ai-coauthors`; black 26.5.1; ruff v0.16.5; docformatter v1.7.7; detect-secrets v1.5.0; mypy v2.3.1 (lines 65-68). The pydocstyle hook is commented out (lines 79-82), although `ci.yml` runs a pydocstyle job.

Eval package strictness: `agentic-v2-eval` runs strict mypy, `ruff format --check` and its own 80% gate, per `.claude/rules/ci.md` (cited, not re-verified here).

Line length: 88 per `.claude/rules/ci.md`. The value was not confirmed in `pyproject.toml`.

### 6.3 Dependency management

| Item | Fact | Source |
|---|---|---|
| Lock file | Single `uv.lock` at root, `revision = 3`, `requires-python >=3.11`. No `agentic-workflows-v2/uv.lock` | `uv.lock` |
| Workspace | Root is distribution `agentic-tools` 0.1.0 (hatchling, packages `tools`); workspace members `agentic-workflows-v2` and `agentic-v2-eval` | `pyproject.toml` |
| Root deps | pyyaml, aiohttp, pydantic, langchain-core `<2`, anthropic `<2`, openai `<4`, numpy `<3` | `pyproject.toml` |
| Dev group | pytest, pytest-asyncio, pytest-cov, pytest-mock, pytest-timeout, ruff `>=0.16.10`, mypy `>=2.4.0`, pre-commit `>=4.6.2`, black `>=26.5.1` | `pyproject.toml` |
| Optional extras | `ek = executionkit>=0.4.0,<0.5.0` (line 47); eval extra `agentic-evalkit>=0.4.1,<0.5.0` (line 52) | `agentic-workflows-v2/pyproject.toml` |
| Constraints | 636-line export; header `uv export --locked --no-hashes --no-emit-workspace --all-packages --all-extras`; pins `agentic-evalkit==0.4.1` | `ci-constraints.txt` |
| Regeneration | `just update-constraints` (export only); `just relock` (`uv lock --upgrade` then export) | `justfile` 25-35 |
| Dependabot | Weekly for github-actions `/`, pip `/`, pip `/agentic-workflows-v2`, pip `/agentic-v2-eval`, npm `/agentic-workflows-v2/ui`, docker `/` | `.github/dependabot.yml` |
| Dependabot gap | Dependabot does not update `uv.lock`, so relock is manual or via `dependabot-relock.yml` | `.github/dependabot.yml` 14; `dependabot-relock.yml` |
| Node and Python versions | `.python-version` 3.11; `.nvmrc` 20; `ci.yml` `setup-node` 22 (lines 55, 74); `Dockerfile.ui` `node:26.11-bookworm-slim` | See 6.9 |
| Release manifest | `schema_version = 1`; bundle `0.4.0-rc.1`, tag `v0.4.0-rc.1`, channel `github-prerelease`; components `agentic-tools` 0.1.0, `agentic-workflows-v2` 0.1.0 (smoke `agentic version`), `agentic-v2-eval` 0.3.0 | `release-manifest.toml`, validated by `scripts/verify_release_artifacts.py` |

### 6.4 Containers, deploy and infrastructure

#### Dockerfiles and compose

| Image or stage | Base | Port | Notes | Source |
|---|---|---|---|---|
| `backend-dev` | python:3.11-slim | 8010 | `uvicorn --reload`, editable installs with constraints | `Dockerfile` 16-34 |
| `production` | python:3.11-slim | 8010 | Non-root `appuser`, `HEALTHCHECK`, `uvicorn agentic_v2.server.app:create_app --factory` | `Dockerfile` 37-59 |
| `devcontainer` | python:3.11-slim | none | `CMD sleep infinity` | `Dockerfile` 62-85 |
| `frontend-dev` | node:26.11-bookworm-slim | 5173 | Vite dev server | `Dockerfile.ui` 3-18 |
| `frontend` | nginx-unprivileged:1.31-alpine | 8080 | `HEALTHCHECK` | `Dockerfile.ui` 29-39 |

`docker-compose.yml` services: `backend` (8010, `prompts-backend`), `frontend` (5173, `VITE_API_PROXY_TARGET=http://backend:8010`), `otel-collector` (`otel/opentelemetry-collector-contrib:0.102.1`), `jaeger` (`jaegertracing/all-in-one:1.58`), and a `ui_node_modules` volume. `justfile` `compose-up` starts backend, frontend, otel-collector and jaeger. `.dockerignore` is 52 lines.

Devcontainer: `.devcontainer/devcontainer.json` builds target `devcontainer`. `postCreateCommand` runs editable installs and `npm --prefix agentic-workflows-v2/ui install`. Validated by `devcontainer-validate.yml`.

Release images: `deploy.yml` runs `docker/build-push-action@v7` twice (lines 110, 120), then `attest-build-provenance@v4` (line 173). Publish runs in the `release` environment (line 186).

#### Azure reference (`infra/`)

`infra/azure/` holds `README.md`, `main.bicep` and `main.bicepparam.example`. The README says the templates are not deployed by normal CI and do not prove a live environment exists.

Resources in `main.bicep`: Log Analytics workspace (line 82), Application Insights (97), user-assigned identity (114), ACR (123) with `AcrPull` role assignment (142), Azure Cache for Redis (156, shared circuit-breaker state), Container Apps environment (177) and app (198). Defaults: `minReplicas` 2, `maxReplicas` 10, 50 concurrent requests per replica, 0.5 CPU, 1.0Gi memory (lines 43-58). Outputs at lines 293-299.

`infra-deploy.yml` deploy job (around line 68) references `infra/azure/main.bicepparam`. That file is absent; only the `.example` exists. The job is gated by manual dispatch, so the break is latent (see 6.9).

### 6.5 Observability

| Component | Location | Detail |
|---|---|---|
| OTel collector | `otel/otel-collector-config.yaml` | OTLP receivers (grpc, http), `batch` processor, exporters `otlp/jaeger` (`jaeger:4317`, TLS insecure) and `debug`, `health_check` extension. Traces pipeline only, with no metrics or logs pipeline |
| Jaeger | `docker-compose.yml` | `jaegertracing/all-in-one:1.58` |
| Code instrumentation | `agentic-workflows-v2/agentic_v2/` | 7 files reference `opentelemetry` (grep) |
| Prometheus metrics | `agentic-workflows-v2/agentic_v2/server/app.py` 179 | `AGENTIC_METRICS=1` requires `opentelemetry-exporter-prometheus` |
| Azure telemetry | `infra/azure/main.bicep` | Log Analytics and Application Insights (reference only) |
| Coverage upload | `ci.yml` `test-coverage` | Codecov, non-blocking (`fail_ci_if_error: false`) |
| SonarQube | `sonar-project.properties` | Project key `agentic-runtime-platform`; Python `coverage.xml`; UI lcov at `agentic-workflows-v2/ui/coverage/lcov.sonar.info`; SCM disabled. No workflow in `.github/` references Sonar, so scans run outside CI (unverified; the memory notes a self-hosted server) |
| Load evidence | `load/`, `.github/workflows/load-report-pages.yml` | Load report built from `load/results/*.json` and published with the docs site |

### 6.6 Formal methods (`proofs/`)

- Toolchain: `proofs/lean-toolchain` = `leanprover/lean4:v4.34.0`. No Mathlib or Batteries (`proofs/README.md`).
- Files: `Main.lean`, `Scheduler.lean`, `Scheduler/Validate.lean`, `lakefile.toml`, `lake-manifest.json`, `README.md`. About 116 top-level declarations (theorem, lemma, def, axiom, structure, inductive at column 0) across the three `.lean` files (grep count).
- `sorry`: the two grep hits in `Scheduler.lean` (lines 2537-2538) sit in doc comments and are not proof terms (grep-based). `lakefile.toml` sets `warningAsError`, so real `sorry` fails the build.
- Scope (README): the four ADR-060 scheduler guarantees are proved for a Lean model of `dag_executor.py` over every legal completion order. The Python code is not proved. Linkage is seeded replay on sampled schedules only.
- Outstanding (README "Outstanding proof obligations", line 271 onward): `DAG.get_execution_order` (Kahn's algorithm) is not modelled; legality of FIRST_COMPLETED batches is checked per replayed trace (`checkLegal`), not proved for asyncio; timeout cleanup is covered by `timeout_fails_closed`.
- `lean-proofs.yml`: timeout 20 min on PR, 60 otherwise (line 48). Steps: `lake build` in `proofs/`; replay pytest (`tests/engine/test_dag_executor_lean_replay.py`); exhaustive replay of small plans (`test_dag_executor_lean_exhaustive.py`); differential test (`tests/test_orchestrator_dag_differential.py`); a nightly exhaustive run of 4-step plans with 900s timeout (line 90, schedule gating unverified); axiom audit allowing `propext` and `Quot.sound` (lines 61-63).

### 6.7 Scripts

#### Root `scripts/` (12 files)

| Name | Purpose | Used by (grep) | Status |
|---|---|---|---|
| `build_load_report.py` | Builds load report from `load/results` | `load-report-pages.yml`, `load/run_load.sh`, `docs/load-report.md` | Active |
| `check-doc-drift.py` | Doc and ADR governance drift | `ci.yml` `check-doc-drift`, `justfile` `docs` | Active |
| `eval_gate.py` | Eval gate runner (`--cases`, `--threshold 0.80`, `--live`) | `eval-package-ci.yml` | Active |
| `find-dangling-references.py` | Finds references to deleted files | none | Unreferenced |
| `fix-trailing-whitespace.py` | Strips trailing whitespace (`--dry-run`) | none | Unreferenced (manual utility) |
| `generate-sample-trace.py` | Writes `sample-trace.json` for `score-trace.py` | only `score-trace.py` side | Orphan pair |
| `score-trace.py` | Scores a workflow trace by agent type | only `generate-sample-trace.py` | Orphan pair |
| `generate_doc_stats.py` | Derived doc stats; `--check` mode | `ci.yml` `doc-stats-drift`, `justfile` `docs` | Active |
| `setup_env_loading.ps1` | Sets venv `.env` autoload | none | Unreferenced |
| `strip_ai_coauthors.py` | Strips AI co-author trailers | `.pre-commit-config.yaml` local hook | Active |
| `validate-workflows.py` | Validates workflow YAML | `ci.yml` `validate-workflows` | Active |
| `verify_release_artifacts.py` | Validates `release-manifest.toml`, smoke-tests wheels in isolation | `deploy.yml`, `justfile` `release-check` | Active |

#### `agentic-workflows-v2/scripts/` (14 entries)

| Name | Purpose | Used by (grep) | Status |
|---|---|---|---|
| `check_docs_refs.py` | Docs path and retired-surface checks | `ci.yml` `check-doc-drift`, `justfile` `docs` | Active |
| `check_suppression_ratchet.py` | Suppression ratchet | `ci.yml` `suppression-ratchet` | Active |
| `generate_schemas.py` | Pydantic to JSON schema | `agentic-workflows-v2/tests/test_schema_drift.py` | Active |
| `generate_ts_types.py` | Pydantic to TypeScript types | `ci.yml` `wire-format-drift`, `.gitattributes` | Active |
| `run_coverage.sh` | Coverage run (Bash) | `agentic-v2-eval/README.md` only | Doc-only |
| `run_deep_research.py` | Deep research driver | `run-deep-research.ps1` | Manual |
| `run-deep-research.ps1` | Wrapper with `-Topic` | none | Manual |
| `run-bounded-rereview.ps1` | Bounded re-review against `127.0.0.1:8012` | none | Unreferenced |
| `run-tests.ps1` | Test-runner wrapper (`--coverage`, `--package`) | none | Unreferenced |
| `setup-dev.ps1` | Dev environment setup | `windows-workflows-ci.yml`, `docs/getting-started/installation.md` | Active |
| `start-dev.ps1`, `stop-dev.ps1`, `status-dev.ps1` | Local dev servers | `justfile` `dev`, `dev-stop`, `dev-status` | Active |
| `restart-dev.ps1` | Restart wrapper (`-Reload`) | none by name | Unreferenced |
| `test_sentinel_e2e.py` | One-off sentinel check for a coder step | none | Manual, not in `tests/` |
| `fixtures/` | Smoke and other inputs | `windows-workflows-ci.yml` (`scripts/fixtures/smoke-input.json`) and others | Active |

### 6.8 Docs site

- `mkdocs.yml`: `site_url` `https://tafreeman.github.io/agentic-runtime-platform/`. `docs_dir` is the default `docs/`. All 60 `.md` nav entries exist under `docs/` (checked by script). Three extra stylesheets (`tokens.css`, `console.css`, `landing.css`).
- `exclude_docs` removes `OWASP_LLM_THREAT_MODEL.md` because of broken `docs/`-prefixed links (comment in `mkdocs.yml`).
- Two workflows publish to Pages with `gh-deploy --force`: `docs.yml` and `load-report-pages.yml`. Both build the full site, so they overwrite each other's output (observed design, not tested).
- `site/` exists in the user checkout (`C:/Users/tandf/source/agentic-runtime-platform/site/`) but not in the clean worktree. Treat it as a local build output (its `.gitignore` status is unverified).

### 6.9 Stale, dead and inconsistent items

| # | Item | Evidence | Status |
|---|---|---|---|
| 1 | `manifest-temperature-check.yml` | Not among the 18 workflow files. `docs/deployment-guide.md` line 50 still lists it. `scripts/validate_manifest.py` and `run-manifest.yaml` are absent. ARP's `.claude/rules/portfolio-context.md` calls it dead | Stale doc reference |
| 2 | `infra-deploy.yml` to `infra/azure/main.bicepparam` | File absent; only `main.bicepparam.example` present | Broken reference, gated |
| 3 | Job count | `ci.yml` has 20 job ids. `.claude/rules/portfolio-context.md` says 17 | Doc drift |
| 4 | `ci.yml` `tools-tests` comment | Comment (around line 649) says tools tests were never collected; the job now exists | Stale comment |
| 5 | Evalkit pin | `agentic-workflows-v2/pyproject.toml` line 52 is `>=0.4.1,<0.5.0`. Workspace `CLAUDE.md` section 7 says `>=0.3.0,<0.4.0` at that line | Doc drift in workspace root file |
| 6 | Node version | `.nvmrc` 20; `ci.yml` Node 22; `Dockerfile.ui` Node 26.11 | Three-way inconsistency |
| 7 | pydocstyle | Pre-commit hook commented out (`.pre-commit-config.yaml` 79-82); `ci.yml` runs pydocstyle | Intent unverified |
| 8 | Ruff version | Root dev group `ruff>=0.16.10`; pre-commit pins v0.16.5 | Minor drift |
| 9 | `sonar-project.properties` | No `.github/` reference | No CI consumer |
| 10 | `agenticv2` branch | Named in 7+ workflow triggers; no local or remote-tracking branch matched in the user checkout | Remote existence (unverified) |
| 11 | Unreferenced scripts | `find-dangling-references.py`, `fix-trailing-whitespace.py`, `setup_env_loading.ps1`, `run-tests.ps1`, `run-bounded-rereview.ps1`, `restart-dev.ps1`, `test_sentinel_e2e.py` | No caller found by grep |
| 12 | Orphan pair | `generate-sample-trace.py` and `score-trace.py` only reference each other | Orphan |
| 13 | Coverage gate source | `ci.yml` `test-coverage` runs with `--cov=agentic_v2`; whole-repo report is visibility only | By design |
| 14 | Unverified | Required-check settings; devcontainer job steps; `codeql` and `dependency-audit` blocking status; `deploy.yml` PR behaviour; whether the nightly `eval-live-gate`-style schedules run as described | (unverified) |
