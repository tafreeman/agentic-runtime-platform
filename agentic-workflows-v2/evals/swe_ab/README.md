# ARP SWE-fix A/B — two workflows, one rubric, free models

> **Result (2026-08-27):** Arm A (direct) 48/50 = 96.0%; Arm B (review loop)
> 45/50 = 90.0%. The gap is not statistically significant (McNemar p = 0.25,
> and p = 1.00 once operational timeouts are excluded), but Arm B cost 3.5× the
> wall clock — 37.0 min vs 10.7 min. Full write-up, caveats and the ceiling-effect
> problem: [RESULTS-2026-08-27.md](RESULTS-2026-08-27.md).

Compares two ARP orchestrations on the same software-repair task set, graded by
agentic-evalkit, using models that cost nothing (local Ollama, Ollama Cloud free
tier, NVIDIA NIM free tier).

| | Arm A | Arm B |
|---|---|---|
| Workflow | `workflows/swe_fix_direct.yaml` | `workflows/swe_fix_review_loop.yaml` |
| Steps | parse → patch | parse → root cause → draft → regression review → revise → verify |
| Agents | `tier0_parser`, `tier2_coder` | + `tier2_reviewer`, `tier1_analyzer`, `tier2_tester` |
| Inputs / outputs | identical | identical |
| Rubric | `swe_fix_v1` | `swe_fix_v1` |
| Model | pinned via `model_override` | **same id, same temperature, same seed** |

Everything except orchestration depth is held constant, so a score delta is
attributable to the review loop and nothing else. The question the run answers:
**does the review loop buy more hidden-test passes than it costs in tokens and
latency?**

## Grading stack — deterministic first, judge last

```
workflow output {patch, root_cause, verification_report}
        │
        ├── schema check ......... hard gate: the three fields exist and are strings
        ├── patch applies ........ hard gate: git apply --check at the pinned commit
        ├── tests untouched ...... hard gate: diff touches no tests/ or oracle path
        ├── hidden tests ......... hard gate: HarnessGrader → pytest on the oracle suite
        ├── public tests ......... hard gate: no regression against the pre-patch suite
        ├── diff budget .......... scored 0..1, not gating
        ├── AST safety scan ...... scored, not gating (no eval/exec/subprocess/network)
        └── rubric-bound judge ... weight 0.0, ADVISORY — records a verdict, moves nothing
```

The judge sits at weight 0.0 on purpose. Under EvalKit's ADR-0007 / D-1 an
uncalibrated judge cannot gate, and a judge on a free 8–30B model is emphatically
uncalibrated. To promote it later: label ≥30 good and ≥30 bad judge cases, run
`agentic-evalkit calibrate`, and only if TNR ≥ 0.95 / TPR ≥ 0.85 / age ≤ 90d hold
(Wilson lower bound, not the point estimate) does its weight move off zero.

Rubric: [`rubric.py`](rubric.py) — 8 atomic criteria, 6 decided by running code,
2 by the judge. Validated against EvalKit's `Rubric` model (weights sum to 1.0,
4 hard gates).

Eval set: [`dataset/CASES.md`](dataset/CASES.md) — mined from real `fix(...)`
commits in our own repos. Parent commit = broken repo, commit's tests = hidden
oracle, no gold-patch string comparison anywhere.

## Model matrix (all free)

Hold the system-under-test model constant across arms; use a **different family**
for the judge, because a model scoring its own family's output is a known
self-preference bias.

| Role | Candidate | Lane | Free? |
|---|---|---|---|
| SUT (both arms) | `nvidia:deepseek-ai/deepseek-v4-flash-0731` | NIM cloud | free endpoint |
| SUT alt | `nvidia:poolside/laguna-xs-2.1` | NIM cloud | free endpoint |
| SUT local | `ollama:qwen3-coder:30b` or `ollama:qwen3.5:27b` | local Ollama | free |
| SUT cloud alt | `ollama:kimi-k2.7-code`, `ollama:glm-5.3-flash` | Ollama Cloud | free tier |
| Judge | `nvidia:openai/gpt-oss-120b` | NIM cloud | free endpoint |
| Judge alt | `nvidia:nvidia/nemotron-3-super-120b-a12b` | NIM cloud | free endpoint |

Pick **one lane per run** and pin it for both arms. Mixing a local SUT in Arm A
with a cloud SUT in Arm B measures the models, not the workflows.

ARP's model registry (`agentic_v2/config/defaults/model_registry.yaml`) is
curated by deliberate human edit under ADR-040 — ids not already listed there
(`glm-5.3-flash`, `kimi-k2.7-code`, `gpt-oss`, `minimax-m3`, …) need an entry
added before `model_override` will accept them. Draft entries:
[`models.candidate.yaml`](models.candidate.yaml).

