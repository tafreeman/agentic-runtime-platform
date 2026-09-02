# Development without a model provider

Set `AGENTIC_NO_LLM=1` to replace the runtime's normal native and LangChain
model clients with deterministic placeholder implementations. This prevents
those clients from calling a provider.

Use this mode to test workflow structure, scheduling, events, persistence, and
UI flow. Do not use it to test output meaning or provider behavior.

## Enable it

Bash:

```bash
export AGENTIC_NO_LLM=1
agentic run test_deterministic \
  --input agentic-workflows-v2/tests/fixtures/deterministic_input.json
```

PowerShell:

```powershell
$env:AGENTIC_NO_LLM = "1"
.\.venv\Scripts\agentic.exe run test_deterministic `
  --input agentic-workflows-v2\tests\fixtures\deterministic_input.json
```

`test_deterministic` contains two tier-0 agent steps. In the current native
path those agents still enter the model-client loop, which returns placeholder
values instead of contacting a provider. The workflow finishes with
`Status: SUCCESS`, but may log input-mapping and tool-provider warnings. Use it
as an executor smoke test, not as proof that its step outputs are meaningful.

Depending on the client path, placeholder output may be a fixed text value or
a small mapping such as:

```text
{"placeholder": true, "reason": "llm_unavailable"}
```

## What it covers

- the shared native `LLMClientWrapper`;
- LangChain chat-model construction;
- normal CLI and API paths that use those clients;
- WebSocket and server-sent event plumbing for placeholder responses; and
- deterministic orchestration fallback where implemented.

The LangChain adapter still requires the `langchain` extra because its graph
and message types must be importable:

```text
python -m pip install -e "./agentic-workflows-v2[langchain]"
```

## What it does not prove

Placeholder mode does not test:

- provider credentials, permissions, availability, or quotas;
- model routing against live provider catalogs;
- structured JSON or Pydantic output from a model;
- tool calls selected by a model;
- token-by-token streaming;
- content quality or evaluation quality;
- latency, retry, fallback, or cost behavior; or
- provider SDK request and response compatibility.

Placeholder output is deterministic for the selected path, but its shape is
not a substitute for a real provider response. A step that requires a specific
model schema may fail honestly or take a fallback path. That is not evidence
that the same step will fail with a configured model.

## Independent features

`AGENTIC_NO_LLM` does not turn every AI-related component into a fake:

- `agentic-v2-eval` can run deterministic rubric and metric scoring without a
  key, but its LLM-backed evaluators still need an injected live or fake client.
- Direct provider SDK examples or integrations may have their own credential
  gates. Confirm that a path uses the shared runtime client before assuming
  this flag covers it.

## Dashboard use

Set the variable in the shell that starts the backend:

```powershell
$env:AGENTIC_NO_LLM = "1"
just dev
```

The combined development environment uses FastAPI port `8010` and Vite port
`5173`. A placeholder response is emitted as one chunk, so this mode tests
event delivery but not gradual token streaming.

## Disable it

Start a new process without the variable. In PowerShell:

```powershell
Remove-Item Env:AGENTIC_NO_LLM
```

In Bash:

```bash
unset AGENTIC_NO_LLM
```

Long-running Python processes cache settings and the shared model client. If a
test or notebook deliberately changes the flag after imports, reset both:

```python
from agentic_v2.models.client import reset_client
from agentic_v2.settings import get_settings

get_settings.cache_clear()
reset_client()
```

Normal applications should restart instead of changing mode inside a running
process.

## Accepted values

The settings parser treats `1`, `true`, `yes`, and `on` as true, ignoring
case. It treats `0`, `false`, `no`, `off`, and an empty value as false.

## When not to use it

- production or shared deployments;
- live provider integration tests;
- quality or correctness claims based on model content;
- capacity or performance tests; or
- tool-selection and structured-output tests.
