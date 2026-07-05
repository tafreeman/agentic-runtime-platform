# Local ONNX models

> Modules: `tools.llm.local_model` · `tools.llm.local_model_cli` · `tools.llm.local_model_discovery`

## Overview

The local model stack provides fast, free, offline LLM inference using ONNX models cached locally by the [AI Dev Gallery](https://aka.ms/ai-dev-gallery) or installed manually. No API key or internet connection is required once a model is downloaded.

Three modules work together:

| Module | Responsibility |
|--------|---------------|
| `local_model_discovery.py` | Locate ONNX model directories under `~/.cache/aigallery` |
| `local_model.py` | `LocalModel` — load and run inference against a located model |
| `local_model_cli.py` | CLI entry point wrapping `LocalModel` with four operating modes |

For most callers, the higher-level `LLMClient` (see [llm-client.md](llm-client.md)) is the preferred interface and routes to these modules automatically when a `local:` prefix is used. Use `LocalModel` directly when you need finer control over model loading or the 6-criterion `evaluate_prompt()` output.

---

## Supported models

| Key | AI Dev Gallery directory | Notes |
|-----|---------------------|-------|
| `phi4` / `phi4mini` | `microsoft--Phi-4-mini-instruct-onnx` | Default fallback |
| `phi3` | `microsoft--Phi-3-mini-4k-instruct-onnx` | |
| `phi3.5` | `microsoft--Phi-3.5-mini-instruct-onnx` | |
| `mistral` / `mistral-7b` | `microsoft--mistral-7b-instruct-v0.2-ONNX` | |

Models are resolved in the order `phi4mini → phi3.5 → phi3 → mistral` when no key is specified.

---

## Quick start

```python
from tools.llm.local_model import LocalModel

# Automatically finds the first available model under ~/.cache/aigallery
model = LocalModel()
response = model.generate("Summarise the key points of the following text: ...")
print(response)

# Select a specific model by key
model = LocalModel(model_key="phi4")

# Point to a custom ONNX directory
model = LocalModel(model_path="/mnt/models/my-custom-onnx")

# Get a structured 6-criterion evaluation of a prompt file
result = model.evaluate_prompt(prompt_text)
# → {"clarity": 8.5, "specificity": 7.0, "context": 9.0, ...}
```

---

## Model discovery

### How paths are resolved

The public resolver is `tools.llm.provider_adapters.resolve_local_model_path(model_key, local_models=...)` — this is what `LLMClient`'s `local:` routing uses. It maps the key through the `LOCAL_MODELS` catalog, then locates a directory containing `.onnx` files under `~/.cache/aigallery` (an absolute catalog path is used as-is), preferring candidate subdirectories that match a `-gpu`/`-dml`/`-cpu` variant hint.

`LocalModel` itself uses the module-private helper `local_model_discovery._resolve_model_path(model_key)`, which implements a two-pass lookup:

1. **Key lookup** — if `model_key` is provided (e.g. `"phi4"`), maps to a list of known directory names under `_AI_GALLERY_ROOT` and returns the first match that contains a `*.onnx` file.
2. **Auto-fallback** — if no key is given or the key is unknown, iterates `["phi4mini", "phi3.5", "phi3", "mistral"]` in order and returns the first available.

The AI Gallery root is:

```
~/.cache/aigallery/          ← _AI_GALLERY_ROOT
  microsoft--Phi-4-mini-instruct-onnx/
    cpu-int4-rtn-block-32-acc-level-4/   ← contains *.onnx files
      model.onnx
      ...
```

`_find_onnx_model_dir(base)` walks a model base directory recursively and returns the first subdirectory containing `*.onnx` files.

### `get_model_info() → dict`

Returns availability status without loading the model:

```python
from tools.llm.local_model_discovery import get_model_info

info = get_model_info()
# {
#   "available": true,
#   "model_path": "/home/user/.cache/aigallery/microsoft--Phi-4-mini-instruct-onnx/cpu-int4-rtn.../",
#   "model_key": "phi4mini",
#   "error": null
# }
```

### `check_model_available() → bool`

Lightweight check — returns `True` if any model can be found:

```python
from tools.llm.local_model_discovery import check_model_available

if check_model_available():
    model = LocalModel()
```

---

## `LocalModel` class

```python
from tools.llm.local_model import LocalModel
```

### Constructor

```python
LocalModel(
    model_path: str | None = None,
    model_key: str | None = None,
    verbose: bool = False,
)
```

| Parameter | Type | Description |
|-----------|------|-------------|
| `model_path` | `str \| None` | Explicit path to an ONNX model directory. Takes priority over `model_key`. |
| `model_key` | `str \| None` | Short model name (`"phi4"`, `"mistral"`, etc.). Resolved via the discovery module's path lookup. |
| `verbose` | `bool` | Enable debug-level logging of model load and generation steps. |

Raises `FileNotFoundError` if no model can be located.  
Raises `ImportError` if `onnxruntime-genai` is not installed.

### `generate()`

```python
response: str = model.generate(
    prompt: str,
    max_tokens: int = 1024,
    temperature: float = 0.7,
    top_p: float = 0.9,
    system_prompt: str | None = None,
)
```

Generate text from the model. Formats the prompt using Mistral instruction format (`[INST]...[/INST]`) when a `system_prompt` is provided.

| Parameter | Default | Description |
|-----------|---------|-------------|
| `prompt` | required | User-facing input text |
| `max_tokens` | `1024` | Maximum tokens to generate |
| `temperature` | `0.7` | Sampling temperature — `0.0` for deterministic |
| `top_p` | `0.9` | Nucleus sampling threshold |
| `system_prompt` | `None` | Optional system instruction prepended to the prompt |

### `evaluate_prompt()`

```python
result: dict = model.evaluate_prompt(prompt_text: str)
```

Runs the model with a built-in evaluation rubric and returns a structured scoring dict across 6 criteria:

```json
{
  "clarity":        8.5,
  "specificity":    7.0,
  "context":        9.0,
  "actionability":  6.5,
  "tone":           8.0,
  "completeness":   7.5,
  "overall_score":  7.75,
  "feedback":       "The prompt is clear but could benefit from more specific constraints..."
}
```

All numeric scores are in the range `0.0–10.0`. The model's raw output is parsed with a best-effort JSON extractor; malformed responses fall back to `0.0` for numeric fields via `_safe_float`.

---

## CLI

`local_model_cli.py` is the command-line interface for `LocalModel`. It exposes four operating modes.

### Mode 1 — Direct generation

```bash
python -m tools.llm.local_model_cli "Your prompt text here"
python -m tools.llm.local_model_cli --model-path /path/to/onnx "Your prompt"
python -m tools.llm.local_model_cli --max-tokens 512 --temperature 0.3 "Generate a summary"
```

Exits `0` on success, `1` on error.

### Mode 2 — Check availability (`--check`)

```bash
python -m tools.llm.local_model_cli --check
```

Prints a JSON object describing model availability and exits `0` if a model is found, `1` if not. Equivalent to calling `get_model_info()`:

```json
{
  "available": true,
  "model_path": "/home/user/.cache/aigallery/...",
  "model_key": "phi4mini",
  "error": null
}
```

### Mode 3 — Evaluate a prompt file (`--evaluate`)

```bash
python -m tools.llm.local_model_cli --evaluate path/to/prompt.md
python -m tools.llm.local_model_cli --evaluate path/to/prompt.md --verbose
```

Reads the file, calls `evaluate_prompt()`, and prints the 6-criterion JSON result. Exits `0` on success, `1` if the file is not found or an error occurs.

### Mode 4 — Batch evaluate (`--batch-evaluate`)

```bash
# batch_list.json must be a JSON array of file paths
python -m tools.llm.local_model_cli --batch-evaluate batch_list.json
```

Where `batch_list.json` looks like:

```json
[
  "prompts/advanced/clarity_test.md",
  "prompts/business/executive_summary.md",
  "prompts/developers/code_review.md"
]
```

Loads the model **once** and evaluates all files. Prints a JSON array of results, one per file. Files that cannot be read are included with an `"error"` field instead of scores. Exits `0` if all succeed, `1` if any fail.

### CLI flags reference

| Flag | Default | Description |
|------|---------|-------------|
| `prompt` (positional) | — | Prompt text for direct generation |
| `--model-path`, `-m` | Auto-detect | Path to ONNX model directory |
| `--max-tokens`, `-t` | `1024` | Maximum tokens to generate |
| `--temperature` | `0.7` | Sampling temperature |
| `--check` | — | Check model availability and exit |
| `--evaluate`, `-e` | — | Path to a prompt file to evaluate |
| `--batch-evaluate` | — | Path to a JSON file listing prompt paths |
| `--verbose`, `-v` | — | Enable debug logging |

---

## Installation

```bash
# CPU inference (recommended for most development)
pip install onnxruntime-genai

# NVIDIA GPU
pip install onnxruntime-genai-cuda

# AMD/Intel GPU on Windows (DirectML)
pip install onnxruntime-genai-directml
```

Only one variant should be installed at a time.

### Installing a model

Models are installed via the AI Dev Gallery tooling or manually:

```bash
# AI Dev Gallery (recommended on Windows)
# Open the AI Dev Gallery app (or the VS Code AI Toolkit) and download a model.
# It will be placed under ~/.cache/aigallery/

# Manual — place your ONNX model directory under _AI_GALLERY_ROOT:
# ~/.cache/aigallery/<model-dir>/cpu-int4-rtn-block-32-acc-level-4/model.onnx
```

---

## Troubleshooting

| Error | Cause | Fix |
|-------|-------|-----|
| `FileNotFoundError: No local ONNX model found` | No model in `~/.cache/aigallery` | Install a model via the AI Dev Gallery or pass `--model-path` |
| `ImportError: onnxruntime-genai not installed` | Package missing | `pip install onnxruntime-genai` |
| `RuntimeError: Failed to load model` | Corrupt or incompatible ONNX files | Re-download the model |
| Low-quality output | Temperature too high | Try `--temperature 0.3` or `0.0` for deterministic output |

---

## See also

- [llm-client.md](llm-client.md) — use `LLMClient` with `local:phi4` prefix for most cases
- [model-probing.md](model-probing.md) — check availability before loading with `probe.check_model("local:phi4")`
- [windows-ai.md](windows-ai.md) — Phi Silica on Copilot+ PCs (NPU, no onnxruntime-genai needed)
