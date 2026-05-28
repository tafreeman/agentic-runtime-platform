---
title: Quick Start
description: A narrated 60-second walkthrough — install, enable No-LLM mode, run a workflow, read the artifacts.
tags:
  - getting-started
---

# Quick Start

This page expands the 60-second flow on the landing page into a narrated
walkthrough. Each step explains what is happening under the hood and what
you should see when it works.

By the end you will have:

- The runtime installed in editable mode
- `AGENTIC_NO_LLM=1` enabled (no provider keys needed)
- A `test_deterministic` workflow run with a structured artifact
- An understanding of how to read the run output

## Step 1 — Clone and install

```bash
git clone https://github.com/tafreeman/agentic-runtime-platform.git
cd agentic-runtime-platform/agentic-workflows-v2
pip install -e ".[dev,server]"
```

Two extras are pulled in here. `dev` brings the test toolchain and pre-commit
hooks; `server` brings FastAPI and the async HTTP clients used by the
provider router. Neither extra requires a network call to any LLM provider.

**Expected output:** pip prints the dependency resolution and installs
about 50 packages. The `agentic` console script becomes available on
`$PATH`. Verify with:

```bash
agentic --version
```

If `agentic` is not found, your virtualenv is not active or the editable
install did not register the entry point. Re-run `pip install -e ".[dev,server]"`
and check the printout for warnings.

## Step 2 — Enable zero-credential mode

```bash
# Linux/macOS
export AGENTIC_NO_LLM=1

# Windows PowerShell
$env:AGENTIC_NO_LLM=1
```

This single environment variable flips the model router to a deterministic
placeholder backend. The rest of the runtime — DAG executor, contract
validation, tool registry, evaluation harness — runs unchanged. No API
calls leave your machine, and no credentials are read from disk.

This is the same mode CI uses for every test in the suite. If a workflow
runs cleanly under `AGENTIC_NO_LLM=1`, the only remaining variables when
you swap in a real provider are latency, cost, and content quality — the
plumbing has already been exercised.

[Full reference for No-LLM mode →](../NO_LLM_MODE.md)

## Step 3 — Run a workflow

The `--input` flag expects a JSON **file path**. Create a one-liner input file first:

```bash
# Linux/macOS
echo '{"task":"hello"}' > /tmp/test-input.json
agentic run test_deterministic --input /tmp/test-input.json
```

```powershell
# Windows PowerShell
'{"task":"hello"}' | Out-File -Encoding utf8 test-input.json
agentic run test_deterministic --input test-input.json
```

`test_deterministic` is the simplest workflow shipped with the runtime: a
three-step DAG with no LLM calls and no tool side effects. It exists
specifically so you can confirm the executor, contract validator, and run
recorder all work before introducing any moving parts.

**Expected output:** the CLI prints a structured run record. Abbreviated:

```
Run: 0d4f...   workflow=test_deterministic   status=succeeded
  step=parse        agent=parser    duration=12ms   status=succeeded
  step=transform    agent=mapper    duration=8ms    status=succeeded
  step=summarize    agent=summary   duration=11ms   status=succeeded

Final artifact:
{
  "task": "hello",
  "summary": "...",
  "rubric_score": 0.93
}
```

If you see `status=succeeded` for every step, you have a working install.

## Step 4 — Read the artifacts

Every run writes a structured record to `runs/<run-id>/`:

```
runs/0d4f.../
├── manifest.json         # Workflow definition snapshot
├── inputs.json           # The input you passed
├── outputs.json          # The final artifact
├── timeline.json         # Step-by-step timing and status
├── traces/               # OpenTelemetry spans (if tracing enabled)
└── steps/<step-name>/    # Per-step inputs, outputs, and tool calls
```

The `manifest.json` is the exact YAML the executor saw, frozen at
submission time — re-running it from this manifest is bit-for-bit
reproducible (under `AGENTIC_NO_LLM=1`). This is how the evaluation
harness gates on artifacts: it loads the manifest, replays the run, and
scores the outputs against a rubric.

## Step 5 — Try a real workflow

Once the deterministic run succeeds, try one of the production workflows:

```bash
# Code review pipeline — five steps including LLM-dependent review
agentic run code_review --input examples/code_review_input.json

# Conditional branching — gates downstream steps on a quick triage
agentic run conditional_branching --input examples/conditional_input.json
```

In `AGENTIC_NO_LLM=1` mode, the LLM steps return canned placeholder
responses that satisfy the Pydantic contracts. To exercise a real provider,
unset the variable, set a provider key (for example `GITHUB_TOKEN` for the
free GitHub Models tier), and rerun.

[Full workflow reference →](../workflows/index.md)

## Where this leaves you

You have:

- A working editable install with the dev toolchain
- Confirmation that the DAG executor, contracts, and run recorder are healthy
- An end-to-end run with structured artifacts on disk
- A starting point for switching to a real provider when you are ready

Next up: write your own workflow with the
[First Workflow](first-workflow.md) walkthrough, or read the
[Architecture Overview](../ARCHITECTURE.md) to see how the pieces fit
together.
