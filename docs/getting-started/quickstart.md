---
title: Quick start
description: A narrated 60-second walkthrough — install, enable No-LLM mode, run a workflow, read the output.
tags:
  - getting-started
---

# Quick start

This page expands the 60-second flow on the landing page into a narrated
walkthrough. Each step explains what is happening under the hood and what
you should see when it works.

By the end you will have:

- The runtime installed in editable mode
- `AGENTIC_NO_LLM=1` enabled (no provider keys needed)
- A `test_deterministic` workflow run with a structured result
- An understanding of how to read the run output

## Step 1 — Clone and install

```bash
git clone https://github.com/tafreeman/agentic-runtime-platform.git
cd agentic-runtime-platform/agentic-workflows-v2
pip install -e ".[dev,server]"
```

Two extras are pulled in here. `dev` brings the test and lint toolchain
(pytest, ruff, mypy, black); `server` brings FastAPI and uvicorn for the
REST/WebSocket API. Neither extra requires a network call to any LLM
provider.

**Expected output:** pip prints the dependency resolution and installs
about 50 packages. The `agentic` console script becomes available on
`$PATH`. Verify with:

```bash
agentic version
```

This prints `agentic-workflows-v2 version <x.y.z>`. If `agentic` is not
found, your virtualenv is not active or the editable install did not
register the entry point. Re-run `pip install -e ".[dev,server]"` and check
the printout for warnings.

## Step 2 — Enable zero-credential mode

```bash
# Linux/macOS
export AGENTIC_NO_LLM=1

# Windows PowerShell
$env:AGENTIC_NO_LLM=1
```

This single environment variable flips the model router to a deterministic
placeholder backend. The rest of the runtime — DAG executor, contract
validation, tool registry — runs unchanged. No API calls leave your
machine, and no credentials are read from disk.

This is the same mode CI uses for every test in the suite. If a workflow
runs cleanly under `AGENTIC_NO_LLM=1`, the only remaining variables when
you swap in a real provider are latency, cost, and content quality — the
plumbing has already been exercised.

[Full reference for No-LLM mode →](../NO_LLM_MODE.md)

## Step 3 — Run a workflow

The `--input` flag expects a JSON **file path**. `test_deterministic`
declares one required input, `input_text`, so create a one-liner input
file first:

```bash
# Linux/macOS
echo '{"input_text": "hello"}' > /tmp/test-input.json
agentic run test_deterministic --input /tmp/test-input.json
```

```powershell
# Windows PowerShell
'{"input_text": "hello"}' | Out-File -Encoding utf8 test-input.json
agentic run test_deterministic --input test-input.json
```

`test_deterministic` is the simplest workflow shipped with the runtime: a
two-step DAG with no LLM calls and no tool side effects. `step1`
(agent `tier0_process`) processes the input text, and `step2`
(agent `tier0_counter`) counts its characters. It exists specifically so
you can confirm the executor and contract validator work before
introducing any moving parts.

**Expected output:**

```
╭────────────────── Workflow ──────────────────╮
│ test_deterministic                           │
│ Simple deterministic workflow for testing    │
│ (no LLM calls)                               │
╰──────────────────────────────────────────────╯
- Executing test_deterministic...

Status: SUCCESS
Elapsed: 0.0s

Outputs:
  processed_text: hello
  step_count: 5
```

Add `--verbose` to also print the execution plan (the DAG levels) and a
per-step results table. If you see `Status: SUCCESS`, you have a working
install.

## Step 4 — Read the output

By default the CLI prints the result to the console. To keep a structured
record, pass `--output`:

```bash
agentic run test_deterministic --input /tmp/test-input.json --output result.json
```

The written JSON contains the workflow name, overall status, the resolved
`outputs`, per-step results, any errors, and the elapsed time.

Runs executed through the FastAPI server are additionally logged by the
run logger as flat JSON files under the repo-root `runs/` directory, one
file per run, named
`<timestamp>_<workflow>_<run-id>_<status>.json`. Each record captures the
run id, status, score, per-step inputs/outputs, durations, retries, and
the final output — this is the record the evaluation harness consumes.

## Step 5 — Try a real workflow

Once the deterministic run succeeds, try one of the production workflows.
Each declares its own inputs, so create a matching input file:

```bash
# Code review pipeline — five steps including LLM-dependent review
echo '{"code_file": "agentic_v2/cli/main.py", "review_depth": "quick"}' > /tmp/review-input.json
agentic run code_review --input /tmp/review-input.json

# Conditional branching — gates downstream steps on input parameters
echo '{"feature_spec": "Add rate limiting to the API", "review_depth": "thorough", "target_env": "staging"}' > /tmp/cond-input.json
agentic run conditional_branching --input /tmp/cond-input.json
```

In `AGENTIC_NO_LLM=1` mode, the LLM steps return canned placeholder
responses. To exercise a real provider, unset the variable, set a provider
key (for example `GITHUB_TOKEN` for the free GitHub Models tier), and
rerun.

[Full workflow reference →](../workflows/index.md)

## Where this leaves you

You have:

- A working editable install with the dev toolchain
- Confirmation that the DAG executor and contracts are healthy
- An end-to-end run with a structured result
- A starting point for switching to a real provider when you are ready

Next up: write your own workflow with the
[First workflow](first-workflow.md) walkthrough, or read the
[Architecture overview](../ARCHITECTURE.md) to see how the pieces fit
together.
