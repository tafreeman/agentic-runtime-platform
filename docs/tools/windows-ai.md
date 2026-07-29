# Windows AI and Phi Silica

`tools.llm.windows_ai.WindowsAIModel` calls Phi Silica through the repository's
.NET bridge:

```text
tools/llm/windows_ai_bridge/PhiSilicaBridge.csproj
```

Python does not call the Windows AI API directly. For each check or generation
request it starts the bridge with `dotnet run`.

## Prerequisites

The integration requires:

- Windows;
- a device and Windows configuration that expose Phi Silica;
- a compatible .NET SDK on `PATH`;
- the bridge project and its Windows App SDK dependencies; and
- Limited Access Feature settings when required by the installed Windows/App
  SDK channel.

The repository cannot infer that a machine is supported from its processor name
alone. Use the bridge check.

## Check availability

From the repository root:

```powershell
python -m tools.llm.windows_ai --info
```

Or from Python:

```python
from tools.llm.windows_ai import (
    check_windows_ai_available,
    get_model_info,
)

print(check_windows_ai_available())
print(get_model_info())
```

The check runs:

```text
dotnet run --project <bridge-project> -- --info
```

and parses the bridge's JSON output. `available: true` is stronger evidence than
the project merely building, but a real generation smoke test is still needed.

## Generate text

```python
from tools.llm.windows_ai import WindowsAIModel

model = WindowsAIModel(verbose=True)
response = model.generate(
    "Explain this stack trace.",
    system_instruction="Answer for a software engineer.",
    temperature=0.2,
    max_tokens=600,
)
print(response)
```

Important current behavior:

- construction runs an availability check;
- generation has a 120-second bridge subprocess timeout;
- `temperature` and `max_tokens` are logged in verbose mode but are not passed
  as separate bridge command-line arguments;
- generation failures are returned as strings beginning with `[ERROR]` instead
  of being raised.

Check for the error prefix before treating the response as model output.

## Shared client

The root shared client exposes the bridge through a model prefix:

```python
from tools.llm.llm_client import LLMClient

response = LLMClient.generate_text(
    "windows-ai:phi-silica",
    "Summarize this change.",
)
```

The shared client wraps bridge failures in `LLMClientError`, but the underlying
Windows wrapper may still return an `[ERROR]` string. Test the failure paths
used by your caller.

## Limited Access Feature settings

When the Windows API requires Limited Access Feature credentials, the bridge
reads:

```dotenv
PHI_SILICA_LAF_FEATURE_ID=<feature-id>
PHI_SILICA_LAF_TOKEN=<token>
PHI_SILICA_LAF_ATTESTATION=<attestation>
```

Treat these values as secrets. Do not commit them or print them in diagnostic
output.

## Diagnose a failure

Run checks in this order:

1. `dotnet --info`
2. `dotnet build .\tools\llm\windows_ai_bridge\PhiSilicaBridge.csproj`
3. `dotnet run --project .\tools\llm\windows_ai_bridge\PhiSilicaBridge.csproj -- --info`
4. `python -m tools.llm.windows_ai --info`
5. one short generation request

Common results:

| Result | Meaning |
| --- | --- |
| `Not running on Windows` | The bridge is unavailable on this platform |
| `Bridge project not found` | The repository path or installation is incomplete |
| `dotnet not found` | Install or expose a compatible .NET SDK |
| `available: false` with a bridge error | Read the returned Windows/Phi Silica error |
| `Bridge --info timed out` | The .NET or Windows AI initialization did not finish in the check timeout |
| `[ERROR] Phi Silica request timed out (120s)` | Generation exceeded the Python subprocess timeout |

Keep the full `--info` result, Windows build, bridge revision, and device model
with benchmark evidence.
