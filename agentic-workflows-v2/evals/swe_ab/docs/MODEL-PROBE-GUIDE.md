# Model probe guide

How to find every model this machine can reach, and how to tell which cost
money, before spending anything on a run. Procedure, not a snapshot — the
snapshot taken 2026-08-27 is `../MODEL-INVENTORY-2026-08-27.md`.

**Rule this guide exists to enforce:** never assume a model is free, and never
assume a serving path works because a process is running. Both were wrong on
this machine.

---

## 1. Reuse ARP's own discovery first

ARP already probes four of the six paths. Use it before hand-rolling anything:

```python
from agentic_v2.models.cloud_discovery import discover_cloud_models, discover_nvidia_models
from agentic_v2.models.local_discovery import discover_lmstudio_models, discover_onnx_models
from agentic_v2.models.ollama_discovery import discover_ollama_models
```

Run it with ARP's interpreter so its `.env` loads:
`C:/Users/tandf/source/agentic-runtime-platform/.venv/Scripts/python.exe`

**What ARP does not cover, and you must probe yourself:** Lemonade, Docker Model
Runner, Foundry Local, and **free-vs-paid status for any cloud endpoint**.

---

## 2. Find the serving paths that are actually up

Ports first, because assumptions about them were wrong twice:

```powershell
Get-NetTCPConnection -State Listen | Select-Object -Unique LocalPort, OwningProcess |
  ForEach-Object { $p = Get-Process -Id $_.OwningProcess -ErrorAction SilentlyContinue
    if ($p -and $p.ProcessName -match 'ollama|lms|lemonade|python|docker|foundry|Manager') {
      "{0,-7} {1}" -f $_.LocalPort, $p.ProcessName } } | Sort-Object -Unique
```

| runtime | endpoint | list models |
|---|---|---|
| Ollama | `:11434` | `GET /api/tags` |
| Lemonade | **`:13305`** | `GET /api/v1/models` |
| Docker Model Runner | `:12434` | `GET /engines/v1/models` |
| Foundry Local | `:60160` | `foundry model ls` |
| LM Studio | `:1234` when started | `GET /v1/models` |
| NVIDIA NIM | `integrate.api.nvidia.com/v1` | `GET /models` |

**Lemonade is on 13305, not 8000.** Port 8000 belongs to an unrelated `Manager`
process; probing it returns nothing and looks like Lemonade being down.

---

## 3. Telling free from paid

There is no field in any API that says "free". Determine it by lane:

### Free with no credential
- **Ollama local models** (`ollama:qwen3:1.7b`) — weights on disk, no account.
- **Foundry Local, Lemonade, Docker Model Runner** — all local inference.

### Free but account-bound
- **Ollama Cloud** — model ids ending `-cloud` or `:cloud`
  (`deepseek-v4-flash:0731-cloud`). Served through the *local* `:11434`
  endpoint, so they look local in `/api/tags`. Free tier, rate limits unknown
  and undocumented; treat as best-effort.
- **NVIDIA NIM free endpoints** — the API does **not** expose free status. The
  authority is <https://build.nvidia.com>, where a model card is labelled
  "Free Endpoint". Carry that list in code (see `FREE_CHAT_MODELS` in the probe
  script) and verify only *availability* live.

### Paid — never let these be reachable in an eval
`ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`, `GITHUB_TOKEN`,
`OPENROUTER_API_KEY`, `AZURE_OPENAI_API_KEY`, `AZURE_FOUNDRY_API_KEY`,
`CLAUDE_CODE_OAUTH_TOKEN`.

**ARP will reach for these on its own.** When a step's output misses its
declared contract, `_invoke_with_failover` walks the tier chain into paid
providers; the first probe in this campaign hit Anthropic and returned a billing
error. There is no configuration flag that disables it.

**The only reliable control is the environment.** Delete the keys from the child
process (`PAID_CREDENTIALS` in `run_ab.py`). A provider without a key cannot be
called at all — free by construction, not by policy.

---

## 4. Verifying a model actually answers

Three failure modes look like success. Check for all three.

**a) It responds but returns nothing.** Reasoning models spend the token budget
on internal reasoning before emitting content:

```bash
curl -s http://localhost:11434/api/chat -d '{"model":"deepseek-v4-flash:0731-cloud",
  "messages":[{"role":"user","content":"Reply with exactly: OK"}],
  "stream":false,"think":false,"options":{"num_predict":64}}'
```

Without `"think": false` this returns empty content and `done_reason: length`.
Four NIM models showed exactly this and are **not** failures.

**b) It is listed but cannot load.** `muse-glimmer` is present in Docker Model
Runner and fails with `unknown model architecture: 'muse-glimmer'` — the bundled
llama.cpp does not know it. Listing is not loading; always complete one chat
call.

**c) A capability allocates but has no kernel.** `torch.float8_e4m3fn` tensors
allocate fine on this GPU while `_scaled_mm` raises, and `torch._int_mm`
**segfaults the process** rather than raising. Test the operation, not the
allocation, and isolate each test in its own process.

---

## 5. Local acceleration on this machine

| | |
|---|---|
| GPU | AMD Radeon 890M (gfx1150), 72.7 GB unified |
| NPU | Ryzen AI, reachable via ONNX Runtime `VitisAIExecutionProvider` |
| NVIDIA GPU | none — NVIDIA is cloud-only here |

**Two Python installs, and only one has working ROCm.** PATH `python` is 3.13
with a CPU-only torch. ROCm lives under Python 3.12; a working consistent stack
is at `C:/Users/tandf/rocm72-venv` (torch 2.9.1+rocmsdk20260116). Mixing ROCm
7.14 with 7.2 produces `hipErrorInvalidImage` on every kernel — only the 7.2
`rocm-sdk-libraries-custom` package carries gfx1150 code objects.

Measured on gfx1150: bf16 **8.42 TFLOP/s**, fp16 6.02, fp32 0.80. **16 bits is
the compute floor** — fp8 and int8 have no working matmul; below 16 bits means
narrow storage with wide compute (int8→bf16 dequant measured 5.79 TFLOP/s).

For *this* campaign none of that matters: the SUT is a cloud model and the
bottleneck is the endpoint, not local silicon.

---

## 6. Probe scripts

| purpose | command |
|---|---|
| ARP-native discovery | run the imports in §1 with ARP's interpreter |
| NIM free-tier check | `scratchpad/probe_nim.py` — loads the key via dotenv in a subprocess and prints only model ids and latencies, never the key |
| Local HTTP endpoints | `curl` the table in §2 |
| GPU capability | `scratchpad/rocm_bench.py`, `scratchpad/lowbit_one.py` (one dtype per process) |

**Never print an API key.** Load it inside the subprocess that needs it and emit
only results. `.env` is hook-blocked for a reason; read `.env.example` for key
names.
