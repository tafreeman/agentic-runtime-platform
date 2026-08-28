# Evidence log — ARP SWE-fix A/B

[Kit](../README.md) · [Docs](README.md) — **findings**, append-only; the auditable record and the one running tally · lessons: [BEST-PRACTICES.md](BEST-PRACTICES.md)

Every run, every score, every defect found and fixed. Written so a result can be
audited without re-reading a transcript, and so no number here can be quoted
without its caveats attached.

**Question under test:** does ARP's multi-step review-loop workflow repair more
defects than a single coder call, at equal model and equal input?

**Answer so far:** no detectable difference on 47 paired SWE-bench instances
(McNemar p = 1.00), and the review loop costs 3–6× per case. An earlier apparent
lead for the direct arm did not survive harder cases.

---

## 1. Results, chronological

All runs: `ollama:deepseek-v4-flash:0731-cloud` for both arms, temperature 0,
seed 20260827, attempts 1. Cost zero — free endpoint, paid credentials removed
from the child environment.

### 1.1 Mutation cases, one repository

| date | n | Arm A (direct) | Arm B (review loop) | B−A | McNemar p | B cost |
|---|---|---|---|---|---|---|
| 2026-08-27 | 50 | **48/50 = 96.0%** | 45/50 = 90.0% | −6.0% | 0.25 | 3.5× |

3 discordant pairs. Write-up: `results/2026-08-27-mutations-50.md`.

### 1.2 Mutation cases, four repositories

| date | n | Arm A | Arm B | B−A | McNemar p | B cost |
|---|---|---|---|---|---|---|
| 2026-08-27 | 132 | **125/132 = 94.7%** | 120/132 = 90.9% | −3.8% | 0.23 | 3.0× |

11 discordant pairs. Composition: evk 50, ek 37, arp 30, memoryctl 15; all 132
verified to reproduce before the run. Arm A's figure is the union of
`arm-a-direct.json` (110/132, memoryctl oracle broken) with
`arm-a-direct-memoryctl.json` (15/15 after the fix). Write-up:
`results/2026-08-27-mutations-132.md`.

**Ceiling:** at ~95% for both arms this set cannot separate two competent
orchestrations. That is why the campaign moved to SWE-bench.

### 1.3 SWE-bench Verified, oracle retrieval

| run | n | Arm A | Arm B | note |
|---|---|---|---|---|
| floor check | 5 | 3/5 = 60% | — | model clears the floor |
| big-file probe | 1 | 1/1 | — | 103 KB file returned whole, resolved |
| set 1 — **invalid** | 35 | 25/35 | 18/35 | confounded, see §2.6 and §2.7 |
| set 1 — matched | 35 | **24/35 = 68.6%** | 21/35 = 60.0% | B−A −8.6%, p = 0.45 |
| wave 1 | 12 | 5/12 = 41.7% | **7/12 = 58.3%** | first wave Arm B wins |
| **union** | **47** | **29/47 = 61.7%** | 28/47 = 59.6% | **B−A −2.1%, p = 1.0000** |

Union discordance: 6 A-only, 5 B-only. Write-up: `results/2026-08-28-swebench-35.md`.

**The −8.6% at n=35 did not hold.** Twelve harder instances moved the point
estimate 6.5 points and balanced the discordant pairs. Wave 1's instances are
materially harder (Arm A 41.7% vs 68.6%) because the first set drew the
lowest-offset, smallest-patch instances.

This raises a hypothesis the campaign has **not** settled: the review loop's
value may be conditional on difficulty — nothing to add where the direct arm
already succeeds, something to add where it does not. Testing it needs the
per-difficulty split at a much larger n.

### 1.4 Cost, measured

| set | Arm A / case | Arm B / case | ratio |
|---|---|---|---|
| mutations (132) | 12.8 s | 37.6 s | 3.0× |
| SWE-bench (35) | 23.0 s | 136.6 s | 5.9× |

Arm B re-emits the whole file twice (draft, then revise), so the ratio grows
with file size.

### 1.5 Every report on disk

