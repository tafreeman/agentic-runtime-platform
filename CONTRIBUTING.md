# Contributing to `tafreeman/agentic-runtime-platform`

> **Audience:** Anyone landing their first PR on this monorepo.
> **Outcome:** After reading this, you can clone, change code, pass local gates, and open a merge-ready PR.
> **Last verified:** 2026-04-22

If you just want to run the platform, start at [`docs/ONBOARDING.md`](docs/ONBOARDING.md) — it takes ~5 minutes to a first workflow run. This file is for contributors who intend to land code.

---

## 1. What lives in this repo

| Path | What it is | Build backend | Notes |
|------|-----------|---------------|-------|
| `agentic-workflows-v2/` | Runtime (CLI, DAG executor, LangGraph adapter, FastAPI server, WebSocket streaming) | hatchling | Python 3.11+ |
| `agentic-workflows-v2/ui/` | React 19 dashboard (Vite 6, Tailwind, @xyflow/react) | Vite | Node 20+ |
| `agentic-v2-eval/` | Rubric-based evaluation framework | hatchling | Python 3.11+ |
| `tools/` | Shared LLM client, benchmarks, caching utilities (package name: `agentic-tools`) | hatchling | Python 3.11+ |

Each Python package installs independently. There are **zero cross-package imports** — `tools` is the only optional shared surface, imported with `from tools.llm import LLMClient`.

Package-specific contribution notes live at [`agentic-workflows-v2/CONTRIBUTING.md`](agentic-workflows-v2/CONTRIBUTING.md). This root document covers monorepo-wide policy.

---

## 2. Local setup

```bash
git clone https://github.com/tafreeman/agentic-runtime-platform.git
cd agentic-runtime-platform
just setup          # installs root helpers + all three Python packages + UI deps
```

`just setup` wraps the individual `pip install -e` and `npm install` steps so every contributor ends up with the same environment. If `just` is not on your PATH, install it (`winget install casey.just` on Windows, `brew install just` on macOS) or run the equivalent commands manually — see `justfile` for the exact wrapping.

If you prefer a containerized workspace, open the repo in the provided devcontainer (`.devcontainer/`) — it installs everything at build time.

### Provider credentials

At least one LLM provider must be configured before any non-deterministic workflow will run:

```bash
cp .env.example .env
# edit .env and set ONE of:
#   GITHUB_TOKEN=ghp_…        (free tier, used by CI)
#   GEMINI_API_KEY=…          (free tier)
#   OPENAI_API_KEY=…          (paid)
#   ANTHROPIC_API_KEY=…       (paid)
```

The smart router will use whichever providers are configured. CI uses `GITHUB_TOKEN` with GitHub Models — see [`docs/adr/ADR-016-github-token-as-default-e2e-llm.md`](docs/adr/ADR-016-github-token-as-default-e2e-llm.md) for the trade-off that drove that choice.

---

## 3. Development workflow

