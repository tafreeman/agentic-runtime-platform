# Local ONNX models

`tools.llm.local_model.LocalModel` runs a local text-generation model through
ONNX Runtime GenAI. The model weights must already exist on disk.

Local execution avoids a hosted model request. It does not guarantee that
prompts, logs, or generated files stay private; that depends on the rest of the
application and operating environment.

## Install a runtime

Install one package that matches the target:

```powershell
# CPU
python -m pip install onnxruntime-genai

# NVIDIA CUDA
python -m pip install onnxruntime-genai-cuda

# DirectML on Windows
python -m pip install onnxruntime-genai-directml
```

Use versions supported by the selected model and hardware. Do not install
several provider variants into the same environment without checking the ONNX
Runtime guidance for that platform.

## Model discovery

Automatic discovery searches:

```text
~/.cache/aigallery/
```

It looks for known Phi and Mistral directory names, then selects a nested
directory containing an `.onnx` file.

Check discovery without loading a model:

```powershell
python -m tools.llm.local_model_cli --check
```

The command exits `0` when a model directory is found and `1` otherwise. The
result also reports whether `onnxruntime_genai` is importable.

Discovery is a filesystem check. It does not prove that the model can load on
the current hardware.

## Generate text

Use an explicit model directory when repeatability matters:

```python
from tools.llm.local_model import LocalModel

model = LocalModel(
    model_path=r"C:\models\phi4\cpu-int4",
    verbose=False,
)

response = model.generate(
    "Explain why this test failed.",
    system_prompt="Answer for a software engineer.",
    max_tokens=500,
    temperature=0.2,
    top_p=0.9,
)
print(response)
```

Constructor options:

| Option | Meaning |
| --- | --- |
| `model_path` | Exact ONNX model directory |
| `model_key` | Known discovery key such as `phi4mini`, `phi3.5`, `phi3`, or `mistral` |
| `verbose` | Enable load and generation diagnostics |

If neither path nor key is supplied, discovery selects the first known model it
finds in a stable search order.

`generate()` defaults to `max_tokens=1024`, `temperature=0.7`, and
`top_p=0.9`.

The wrapper currently formats every text prompt with Mistral-style
`<s>[INST] ... [/INST]` markers. Verify that format against the tokenizer and
chat template of the selected model. A model can load successfully and still
produce poor output when the template is wrong.

## Command line

Send one prompt:

```powershell
python -m tools.llm.local_model_cli `
  --model-path C:\models\phi4\cpu-int4 `
  --max-tokens 512 `
  --temperature 0.2 `
  "Summarize the failure."
```

Evaluate one prompt file with the built-in prompt-review routine:

```powershell
python -m tools.llm.local_model_cli `
  --model-path C:\models\phi4\cpu-int4 `
  --evaluate .\reviewer-prompt.md
```

Evaluate several prompt files while loading the model once:

```json
[
  "prompts/reviewer.md",
  "prompts/coder.md"
]
```

```powershell
python -m tools.llm.local_model_cli `
  --model-path C:\models\phi4\cpu-int4 `
  --batch-evaluate .\prompt-files.json
```

The evaluation modes use model-generated scoring. Treat their output as judge
evidence, not an objective measurement.

## Shared client

The root shared client accepts catalog keys:

```python
from tools.llm.llm_client import LLMClient

text = LLMClient.generate_text(
    "local:phi4mini",
    "Write a small retry function.",
)
```

Catalog resolution and `LocalModel` discovery use related but not identical
maps. Pass an explicit path to `LocalModel` when a catalog alias is ambiguous.

## Operational checks

Before using a local model in a benchmark or workflow:

1. Record the full model directory and weight hashes.
2. Confirm the execution provider matches the hardware.
3. Run a load and one-token generation smoke test.
4. Verify the prompt template.
5. Measure memory use, startup time, and output latency.
6. Test concurrent load behavior before starting several workers.
7. Store model license and source information with the deployment.

Common failures:

| Symptom | Check |
| --- | --- |
| `No local ONNX model found` | Pass `--model-path` or place a known model under the AI Gallery cache |
| `onnxruntime-genai not installed` | Install one matching runtime package |
| Model load failure | Confirm model format, execution provider, architecture, and available memory |
| Repeated prompt text in output | Verify tokenizer and prompt-template compatibility |
| Poor or unstable scores | Fix the judge prompt, lower sampling, and compare with human-scored cases |
