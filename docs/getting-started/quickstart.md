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

Requirements: Python 3.11+, Node.js 22.22.2+, and npm. CI uses Node 22. Node
20.19+ or 22.12+ is enough for `npm run dev` and `npm run build`, but the UI
test dependencies (Vitest 5, jsdom 30) need Node 22.22.2+, 24.15+, or 26+.

Windows (PowerShell with [`just`](https://github.com/casey/just)):

```powershell
git clone https://github.com/tafreeman/agentic-runtime-platform.git
cd agentic-runtime-platform
just setup
.\.venv\Scripts\Activate.ps1
```

`just setup` creates `.venv` and installs into it, but it does not activate the
environment in your shell. Activate it as above, or call
`.\.venv\Scripts\agentic.exe` explicitly.

Linux or macOS (the `justfile` uses PowerShell, so use the manual path):

```bash
git clone https://github.com/tafreeman/agentic-runtime-platform.git
cd agentic-runtime-platform
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e . -c ci-constraints.txt
python -m pip install \
  -e "./agentic-workflows-v2[dev,server,langchain,tracing]" \
  -c ci-constraints.txt
python -m pip install -e "./agentic-v2-eval[dev]" -c ci-constraints.txt
npm --prefix agentic-workflows-v2/ui install
```

The root tools package is installed first, and the `langchain` extra provides
the default named-workflow adapter. The same steps, with a PowerShell variant,
are in [Installation](installation.md#manual-setup).

Verify the CLI:

```bash
agentic version
agentic list workflows
```

## 2. Create the input file

`agentic run --input` accepts a JSON file path, not inline JSON. The
deterministic workflow requires one string named `input_text`. The repository
ships a ready-made input at
`agentic-workflows-v2/tests/fixtures/deterministic_input.json` that you can
pass directly. To create your own:

Bash:

```bash
printf '{"input_text":"hello"}\n' > /tmp/agentic-input.json
```

PowerShell:

```powershell
'{"input_text":"hello"}' |
  Set-Content -Encoding ascii .\agentic-input.json
```

Use `-Encoding ascii` (or the shipped fixture) here. Windows PowerShell 5.1
writes a byte-order mark with `-Encoding utf8`, and the CLI rejects a
BOM-prefixed file with `Unexpected UTF-8 BOM`. PowerShell 7 does not add one.

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

The run also prints the workflow outputs, `processed_text` and `step_count`.

`test_deterministic` has two tier-0 agent steps:

1. `step1` reads and processes `input_text`.
2. `step2` waits for `step1` and counts the processed characters.

Tier-0 agents run deterministic Python handlers on both execution engines, so
`test_deterministic` never calls a model. `AGENTIC_NO_LLM=1` is a safeguard
here: it replaces every model call with fixed placeholder text
(`PlaceholderChatModel` on the LangGraph path, a mock backend on the native
path), which protects you from an accidental provider call if you move on to
an LLM-backed workflow. It does not test response quality. The command may log
input-mapping or tool-provider warnings while still completing successfully.

Add `--verbose` to print the execution plan and step result table:

```bash
agentic run test_deterministic \
  --input /tmp/agentic-input.json \
  --verbose
```

## 4. Save the result

Use `--output` to write a JSON summary of the run. A relative path works the
same in every shell:

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

Whichever engine ran, the file holds the CLI summary, not the full
`WorkflowResult` model:

- `workflow_name`;
- `status`, lowercase (for example `success`);
- `outputs`, the workflow's declared outputs (`processed_text` and
  `step_count` for `test_deterministic`);
- `steps`, a map of step name to `status`, `outputs`, and `error`;
- `errors`; and
- `elapsed_seconds`.

Model fields such as `run_id`, `overall_status`, `step_results`, and
`final_output` are not written. Inspect the result:

```bash
python -c "import json; d=json.load(open('result.json')); print(d['status'], d['outputs'])"
```

PowerShell:

```powershell
(Get-Content .\result.json -Raw | ConvertFrom-Json) | Select-Object status, outputs
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

## 6. Confirm the approval gate fails closed

High-impact tools (`shell`, `file_write`, `build_app`, `http_post`, and
others) need approval from a registered `ApprovalProvider`. A fresh install
registers none, so the call is denied before the tool body runs. From the
repository root, with the environment active:

```bash
python -m pytest agentic-workflows-v2/tests/test_approval_gates.py -k fails_closed -q
```

See [Known limitations section 4.3](../KNOWN_LIMITATIONS.md) for what the gate
covers today.

## 7. Validate another workflow

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

## 8. Open the dashboard

On Windows, `just dev` starts the backend and the UI, and `just dev-stop`
stops both. Without `just`, use two terminals with the environment active.

Terminal 1:

```bash
AGENTIC_NO_LLM=1 agentic serve --port 8010 --no-open
```

PowerShell:

```powershell
$env:AGENTIC_NO_LLM = "1"
agentic serve --port 8010 --no-open
```

Terminal 2:

```bash
npm --prefix agentic-workflows-v2/ui run dev
```

The UI is at `http://127.0.0.1:5173` and the API at `http://127.0.0.1:8010`
(OpenAPI at `/docs`). Vite proxies `/api` and `/ws` to port 8010 by default.
`agentic serve` itself defaults to port 8000, so pass `--port 8010` to match
the proxy. The [five-minute demo](../DEMO.md) walks through the dashboard.

## Next

- [CLI reference](../cli-reference.md)
- [First workflow](first-workflow.md)
- [Workflow reference](../workflows/index.md)
- [Architecture](../ARCHITECTURE.md)
