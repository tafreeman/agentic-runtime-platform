# SWE-fix A/B — 132 cases, four repositories

Supersedes the 50-case run in `RESULTS-2026-08-27.md`. Same question, a case set
2.6× larger drawn from four repositories instead of one.

**Answer: unchanged. The direct arm scores higher on every reading, the gap is
still not statistically significant, and the review loop costs 3× the wall
clock.** Tripling the case count did not change the conclusion — it tightened
the interval and quadrupled the discordant pairs, and the answer held.

## Setup

| | |
|---|---|
| Cases | 132 — evk 50, ek 37, arp 30, memoryctl 15 |
| Verification | 132/132 replay correctly before the run |
| Arm A | `swe_fix_direct` — 1 step |
| Arm B | `swe_fix_review_loop` — 5 steps |
| Model | `ollama:deepseek-v4-flash:0731-cloud`, pinned to every tier, both arms |
| Temperature / seed | 0.0 / 20260827, attempts=1, concurrency=3 |
| Timeouts | A 300 s, B 600 s |
| Cost | zero — free endpoint, paid credentials deleted from the child env |

## Headline

| | Arm A (direct) | Arm B (review loop) |
|---|---|---|
| Pass rate | **125/132 = 94.7%** [89.5–97.4] | 120/132 = 90.9% [84.8–94.7] |
| Accuracy where both answered (n=127) | **123/127 = 96.9%** | 119/127 = 93.7% |
| Timeouts | 3 | 4 |
| Wall clock | **31.4 min** | 93.1 min |
| Median per case | **12.8 s** | 37.6 s |

## The paired read

Both solved 117, **only A** 8, **only B** 3, neither 4.

- Difference (B − A): **−3.8%**, 95% bootstrap CI **[−9.1%, +0.8%]**
- McNemar exact **p = 0.2266** on 11 discordant pairs
- Verdict-only (n=127): A-only 6, B-only 2, **p = 0.2891**

Eleven discordant pairs, up from three at n=50. The direction is stable and the
interval now barely crosses zero — but it does cross, so this is still not a
significant difference. **The interval is the result.**

## What changed from the 50-case run, and what did not

| | 50 cases | 132 cases |
|---|---|---|
| A | 96.0% | 94.7% |
| B | 90.0% | 90.9% |
| B − A | −6.0% | −3.8% |
| McNemar p | 0.25 | 0.23 |
| Discordant pairs | 3 | 11 |
| A's cost multiple | 3.5× | 3.0× |

Nothing reversed. More data narrowed the estimate and left the conclusion where
it was.

## Two process failures worth recording

**A broken oracle scored 15 cases as failed repairs.** memoryctl's cases carried
a bare `python -m pytest`, which resolves against the PATH of whoever runs it.
The miner ran under system Python 3.13 (has pytest); the grader runs under
`uv run`, whose managed 3.12.11 does not. All 15 failed with "No module named
pytest" while the sanity grader passed the model's source in the same breath.
Fixed twice over: absolute interpreters in the oracles, and the harness now
returns `UNAVAILABLE` rather than `resolved=False` when a run never reaches a
verdict — which is what ADR-0008 required all along.

**Fixing it mid-run created a confound.** The patch landed while Arm B was in
flight, so Arm B was graded with a working oracle and Arm A was not. That
produced an apparent 7.6-point win for Arm B which was entirely artefact: on the
117 cases graded identically, Arm A led by 4.3. Both arms were then re-run over
the 15 cases under identical code — both scored 15/15, making those cases
concordant and uninformative — and the union above is the comparable pair. The
lesson is narrow and real: **do not change grading rules while a comparison is
running**, even to fix a genuine bug.

## What this still does not show

**The ceiling did not lift.** At 94.7% the expanded set is no more discriminating
than the 50-case one was. memoryctl briefly looked like hard cases in Arm A's
column, but that was the broken oracle; with it fixed, every repo sits in the
88–97% band. Four repositories of single-operator mutations are still one kind
of case, and this model solves that kind almost always. To separate two
competent orchestrations the set needs cases the direct arm genuinely fails:
multi-hunk repairs, multi-file changes, or no failing-test hint.

The SWE-bench data already sitting in `~/.cache/huggingface/hub` — Verified,
Lite and full — is the obvious next source, and EvalKit already ships a
`swebench-verified@1` adapter and Docker harness for it.

**Still one model, one seed, one attempt.** `attempts=1` means per-case outcomes
carry sampling noise that a single pass@1 number hides.

**The judge still contributed nothing**, by design: weight 0.0, uncalibrated.

## Recommendation

1. Keep `swe_fix_direct` as the default for single-file defect repair — equal or
   better accuracy at a third of the wall clock.
2. Do not read this as "review loops don't work". Read it as: on defects a
   competent model one-shots, a review loop has nothing left to add and costs
   3× to discover that. The interesting test is defects it cannot one-shot.
3. Run SWE-bench Verified next. The data is local, the adapter exists, and the
   difficulty is in a different league.
