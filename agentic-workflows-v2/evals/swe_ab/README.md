# ARP SWE-fix A/B — two workflows, one rubric, free models

Does ARP's multi-step review-loop workflow repair more defects than a single
coder call, at equal model and equal input?

> **Reading as of 2026-08-28, 47 paired SWE-bench instances:** Arm A (direct)
> 61.7%, Arm B (review loop) 59.6%. Difference −2.1%, McNemar **p = 1.00** — no
> detectable difference, and Arm B costs 3–6× per case. An earlier −8.6% at
> n = 35 did not survive harder cases.
>
> **Oracle retrieval — not a SWE-bench leaderboard number.** The live tally is
> [docs/EVIDENCE.md §1.3](docs/EVIDENCE.md#13-swe-bench-verified-oracle-retrieval),
> not this banner.

**Start here → [docs/README.md](docs/README.md)** — the documentation map, with
a reading path for whichever of the four jobs you are here to do: run a wave,
design an eval, choose models, or audit a number.

| I want to… | go to |
|---|---|
| Run the next wave | [docs/TEST-SETUP.md](docs/TEST-SETUP.md) → [docs/WAVE-RUNBOOK.md](docs/WAVE-RUNBOOK.md) |
| Hand it to an agent | [docs/SUBAGENT-PROMPT.md](docs/SUBAGENT-PROMPT.md) |
| Design a different eval | [docs/BEST-PRACTICES.md](docs/BEST-PRACTICES.md) |
| Pick models / not spend money | [docs/MODEL-PROBE-GUIDE.md](docs/MODEL-PROBE-GUIDE.md) |
| Audit a number | [docs/EVIDENCE.md](docs/EVIDENCE.md) → [docs/results/](docs/results/) |
| Fix the platform, not the eval | [docs/ARP-IMPROVEMENTS-PROMPT.md](docs/ARP-IMPROVEMENTS-PROMPT.md) |

---

## The experiment

| | Arm A | Arm B |
|---|---|---|
| Workflow | `workflows/swe_fix_direct.yaml` | `workflows/swe_fix_review_loop.yaml` |
| Steps | parse → patch | parse → root cause → draft → regression review → revise → verify |
| Agents | `tier0_parser`, `tier2_coder` | + `tier2_reviewer`, `tier1_analyzer`, `tier2_tester` |
| Inputs / outputs | identical | identical |
| Rubric | `swe_fix_v1` | `swe_fix_v1` |
| Model | pinned via `model_override` | **same id, same temperature, same seed** |

Everything except orchestration depth is held constant, so a score delta is
attributable to the review loop and nothing else. Models cost nothing — local
Ollama, Ollama Cloud free tier, NVIDIA NIM free tier — and paid credentials are
deleted from the child environment so no failover can reach them.

### Three case sets, one answer

| set | n | Arm A | Arm B | B − A | McNemar p | B's cost |
|---|---|---|---|---|---|---|
| [mutations, 1 repo](docs/results/2026-08-27-mutations-50.md) | 50 | 96.0% | 90.0% | −6.0% | 0.25 | 3.5× |
| [mutations, 4 repos](docs/results/2026-08-27-mutations-132.md) | 132 | 94.7% | 90.9% | −3.8% | 0.23 | 3.0× |
| [SWE-bench Verified](docs/results/2026-08-28-swebench-35.md) | 35 | 68.6% | 60.0% | −8.6% | 0.45 | 5.9× |
| **SWE-bench union** | **47** | **61.7%** | 59.6% | −2.1% | **1.00** | — |

Arm A leads on every set, never significantly. The mutation sets sat at ~95% for
both arms — a ceiling that cannot separate two competent orchestrations, which
is why the campaign moved to SWE-bench. Settling the question needs ~200 paired
instances; the campaign is accumulating them in waves.

**The open hypothesis:** the review loop may only help where the direct arm
fails. Wave 1's harder instances went A 41.7% / B 58.3% — the one slice where
Arm B led. Testing that needs a per-difficulty split at much larger n.

## Grading stack — deterministic first, judge last

```
workflow output {patch, root_cause, verification_report}
        │
        ├── schema check ......... hard gate: the three fields exist and are strings
        ├── patch applies ........ hard gate: git apply --check at the pinned commit
        ├── tests untouched ...... hard gate: diff touches no tests/ or oracle path
        ├── hidden tests ......... hard gate: the real oracle suite (SWE-bench harness,
        │                          in-container, or the case's covering pytest file)
        ├── public tests ......... hard gate: no regression against the pre-patch suite
        ├── diff budget .......... scored 0..1, not gating
        ├── AST safety scan ...... scored, not gating (no eval/exec/subprocess/network)
        └── rubric-bound judge ... weight 0.0, ADVISORY — records a verdict, moves nothing
```

The judge sits at weight 0.0 on purpose. Under EvalKit's ADR-0007 / D-1 an
uncalibrated judge cannot gate, and a judge on a free 8–30B model is emphatically
uncalibrated. To promote it: label ≥30 good and ≥30 bad judge cases, run
`agentic-evalkit calibrate`, and only if TNR ≥ 0.95 / TPR ≥ 0.85 / age ≤ 90d hold
on the **Wilson lower bound** does its weight move off zero.

On SWE-bench the composite is replaced outright by `SwebenchGrader`, which
sequences explicitly: sanity failure → FAIL; harness cannot run → **UNAVAILABLE,
never PASS**; harness ran → its verdict. That exists because
`CompositeGrader` excludes UNAVAILABLE from its weighted mean and once reported
**5/5 passed on a benchmark that never ran**
([EVIDENCE §2.1](docs/EVIDENCE.md#21-a-grader-that-passed-a-benchmark-it-never-ran--critical)).

Rubric: [`rubric.py`](rubric.py) — 8 atomic criteria, 6 decided by running code,
2 by the judge, validated against EvalKit's `Rubric` model.

## Models — one lane per run, pinned for both arms

**What every result above actually ran on:** `ollama:deepseek-v4-flash:0731-cloud`
for both arms and every tier, temperature 0, seed 20260827, `attempts=1`. Free
Ollama Cloud tier, served through the local `:11434` endpoint.

| Role | Candidate | Lane | Cost |
|---|---|---|---|
| **SUT, as run** | `ollama:deepseek-v4-flash:0731-cloud` | Ollama Cloud | free tier |
| SUT alt, different family | `nvidia:nvidia/nemotron-3-nano-30b-a3b` | NIM cloud | free endpoint |
| SUT local control | `foundry-local:qwen2.5-coder-7b` (NPU) | Foundry Local | local |
| Judge, as run | `ollama:nemotron-3-ultra:cloud` | Ollama Cloud | free tier |

Rules that make the comparison mean anything:

- **Pick one lane per run and pin it for both arms.** A local SUT in Arm A and a
  cloud SUT in Arm B measures the models, not the workflows.
- **Judge from a different family than the SUT.** A model scoring its own
  family's output is a known self-preference bias. It gates nothing regardless
  (weight 0.0) until calibrated.
- **Disable reasoning or raise the token budget** on any thinking model first.
  Four NIM models return empty content with `done_reason: length` on a small
  budget and look dead when they are not — set `"think": false` where supported.
- **`model_override` does not confine a run to one model.** It only *prepends* to
  the candidate list; ARP's fallback chain still follows and contains paid
  providers. The only working control is deleting paid credentials from the child
  environment, which `run_ab.py` does.
- **A model id not already in ARP's registry cannot be used.**
  `agentic_v2/config/defaults/model_registry.yaml` is curated by deliberate human
  edit under ADR-040 — ids absent from it are rejected by `model_override`. Draft
  entries: [`models.candidate.yaml`](models.candidate.yaml).

Env: `OLLAMA_BASE_URL` / `OLLAMA_HOST` for local and Ollama Cloud,
`NVIDIA_API_KEY` for NIM (or `NVIDIA_BASE_URL` for self-hosted). Both are already
wired in ARP's `langchain/model_builders.py`. Full lane-by-lane detail, including
which endpoints are free and how to tell:
[docs/MODEL-PROBE-GUIDE.md](docs/MODEL-PROBE-GUIDE.md).

## Case sets

**Mined mutations** — [`dataset/CASES.md`](dataset/CASES.md). 132 cases across
four of our own repositories (evk 50, ek 37, arp 30, memoryctl 15), each a
verified mutation that makes a named real test fail. Every one replays before a
run. Ground truth is the hidden test suite; no gold-patch string comparison
anywhere, so two different correct patches both score 1.0.

**SWE-bench Verified** — 50 instance directories built so far, graded by the
official harness running each instance's real FAIL_TO_PASS and PASS_TO_PASS
suites inside a container. Retrieval is **oracle** — the model is told which file
to fix — so these are not leaderboard numbers.

Case data is gitignored and rebuilt by `tools/mine_cases.py` and
`tools/build_swebench_cases.py`; the directories are the source of truth and the
JSONL index is derived from them.

## Reading the result — the gotcha, stated up front

`agentic-evalkit compare arm_a.json arm_b.json` **refuses this comparison**, and
it is right to. `target_name` and `target_fingerprint` are non-waivable
provenance (ADR-0015); two different workflows are two different systems, so
`compare_runs` raises `IncompatibleRuns` rather than reporting a delta.

Do **not** work around it by giving both arms the same target name — that
launders a real difference past the gate and is the specific failure mode this
whole library exists to prevent. The honest read is a paired analysis over the
shared `sample_id`s: per-case hidden-test outcome, McNemar exact on the
discordant pairs, bootstrap CI on the paired difference, Wilson intervals on each
arm. That is [`analyze.py`](analyze.py).

**Power, before anyone quotes a number.** At 47 paired instances with 11
discordant pairs the interval is ±14 points; resolving a difference this size
needs ~200. The interval is the result, not the point estimate.

## How it runs

```bash
cd C:/Users/tandf/source/agentic-runtime-platform/agentic-workflows-v2/evals/swe_ab

# preflight — do not proceed unless this prints READY
uv run python -c "import sys; sys.path.insert(0,'.'); \
  from container_harness import container_preflight; print(container_preflight() or 'READY')"

# one wave: ~16 paired instances, both arms, ~50 min, pinned settings
uv run python tools/run_wave.py --wave N --size 16 --prune-images

# union every wave so far — one --left/--right pair per report
uv run python analyze.py --left reports/arm-a-direct-wave1.json \
                         --right reports/arm-b-review-loop-wave1.json
```

**Never pass `--model`, `--concurrency` or `--timeout`.** They are pinned in
`CAMPAIGN` inside `tools/run_wave.py` on purpose: two of this campaign's worst
errors were mid-experiment changes. Waves union soundly only while every wave
shares an arm, a model and a configuration — a wave needing different settings
is a different experiment. Full procedure:
[docs/WAVE-RUNBOOK.md](docs/WAVE-RUNBOOK.md).

**Process boundary:** `run_ab.py` runs in **EvalKit's** venv and imports only
`agentic_evalkit`; `bridge.py` runs in **ARP's** venv and imports only
`agentic_v2`. They meet over EvalKit's subprocess JSONL protocol — one process
per sample, one request line in, one response line out. Neither package ever
imports the other, which is what the dependency contract requires.

## What the campaign surfaced about the platform

Four findings that changed how the eval had to be built. The first is the one
that costs money; all four are worked up as a fix in
[docs/ARP-IMPROVEMENTS-PROMPT.md](docs/ARP-IMPROVEMENTS-PROMPT.md).

**1. ARP fails over to paid providers, and nothing turns it off.** When a step's
response misses its declared output contract, `_invoke_with_failover` walks the
tier chain — and on the first probe it reached Anthropic and returned a billing
error. `model_override` only *prepends*; the paid fallbacks still follow it. The
control used here is the child environment: `run_ab.py` deletes every paid
credential before spawning the bridge, so those candidates cannot be called at
all. Free by construction, not by promise — and the wrong layer for the fix.

**2. ARP discovers four of seven serving paths on this machine.** Lemonade
(`:13305`), Docker Model Runner (`:12434`) and Foundry Local (`:60160`) are not
probed at all, and no discovery path has any notion of which cloud endpoints are
free — NIM's catalogue is visible but its free-endpoint list is not. Both gaps
were filled by hand for this campaign.

**3. The coder agent tried to write into a live source tree.** Given file tools,
`tier2_coder` called `file_write` on a real checkout path, relative to the
inherited working directory. ARP's fail-closed approval governance denied it.
Two fixes, kept both: every step declares `tools: []`, and the bridge `chdir`s
into a sandbox first.

**4. Ask for the file, not a diff; inline the source.** The first contract asked
for a unified diff, which would have measured diff-formatting skill rather than
repair skill. And passing a file path made the result depend on whether the agent
had working file tools. Both arms now receive the source inline, byte-identical,
and return the complete corrected file.

## Status

Built and exercised end to end: both workflows, the rubric, the mining and
SWE-bench case builders, the ARP bridge, both grader stacks, the wave runner,
the advisory judge, and `analyze.py` (McNemar exact + paired bootstrap + Wilson
intervals).

Deliberately not built:

- **Calibration labelled set** — needed before the judge's weight can leave 0.0.
- **`attempts=3`** — would separate capability from sampling noise. It is a
  campaign change and must not be made mid-campaign.
- **Per-difficulty split** — the open hypothesis needs it, and it needs n ≈ 200.
- **In-flight progress** — `run_ab.py` prints only at the end. Wiring
  `EvalRunner.run(event_sink=…)` is the proper fix.
