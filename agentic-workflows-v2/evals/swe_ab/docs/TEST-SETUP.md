# Test setup

Everything required to run this A/B, and how to verify each piece before
spending an hour discovering it was missing. Written so a fresh agent or a
fresh session can pick the campaign up mid-flight.

---

## 1. Preflight — run this first, every session

```bash
# 1. Docker daemon, Linux containers
docker version --format '{{.Server.Os}}/{{.Server.Arch}} engine {{.Server.Version}}'
#    expect: linux/amd64 engine 29.x

# 2. The SWE-bench runner image exists
docker image inspect swebench-runner:local >/dev/null 2>&1 && echo "runner: ok" || echo "runner: BUILD IT"

# 3. The harness can run and reach the daemon (this is the real gate)
cd <kit> && uv run python -c "import sys; sys.path.insert(0,'.'); \
  from container_harness import container_preflight; print(container_preflight() or 'READY')"
#    expect: READY

# 4. Model endpoint answers
curl -s http://localhost:11434/api/chat -d '{"model":"deepseek-v4-flash:0731-cloud",
  "messages":[{"role":"user","content":"Reply with exactly: OK"}],
  "stream":false,"think":false,"options":{"num_predict":32}}' | grep -o '"content":"[^"]*"'

# 5. Disk — each instance costs ~2 GB after layer sharing
df -h /c | tail -1
```

If step 3 does not say `READY`, nothing downstream is trustworthy: the grader
will report `UNAVAILABLE`, which is correct behaviour but produces no verdicts.

---

## 2. Requirements

### Required

| requirement | why | verify |
|---|---|---|
| **Docker Desktop, Linux engine** | instance containers and the runner | `docker run --rm hello-world` |
| **`swebench-runner:local` image** | Windows cannot import `swebench` | `docker image inspect swebench-runner:local` |
| **Ollama at `:11434`** | serves the cloud SUT model | `curl -s localhost:11434/api/tags` |
| **Ollama Cloud account** | `deepseek-v4-flash:0731-cloud` | the chat call in §1 |
| **EvalKit venv with `swebench` extra** | grader imports | `uv sync --extra swebench` |
| **ARP venv** | `bridge.py` runs there | `.../agentic-runtime-platform/.venv/Scripts/python.exe` |
| **SWE-bench Verified parquet** | case source | see §3 |
| **~2 GB free disk per instance** | instance images | `df -h /c` |

### Not required, despite appearances

- **WSL** — an earlier design ran the harness there. Not used. This machine's
  Ubuntu-24.04 has an interrupted dpkg (`dpkg was interrupted, you must manually
  run 'dpkg --configure -a'`) and cannot install packages. The container route
  replaced it and touches nothing on the host.
- **A GPU, ROCm, or any local model host** — the SUT is a cloud model. LM Studio,
  Lemonade and Foundry Local were measured at ~200 MB idle and are irrelevant
  here.
- **NVIDIA API key** — only needed for the NIM lane, which this campaign does
  not use.

---

## 3. Building the pieces

### The runner image

```bash
docker build -t swebench-runner:local -f Dockerfile.swebench-runner .
```

`swebench.harness.prepare_images` imports `resource`, a Unix-only stdlib module,
so the harness **cannot be imported on Windows at all** — not the package, not
even its constants. The image is a `python:3.12-slim` with swebench installed;
it mounts the host Docker socket and spawns instance containers as siblings
against the same daemon and the same prebuilt images.

### The dataset

SWE-bench Verified is expected in the HF cache:

```
~/.cache/huggingface/hub/datasets--princeton-nlp--SWE-bench_Verified/
  snapshots/c104f840cc67f8b6eec6f759ebc8b2693d585d4a/data/test-00000-of-00001.parquet
```

If absent: `huggingface-cli download princeton-nlp/SWE-bench_Verified --repo-type dataset`.
The snapshot hash is hard-coded in `tools/build_swebench_cases.py:PARQUET`;
update it if you re-download.

### The EvalKit venv

```bash
cd C:/Users/tandf/source/agentic-evalkit && uv sync --extra swebench
```

---

## 4. Isolation — what is protected from what