Env: `OLLAMA_BASE_URL` / `OLLAMA_HOST` for local, `NVIDIA_API_KEY` for NIM cloud
(or `NVIDIA_BASE_URL` for a self-hosted NIM). Both already wired in ARP's
`langchain/model_builders.py`.

## Reading the result — one gotcha, stated up front

`agentic-evalkit compare arm_a.json arm_b.json` **will refuse this comparison**,
and it is right to. `target_name` and `target_fingerprint` are non-waivable
provenance fields (ADR-0015); two different workflows are two different systems,
so `compare_runs` raises `IncompatibleRuns` rather than reporting a delta. That
gate exists to stop exactly the mistake of comparing runs that aren't comparable.

Do **not** work around it by giving both arms the same target name — that
launders a real difference past the gate and is the specific failure mode this
whole library exists to prevent.

The honest read is a paired analysis over the shared `sample_id`s, which is the
same arithmetic `compare_runs` does internally minus the same-system assumption:
per-case hidden-test outcome, McNemar on the discordant pairs, bootstrap CI on
the paired difference. That lands in `analyze.py` (not yet written).

Power, before anyone quotes a number: at 30 cases a paired A/B detects roughly a
22-point swing at 80% power. A 5-point difference on 30 cases is noise. Report
pass@1 and pass@3 side by side, split by `contamination_risk`, with cost and
wall-clock per arm — a review loop that wins by 3 points and costs 4× the tokens
lost.

## How it actually runs

```bash
# 1. build the eval set (no models involved; ~12 min for 50 cases)
python tools/mine_cases.py --repo evk --count 50 --fresh --path <scratch-worktree>

# 2. run an arm (from EvalKit's checkout, so uv resolves the right venv)
uv run python run_ab.py --arm a --concurrency 3
uv run python run_ab.py --arm b --concurrency 3

# 3. decide which scored higher
uv run python analyze.py
```

Process boundary: `run_ab.py` runs in **EvalKit's** venv and imports only
`agentic_evalkit`; `bridge.py` runs in **ARP's** venv and imports only
`agentic_v2`. They meet over EvalKit's subprocess JSONL protocol — one process
per sample, one request line in, one response line out. Neither package ever
imports the other, which is what the dependency contract requires.

## Four things the first run surfaced

**1. ARP fails over to paid providers.** When a step's response misses its
declared output contract, `_invoke_with_failover` walks the tier chain — and on
the first probe it reached Anthropic and returned a billing error. There is no
"no failover" switch. The control used here is the child environment:
`run_ab.py` deletes every paid credential (`ANTHROPIC_API_KEY`,
`OPENAI_API_KEY`, `GEMINI_API_KEY`, `GITHUB_TOKEN`, `OPENROUTER_API_KEY`, …)
before spawning the bridge, so those candidates cannot be called at all. Free
by construction, not by promise.

**2. The coder agent tried to write into EvalKit's source tree.** Given file
tools, `tier2_coder` answered by calling `file_write` on
`src/agentic_evalkit/stats/compare.py` — relative to the inherited working
directory, i.e. the live repo. ARP's fail-closed approval governance denied it.
Two fixes, kept both: every step declares `tools: []`, and the bridge `chdir`s
into a sandbox before running anything.

**3. Ask for the file, not a diff.** The first contract asked for a unified
diff. Models produce malformed diffs often enough that the run would have
measured diff-formatting skill instead of repair skill. Both arms now return
the complete corrected file and the harness computes the diff itself.

**4. Inline the source.** Passing a path made the result depend on whether the
agent had working file tools. The source now arrives inline, byte-identical to
both arms.

## Status

Built, and exercised end to end:
- [x] `workflows/swe_fix_direct.yaml` (Arm A) — loads in ARP, 1 step
- [x] `workflows/swe_fix_review_loop.yaml` (Arm B) — loads in ARP, 5 steps
- [x] `rubric.py` — `swe_fix_v1`, validates against EvalKit's `Rubric`
- [x] `tools/mine_cases.py` — **50 cases mined and verified**, every one a real
      mutation that makes a named EvalKit test fail
- [x] `bridge.py` — EvalKit subprocess protocol ↔ `WorkflowRunner.run(model_override=…)`
- [x] `graders.py` — pytest oracle harness + deterministic sanity gate
- [x] `run_ab.py` — smoke-tested 2/2 passed, full 50-case run executed
- [x] `judge_free.py` — advisory rubric judge on `nemotron-3-ultra:cloud`,
      smoke-tested; weight 0.0 and uncalibrated, so it gates nothing
- [x] `analyze.py` — McNemar exact + paired bootstrap + Wilson intervals

Not built (deliberately deferred):
- [ ] calibration labelled set — needed before the judge's weight can leave 0.0
- [ ] `BF` cases from real historical fix commits — only 6 qualify in EvalKit;
      the set is currently 50/50 `MUT`
- [ ] second and third source repos (EK, ARP) for case diversity
