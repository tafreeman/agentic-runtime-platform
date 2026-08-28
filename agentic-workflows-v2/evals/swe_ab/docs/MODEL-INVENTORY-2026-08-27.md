# Model inventory — 2026-08-27

[Kit](../README.md) · [Docs](README.md) — **reference**, point-in-time snapshot; re-probe rather than trusting it · procedure: [MODEL-PROBE-GUIDE.md](MODEL-PROBE-GUIDE.md)

A full probe of every serving path on this machine plus the NVIDIA cloud, taken
so the A/B picks models on evidence rather than assumption.

Where possible this reuses ARP's own discovery (`discover_cloud_models`,
`discover_ollama_models`, `discover_lmstudio_models`, `discover_onnx_models`)
rather than a parallel implementation. ARP's probe does **not** cover Lemonade,
Docker Model Runner, or Foundry Local, and it has no notion of which cloud
endpoints are free — those three gaps are what the extra probing filled.

## Hardware, and one correction

| | |
|---|---|
| GPU | AMD Radeon 890M (Ryzen AI APU iGPU), 4 GB dedicated + shared |
| NPU | Ryzen AI NPU present — Foundry registered `VitisAIExecutionProvider` |
| NVIDIA GPU | **none** — NVIDIA is cloud-only here, as you said |
| torch (PATH, Python 3.13) | 2.9.1+cpu — no ROCm |
| torch (Python **3.12**) | **2.12.0+rocm7.14.0**, HIP 7.14, `is_available()` True |
| GPU memory visible to torch | **72.7 GB** (unified with system RAM) |

**Correction to an earlier claim in this file: ROCm PyTorch *is* installed.** The
first probe read the interpreter on PATH (Python 3.13, CPU wheel) and concluded
there was no ROCm build. There is one, under Python 3.12, and it enumerates the
890M with 72.7 GB of addressable unified memory.

It does not currently execute, and the reason is specific:

```
torch.AcceleratorError: CUDA error: device kernel image is invalid   (hipErrorInvalidImage)
```

This is **not** an unsupported-GPU problem — `torch.cuda.get_arch_list()`
includes `gfx1150`, which is exactly what the device reports. It is a
version-skewed stack:

| Package | Version | gfx1150 device-code files |
|---|---|---|
| `rocm-sdk-core` | 7.14.0 | 0 |
| `rocm-sdk-libraries` | 7.14.0 | **0** |
| `rocm-sdk-libraries-custom` | **7.2.0.dev0** | **191** |
| `torch` | 2.12.0+rocm7.14.0 | — |

Only the 7.2 *custom* package — the one AMD's Adrenalin installer adds for this
iGPU — carries gfx1150 code objects. torch 2.12+rocm7.14 loads the 7.14 core and
7.14 libraries, which have none, so every kernel launch fails. Setting
`HSA_OVERRIDE_GFX_VERSION` to 11.0.0, 11.5.0 or 11.5.1 does not help, and would
not: the code objects simply are not in the libraries being loaded.

The fix is to use the consistent ROCm 7.2 set AMD prescribes (`rocm_sdk_core`,
`rocm_sdk_devel`, `rocm_sdk_libraries` from `.rocm-rel-7.2_a`, plus
`torch-2.9.1+rocm`, `torchvision-0.24`, `torchaudio-2.9`) **in a virtual
environment** — which is what the Adrenalin dialog's "Create a Virtual
Environment" button does. Mixing 7.2 and 7.14 in the global environment is what
produced this state; installing into a venv keeps the working set separate from
whatever the global environment needs.

Until then the iGPU and NPU remain reachable through ONNX Runtime (VitisAI /
MIGraphX / WebGPU) and llama.cpp — Lemonade and Foundry Local both use those and
both work today.

## Precision floor on gfx1150, measured

Once the 7.2 venv worked, every dtype was tested for allocation and for an
actual matmul, each in its own process — because one of them does not fail
politely.

| dtype | matmul | time (2048³) | TFLOP/s | note |
|---|---|---|---|---|
| float32 | ✅ | 21.6 ms | 0.80 | matches CPU |
| float16 | ✅ | 2.9 ms | 6.02 | matches CPU |
| **bfloat16** | ✅ | **2.0 ms** | **8.42** | matches CPU — the fast path |
| float8_e4m3fn | ❌ | — | — | casts fine; `_scaled_mm` raises RuntimeError |
| float8_e5m2 | ❌ | — | — | same |
| int8 (`_int_mm`) | 💥 | — | — | **access violation, kills the process** |
| int8 → bf16 dequant | ✅ | 3.0 ms | 5.79 | 8-bit storage, 16-bit compute |
| 4-bit | n/a | — | — | no native torch dtype |

