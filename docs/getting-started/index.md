---
title: Getting started
description: Choose the shortest setup path for running, authoring, or integrating Agentic Runtime Platform.
tags:
  - getting-started
---

# Getting started

Choose the path that matches the work you want to do.

## Run an existing workflow

Start with the [quick start](quickstart.md) if you want to verify the runtime
without provider credentials. You will:

1. install the workspace;
2. create a JSON input file;
3. run the deterministic workflow; and
4. inspect the result.

`AGENTIC_NO_LLM=1` is available when you want to run an LLM-backed workflow
without making provider calls. It returns fixed placeholder text, so it checks
control flow rather than model quality.

## Write a workflow

Start with [your first workflow](first-workflow.md) if you want to define steps,
dependencies, inputs, and outputs in YAML. Continue with:

- [Workflow authoring](../WORKFLOW_AUTHORING.md) for the full schema;
- [Workflow reference](../workflows/index.md) for the shipped definitions; and
- [Pattern catalog](../PATTERN_CATALOG.md) for branching, fan-in, loops, and
  review patterns.

## Run the server and dashboard

Start with [installation](installation.md), then run:

```bash
just dev
```

The development launcher starts:

- FastAPI on `http://127.0.0.1:8010`;
- Vite on `http://127.0.0.1:5173`; and
- the UI proxy from `/api` and `/ws` to the backend.

Use `just dev-status` to inspect the processes and `just dev-stop` to stop
them.

## Integrate the platform

Read these pages before connecting the runtime to another system:

| Need | Reference |
|---|---|
| CLI commands and exit behavior | [CLI reference](../cli-reference.md) |
| HTTP, SSE, and WebSocket routes | [API contracts](../api-contracts-runtime.md) |
| Environment variables | [Configuration](../configuration.md) |
| Runtime and package boundaries | [Architecture](../ARCHITECTURE.md) |
| Authentication and tool controls | [Security hardening](../operations/security-hardening.md) |
| Deployment gaps and workarounds | [Known limitations](../KNOWN_LIMITATIONS.md) |

## Requirements

- Python 3.11 or newer
- Node.js 20 or newer for the dashboard
- npm
- Git
- `just` for the repository shortcuts, or the ability to run the equivalent
  commands manually

Docker and provider credentials are not required for the deterministic
workflow. A real model-backed run needs the package extra and credential for
the provider path you select.

## Useful checks

```bash
agentic version
agentic list workflows
agentic list adapters
agentic validate test_deterministic
```

If a command fails, use the [troubleshooting guide](../operations/troubleshooting.md)
and check [known limitations](../KNOWN_LIMITATIONS.md) before opening an issue.