1. Create a branch from `main`. Branch naming: `feature/…`, `fix/…`, `chore/…`, `docs/…`.
2. Make the smallest coherent change. Prefer one concern per PR.
3. Write tests first (TDD). New backend code targets 80% coverage on changed lines; the UI package enforces a 60% floor in `ui/vitest.config.ts`.
4. Update the docs in the same PR if the change touches user-facing behavior, configuration, or a new pattern. See the [documentation mapping](#7-documentation) below.
5. Run local gates before pushing (next section).
6. Push with `-u` on first push and open a PR against `main`.

Do not push directly to `main`. All changes land via PR.

---

## 4. Required local gates

These must all pass before a PR will merge. Run them from the repo root:

```bash
just test                     # runs the full backend + eval + UI test suite
just docs                     # verifies documentation (links, code fences, etc.)
pre-commit run --all-files    # black, isort, ruff, docformatter, mypy, pydocstyle, detect-secrets
```

### Per-package test entrypoints

If you only touched one package, you can narrow the run:

| Package | Command |
|---------|---------|
| Runtime | `cd agentic-workflows-v2 && python -m pytest tests/ -q` |
| Runtime + coverage | `cd agentic-workflows-v2 && python -m pytest tests/ -q --cov=agentic_v2 --cov-report=term-missing` |
| Eval | `cd agentic-v2-eval && python -m pytest tests/ -q` |
| UI unit | `cd agentic-workflows-v2/ui && npm test` |
| UI coverage | `cd agentic-workflows-v2/ui && npm run test:coverage` |
| UI build check | `cd agentic-workflows-v2/ui && npm run build` |

### CI gates you must not break

| Gate | What it enforces | Source |
|------|------------------|--------|
| Ruff lint | `E,F,W,I,N,UP,S,B,A,C4,SIM,TCH,RUF` — no warnings in changed files | `.github/workflows/ci.yml` |
| Mypy | `mypy --strict` on `agentic-workflows-v2/agentic_v2/`. `agentic-v2-eval` runs with 35 known findings (Sprint B) — see [`KNOWN_LIMITATIONS.md`](docs/KNOWN_LIMITATIONS.md). Note: mypy config is relaxed while type debt is being paid down (see `pyproject.toml` `[tool.mypy]`). | `ci.yml`, `eval-package-ci.yml` |
| Coverage floor | 80% on `agentic-workflows-v2/`, 60% on `ui/` | `ci.yml` |
| Schema drift | Snapshot test on `contracts/` Pydantic models — any wire-format change must be explicitly accepted by regenerating the snapshot | `scripts/generate_schemas.py`, see [ADR-014](docs/adr/ADR-014-pydantic-wire-format.md) |
| Playwright streaming (5×) | End-to-end streaming flow runs 5× per PR. One failure blocks merge | `ci.yml` |
| Nightly reliability (50×) | Rolling flake-rate gate over 50 runs. Failure blocks a release cut, not a PR | `nightly.yml` |
| Time-to-first-span p95 | SLO gate on trace latency — see [ADR-015](docs/adr/ADR-015-slo-in-git-rolling-window.md) for the git-as-time-series pattern | `nightly.yml` |
| pip-audit | No High/Critical advisories | `dependency-review.yml` |
| detect-secrets | Baseline-driven — see `.secrets.baseline` | pre-commit |

Full CI job catalogue: [`.github/workflows/`](.github/workflows/).

---

## 5. Commit format

Conventional commits. Enforced by review, not by hook.

```
<type>(<scope>): <subject>

<optional body>
```

| Type | Use for |
|------|--------|
| `feat` | New user-facing behavior |
| `fix` | Bug fix |
| `refactor` | No behavior change |
| `test` | Tests only |
| `docs` | Documentation only |
| `chore` | Tooling, CI, dependency bumps |
| `perf` | Performance improvement with benchmark evidence |
| `ci` | CI pipeline changes |
| `style` | Formatting only (rare — pre-commit handles this) |
| `wip` | Reserved for draft commits on feature branches — **squash before merge** |

Scopes match the package or subsystem: `contracts`, `ui`, `server`, `engine`, `eval`, `rag`, `ci`, `slo`, `mcp/results`, etc. Read the last 40 commits on `main` (`git log --oneline -40`) to calibrate tone — terse, specific, present tense.

AI-assistant attribution (`Co-Authored-By: Claude` / `Generated with Claude Code`) is intentionally disabled for this repo and must not be re-enabled. It is stripped at the source (`.claude/settings.json`, `includeCoAuthoredBy: false`) and backstopped by a `commit-msg` hook (`scripts/strip_ai_coauthors.py`). The hook only removes assistant trailers — human and PR-bot co-authors (`dependabot`, `gemini-code-assist`, `copilot`) are preserved. After cloning, install it once with:

```bash
pre-commit install --install-hooks   # installs the commit-msg stage too
```

### Commit signing

Signing commits is strongly recommended to show the "Verified" badge on GitHub, which matters for a repo claiming enterprise-grade practices.

**SSH signing (recommended — no GPG installation required):**

```bash
# 1. Generate a signing key (skip if you already have one)
ssh-keygen -t ed25519 -C "your-email@example.com" -f ~/.ssh/id_ed25519_signing

# 2. Add the public key to GitHub → Settings → SSH and GPG keys → New SSH key (type: Signing Key)

# 3. Configure git to use it
git config --global gpg.format ssh
git config --global user.signingkey ~/.ssh/id_ed25519_signing.pub
git config --global commit.gpgsign true
git config --global tag.gpgsign true
```

**GPG signing (if you prefer GPG):**

```bash
gpg --full-generate-key              # RSA, 4096 bits, no expiry for a signing key
gpg --list-secret-keys --keyid-format=long
git config --global user.signingkey <YOUR_KEY_ID>
git config --global commit.gpgsign true
# Upload public key to GitHub → Settings → SSH and GPG keys → New GPG key
```

Once configured, every `git commit` is signed automatically. Verify with `git log --show-signature -1`.

---

## 6. When to write an ADR

Open an Architecture Decision Record under [`docs/adr/`](docs/adr/) when you:

- Introduce a new wire-format contract (request/response schema, event shape, persistence format).
- Add, replace, or deprecate an execution engine, provider adapter, or storage backend.
- Change a security boundary (tool allowlist, secret source, auth model).
- Pick a pattern that future contributors might reasonably challenge (a new rolling-window design, a retry strategy, an SLO methodology).

Use the existing ADR numbering scheme. Next free number is **017** as of 2026-04-22. Skip to the next free integer if you land in a race. ADRs 004-006 are deliberately unused and **should not be reclaimed** — the numbering gap is documented in [`docs/adr/ADR-INDEX.md`](docs/adr/ADR-INDEX.md).

An ADR is **not** required for:

- Bug fixes, refactors, or test additions.
- UI polish that doesn't change contracts.
- New workflows, personas, or tools that use existing patterns.
- Pre-commit or lint rule tweaks.

If in doubt, propose the ADR as a stub in the PR and let the reviewer decide.

---

## 7. Documentation

Docs live close to what they describe. The mapping for changes:

| Change | Update |
|--------|--------|
| New or modified workflow | [`docs/WORKFLOW_AUTHORING.md`](docs/WORKFLOW_AUTHORING.md) |
| New environment variable | Root [`README.md`](README.md), [`.env.example`](.env.example), [`docs/ONBOARDING.md`](docs/ONBOARDING.md) |
| New REST or WebSocket endpoint | [`docs/api-contracts-runtime.md`](docs/api-contracts-runtime.md) |
| New architecture pattern | [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) (umbrella) + relevant `docs/architecture-*.md` |
| New bootstrap / devcontainer behavior | Root `README.md`, `docs/ONBOARDING.md`, this file |
| User-visible change (per release) | `CHANGELOG.md` under `## [Unreleased]` |
| Breaking or migration-worthy change | [`docs/MIGRATIONS.md`](docs/MIGRATIONS.md) |
| Known limitation or temporary defect | [`docs/KNOWN_LIMITATIONS.md`](docs/KNOWN_LIMITATIONS.md) |
| Proposed epic or major initiative | [`docs/ROADMAP.md`](docs/ROADMAP.md) |

Docs must be runnable or falsifiable. Command blocks must actually work. Diagrams use Mermaid. Every top-level doc carries a "last verified" date — update it when the doc is touched.

---

## 8. Security

- Never commit secrets, API keys, or production tokens. `.env` is gitignored; `.env.example` is the only committed template.
- Resolve runtime secrets through `agentic_v2.models.secrets.get_secret()` / `get_first_secret()` — not `os.environ` directly.
- Follow the disclosure process in [`SECURITY.md`](agentic-workflows-v2/SECURITY.md) for any vulnerability report.
- AI-generated code is untrusted input — run full lint + type check + tests before accepting.

---

## 9. Need help

- Open a discussion or issue on the repository.
- Read [`docs/GLOSSARY.md`](docs/GLOSSARY.md) for domain terms.
- Support channels and response expectations: [`SUPPORT.md`](SUPPORT.md).
- For architecture questions, start at [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) and the ADRs.

---

## 10. PR checklist

Copy into your PR description:

```markdown
- [ ] Branch from main; name follows `feature|fix|chore|docs/…`
- [ ] Tests added or updated; coverage holds on changed lines
- [ ] `just test && just docs && pre-commit run --all-files` green locally
- [ ] CHANGELOG.md [Unreleased] updated for user-visible changes
- [ ] ADR added (or confirmed not required — see CONTRIBUTING §6)
- [ ] Docs updated per CONTRIBUTING §7 table
- [ ] No secrets, no `.env` committed
- [ ] Commit message follows conventional format
```

---

## Development Provenance & Verification

This repository is built solo with AI-assisted tooling. Because there is no second human reviewer, correctness is gated by **automated evidence**, not peer sign-off:

- **CI gates (every push / PR):** ruff, `mypy --strict` (engine + contracts), the 80% coverage gate, the Pydantic↔TypeScript wire-format drift check, Playwright E2E (×5), CodeQL, SBOM gen