**16 bits is the compute floor.** Below it the GPU stores narrow and computes
wide: `int8 → bf16` dequantise-on-the-fly runs at 5.79 TFLOP/s, only about 30%
off pure bf16, which is the trade every quantised inference stack makes anyway
(bitsandbytes, GPTQ, AWQ, llama.cpp's Q4/Q8 all dequantise into a 16-bit matmul).

Two hazards worth knowing:

- `torch._int_mm` does not raise on this GPU, it **segfaults**. Any library that
  probes for int8 tensor-core support by calling it will take the whole process
  down rather than falling back. If a quantisation stack dies without a
  traceback here, this is why.
- fp8 *allocates*, so a capability check that only tests `torch.zeros(...,
  dtype=torch.float8_e4m3fn)` will wrongly conclude fp8 works. Only the matmul
  reveals it does not.

### What 72 GB buys, by precision

| Precision | Weights that fit |
|---|---|
| bf16 / fp16 | ~36 B parameters |
| 8-bit | ~72 B parameters |
| 4-bit | ~144 B parameters |

Capacity is not the constraint on this machine — an iGPU shares system memory,
so a 70B model at 4-bit fits with room to spare. Bandwidth is the constraint,
and it is why the free cloud endpoints still beat local for the A/B.

## Serving paths, probed live

| Runtime | Endpoint | Status | Models |
|---|---|---|---|
| Ollama | `:11434` | up | 12 — 3 cloud, 2 local chat, 7 embedding |
| Lemonade | `:13305` | up | 6 downloaded, incl. Ryzen AI hybrid |
| Docker Model Runner | `:12434` | up | 3 |
| Foundry Local | `:60160` | up | ~22 aliases, NPU/GPU/CPU variants each |
| LM Studio | — | **not running** | 10 cached on disk |
| NVIDIA NIM | cloud | up | 76 visible, 14 on free endpoints |

Earlier I probed `:8000` for Lemonade and got nothing — that port belongs to an
unrelated `Manager` process. Lemonade is on **13305** (and 9000, which does not
answer). Worth correcting anywhere it was written down.

### Ollama (`:11434`)

Local: `nemotron-3.5-lightning:latest` (25.4 GB), `qwen3:1.7b`.
Cloud (free tier, served through the local endpoint):
`deepseek-v4-flash:0731-cloud`, `deepseek-v4-pro:preview-cloud`,
`nemotron-3-ultra:cloud`. Plus 7 embedding models.

**`deepseek-v4-flash:0731-cloud` is the current A/B model** — 404 ms to first
answer with `think:false`, free, and it satisfied the workflow output contract
where `qwen3:1.7b` could not.

### Lemonade (`:13305`) — the NPU path

| Model | Size | Recipe | Labels |
|---|---|---|---|
| Gemma-4-26B-A4B-it-GGUF | 16.9 GB | llamacpp | tool-calling, vision |
| **CodeLlama-7b-Instruct-hf-Hybrid** | 6.74 GB | **ryzenai-llm** | coding |
| Gemma-4-E2B-it-GGUF | 3.1 GB | llamacpp | tool-calling, vision |
| bge-reranker-v2-m3-GGUF | 0.53 GB | llamacpp | reranking |
| nomic-embed-text-v2-moe-GGUF | 0.51 GB | llamacpp | embeddings |
| nomic-embed-text-v1-GGUF | 0.08 GB | llamacpp | embeddings |

The `ryzenai-llm` recipe is the hybrid NPU+iGPU path — the only thing here that
uses the AI silicon rather than the CPU.

### Foundry Local (`:60160`) — ONNX, NPU/GPU/CPU per model

Coding-relevant aliases: `qwen2.5-coder-14b` (GPU 8.79 GB), `qwen2.5-coder-7b`
(**NPU** 4.73 GB), `qwen2.5-coder-1.5b` (NPU), `qwen2.5-coder-0.5b` (NPU),
`gpt-oss-20b` (GPU 11.78 GB), `phi-4` (GPU 8.37 GB), `deepseek-r1-14b`,
`deepseek-r1-7b` (NPU), `qwen3-14b`, `qwen3-4b`, `mistral-7b-v0.2` (NPU).

This is the richest local catalogue on the machine and the only one with
NPU-quantised coding models ready to run.

### Docker Model Runner (`:12434`)

`nemotron-3.5-lightning`, `qwen3-embedding`, and `muse-glimmer` — but see below.

### LM Studio — cached, server down

10 models on disk including `meta/muse-glimmer`, `google/gemma-4-31b`,
`qwen/qwen3.8-27b`, `prism-ml/bonsai-27b`, `nvidia/nemotron-3-nano-4b`. Starting
the server would add all of them; nothing is reachable while it is stopped.

## muse-glimmer, specifically

| Path | Result |
|---|---|
| Docker Model Runner | **fails to load** — `unknown model architecture: 'muse-glimmer'` |
| NVIDIA NIM cloud | responds in 0.3 s (`meta/muse-glimmer-30b`, free endpoint) |
| LM Studio | cached on disk, server not running |

Docker's bundled llama.cpp does not know the architecture, so the local pull is
inert until Docker ships a build that does. Use the **NIM free endpoint**, or
start LM Studio and try its build. It is a 30B multimodal reasoning model with
native tool-calling and separate reasoning output — the tool-calling matters if
a future arm gives agents real tools.

## NVIDIA NIM free endpoints, live-tested

All 14 are visible to this account. Latency is one cold call each:

| Model | Result |
|---|---|
| `minimaxai/minimax-m3` | ✅ `OK` in 26.1 s |
| `nvidia/nemotron-3-super-120b-a12b` | ✅ 0.9 s (reasoning preamble) |
| `nvidia/nemotron-3-nano-30b-a3b` | ✅ 0.3 s (reasoning preamble) |
| `nvidia/nemotron-3-ultra-550b-a55b` | ✅ 33.8 s (reasoning preamble) |
| `deepseek-ai/deepseek-v4-flash-0731` | ⚠️ 5.5 s, empty content |
| `meta/muse-glimmer-30b` | ⚠️ 0.3 s, empty content |
| `stepfun-ai/step-3.7-flash` | ⚠️ 0.2 s, empty content |
| `openai/gpt-oss-20b` | ⚠️ 0.4 s, empty content |
| `deepseek-ai/deepseek-v4-pro-0813` | ⏱ timeout at 60 s |
| `nvidia/nemotron-3.5-lightning-30b-a3b` | ⏱ timeout at 60 s |
| `openai/gpt-oss-120b` | ⏱ timeout at 60 s |
| `google/gemma-4-31b-it` | ⏱ timeout at 60 s |
| `mistralai/mistral-nemotron` | ⏱ timeout at 60 s |
| `poolside/laguna-xs-2.1` | ❌ HTTP 503 `ResourceExhausted` |

**The empty ones are not failures.** They are thinking models that spent the
12-token budget on reasoning before emitting any content — the same behaviour
`deepseek-v4-flash` showed on Ollama until `think:false` was set. Any of them
needs either reasoning disabled or a much larger `max_tokens` before its output
means anything. The timeouts are cold-start or capacity, not absence.

The key was loaded from ARP's `.env` by `python-dotenv` inside the probe
subprocess. It was never read, printed, or returned here.

## Already on disk: the benchmark datasets

`~/.cache/huggingface/hub` (30 GB) holds **SWE-bench**, **SWE-bench_Lite**,
**SWE-bench_Verified**, **HumanEval**, **HumanEval+**, **MBPP**, and **APPS**,
plus several code-instruct datasets. The original ask — "SWE-bench or some type
of software development task" — has its data sitting local already. EvalKit
ships a `swebench-verified@1` adapter and a Docker harness, so that path is
closer than the mined-mutation path suggested.

## What to download, if anything

Only two formats run well here: **GGUF** (llama.cpp, via Ollama/Lemonade/DMR)
and **Ryzen AI hybrid ONNX** (Lemonade's `ryzenai-llm`). A plain HF transformers
checkpoint would run on CPU through torch and be far too slow for 132 cases.

Worth pulling, in order of value for a coding eval:

1. **`amd/Qwen2.5-Coder-7B-Instruct-onnx-ryzenai-1.7-hybrid`** — same hybrid
   recipe as the CodeLlama-7b already installed, but a materially stronger
   coding model. The most direct upgrade to the local NPU path.
2. **`amd/Qwen3-14B-onnx-ryzenai-1.7-hybrid`** — larger, still hybrid.
3. A GGUF MoE with few active parameters (Qwen3-Coder-30B-A3B class) — 30B
   quality at ~3B active cost, which is what makes a 30B tolerable without a
   discrete GPU.

Full list: [Ryzen-AI-1.7-Hybrid-LLM collection](https://huggingface.co/collections/amd/ryzen-ai-17-hybrid-llm).
AMD also publishes 1.8 Hybrid / NPU-4K / NPU-16K collections.

Nothing needs downloading for the A/B as configured — the cloud lane is free
and faster than anything local here.

## Recommendation for the next A/B

- **System under test:** keep `deepseek-v4-flash:0731-cloud` (fast, free, meets
  the contract). If you want a second data point, `nemotron-3-nano-30b-a3b` on
  NIM answered in 0.3 s and is a different family.
- **Judge:** `nemotron-3-ultra:cloud` via Ollama, already smoke-tested. Different
  family from the SUT, which is the point.
- **Local control arm** (optional): Foundry Local's `qwen2.5-coder-7b` on NPU —
  the only way to get an apples-to-apples "does local silicon suffice" answer.
- **Disable reasoning or raise `max_tokens`** on any thinking model before
  trusting a single number from it.