| report | n | pass | fail | err | timeout |
|---|---|---|---|---|---|
| `arm-a-direct.json` | 132 | 110 | 19 | 0 | 3 |
| `arm-b-review-loop.json` | 132 | 120 | 8 | 0 | 4 |
| `arm-a-direct-memoryctl.json` | 15 | 15 | 0 | 0 | 0 |
| `arm-b-review-loop-memoryctl.json` | 15 | 15 | 0 | 0 | 0 |
| `arm-a-direct-swebench-floor.json` | 5 | 3 | 2 | 0 | 0 |
| `arm-a-direct-bigfile-probe.json` | 1 | 1 | 0 | 0 | 0 |
| `arm-a-direct-swebench.json` *(invalid)* | 35 | 25 | 9 | 1 | 0 |
| `arm-b-review-loop-swebench.json` *(invalid)* | 35 | 18 | 16 | 1 | 0 |
| `arm-a-direct-swebench-c4.json` | 35 | 24 | 11 | 0 | 0 |
| `arm-b-review-loop-swebench-fixed.json` | 35 | 21 | 14 | 0 | 0 |
| `arm-a-direct-wave1.json` | 12 | 5 | 7 | 0 | 0 |
| `arm-b-review-loop-wave1.json` | 12 | 7 | 4 | 0 | 1 |

The two marked *invalid* are retained deliberately: they are the evidence for
the confounds in §2.6 and §2.7, and deleting them would erase the record of
why the matched pair had to be re-run.

---

## 2. Defects found and fixed

Each changed a number, or would have. Ordered by severity.

### 2.1 A grader that passed a benchmark it never ran — CRITICAL

The first SWE-bench floor check reported **5/5 passed**. The harness had
reported `UNAVAILABLE` on all five. `CompositeGrader` excludes
ABSTAIN/ERROR/UNAVAILABLE from its weighted mean — correct for an advisory
component, wrong for the authoritative one — so the sanity check alone carried
the score.

**Fix:** `SwebenchGrader` replaces the composite and sequences explicitly:
sanity failure → FAIL; harness cannot run → **UNAVAILABLE, never PASS**; harness
ran → its verdict. (`swebench_graders.py`)

### 2.2 An oracle that could not run scored 15 repairs as failures — CRITICAL

memoryctl cases carried a bare `python -m pytest`. The miner ran under system
Python 3.13 (has pytest); the grader runs under `uv run`, whose managed 3.12.11
does not. All 15 failed with "No module named pytest" — 0/15 while every other
repo sat at 93–95%.

**Fix, two layers:** absolute interpreters in the oracles and the miner; and the
harness now returns `UNAVAILABLE` when a run never reaches a verdict (missing
pytest, or pytest exit codes 2/3/4/5). ADR-0008 required the distinction; the
grader was not honouring it.

### 2.3 Arm B discarded its own repairs — HIGH

On 6 of 35 SWE-bench instances Arm B ran all five steps, **diagnosed the bug
correctly**, and returned the file byte-identical to the original.
`revise_repair` held both the draft and the untouched `source_code`, with the
instruction "if the review raised no risks, return the draft unchanged" —
ambiguous about which input to echo.

**Fix:** `source_code` removed from that step; it cannot echo what it cannot
see. Arm B went 18 → 21 resolved, unchanged-file returns 6 → 1.

### 2.4 The coder agent tried to write into a live repository — HIGH

Given file tools, `tier2_coder` called `file_write` on
`src/agentic_evalkit/stats/compare.py`, relative to the inherited working
directory — the real checkout. ARP's fail-closed approval governance denied it.

**Fix, two layers:** every workflow step declares `tools: []`, and `bridge.py`
`chdir`s into a sandbox before running anything.

### 2.5 ARP fails over to paid providers — HIGH

When a step's response misses its declared output contract,
`_invoke_with_failover` walks the tier chain. The first probe reached Anthropic
and returned a billing error. There is no off-switch.

**Fix:** `run_ab.py` deletes every paid credential from the child environment
before spawning, so those candidates cannot be called at all. Free by
construction, not by policy.