| risk | control |
|---|---|
| Agent writing into a live repo | every workflow step declares `tools: []`; `bridge.py` `chdir`s to a sandbox |
| Paid provider billed by ARP failover | `PAID_CREDENTIALS` deleted from the child env in `run_ab.py` |
| Mutation left in a real checkout | mining and grading run in throwaway git worktrees under the scratchpad, never in a live repo |
| One repo's grading colliding with another's | one worktree per source repo, each with its own lock |
| Instance containers touching the host | each runs in its own container; `--rm`; the harness removes them |
| Another project's source entering this repo | `dataset/cases/` and `dataset/swebench_cases/` are gitignored and rebuilt |

**A hard kill can defeat the worktree restore.** Stopping a miner mid-mutation
left `executionkit/batches.py` modified in its worktree. After any interrupted
run: `git -C <worktree> checkout -- .`

---

## 5. Running

```bash
# One wave, both arms, pinned settings (the normal path)
uv run python tools/run_wave.py --wave N --size 16

# Same, and drop this wave's images afterwards (long campaigns)
uv run python tools/run_wave.py --wave N --size 16 --prune-images

# Analysis across every wave so far
uv run python analyze.py \
  --left  reports/arm-a-direct-swebench-c4.json --left  reports/arm-a-direct-wave1.json \
  --right reports/arm-b-review-loop-swebench-fixed.json --right reports/arm-b-review-loop-wave1.json
```

**Do not pass `--model`, `--concurrency` or `--timeout` to `run_wave.py`.** They
are pinned in `CAMPAIGN` inside the module on purpose: two of this campaign's
worst errors were mid-experiment changes (an oracle patched while a run was in
flight; arms run at different concurrency). Waves union soundly only while every
wave shares an arm, a model and a configuration. **A wave needing different
settings is a different experiment.**

### Timing, measured at concurrency 4

| | per instance | 16-instance wave |
|---|---|---|
| Arm A | 0.75 min | ~12 min |
| Arm B | 1.79 min | ~29 min |
| Image pulls | ~1 min (new only) | ~10 min |
| **Total** | **~2.5 min** | **~50 min** |

---

## 6. Resuming mid-campaign

State lives on disk; nothing depends on a session being alive.

1. **What is banked** — every `reports/*.json`. `analyze.py` unions any subset.
2. **What has been built** — directories under `dataset/swebench_cases/`. The
   builder skips these automatically, so **waves never overlap** regardless of
   which wave number you pass.
3. **Next wave number** — highest existing `cases.swebench.waveN.jsonl`, plus 1.
   Only used for naming; overlap prevention does not depend on it.

```bash
ls dataset/cases.swebench.wave*.jsonl          # waves built so far
ls dataset/swebench_cases | wc -l              # instances built so far
ls reports/*wave*.json                         # waves run so far
```

**Progress within a wave is not observable.** `run_ab.py` prints only at the
end. To gauge a run in flight, count spilled artifacts — one per graded sample:

```bash
find artifacts -name "*.bin" -newermt "<wave start time>" | wc -l
```

Wiring `EvalRunner.run(event_sink=...)` to a progress log is the proper fix and
is **not yet done**.

---

## 7. Campaign state, 2026-08-28

| | |
|---|---|
| Banked | **47 paired SWE-bench instances** — A 61.7%, B 59.6%, p = 1.00 |
| Built | 50 SWE-bench case directories, 132 mutation cases |
| Waves run | wave 1 (12 instances) plus the 35-instance hand-built set |
| Target | ~200 paired instances (≈ 10 more hour-waves) |
| Next | `run_wave.py --wave 2 --size 16` |

---

## 8. Known environment traps

| trap | symptom | fix |
|---|---|---|
| Git Bash mangles the Docker socket path | `mkdir C:\Program Files\Git\var: Access is denied` | `MSYS_NO_PATHCONV=1` before `docker run -v /var/run/docker.sock:...` |
| Two Pythons, different capabilities | torch says CPU-only | PATH python is 3.13; ROCm is 3.12 (`C:/Users/tandf/rocm72-venv`) |
| Reasoning models return empty content | `done_reason: length`, no text | `"think": false` or a much larger `num_predict` |
| Lemonade probed on the wrong port | nothing answers on `:8000` | it serves on **`:13305`** |
| WSL apt is broken | `dpkg was interrupted` | not needed; the container route replaces it |
