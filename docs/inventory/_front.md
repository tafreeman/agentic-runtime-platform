# Agentic Runtime Platform — Repository Inventory

## 0. Executive summary

> **Snapshot:** `origin/main` @ `c3b2d328` (2026-10-12, after tafreeman/agentic-runtime-platform#387), inventoried from a clean detached worktree so in-flight branch work does not skew the counts. In-flight work is reported separately in §9. Git and PR state in this repo moves hourly; re-run the scripts before acting on any count.

### What this repository is

A tier-routed, multi-agent LLM workflow runtime. YAML workflows compile to a DAG. The DAG runs either on a native Kahn's-algorithm asyncio executor or on a LangGraph adapter (the default for named workflows). Each step names a capability tier, never a model. `SmartModelRouter` resolves the tier to a provider through three-state circuit breakers and bulkheads. A FastAPI server streams execution over WebSocket and SSE to a React 19 "ARP Console". A fail-closed governance layer (human-in-the-loop tool approval and an SSRF egress guard) sits in front of tool dispatch. Around the runtime are:

- an offline evaluation harness (`agentic-v2-eval`, being migrated to the external `agentic-evalkit`);
- a shared `tools/` package (model probes, benchmarks);
- Lean 4 proofs of the scheduler.

### Shape at a glance

| Area | Size (main @ c3b2d328) | Health |
|---|---|---|
| Runtime `agentic_v2` | ~244 modules, ~62k LOC, 22 subpackages | Active; 8 modules over 800 LOC; 17% of LOC excluded from the coverage gate |
| Python tests | 287 files, ~4,600 test functions | 80% gate on `agentic_v2`; `tools/tests` runs with 11 deselected tests |
| UI (`agentic-workflows-v2/ui`) | 203 TS/TSX files, 10 routes, 66 unit test files, 13 Playwright specs | Active; Evidence Ledger redesign in flight (#388) |
| HTTP API | 53 `/api` routes and a WebSocket | 7 routes have no UI caller |
| Workflows | 9 YAML definitions | 2 are test fixtures (one duplicates the other) |
| CI | 18 workflow files, 20 jobs in `ci.yml` | One referenced workflow and one bicepparam file are missing |
| Docs | 133 markdown docs, 55 ADRs (5 Proposed) | Many root status docs are stale (HANDOFF, ROADMAP, KNOWN_LIMITATIONS) |

### Top findings (cross-section)

1. **Generated chat contract is checked by CI but never used.** `ui/src/api/chat_request.generated.ts` and `chat_stream_event.generated.ts` pass the `wire-format-drift` gate, but nothing imports them. The UI uses hand-written copies in `ui/src/api/types.ts`. A backend schema change would therefore stay green while the UI types silently drift (§3.5, §4.6).
2. **A silent broken import disables the benchmark LLM-judge.** `tools/agents/benchmarks/evaluation_pipeline.py:34-40` imports reporting helpers from `llm_evaluator`, but they moved to `evaluator_reporting.py`. A `try/except ImportError` swallows the failure, so `HAS_LLM_EVALUATOR` is always False. This is the real cause of the 10 deselected `TestEvaluateTaskOutputLlm` tests (§5.6).
3. **There is no route to submit HITL approval decisions.** `ApprovalRequiredEvent` and `ApprovalDecisionEvent` exist, but no HTTP or WebSocket handler accepts a decision. The WebSocket also ignores every client message, including the `node_config_update` frames the UI sends (§3.1, §4.6).
4. **The two engines aren't interchangeable.** `model_override`, `persona`, `observers` and `model_params` are honoured only by the LangChain adapter. There are two parallel YAML parsers (`workflows/loader.py` and `langchain/config.py`) and two `WorkflowRunner`s. `docs/WORKFLOW_AUTHORING.md` mentions none of this (§2, §5.1).
5. **Dead code is small and well-bounded.** Deletion candidates:
   - Python: `engine/patterns.py` (empty stub), `models/llm.py` (legacy adapter scheduled for deletion by ADR-042), `tools/core/{cache,response_cache,prompt_db}.py` (`cache.py` doesn't even import), `tools/llm/list_gemini.py`.
   - UI: nine unused shadcn primitives (making `react-resizable-panels` a dead dependency), `BBox`, `BSpark`, `useNodeConfigUpdate`, the `NodeConfigOverlay` prototype, `PrototypeLabPage`, and the test-only `SettingsPage` (§2, §4.6, §5.6).
6. **Config and docs have drifted from the code:**
   - `.env.example` documents 5 keys nothing reads and omits about 6 keys the code reads (§3.8).
   - The workspace `CLAUDE.md` §7 and ADR-042 quote the EK and EVK pins as `0.3.x`, but main pins `executionkit>=0.4.0,<0.5.0` and `agentic-evalkit>=0.4.1,<0.5.0` (§1.3).
   - `portfolio-context.md` says 17 CI jobs; there are 20 (§6.1).
   - `docs/deployment-guide.md` still lists the deleted `manifest-temperature-check.yml` (§6.9).
7. **Toolchain versions disagree.** `.nvmrc` says Node 20, CI uses 22, `Dockerfile.ui` uses 26.11. Pre-commit ruff is 0.16.5, but the dev group requires ≥0.16.10. `nginx.conf` proxies neither `/api` nor `/ws` (§4.1, §6.3).
8. **Docs still advertise retired things.**
   - `docs/configuration.md:63` and `docs/getting-started/installation.md:168` still list GitHub Models, which was retired on 2026-07-30 (ADR-016).
   - `docs/deployment-guide.md:13` says CI has "fourteen jobs"; it has 20.
   - ADR-008 says Proposed in its file but Accepted in `ADR-INDEX.md`.
   - `check_docs_refs.py` scans only 19 of about 205 markdown files, so most of `docs/**` is never link-checked (§8).
9. **About 1.2 GB of local-only clutter is on disk.**
   - Safe to delete: caches and build outputs, for example `.mypy_cache/` (620 MB), `.cache/` (134 MB), `proofs/.lake/` (116 MB) and `site/`.
   - Also deletable: the `__pycache__`-only orphan packages `agentic_v2/rag/` and `agentic_v2/memoryctl/`, and `agentic-workflows-v2/New folder (2)/`.
   - Keep: `runs/`, the replay DBs and `.env`, which hold user data (§7).
10. **Some work exists only on this machine.** At extract time:
   - Unpushed or uncommitted: about 2.1k lines of untracked Evidence Ledger components, probe-tooling edits, and a tech-debt plan on the unpushed `docs/tech_debt_plans` branch.
   - `feature/criterion_aggregation`: no PR open.
   - Stalled: #384 (38 dependency bumps, 26 failing checks) (§9).

### How this inventory was produced

All counts come from scripts committed alongside this document. Re-run them against a fresh `origin/main` worktree:

```bash
git worktree add --detach C:/tmp/arp-main-inventory origin/main
ARP_INVENTORY_REPO=C:/tmp/arp-main-inventory .venv/Scripts/python.exe scripts/inventory/run_all.py
.venv/Scripts/python.exe scripts/inventory/assemble.py
uv run --no-project --with markdown python scripts/inventory/render_html.py
```

| Script | Extracts |
|---|---|
| `scripts/inventory/fs_inventory.py` | Per-directory tracked and untracked counts, sizes, last-commit age, large files, orphan `__pycache__`-only packages |
| `scripts/inventory/py_inventory.py` | AST per module: LOC, classes (Pydantic, Protocol, Enum, …), functions, FastAPI routes, import graph (absolute, relative and lazy), env-var reads, TODO markers, test references, orphan candidates |
| `scripts/inventory/ui_inventory.py` | TS/TSX import graph, exports, `/api` calls, routes, unused and test-only files, external package usage |
| `scripts/inventory/meta_inventory.py` | Workflow YAML steps, CI jobs, ADR statuses, doc staleness and broken links, dependency manifests, git branches, worktrees and PRs |
| `scripts/inventory/assemble.py` / `render_html.py` | Concatenate the section files and render the Superdesign-styled HTML report |

The section narratives (§1–§9) were written by parallel research agents working from that data and the code, each told to verify its claims. Read them with these limitations in mind:

- **Orphan detection is a candidate list, not a verdict.** Registry and string-based wiring evades static import graphs. Every "unused" item in §2, §4 and §5 was re-checked with grep.
- **The env-var extractor misses some reads.** It doesn't catch reads through pydantic `Settings` fields or `get_secret()`; §3.8 corrects for this by hand.
- **File age isn't a reliable staleness signal for the UI.** A broad restyle sweep touched most files within the last week.
- **Items marked "(unverified)" were not confirmed.**
