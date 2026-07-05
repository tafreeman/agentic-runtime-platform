# Five-minute demo

**Audience:** a reviewer or teammate who already cloned the repo and ran `scripts/setup-dev.ps1`. This page answers one question: *what do I do now?*

If you haven't run setup yet, start at [`docs/ONBOARDING.md`](./ONBOARDING.md) instead.

---

## The narrative arc

You are about to:

1. **Run a deterministic workflow** (no LLM, no keys) to prove the runtime is alive — ~5 seconds.
2. **Run an LLM-backed workflow** (`code_review` against a real file) to see the full agent pipeline — ~30 seconds.
3. **See both runs in the live dashboard** with the DAG animating step-by-step — instant.

Expected total wall time: **under 5 minutes** — closer to 3 on a warm cache.

---

## Prerequisites

- You ran `agentic-workflows-v2/scripts/setup-dev.ps1` (Windows) or `just setup` (macOS/Linux) successfully.
- At least one LLM provider key is in your `.env` — **needed for step 2 only**; steps 1 and 3 run without any key (the cheapest path is `GITHUB_TOKEN` — see [`docs/ONBOARDING.md`](./ONBOARDING.md#prerequisites)).

---

## Step 1 — Deterministic workflow (no LLM)

This validates the runtime and CLI wiring without spending a token.

```bash
# from repo root
agentic run test_deterministic --input agentic-workflows-v2/scripts/fixtures/smoke-input.json --verbose
```

**Expected output (abridged):**

```
Status: SUCCESS
Elapsed: 0.1s
```

If that failed, the platform is not installed correctly — go back to `ONBOARDING.md` section "Bootstrap the workspace" before continuing.

---

## Step 2 — LLM-backed workflow (code_review)

This exercises the full pipeline: tiered model routing, 5-step DAG, tool calls, the WebSocket event stream, and the run logger.

Create `examples/hello.json` at the repo root (or reuse the committed fixture):

```bash
# option A: use the committed minimal fixture
agentic run code_review \
  --input agentic-workflows-v2/tests/fixtures/code_review_input.json \
  --verbose

# option B: review a real file (PowerShell)
New-Item -ItemType Directory -Force examples | Out-Null
@'
{
  "code_file": "agentic-workflows-v2/agentic_v2/cli/main.py",
  "review_depth": "quick"
}
'@ | Set-Content examples/hello.json
agentic run code_review --input examples/hello.json --verbose
```

**Expected output (abridged):**

```
▶ workflow_start        run_id=r-...
  ▶ step_start          parse_code          [tier0]
  ✓ step_end            parse_code          92ms
  ▶ step_start          style_check         [tier1]
  ✓ step_end            style_check         2.4s
  ▶ step_start          complexity_analysis [tier1]
  ✓ step_end            complexity_analysis 1.8s
  ▶ step_start          review_code         [tier2]
  ✓ step_end            review_code         6.1s
  ▶ step_start          generate_summary    [tier2]
  ✓ step_end            generate_summary    3.7s
✓ workflow_end          status=success       12.1s

Status: SUCCESS
```

Exact timings vary by provider. The run is logged to `agentic-workflows-v2/runs/r-<id>.json`.

---

## Step 3 — See it live

Open two terminals:

**Terminal 1 — backend** (from `agentic-workflows-v2/`):

```bash
python -m uvicorn agentic_v2.server.app:app --host 127.0.0.1 --port 8010
```

**Terminal 2 — frontend** (from `agentic-workflows-v2/ui/`):

```bash
npm run dev
```

Open http://127.0.0.1:5173 in a browser.

1. Click **Workflows** in the sidebar.
2. Click **`code_review`**.
3. Click **Run**. You'll be redirected to `/live/{run_id}`.
4. Watch the DAG animate as each step transitions **queued → running → complete**. Step nodes glow while running (the `clay-glow` keyframe). Edges between completed and running steps show a flowing dash pattern.
5. Click any step node to open the 5-field drill-down panel (inputs, outputs, scores, status, duration).

When the workflow completes, the header badge flips to `[OK]` (or `[ERR]` on failure).

---

## What you just proved

| Capability | Where to look next |
|---|---|
| DAG execution with parallel steps | [`docs/architecture-runtime.md`](./architecture-runtime.md) |
| Tiered model routing across providers | [`docs/architecture-runtime.md`](./architecture-runtime.md) §Tiered Model Router |
| WebSocket event streaming | [`docs/api-contracts-runtime.md`](./api-contracts-runtime.md) §`/ws/execution/{run_id}` |
| Live DAG animation + drill-down | [`agentic-workflows-v2/ui/README.md`](https://github.com/tafreeman/agentic-runtime-platform/blob/main/agentic-workflows-v2/ui/README.md) |
| Rubric-based evaluation | [`docs/architecture-eval.md`](./architecture-eval.md) |

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `agentic: command not found` | Package not installed in the active venv | `pip install -e agentic-workflows-v2/` |
| Workflow hangs on `style_check` or `review_code` | No LLM provider key in `.env` | See [`docs/ONBOARDING.md`](./ONBOARDING.md#prerequisites) |
| Frontend shows "Connecting…" forever on `/live/...` | Backend not running on port 8010 | Start Terminal 1 first; check `curl http://127.0.0.1:8010/api/health` |
| `[ERR]` status on every LLM step | Rate-limited / key invalid | Rotate the key; check `agentic-workflows-v2/runs/r-<id>.json` for error detail |
| Port 8010 or 5173 already in use | Another dev server is running | `python -m agentic_v2.cli port-guard` |

For anything else, see [`docs/KNOWN_LIMITATIONS.md`](./KNOWN_LIMITATIONS.md) or [open an issue](https://github.com/tafreeman/agentic-runtime-platform/issues/new) on the repository.
