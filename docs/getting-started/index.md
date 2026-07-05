---
title: Getting started
description: Three install paths into Agentic Runtime Platform — pick the one that matches what you are evaluating.
tags:
  - getting-started
---

# Getting started

Agentic Runtime Platform is a monorepo. Three different audiences typically pick three
different entry points; this page lays out which path suits which goal so you
do not have to read the full architecture before your first run.

## Pick your path

### 1. The 60-second evaluator

You want to confirm the runtime works on your machine and produces sensible
artifacts before committing real reading time.

- **Time:** about 60 seconds after install completes
- **Credentials:** none — `AGENTIC_NO_LLM=1` runs the full DAG against
  deterministic placeholders
- **Output:** a structured run record with step timings, tool calls, and a
  final artifact
- **Continue with:** [Quick start](quickstart.md)

### 2. The workflow author

You want to write your own multi-agent workflows. You have likely already
seen the demo and want to understand the YAML grammar and step contracts.

- **Time:** 15–30 minutes for the first hand-authored workflow
- **Credentials:** still optional — `AGENTIC_NO_LLM=1` lets you iterate on
  graph shape and contracts before any provider is wired
- **Output:** a custom workflow definition that runs end-to-end
- **Continue with:** [First workflow](first-workflow.md), then the
  [Workflow authoring guide](../WORKFLOW_AUTHORING.md)

### 3. The platform integrator

You are wiring real providers, the FastAPI server, and the React dashboard
into a longer-lived environment — staging, demo, or a customer trial.

- **Time:** 1–2 hours including provider keys, OpenTelemetry collector,
  and the UI build
- **Credentials:** at least one real LLM provider key (OpenAI, Anthropic,
  Gemini, Azure OpenAI, Azure Foundry, GitHub Models, Ollama, or local ONNX)
- **Output:** a running server on port `8010` with the live UI on `5173`
- **Continue with:** [Installation](installation.md), then the
  [Architecture overview](../ARCHITECTURE.md)

## What you'll have when you're done

Whichever path you take, the install gives you the same surface area:

| Artifact | Where it lives | Why it matters |
|----------|----------------|-----------------|
| `agentic` CLI | Installed on `$PATH` after `pip install -e` | Lists workflows, agents, tools; runs and validates workflows; ingests RAG documents |
| FastAPI server | `agentic-workflows-v2/agentic_v2/server/` | REST + WebSocket + SSE surface for browser clients and long-lived integrations |
| React 19 dashboard | `agentic-workflows-v2/ui/` | Live DAG visualizer with step-level streaming, run history, and rubric scores |
| Evaluation harness | `agentic-v2-eval/` | Rubric runner with batch and async streaming modes, plus the LLM-as-judge protocol |
| Shared LLM client | `tools/` (`agentic-tools` package) | Multi-provider client with caching, retries, and the canonical error taxonomy |

## Prerequisites

- **Python 3.11 or newer.** The runtime exercises `asyncio.TaskGroup` and
  `Self` from `typing` — there is no fallback path for 3.10 or older.
- **Node 20+ and npm 10+** for the dashboard. The frontend uses Vite 8 and
  React 19, both of which require modern toolchains.
- **Git** with the ability to fetch full history. The
  `git-revision-date-localized` plugin embeds last-modified dates into the
  documentation site, and CI runs with `fetch-depth: 0` for that reason.

You do not need Docker, a Postgres instance, or any cloud account to run the
deterministic test workflow. Provider credentials become relevant only when
you are ready to leave No-LLM mode.

## Common starting commands

```bash
# Show every workflow and agent the runtime knows about
agentic list workflows
agentic list agents

# Validate a workflow definition without executing it
agentic validate code_review

# Compare native and LangGraph adapters on the same input
# (run from agentic-workflows-v2/; the fixture ships with the test suite)
agentic compare test_deterministic --input tests/fixtures/deterministic_input.json
```

If you get stuck, the [Known Limitations](../KNOWN_LIMITATIONS.md) page is
an honest accounting of items that are shipped with caveats — start there
before opening an issue.
