# Windows AI (Phi Silica)

> Module: `tools.llm.windows_ai`

## Overview

`windows_ai.py` integrates **Phi Silica** — Microsoft's on-device SLM that runs on the NPU of [Copilot+ PCs](https://www.microsoft.com/windows/copilot-plus-pcs). Unlike `LocalModel` (which uses `onnxruntime-genai`), Phi Silica calls the Windows AI APIs via the Windows App SDK and runs on dedicated NPU silicon, delivering very low latency without consuming GPU or CPU resources.

The Python module communicates with the Windows AI APIs through a **C# bridge** (`tools/llm/windows_ai_bridge/PhiSilicaBridge.csproj`) because the WinRT APIs are not directly accessible from Python.

### When to use this vs `LocalModel`

| Concern | `WindowsAIModel` (Phi Silica) | `LocalModel` (ONNX) |
|---------|-------------------------------|----------------------|
| Hardware requirement | Copilot+ PC with NPU | Any machine |
| OS requirement | Windows only | Cross-platform |
| Install requirement | .NET SDK + `dotnet build` | `pip install onnxruntime-genai` |
| Inference speed | Very fast (NPU dedicated) | Depends on CPU/GPU |
| Power usage | Low (NPU dedicated) | Higher |
| Model choice | Phi Silica only | phi4, phi3, mistral, custom |
| LAF token required? | Sometimes (see below) | No |

---

## Requirements

