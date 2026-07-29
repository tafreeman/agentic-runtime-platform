---
title: Quick start
description: Install the workspace, run the deterministic workflow, and inspect its result.
tags:
  - getting-started
---

# Quick start

This walkthrough verifies the CLI, workflow discovery, input validation,
dependency ordering, and result serialization. It does not need a provider
credential.

## 1. Install

```powershell
git clone https://github.com/tafreeman/agentic-runtime-platform.git
cd agentic-runtime-platform
just setup
```

The current `justfile` uses PowerShell. On Linux, macOS, or a system without
`just`, follow the
[manual installation steps](installation.md). The manual path installs the
root tools package before the runtime and includes the `langchain` extra used
by the default named-workflow adapter.

Verify the CLI:

```bash
agentic version
agentic list workflows
```

## 2. Create the input file

`agentic run --input` accepts a JSON file path. The deterministic workflow
requires one string named `input_text`.

Bash:

```bash
printf '{"input_text":"hello"}\n' > /tmp/agentic-input.json
```

PowerShell:

```powershell
'{"input_text":"hello"}' |
  Set-Content -Encoding utf8 .\agentic-input.json
```

## 3. Run the workflow

Bash:

```bash
AGENTIC_NO_LLM=1 agentic run test_deterministic \
  --input /tmp/agentic-input.json
```

PowerShell:

```powershell
$env:AGENTIC_NO_LLM = "1"
agentic run test_deterministic --input .\agentic-input.json
```

The expected status is:

```text
Status: SUCCESS
```

`test_deterministic` has two tier-0 agent steps:

1. `step1` reads and processes `input_text`.
2. `step2` waits for `step1` and counts the processed characters.

The current native path still resolves those agents through the model-client
loop. With `AGENTIC_NO_LLM=1`, it returns placeholder values without an
external provider call. The command may log input-mapping or tool-provider
warnings while still completing successfully.

Add `--verbose` to print the execution plan and step result table:

```bash
agentic run test_deterministic \
  --input /tmp/agentic-input.json \
  --verbose
```

## 4. Save the result

Use `--output` to write the `WorkflowResult` JSON:

```bash
agentic run test_deterministic \
  --input /tmp/agentic-input.json \
  --output result.json
```

PowerShell:

```powershell
agentic run test_deterministic `
  --input .\agentic-input.json `
  --output .\result.json
```

The document contains:

- `workflow_name`;
- `run_id`;
- `overall_status`;
- `step_results`;
- `final_output`;
- start and completion timestamps;
- derived duration and success fields; and
- errors and metadata when present.

Inspect the resolved outputs:

```bash
python -c "import json; print(json.load(open('result.json'))['final_output'])"
```

PowerShell:

```powershell
(Get-Content .\result.json -Raw | ConvertFrom-Json).final_output
```

## 5. Check both adapters

The named workflow path defaults to LangGraph. Run the same definition through
the native engine:

```bash
agentic run test_deterministic \
  --input /tmp/agentic-input.json \
  --adapter native
```

Or compare both:

```bash
agentic compare test_deterministic \
  --input /tmp/agentic-input.json \
  --adapters native,langchain
```

Both runs should succeed. A failed side makes `agentic compare` exit non-zero.

## 6. Validate another workflow

Validation checks schema, dependencies, cycles, and LangGraph compilation
without calling a provider:

```bash
agentic validate code_review --verbose
agentic run code_review --dry-run
```

Do not use placeholder mode as proof that an LLM-backed workflow produces valid
business output. The placeholder is fixed text. Workflows that require JSON,
source code, tool calls, or typed artifacts can fail or produce unresolved
outputs by design.

For a real model-backed run:

1. copy `.env.example` to `.env`;
2. set one supported provider credential;
3. unset `AGENTIC_NO_LLM`; and
4. supply the inputs required by the selected workflow.

See [Configuration](../configuration.md) and
[No-LLM mode](../NO_LLM_MODE.md).

## Next

- [CLI reference](../cli-reference.md)
- [First workflow](first-workflow.md)
- [Workflow reference](../workflows/index.md)
- [Architecture](../ARCHITECTURE.md)
