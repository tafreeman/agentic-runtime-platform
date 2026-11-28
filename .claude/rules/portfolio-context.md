# Portfolio context and CI gotchas

## Command catalogue

```bash
# cd C:/Users/tandf/source/agentic-runtime-platform   (justfile shell is PowerShell; venv is .venv/Scripts/python.exe)
just setup                 # venv + 3 editable installs, each pinned -c ci-constraints.txt, + npm install
just test                  # runtime + eval + root e2e + UI; _require-venv throws on a POSIX .venv layout
just docs                  # check_docs_refs.py, then generate_doc_stats.py --check
pre-commit install --install-hooks   # once: also installs the commit-msg AI-trailer stripper
just relock                # reconcile a Dependabot pip PR: uv lock --upgrade, then re-export constraints
```

```bash
# cd agentic-workflows-v2                    # what CI actually runs
python -m pytest tests/ -q -m "not integration and not slow" --ignore=tests/e2e -x --timeout=120
python -m pytest tests/ -q -m "not integration and not slow" --cov=agentic_v2 --cov-report=term-missing
python -m coverage report --fail-under=80    # the step that actually blocks
python -m ruff check --fix --show-fixes agentic_v2/ tests/   # CI diffs after --fix; commit the result
python -m mypy agentic_v2/engine agentic_v2/contracts --config-file pyproject.toml \
  --follow-imports=skip --disallow-untyped-defs --warn-return-any --no-incremental
python scripts/check_suppression_ratchet.py
python -m scripts.generate_ts_types          # then, from ui/: npm run generate:types
```

Single cross-package E2E, from the repo root: `python -m pytest tests/e2e/test_cross_package.py -q -m e2e`. `pyproject.toml` sets `timeout = 30`, so a long single test needs an explicit `--timeout=`.

## Architecture invariants

- Steps name a **capability tier**, never a model — `models/smart_router.py` resolves it.
- `"langchain"` is the default engine for named YAML workflows, `"native"` for runtime-generated DAGs.
- Python↔TypeScript is a *compiled* contract: Pydantic models → JSON Schemas → `.generated.ts` mirrors.
- Governance interposes the approval gate **before** validation at both tool dispatch points; with no `ApprovalProvider` registered the call is DENIED.
- Only the root `tools/` package is shared — zero cross-imports between the two workspace packages.

## Gotchas beyond the other rules files

- `ci-constraints.txt` is **generated from `uv.lock`**; the `lockfile-constraints` job (pinned `uv==0.11.2`) regenerates and diffs it. Dependabot bumps pyproject + constraints but **not** `uv.lock` — use `just relock`.
- Every `pip install` line in the root `Dockerfile` must carry `-c ci-constraints.txt` (job `dockerfile-constraints` greps line-by-line; only `--upgrade pip` is exempt).
- **Suppression ratchet:** a new ruff `ignore`, a new per-file-ignore, or a new mypy `ignore_errors` override fails CI. Silencing a lint error is a blocked path.
- A clean local `mypy` does **not** predict CI: `[tool.mypy]` is deliberately relaxed, and `--follow-imports=skip` makes anything outside `engine`/`contracts` `Any`, so returning its attributes trips `no-any-return` only in CI.
- The EK bridge suite module-skips without `executionkit`, and **only** the `ek-delegation-tests` job installs the `ek` extra. This blind spot previously let an ADR-047 regression pass CI.
- `docs/adr/ADR-INDEX.md` is authoritative for the next free ADR number and for which numbers are intentionally unused.
- Install paths diverge: `just setup` uses pip+constraints, but `windows-workflows-ci.yml` uses `uv sync --frozen` (no `ek` extra) with `PYTHONIOENCODING=utf-8` / `PYTHONUTF8=1` — replicate those when debugging Rich output on a cp1252 console.
- `agentic-v2-eval` is held to a stricter bar than the runtime: `strict = true` mypy, `ruff format --check` enforced, its own 80% gate, and a Windows + py3.12 matrix.
- `eval-package-ci.yml`'s `eval-golden-gate` is a required check on `main` (hence no paths filter). Nightly 50× streaming + flake/SLO gates block a *release cut*, not a PR.