### 2.6 Grading rules changed mid-run — HIGH (process)

The memoryctl oracle fix landed while Arm B was in flight: Arm B was graded with
a working oracle, Arm A was not. That produced an apparent 7.6-point win for Arm
B which was entirely artefact.

**Fix:** both arms re-run over the affected cases under identical code before
the pair was quoted. **Rule: never change grading rules while a comparison is
running, however good the reason.**

### 2.7 Arms ran at different concurrency — HIGH (process)

SWE-bench set 1 ran Arm A at concurrency 1 and Arm B at 4 — the same class of
error as 2.6.

**Fix:** both re-run at concurrency 4. Campaign settings are now pinned in
`tools/run_wave.py` and deliberately not exposed as flags.

### 2.8 A miner pass deleted another repository's cases — MEDIUM

An `--append` patch silently failed to apply; the memoryctl pass overwrote
`cases.jsonl`, dropping 50 mined evk rows. The case directories survived.

**Fix:** `tools/rebuild_index.py` regenerates the index from the case
directories, idempotently. The directories are the source of truth; the JSONL is
derived.

### 2.9 A hung test blocked a mining pass for 20 minutes — MEDIUM

Mutating a comparison inside `executionkit/batches.py`'s retry loop makes its
suite hang rather than fail. Under a flat 150 s ceiling each such candidate cost
the full timeout; an EK pass produced 1 case in 20 minutes.

**Fix:** mutation runs are bounded at 10× the module's measured baseline, and a
hang is skipped explicitly as "not a usable oracle at any length". EK yielded
**37 cases** on the next pass.

### 2.10 Waves would have re-run existing instances — MEDIUM

Wave 1 at offset 0 drew exactly the instances the first hand-built set used — an
hour of work adding zero evidence.

**Fix:** the builder skips any instance that already has a case directory.
Non-overlap is a property of the data on disk, not of offset bookkeeping.

### 2.11 Smaller fixes

| defect | fix |
|---|---|
| Subprocess response omitted `sample_id`; every sample errored | echo it in `bridge.py` |
| A diff-returning contract measured diff formatting, not repair | workflows return the corrected file; the diff is computed for them |
| Passing a file path made results depend on agent tool access | source is inlined, byte-identical to both arms |
| Grading was hard-wired to one repository's worktree | one worktree per source repo, keyed by `source_repo`, with a lock each |
| A custom evaluator's report was not unwrapped | return `payload[instance_id]` — the default evaluator unwraps, a custom one must too |
| Django source was committed into ARP | `dataset/swebench_cases/` gitignored; the builder reproduces it |
| A 200-instance run would exhaust the disk | waves with `--prune-images` |

---

## 3. Standing caveats on every number above

1. **Oracle retrieval.** The model is told which file to fix. Full SWE-bench also
   requires finding it. **These are not leaderboard numbers.**
2. **Underpowered.** 47 paired instances with 11 discordant pairs cannot resolve
   a difference of this size; ~200 are needed at 80% power.
3. **One model, one attempt.** `attempts=1`; pass@1 hides per-case sampling noise.
4. **Contamination.** django is over half the SWE-bench set and the most
   represented Python repo in any training corpus. Cases are marked
   `contamination_risk: high`.
5. **Mutation cases are synthetic.** Real ground truth — a real test really fails
   — but not the distribution of human-written bugs.
6. **The judge contributed nothing**, by design: weight 0.0 and uncalibrated
   throughout (ADR-0007 / D-1).

---

## 4. Artefacts

| | |
|---|---|
| Branch | `swe_ab_evals` (agentic-runtime-platform) |
| Kit | `agentic-workflows-v2/evals/swe_ab/` |
| Reports | `reports/*.json`, one per arm per run |
| Case data | gitignored; rebuilt by `tools/mine_cases.py`, `tools/build_swebench_cases.py` |
| Environment requirements | `docs/TEST-SETUP.md` |
| Model probing procedure | `docs/MODEL-PROBE-GUIDE.md` |
| Continuing the campaign | `docs/WAVE-RUNBOOK.md` |