1. **Windows** — Phi Silica is a Windows-only API.
2. **Copilot+ PC** — The device must have a qualifying NPU. See [the Microsoft device list](https://www.microsoft.com/windows/copilot-plus-pcs).
3. **[.NET SDK](https://dotnet.microsoft.com/download)** — Required to build and run the C# bridge.
4. **Build the bridge** before first use:

```powershell
dotnet build tools/llm/windows_ai_bridge/PhiSilicaBridge.csproj
```

---

## Limited Access Features (LAF)

On some Windows/App SDK channels, Phi Silica is gated behind a **Limited Access Feature (LAF)** token. If you encounter a "feature not available" error, you may need LAF credentials from Microsoft.

Configure LAF via environment variables:

| Variable | Description |
|----------|-------------|
| `PHI_SILICA_LAF_FEATURE_ID` | LAF feature identifier string |
| `PHI_SILICA_LAF_TOKEN` | LAF bearer token |
| `PHI_SILICA_LAF_ATTESTATION` | LAF attestation payload |

All three must be set together. The C# bridge reads them from the process environment automatically.

Resources:
- [Phi Silica documentation](https://learn.microsoft.com/windows/ai/apis/phi-silica)
- [Unlock Phi Silica (aka.ms/phi-silica-unlock)](https://aka.ms/phi-silica-unlock)
- [Troubleshooting](https://learn.microsoft.com/windows/ai/apis/troubleshooting)

---

## Quick Start

```python
from tools.llm.windows_ai import WindowsAIModel, check_windows_ai_available

# Check availability without loading
if not check_windows_ai_available():
    print("Phi Silica not available — falling back to LocalModel")
else:
    model = WindowsAIModel()
    response = model.generate("Summarise this text in three bullet points: ...")
    print(response)
```

---

## `WindowsAIModel` Class

```python
from tools.llm.windows_ai import WindowsAIModel
```

### Constructor

```python
WindowsAIModel(verbose: bool = False)
```

| Parameter | Default | Description |
|-----------|---------|-------------|
| `verbose` | `False` | Enable debug-level logging |

**Raises at construction time:**

- `OSError` — if not running on Windows
- `RuntimeError` — if Phi Silica is not available (bridge reports `available: false`)

If construction succeeds, the model is ready and subsequent `generate()` calls will not re-probe availability.

### `generate()`

```python
response: str = model.generate(
    prompt: str,
    system_instruction: str | None = None,
    temperature: float = 0.7,
    max_tokens: int = 2000,
)
```

| Parameter | Default | Description |
|-----------|---------|-------------|
| `prompt` | required | User input |
| `system_instruction` | `None` | Optional system prompt prepended to the input |
| `temperature` | `0.7` | Sampling temperature (`0.0–1.0`) |
| `max_tokens` | `2000` | Maximum tokens to generate |

Returns the generated text as a string. On bridge errors, returns an error string prefixed with `[ERROR]` rather than raising, so callers can detect failure without wrapping in try/except.

---

## Utility Functions

### `check_windows_ai_available() → bool`

Safe availability check — returns `False` (not `RuntimeError`) on any failure:

```python
from tools.llm.windows_ai import check_windows_ai_available

if check_windows_ai_available():
    # Safe to construct WindowsAIModel
    ...
```

### `get_model_info() → dict`

Detailed diagnostic info for the current machine:

```python
from tools.llm.windows_ai import get_model_info

info = get_model_info()
print(info)
# {
#   "platform": "win32",
#   "bridge": {
#     "project": "C:/path/to/PhiSilicaBridge.csproj",
#     "dotnet_on_path": true
#   },
#   "info": {
#     "available": true,
#     "model": "Phi Silica",
#     "version": "1.0"
#   }
# }
```

### `get_phi_silica_bridge_info(timeout_s=60) → tuple[dict | None, str | None]`

Low-level function that invokes the C# bridge and returns `(parsed_dict, raw_stdout)`. Most callers should use `check_windows_ai_available()` or `get_model_info()` instead.

---

## How the C# Bridge Works

The bridge (`tools/llm/windows_ai_bridge/PhiSilicaBridge.csproj`) is a minimal C# console application that:

1. Accepts the prompt as a command-line argument
2. Calls the Windows AI `PhiSilicaClient` WinRT API
3. Prints the generated text to stdout

Python invokes it via `subprocess.run(["dotnet", "run", "--project", bridge_proj, "--", prompt], ...)` with a 120-second timeout.

The C# bridge reads LAF environment variables (`PHI_SILICA_LAF_FEATURE_ID`, `PHI_SILICA_LAF_TOKEN`, `PHI_SILICA_LAF_ATTESTATION`) from the process environment, so they must be set before the Python process starts or in the same shell session.

---

## Troubleshooting

| Error | Cause | Fix |
|-------|-------|-----|
| `OSError: Windows AI APIs are only available on Windows` | Running on Linux/macOS | Use `LocalModel` instead |
| `RuntimeError: Phi Silica not available` | Hardware doesn't have NPU or LAF tokens missing | Check device eligibility; configure LAF env vars |
| `[ERROR] C# bridge not found. Run: dotnet build ...` | Bridge not built | `dotnet build tools/llm/windows_ai_bridge/PhiSilicaBridge.csproj` |
| `[ERROR] dotnet not found` | .NET SDK not installed | Install from [dotnet.microsoft.com](https://dotnet.microsoft.com/download) |
| `[ERROR] Phi Silica request timed out (120s)` | Bridge hung | Check Windows AI service state; reboot device |
| `[ERROR] Bridge error: Feature not available` | LAF gate | Configure `PHI_SILICA_LAF_*` env vars — see [aka.ms/phi-silica-unlock](https://aka.ms/phi-silica-unlock) |

---

## Using via `LLMClient`

`LLMClient` routes to `WindowsAIModel` automatically when model availability probing detects Phi Silica. You can also call it explicitly with a `windows-ai:` prefix (check `llm_client.py` for the current prefix if this changes):

```python
from tools.llm.llm_client import LLMClient

# Check first — LLMClient will raise if the model is unavailable
from tools.llm.windows_ai import check_windows_ai_available
if check_windows_ai_available():
    response = LLMClient.generate_text("windows-ai:phi-silica", "Hello world")
```

---

## See Also

- [local-models.md](local-models.md) — ONNX inference via `onnxruntime-genai` (cross-platform)
- [model-probing.md](model-probing.md) — probe both `local:` and `windows-ai:` models with one call
- [configuration.md](../configuration.md) — `PHI_SILICA_LAF_*` environment variable reference
