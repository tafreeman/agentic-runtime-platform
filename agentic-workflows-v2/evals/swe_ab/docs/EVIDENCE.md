# Evidence log — ARP SWE-fix A/B

[Kit](../README.md) · [Docs](README.md) — **findings**, append-only; the auditable record and the one running tally · lessons: [BEST-PRACTICES.md](BEST-PRACTICES.md)

Every run, every score, every defect found and fixed. Written so a result can be
audited without re-reading a transcript, and so no number here can be quoted
without its caveats attached.

**Question under test:** does ARP's multi-step review-loop workflow repair more
defects than a single coder call, at equal model and equal input?

**Answer so far:** no detectable difference on 115 paired SWE-bench instances
(McNemar p = 1.00), and the review loop costs 3–6× per case. An earlier apparent
lead for the direct arm did not survive harder cases.

**Segment boundary, 2026-08-29 — read before extending any number below.**
Everything in §1.3 through wave 7, plus the hard-rated slice in §1.4 (135
instances total: 115 unioned + 20 standalone), was graded against the harness
as it existed before `PR #282` merged into `swe_ab_evals`'s upstream branch.
That merge landed a concurrent session's independent rewrite of `run_ab.py`,
`graders.py`, `rubric.py`, `swebench_graders.py`, `analyze.py`, `bridge.py`
and `mine_cases.py` — none of it reviewed against this session's results
before or after. The commit messages describe genuine correctness fixes
("decide the A/B on verdicts, and pin grading to the mined revision," "never
grade a sample the model under test did not produce," fingerprinting the
runtime/orchestration/grader) — precisely the class of defect this campaign
has caught twice before (§2.1, §2.3). Whether any of those fixes would have
changed any of the 135 instances below has **not** been checked. **Do not
union anything graded from wave 8 onward with the rows above** — new waves
run on the post-merge harness; this is a new segment, not a continuation.
Wave 8's cases were already built (§2.15/§2.16's `WAVE_MIX`/offset fixes,
which survived the merge intact) but never graded under the old harness, so
it cleanly opens the new segment rather than straddling the boundary.

---

## 1. Results, chronological

All runs: `ollama:deepseek-v4-flash:0731-cloud` for both arms, temperature 0,
seed 20260827, attempts 1. Zero marginal cost — a flat Ollama subscription
already paid for, capped by usage rather than billed per call (30% used after
a full week as of 2026-08-28), not a free-to-anyone endpoint. Paid credentials
removed from the child environment regardless.

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
| wave 2 | 12 | 6/12 = 50.0% | 7/12 = 58.3% | one django instance dropped from the target 16, see §2.12 |
| wave 3 | 8 | 5/8 = 62.5% | 6/8 = 75.0% | hit the offset/small-pool bug, not real exhaustion — see §2.13 |
| wave 4 | 12 | 6/12 = 50.0% | 6/12 = 50.0% | offset fix (§2.13) reached scikit-learn/matplotlib again; another django instance dropped, see §2.12 |
| wave 5 | 12 | 7/12 = 58.3% | 4/12 = 33.3% | graded concurrently with wave 6, see §2.14 |
| wave 6 | 7 | 3/7 = 42.9% | 4/7 = 57.1% | scikit-learn pool hit real, permanent exhaustion this wave — see §2.14 |
| wave 7 | 17 | 8/17 = 47.1% | 10/17 = 58.8% | first wave on the widened `WAVE_MIX` (§2.15), first wave with the encoding fix (§2.16) — 17/17 built, zero drops |
| **union — CLOSED at wave 7** | **115** | **64/115 = 55.7%** | 65/115 = 56.5% | **B−A +0.9%, p = 1.0000** |

Union discordance: 14 A-only, 15 B-only. Write-up: `results/2026-08-28-swebench-35.md`.
**This union is closed as of wave 7** — see the segment-boundary note above §1.
Wave 8 onward belongs to a new segment on the post-`PR #282` harness and gets
its own union table, not another row appended here.

**The −8.6% at n=35 did not hold.** Twelve harder instances moved the point
estimate 6.5 points and balanced the discordant pairs. Wave 1's instances are
materially harder (Arm A 41.7% vs 68.6%) because the first set drew the
lowest-offset, smallest-patch instances. Waves 2–7 have held close to dead
even, drifting slightly positive at wave 7. At n=115 — past the halfway point
to the ~200 target — the two arms remain statistically indistinguishable
(95% CI on B−A: [−8.7%, +10.4%]).

This raises a hypothesis the campaign has **not** settled: the review loop's
value may be conditional on difficulty — nothing to add where the direct arm
already succeeds, something to add where it does not. Testing it needs the
per-difficulty split at a much larger n. **Caution:** "harder" in the wave 1
sense above means *lower Arm A pass rate within the existing difficulty
bands* (`<15 min fix` / `15 min - 1 hour`), not SWE-bench's own difficulty
label. §1.4 tests the difficulty label directly, on a different slice, and
should not be read as confirming or refuting the wave 1 pattern — they are
measuring different things.

### 1.4 Difficulty split: the hard-rated slice, 2026-08-29

Every wave so far drew from `<15 min fix` and `15 min - 1 hour`. SWE-bench
Verified's `1-4 hours`/`>4 hours` labels are a separate, much smaller pool:
only 45 of the 500 instances are rated hard at all, and only 20 of those are
single-file (the case format requires exactly one target file — oracle
retrieval, per the standing caveat). **20 is the entire available population
at this difficulty**, not a sample of a larger one; every hard, single-file
instance in SWE-bench Verified is in this set. Patch length was uncapped to
reach all 20 (median 57 lines, max 474) — the only wave/set in this campaign
without the ≤40-line cap, because the hard pool barely exists under it (8
instances).

| set | n | Arm A | Arm B | B−A | McNemar p |
|---|---|---|---|---|---|
| hard-rated slice | 20 | 5/20 = 25.0% | 3/20 = 15.0% | −10.0%, 95% CI [−35.0%, +15.0%] | 0.7266 |

8 discordant pairs (5 A-only, 3 B-only), 0 solved by both arms. Both arms
score far below their difficulty-mixed rate (55.7%/56.5% at n=115) — 25%/15%
on genuinely hard cases is a real signal that the difficulty label tracks
something the model actually struggles with. The review-loop arm shows a
nonsignificant *disadvantage* here (opposite direction from wave 1's hint),
but n=20 with 8 discordant pairs cannot resolve a 10-point difference — this
is directional at best, not a finding. **Cost scales sharply with
difficulty:** median 448.9 s/case (Arm A) and 1010.2 s/case (Arm B), roughly
20× and 7× the difficulty-mixed medians (23.0 s / 136.6 s) respectively —
bigger files take longer to generate and Arm B's ratio compresses because
both arms' floor rises with file size, not because the review step gets
relatively cheaper.

**This is the entire hard-rated population, so it cannot grow.** Any further
depth on this hypothesis needs either the 25 hard multi-file instances
(requires redesigning the case format to hand the model more than one
file — a workflow-contract change, touching both the case builder and the
workflows themselves, not just which instances get sampled) or accepting
that "hard" stays an n=20, low-power probe in this campaign.

### 1.5 Cost, measured

| set | Arm A / case | Arm B / case | ratio |
|---|---|---|---|
| mutations (132) | 12.8 s | 37.6 s | 3.0× |
| SWE-bench, difficulty-mixed (35) | 23.0 s | 136.6 s | 5.9× |
| SWE-bench, hard-rated (20) | 448.9 s | 1010.2 s | 2.2× |

Arm B re-emits the whole file twice (draft, then revise), so the ratio grows
with file size — except at the hard-rated extreme, where both arms' floor
rises with file size and the ratio compresses rather than growing further
(§1.4).

### 1.6 Every report on disk

Regenerated 2026-09-02 from `reports/` (42 files, in start order) when
the campaign landed on `main`; each row is the report's own `summary` block.
`err` and `timeout` are operational non-verdicts (ADR-0008), never folded into
`fail`. Which rows may be unioned is governed by §1.3, §1.7-§1.9 and the
segment-boundary note above §1, not by this inventory.

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
| `arm-b-review-loop-swebench-fixed.json` | 35 | 21 | 14 | 0 | 0 |
| `arm-a-direct-swebench-c4.json` | 35 | 24 | 11 | 0 | 0 |
| `arm-a-direct-wave1.json` | 12 | 5 | 7 | 0 | 0 |
| `arm-b-review-loop-wave1.json` | 12 | 7 | 4 | 0 | 1 |
| `arm-a-direct-wave2.json` | 12 | 6 | 5 | 1 | 0 |
| `arm-b-review-loop-wave2.json` | 12 | 7 | 3 | 1 | 1 |
| `arm-a-direct-wave3.json` | 8 | 5 | 3 | 0 | 0 |
| `arm-b-review-loop-wave3.json` | 8 | 6 | 2 | 0 | 0 |
| `arm-a-direct-wave4.json` | 12 | 6 | 5 | 1 | 0 |
| `arm-b-review-loop-wave4.json` | 12 | 6 | 6 | 0 | 0 |
| `arm-a-direct-wave5.json` | 12 | 7 | 4 | 1 | 0 |
| `arm-b-review-loop-wave5.json` | 12 | 4 | 8 | 0 | 0 |
| `arm-a-direct-wave6.json` | 7 | 3 | 4 | 0 | 0 |
| `arm-b-review-loop-wave6.json` | 7 | 4 | 2 | 0 | 1 |
| `arm-a-direct-wave7.json` | 17 | 8 | 9 | 0 | 0 |
| `arm-b-review-loop-wave7.json` | 17 | 10 | 7 | 0 | 0 |
| `arm-a-direct-hard-slice.json` | 20 | 5 | 15 | 0 | 0 |
| `arm-b-review-loop-hard-slice.json` | 20 | 3 | 16 | 0 | 1 |
| `arm-a-direct-wave8.json` | 17 | 11 | 4 | 2 | 0 |
| `arm-b-review-loop-wave8.json` | 17 | 8 | 5 | 3 | 1 |
| `arm-a-direct-wave9.json` | 16 | 6 | 5 | 4 | 1 |
| `arm-b-review-loop-wave9.json` | 16 | 5 | 1 | 9 | 1 |
| `arm-a-direct-nim1.json` | 16 | 8 | 6 | 0 | 2 |
| `arm-a-direct-wave10.json` | 18 | 12 | 6 | 0 | 0 |
| `arm-b-review-loop-wave10.json` | 18 | 8 | 10 | 0 | 0 |
| `arm-b-review-loop-nim1.json` | 16 | 8 | 5 | 3 | 0 |
| `arm-a-direct-wave11.json` | 18 | 9 | 9 | 0 | 0 |
| `arm-b-review-loop-wave11.json` | 18 | 6 | 12 | 0 | 0 |
| `arm-a-direct-run3backfill.json` | 168 | 94 | 72 | 2 | 0 |
| `arm-a-direct-nimbackfill.json` *(arm A only, degraded endpoint — §1.8)* | 204 | 26 | 53 | 22 | 103 |
| `arm-a-direct-minimax1.json` | 204 | 59 | 140 | 4 | 1 |
| `arm-b-review-loop-minimax1.json` | 204 | 50 | 146 | 8 | 0 |
| `arm-a-direct-glm53.json` *(non-viable — §2.22)* | 204 | 0 | 0 | 204 | 0 |
| `arm-b-review-loop-glm53.json` *(non-viable — §2.22)* | 204 | 0 | 0 | 204 | 0 |

Retained deliberately, per WAVE-RUNBOOK rule 3: the two marked *invalid* are the
evidence for the confounds in §2.6 and §2.7; `arm-a-direct-nimbackfill.json`
(arm A only, 103 timeouts against a degraded free endpoint, §1.8) and the `glm53`
pair (204/204 errors on both arms, §2.22) are the record of why those tracks
stopped, not capability readings. Deleting any of them would erase the record of
why a re-run or a track change was needed.

### 1.7 SWE-bench Verified, new segment (post-`PR #282` harness)

Opens fresh per the segment-boundary note above §1 — not unioned with §1.3's
115 or §1.4's 20. Same question, same pinned `CAMPAIGN` settings, a rewritten
harness underneath.

**Sub-segmented again as of wave 10** — `analyze.py` itself refused to union
wave 8/9 with wave 10 (`target_fingerprint` differs:
`...@22e3ed974042` vs `...@20ace0a669f0`). Recorded at the time as Ollama
Cloud pushing a live update to `deepseek-v4-flash:0731-cloud`'s served
weights. **Corrected 2026-09-02 (§2.21):** the fingerprint hashes the model
*id* plus `workflows/<arm>.yaml` and `bridge.py`, and both values reproduce
byte-for-byte from `bridge.py` before and after the §2.18 fix (`aff74062`,
committed 19 minutes before wave 10 started; the YAMLs are identical across
it). The boundary is a harness change, which rule 2 makes a slice boundary
anyway, so the three slices stand — but they are harness slices, not
model-identity slices, and whether the served model ever changed is unknown.

**Naming, 2026-08-30 — "Run" replaces "wave N" as the unit that matters.**
The campaign's wave counter is a shared file-naming sequence across every
model-identity slice; it says nothing about which slice a wave belongs to,
and calling something "wave 11" implied 11 waves of continuity that never
existed for this specific model. From here: **Run 1** = the closed segment
(waves 1-7 + hand-built + hard-slice, pre-`PR #282` harness, 135 instances).
**Run 2** = fingerprint `22e3ed974042` (waves 8-9, 33 instances). **Run 3** =
fingerprint `20ace0a669f0` (waves 10-11 plus the backfill below), current
and active. Wave numbers keep incrementing for file-naming/non-overlap
purposes (`run_wave.py`'s mechanism), but every reading is reported by Run,
not by wave range, from here on.

**Run 3 backfilled toward ~200, 2026-08-30 — reusing Run 1 and Run 2's
already-mined instances.** These are stateless grading calls with no
fine-tuning or memory between runs (human-confirmed): an instance graded
under Run 1 or Run 2 carries zero information into a Run 3 call on the same
instance, so re-grading it under Run 3's current model is independent,
valid evidence for Run 3 — not contamination, not a repeat. `cases.swebench.run3-backfill.jsonl`
merges Run 1's 135 (`full.jsonl` + waves 1-7 + hard-slice) with Run 2's 33
(waves 8-9) into 168 unique instances, deliberately excluding only Run 3's
own wave 10/11 (36 instances, already graded under this exact model — no
reason to repeat them). This needed zero new mining: every instance's case
directory (repo checkout, patch) already existed on disk from when it was
originally built, so this is pure grading time, no docker pulls. Graded
directly via `run_ab.py` (bypassing `run_wave.py`'s mining path entirely,
same mechanism as the abandoned §2.19 reuse batch — the difference this
time is explicit direction to do exactly this). Once graded: Run 3 =
36 (wave 10-11) + up to 168 (backfill) = up to 204, comfortably past the
~200 target, contingent on the backfill batch's own fingerprint matching
wave 10/11's (checked before unioning, same discipline as §2.21).

| run | n | Arm A | Arm B | note |
|---|---|---|---|---|
| wave 8 | 17 | 11/17 = 64.7% | 8/17 = 47.1% | first wave graded on the merged harness; fingerprint `22e3ed974042` |
| wave 9 | 16 | 6/16 = 37.5% | 5/16 = 31.25% | narrowed `WAVE_MIX` (§2.17); fingerprint `22e3ed974042`, unions with wave 8 |
| **wave 8+9 union** | **33** | **17/33 = 51.5%** | **13/33 = 39.4%** | B−A −12.1%, 95% CI [−24.2%, −3.0%], McNemar p = 0.1250, 4 discordant |
| wave 10 | 18 | 12/18 = 66.7% | 8/18 = 44.4% | fingerprint `20ace0a669f0` — **does not union with wave 8/9** |
| wave 11 | 18 | 9/18 = 50.0% | 6/18 = 33.3% | django-consolidated `WAVE_MIX` (§2.20); same fingerprint as wave 10, unions with it |
| **wave 10+11 union** | **36** | **21/36 = 58.3%** | **14/36 = 38.9%** | **B−A −19.4%, 95% CI [−33.3%, −5.6%], McNemar p = 0.0391 — significant at n=36** |

Wave 8+9 paired: 13 both solved, 4 A-only, 0 B-only, 16 neither. Restricted
to the 18 cases where both arms reached a verdict: A 15/18 = 83.3%, B
13/18 = 72.2%, p = 0.5000. 15 excluded for no verdict on at least one arm.

**Wave 10+11 is the first statistically significant reading in this
campaign.** Paired: 13 both solved, 8 A-only, 1 B-only, 14 neither — 9
discordant pairs, McNemar p = 0.0391. Zero excluded cases in either wave
(36/36 real verdicts both arms — the cleanest reading this segment has
produced, consistent with §2.18's fallback-exclusivity fix landing before
either wave ran). Verified before recording: arm A's fingerprint matches
itself across wave 10 and 11 (`20ace0a669f0`), and arm B's matches itself
across both too (`ddf23322d15f`, deliberately different from A's —
different workflow, not a data problem; EvalKit's own comparability gate
flags exactly this every time and is not the check that governs whether a
union is valid, which is same-arm-across-waves fingerprint agreement).

**Read this cautiously despite crossing p < 0.05:** n=36 with 9 discordant
pairs is still a small sample by this campaign's own stated bar (~200
needed for real power, §3 below); a single further wave could move the
point estimate substantially, the way wave 1's early lead for the direct
arm didn't survive more instances (§1.3). It is nonetheless the first slice
in this campaign, closed or new, where the review loop's disadvantage is
distinguishable from noise rather than just directionally suggestive —
worth tracking closely as wave 10+11's own accumulation continues, not yet
worth calling a finding on its own.

**No single slice is n=200, or close.** Wave 8+9 (33) and wave 10+11 (36)
are each their own accumulation now, and neither compares to the closed
segment's 55.7%/56.5% even directionally — different harness, and now
different underlying model weights too.

### 1.8 NVIDIA NIM track — a separate provider, own segment (§2.19)

`nvidia:deepseek-ai/deepseek-v4-flash-0731`, free NIM endpoint, same two
workflows, its own quota entirely (relieves the Ollama weekly cap — see
§2.19 for why this exists). 16 fresh instances (`cases.swebench.nim1.jsonl`,
django only — mined quickly from the repo with the deepest remaining pool
rather than following `WAVE_MIX`, since this is a one-off probe wave, not
yet a repeating one).

| run | n | Arm A | Arm B | note |
|---|---|---|---|---|
| nim1 | 16 | 8/16 = 50.0% | 8/16 = 50.0% | first NIM-track wave |

Paired: 7 both solved, 1 A-only, 1 B-only, 7 neither. B−A +0.0%, 95%
bootstrap CI [−18.8%, +18.8%], McNemar exact p = 1.0000 (2 discordant
pairs). Restricted to the 13 cases where both arms reached a verdict: A
8/13 = 61.5%, B 8/13 = 61.5%, identical. 3 excluded for no verdict on at
least one arm — arm A 2 timeouts, arm B 3 errors, zero of either kind
crossing arms (operational, ADR-0008). Cost: arm A wall clock 29.7 min,
arm B 47.6 min, for 16 cases each.

**n=16, one wave, exactly tied — noise, not a finding.** Same caution as
every other slice above: this needs its own accumulation toward a
comparable n before the tie (or any future gap) means anything.

**204-instance backfill, arm A only, stopped 2026-08-30 — NIM's free
endpoint was severely degraded, not just slow.** Reused 204 previously-mined
instances from Run 1/2/3 (§2.19's backfill rationale — stateless grading,
no memory between runs). Arm A took over 8 hours and returned:

| run | n | Arm A | note |
|---|---|---|---|
| nim-backfill (arm A only) | 204 | 26/204 = 12.7% real passes | **103/204 = 50.5% timed out** — not a capability reading |

Only 79/204 (38.7%) reached a real verdict (26 passed, 53 failed); the
other 125 were operational failures (103 timeouts, 22 errors), never
folded into the task-failure count (ADR-0008) but dominating the sample
regardless. Verified this was real, ongoing work and not a hung process
before waiting it out: `py-spy dump --locals` on the live PID showed an
active `docker run` call mid-harness-evaluation; Docker's event log (short
retention window, but real-time) showed containers for different
instances cycling through create/start/kill/destroy; `vmmemWSL` was
holding 34.8 GB. All three independent signals agreed it was genuinely
working, just against a badly overloaded free endpoint. **Arm B stopped
before starting** (human-directed) rather than spend several more hours
for equally unreliable data — this arm-A-only result is kept on disk as
the evidence for why (rule 3, never delete a report), not unioned with
anything and not treated as a capability reading of the model.

### 1.9 OpenRouter free-tier track — minimax-m3

`openrouter:minimax/minimax-m3:free`, chosen after checking OpenRouter's
own benchmarks API (`/v1/benchmarks?task_type=coding`): highest real
coding/agentic score (58.6 / 36.1) among models actually reachable at the
time — `z-ai/glm-5.2:free` scored higher (68.8 / 45.7) but was persistently
rate-limited on OpenRouter's shared free pool (verified: 4 retries with
backoff, all 429), and `thinkingmachines/inkling[-small]:free` returned 403
("only available on agentic harnesses"), not usable via plain chat
completion. Same 204-instance backfill pool as the NIM attempt above.

| run | n | Arm A | Arm B | note |
|---|---|---|---|---|
| minimax1 | 204 | 59/204 = 28.9% | 50/204 = 24.5% | clean run, 5 and 8 non-verdicts respectively |

Paired: 26 both solved, 33 A-only, 24 B-only, 121 neither. B−A −4.4%, 95%
bootstrap CI [−11.8%, +2.9%], McNemar exact p = 0.2892 (57 discordant
pairs). Restricted to the 192 cases where both arms reached a verdict: A
57/192 = 29.7%, B 50/192 = 26.0%, p = 0.4188 — no significant difference.
Operational health: arm A `{completed: 201, timeout: 1, error: 2}`, arm B
`{completed: 197, error: 7}` — clean by this campaign's standards, unlike
the NIM attempt above.

**Notably weaker than the SUT model despite a similar benchmark score.**
minimax-m3's coding index (58.6) isn't far below deepseek-v4-flash's
(69.1), but its actual pass rate here (29.7% verdict-only) is well below
every Ollama-segment reading for the SUT model (51.5%–58.3% depending on
slice). A real gap between a general coding/agentic benchmark and this
specific harness's oracle-retrieval task, not a data-quality problem —
this run was clean.

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

### 2.12 A dependency that existed nowhere in the lockfile — MEDIUM, open

Wave 2 built **0/16** cases on its first attempt: `build_swebench_cases.py`
failed on every repo with `ModuleNotFoundError: No module named 'pandas'`
(needed to read the SWE-bench Verified parquet). `pandas` was absent from
every `pyproject.toml` and `uv.lock` in ARP — it had only ever existed as an
untracked, manually-installed package in the shared `.venv`. That venv is used
by many concurrent sessions; any of them running `uv sync` (or `uv run`,
which syncs implicitly) reconciles the venv exactly to the lockfile and drops
anything the lockfile does not know about.

**Fix:** `uv add pandas` in `agentic-workflows-v2/pyproject.toml`, so `uv.lock`
pins it and every future sync — on this machine or a fresh clone — keeps it.
Confirmed to survive a subsequent `uv run` from `evals/swe_ab`.

**2026-09-02, on landing to `main`:** pandas moved from the runtime dependency
set to a `swe-ab` extra (`agentic-workflows-v2/pyproject.toml`), since only
`build_swebench_cases.py` imports it. The lockfile still pins it, but a plain
exact `uv sync` without `--extra swe-ab` drops it again — so every runbook
command that builds cases now reads `uv run --extra swe-ab ...`, and
`TEST-SETUP.md` §2 says so.

Retrying wave 2 then hit a second, unrelated bug: `docker()` in
`build_swebench_cases.py` crashed with `TypeError: unsupported operand
type(s) for +: 'NoneType' and 'str'` on one django instance — a
`UnicodeDecodeError` in `subprocess.run` (no `encoding=` given, so Windows
defaulted to `cp1252` and raised on the first non-ASCII byte in that
instance's source) left `proc.stdout` `None`, and the `+` concatenation with
`proc.stderr` then raised. Recurred in waves 3-7, always on whichever
instance was first in a bucket's unbuilt ordering. Initially thought to just
drop one instance per wave; §2.16 found the real effect is worse (the
exception is unhandled, so it kills the *entire bucket's* allocation for that
wave, not one instance) and fixed it.

### 2.13 A shared offset outran small pools and looked like exhaustion — MEDIUM

Wave 3 built only 8/16 target cases. The scikit-learn and matplotlib
`15 min - 1 hour` buckets both returned **0** new instances, which read like
"pool exhausted" — the `WAVE-RUNBOOK.md` stopping condition for a wave under
~8 cases. It is not exhaustion.

`run_wave.py` computes `offset = (wave - 1) * 8` and passes the **same**
offset to every bucket in `WAVE_MIX` regardless of that bucket's size.
`build_swebench_cases.py` then does `pool.iloc[args.offset :]` — slicing by
position — **before** checking which instances already have a case directory.
scikit-learn's and matplotlib's filtered pools (single-file patches, ≤40
lines, matching difficulty) are only 13 rows each; wave 3's offset of 16 skips
past the entire pool before the already-built check ever runs. Verified
directly against the parquet: scikit-learn still has 4 unbuilt instances in
that bucket, matplotlib has 9. They are not gone — they are unreachable by
this offset scheme, and every later wave's larger offset makes it worse for
any pool smaller than the offset (sphinx's 21-row pool hits the same wall at
wave 4, sympy's 28-row pool at wave 5).

The `already`-built directory check (§2.10) already makes non-overlap a
property of the data on disk. `offset` was redundant for that guarantee and
actively harmful here: it could permanently strand real, unbuilt instances in
small pools.

**Fix, approved as a tooling change rather than a campaign change:** `offset`
in `tools/run_wave.py` is now pinned at `0` for every wave; the `already`-built
check alone provides non-overlap, regardless of pool size. This changes which
instances get *sampled* into future waves, not how any instance is graded —
the model, workflow, oracle and grader are untouched, and every already-graded
instance's result stands, so earlier waves stay unionable with later ones.

### 2.14 Real pool exhaustion, and a validated build-ahead + concurrent-grading path

**Real exhaustion, distinct from §2.13.** Wave 6 built only 7/16 target cases.
Checked directly against the parquet after the wave: scikit-learn's
`15 min - 1 hour` bucket is now genuinely at 0/13 remaining (fully built).
sympy, sphinx and matplotlib are each down to 3-4 remaining in their buckets.
Only django's two buckets still have real room (72 and 60 remaining). This is
the actual `WAVE-RUNBOOK.md` stop condition, not the offset bug — continuing
to draw waves as configured will increasingly skew toward django, which is
already flagged `contamination_risk: high`. `WAVE_MIX` needs a human decision
(widen to more repos, or accept a django-heavy tail) before wave 7.

**Concurrent grading, trialled and safe.** To speed up the campaign,
pre-built two waves sequentially with `run_wave.py --build-only` (avoids the
instance-selection race in §2.13, since building stays one-at-a-time), then
ran all 4 resulting grading jobs (wave 5 arm A/B, wave 6 arm A/B — 4 ×
concurrency-4 = 16 theoretical concurrent instance slots) at once. Measured
during the run: at most 2 instance-execution containers ever ran
simultaneously, host CPU stayed near ~18%, and RAM had >20 GB free throughout.
The real bottleneck is Ollama inference latency, not Docker/CPU — grading
wall-clock is dominated by waiting on the model, so container bursts from
different waves rarely overlap. All 4 jobs completed cleanly, no
`unavailable` verdicts, no errors attributable to contention. **Concurrent
grading across already-built waves is safe on this machine**; the risk was
always in the build phase, not the grading phase, and building sequentially
avoids it entirely.

### 2.15 WAVE_MIX widened, 2026-08-29 — a deliberate campaign change

§2.14 found real, permanent exhaustion (scikit-learn) and near-exhaustion
(sympy, sphinx, matplotlib). Checked five candidate repos against the parquet
(single-file patches, ≤40 lines, unbuilt) and pulled one real image per repo
to measure size rather than guess:

| repo | image size | usable pool |
|---|---|---|
| pydata/xarray | 7.57 GB | 15 (10 @ 15min-1hr, 5 @ <15min) |
| astropy/astropy | 4.16 GB | 17 (12 @ 15min-1hr, 4 @ <15min, 1 @ 1-4hr) |
| pylint-dev/pylint | 4.05 GB | 4 (1 @ 15min-1hr, 3 @ <15min) |
| pytest-dev/pytest | 3.84 GB | 13 (5 @ 15min-1hr, 8 @ <15min) |
| psf/requests | 3.81 GB | 8 (2 @ 15min-1hr, 6 @ <15min) |

**Change, approved by the user after reviewing pool depth and disk cost:**
`WAVE_MIX` in `tools/run_wave.py` drops scikit-learn (genuinely dry), keeps
sympy/sphinx/matplotlib at reduced weight so they drain naturally rather than
vanish abruptly, and adds astropy/xarray/pytest/requests/pylint sized to
their measured remaining depth. django's combined share falls from 40% to
27.5% of the nominal mix, which also reduces its dominance in a set already
`contamination_risk: high`. Nothing about the model, workflow, oracle,
grader, or concurrency changed — only which repos and difficulty buckets
future waves draw instances from.

**Why this stays unioned rather than starting a new campaign table:** the
paired McNemar analysis treats each instance as an independent paired
observation graded identically by both arms; it does not require the
sampling population to stay fixed across the whole campaign (the union
already blends "matched"/"invalid" sets, mutation cases, and multiple
difficulty tiers). Waves 1-6 drew from the pre-2026-08-29 mix; wave 7 onward
draws from this one. Both are unioned in §1.3 as before, with this entry as
the record of exactly where and why the population composition changed.

### 2.16 The encoding bug (§2.12) zeroed whole buckets, not one instance — fixed

Building wave 7 with the new mix (§2.15) got **zero** django cases from
either bucket — not one dropped instance, all of them. Root cause: the
exception from §2.12 is unhandled in `build_swebench_cases.py`'s per-instance
loop, so it kills the entire `subprocess.run` call for that repo/difficulty
before it writes any output — not "skip this instance, try the next." Because
`offset` is pinned at 0 (§2.13) and non-overlap depends on the `already`-built
check, a broken instance sitting first in a bucket's unbuilt ordering blocks
that whole bucket, on every wave, forever, since a bucket that always crashes
before writing its part file never gets `already` credit for anything past
the broken instance either.

`django__django-11999` (15 min-1 hour) and `django__django-13023` (<15 min
fix) hit this in every wave since the offset fix — wave 7 was the first time
*both* django buckets zeroed simultaneously, because wave 6 had built past
the previous first-in-line instances and landed on these two.

**Fix, approved by the user:** `docker()` now passes `encoding="utf-8",
errors="replace"` to `subprocess.run` instead of relying on the platform
default (`cp1252` on Windows). Verified: rebuilding wave 7 after the fix
built both previously-stranded instances successfully and reached the full
17/17 target with zero drops — a pure decoding fix, no change to which files
get selected or how they are graded.

### 2.17 WAVE_MIX narrowed again, 2026-08-29, wave 9 — sympy/sphinx/matplotlib/pylint dropped, django re-inflated

Wave 9 (the new segment opened at wave 8, §1.7) refused to run: `matplotlib`'s
`15 min - 1 hour` bucket yielded 0 of 1 cases. Measuring every `WAVE_MIX`
bucket against the real filter (single-file, ≤40-line patch, minus what's
already built) found it was not a one-bucket problem:

| repo / difficulty | pool | remaining |
|---|---|---|
| sympy/sympy 15min-1hr | 28 | **0 — exhausted** |
| sphinx-doc/sphinx <15min | 21 | **0 — exhausted** |
| matplotlib/matplotlib 15min-1hr | 13 | **0 — exhausted** |
| pylint-dev/pylint <15min | 3 | **0 — exhausted** |
| astropy/astropy <15min | 4 | 1 (thin) |
| pydata/xarray 15min-1hr | 10 | 4 (thin vs. weight 5) |
| pytest-dev/pytest 15min-1hr | 5 | 2 (thin vs. weight 3) |
| django/django (both buckets) | 173 | 120 |

Before dropping the four exhausted buckets, raising the patch-line cap was
measured as an alternative (up to 250 lines): sphinx-doc and pylint-dev stay
at exactly 0 regardless of cap — no single-file patch of any size remains
unbuilt for either — and sympy/matplotlib only recover +9/+3 respectively.
Not enough to justify changing what the patch-size cap tests, so the option
was declined.

**Change, approved by the user:** `WAVE_MIX` drops sympy, sphinx-doc,
matplotlib and pylint-dev outright (all confirmed permanently exhausted at
any patch size for their assigned difficulty bucket) and folds their combined
weight (7) into django, proportional to its existing 6:5 split (10:8).
django's share of the nominal mix rises to 45% — above the 40% it was
reduced from before wave 7 (§2.15), and knowingly so: the alternative
buckets are themselves mostly thin (see table above), and adding new repos
was considered and explicitly declined in favor of the simpler fix. Nothing
about the model, workflow, oracle, grader, or concurrency changed.

**Why this doesn't touch the closed segment or wave 8:** this is entirely
inside the segment opened at wave 8 (EVIDENCE.md's segment-boundary note
above §1). Wave 8 alone drew from the pre-2026-08-29 (wave 7) mix; wave 9
onward draws from this one. Both stay unioned in §1.7 the same way §2.15's
change stayed unioned within the closed segment's §1.3 — the paired McNemar
analysis doesn't require a fixed sampling population, only that each
instance is graded identically by both arms.

Six real case directories were left on disk from wave 9's aborted attempt (2
django × 2 buckets, 1 sympy, 1 sphinx) before it failed at matplotlib —
`run_wave.py` only deletes the temporary per-bucket JSONL slices on failure,
not the built case directories, so these are not wasted: the `already`-built
check (§2.10) means a future wave picks them up rather than re-building them.

### 2.18 A failed Ollama call could silently spend the operator's own Claude subscription — HIGH

Wave 9's arm B logged a 56% error rate (9/16) against wave 8's 23.5% (4/17,
run without concurrent load) — the two ran partly overlapping, and 7 of
wave 9's 9 errors carried the same stderr pattern: `Step ... response from
ollama:deepseek-v4-flash:0731-cloud failed declared output requirements;
failing over (1/N candidates tried)` followed by `model fallback: requested
'ollama:...' but 'anthropic:claude-sonnet-4-6-20260219' also answered;
refusing to grade a sample the model under test did not produce`.

`bridge.py`'s model-substitution check (the second message above) is working
exactly as designed: it inspects each executed step's real metadata and
refuses to grade any sample where a model other than the one under test
answered, converting it to a clean `target_failure` rather than a false
verdict. The *score* was never at risk. But tracing where the fallback
actually landed found the subprocess call had already completed by the time
that check fires. `anthropic:claude-sonnet-4-6-20260219` isn't reached
through a pay-per-call API key -- `agentic_v2/models/backends_claude.py`
documents this backend as authenticating via the Claude Code CLI's own
**subscription login**, specifically so it keeps answering with no API key
present (`_SIGN_IN_HINT`: "this backend authenticates with a Claude
subscription, not an API key"). `PAID_CREDENTIALS` in `run_ab.py` blanks
`ANTHROPIC_API_KEY` and `CLAUDE_CODE_OAUTH_TOKEN` in the child env, but
neither governs this backend's real credential path, so blanking them does
nothing to stop it. Every Ollama validation failure that falls through to
this candidate spends a live chunk of the operator's own Claude subscription
quota -- the same account running this campaign's sessions -- confirmed via
the Console's own dashboards: 0% used on every API-key-billed quota over
24h (so no pay-per-call billing occurred), but the Claude Code Max-plan
session/weekly usage páges showed real, non-trivial usage against the exact
window this campaign was running in.

Root cause: `AGENTIC_MODEL_TIER_{tier}` (already set for every tier in
`build_child_env`, specifically to prevent substitution) only *reorders*
`get_model_candidates_for_tier`'s output -- the function unconditionally
appends the registry's tier default and fallback chain after the pin
(`agentic_v2/langchain/models.py:796-800`), so a step whose call fails its
output contract falls through to them regardless. A cost-lane ceiling
(`AGENTIC_MAX_COST_LANE=free`) was tried and rejected first: measured
directly, `ollama:deepseek-v4-flash:0731-cloud` is not curated in the
registry at all and so resolves to `"paid"` under `model_registry.py`'s
fail-closed default -- the same lane as everything the ceiling was meant to
exclude, so it would have filtered out the model under test along with the
real fallback.

**Fix:** `bridge.py` now monkeypatches
`agentic_v2.langchain.models.get_model_candidates_for_tier` to return
*exactly* `[resolved_model_override]` when an override is given, no
registry default or fallback chain appended, before importing
`WorkflowRunner` -- ahead of `graph_wiring.py`/`graph.py` doing their own
`from .models import get_model_candidates_for_tier` and binding a stale
reference. Verified in a fresh subprocess: both modules' bound names resolve
to the patched function, and candidate resolution for any tier returns only
the pinned model. Because `bridge.py` is a fresh subprocess per sample
(EvalKit's subprocess protocol), this took effect for every sample not yet
started in an already-running wave, no restart needed.

### 2.19 A parallel NVIDIA NIM track, to relieve the Ollama weekly cap

The Ollama Cloud account's weekly usage reached 71.3% with a 20-hour reset
window remaining, and `deepseek-v4-flash:0731` alone logged 2557 requests
this week (dashboard-confirmed) -- the dominant consumer, but not the only
active one on the account (~40 unrelated python/ollama processes observed
running independent of this campaign). A single already-in-flight batch
(the §2.17-adjacent reuse-135 grading run) was independently estimated at
~10-11 hours at its observed pace, comparable to the reset window itself.

NIM was investigated earlier in this campaign as a **candidate second
lane**, not a substitute: equivalence-tested with proper token/timeout
budgets and found byte-identical to Ollama's output on the one case tested,
and `nvidia:deepseek-ai/deepseek-v4-flash-0731` is confirmed free
(`price_in`/`price_out`: 0.0) in `evals/swe_ab/models.candidate.yaml`'s
draft registry entry -- prepared but never applied (`ADR-040` reserves
`model_registry.yaml` for deliberate human curation). Re-verified live before
use: the raw NIM endpoint answers `deepseek-ai/deepseek-v4-flash-0731`
correctly, and `chat_template_kwargs: {"thinking": false}` suppresses
reasoning tokens (58 → 2 completion tokens on the same prompt) -- confirming
`model_builders.py`'s `NVIDIA_DISABLE_THINKING` fix (landed via `PR #282`)
works end to end.

`NVIDIA_API_KEY` lives in `.env` (workspace root and/or ARP's own), not the
shell -- `source`d inline per invocation rather than exported persistently,
since the Bash tool's shell state doesn't survive between commands anyway.
One more gap found before use: `PAID_CREDENTIALS` blanks `NVIDIA_API_KEY`
unconditionally, written under the assumption NVIDIA only ever appears as an
*unwanted* fallback (§2.18's `AGENTIC_API_KEY` comment), never as the model
under test. **Fix:** `build_child_env` now exempts a provider's own
credential vars (`_OWN_CREDENTIALS_BY_PREFIX`) from blanking when that
provider is the pinned model -- safe only in combination with §2.18's fix,
since that guarantees no *other* model can ever be reached in the same run
regardless.

This is a genuinely separate segment: switching provider is a configuration
change under this campaign's own pinning rules (`WAVE-RUNBOOK.md` rule 1),
same as a model change would be. NIM-graded instances get their own case
files, their own report suffix, and their own union table -- never merged
into either the closed (waves 1-7) or the new (wave 8+) Ollama segments.

### 2.20 WAVE_MIX consolidated on django, wave 10 -- every specialty bucket down to single digits

Wave 10 hit two more real exhaustions in a row (astropy's `15 min - 1 hour`
bucket, pool of 12, then 0 remaining) on top of §2.17/§2.19's fixes.
Re-measuring every remaining bucket found the pattern had generalized:
xarray (3), pytest (5) and requests (2) remaining, astropy (0) -- every
non-django repo has drained to single digits after ten waves against a
fixed population, while django alone still has 75 remaining across both
buckets. Repeatedly narrowing one bucket at a time as each empties in turn
was costing a wave each time. **Change:** consolidates hard on django
(36 of 40 nominal weight) and keeps xarray/pytest/requests at token
weight 1-2 each -- a "drain naturally, drop silently once empty" bonus
rather than buckets sized to recur. Also chose, alongside this campaign
work, to stop reusing the closed segment's 135 already-graded instances for
new-segment progress (the in-flight reuse batch from §2.19 was stopped at
70/135 arm A, human-directed) in favor of every new-segment wave drawing
strictly never-before-graded instances, matching the campaign's existing
non-overlap guarantee (§2.10) rather than an exception to it.

### 2.21 A fingerprint change mid-segment — recorded as a live Ollama model update, corrected 2026-09-02 to the §2.18 harness fix

`analyze.py` refused to union wave 8/9 with wave 10 on `target_fingerprint`:
`ollama:deepseek-v4-flash:0731-cloud@22e3ed974042` (waves 8-9) versus
`...@20ace0a669f0` (wave 10). Same model name, same tag, different served
weights — Ollama Cloud pushed an update to the `:0731-cloud` tag sometime
between the two runs, something no wave in this campaign controls or is
notified of. This is the same class of hazard as §2.6/§2.7 (grading rules
changed mid-run; arms run at different concurrency) but from a source
entirely outside this codebase: the *pin* was correct (`CAMPAIGN["model"]`
never changed), the thing pinned to changed underneath it.

No fix applies here beyond what already exists: the merged harness's
fingerprinting (`PR #282`) caught it automatically, and `analyze.py`
correctly refused to silently blend two systems into one union. The
practical consequence is the new segment is now three model-identity
slices rather than one (wave 8+9, wave 10, and whatever wave 11 turns out
to fingerprint as) — recorded in §1.7, not something to try to undo by
re-running earlier waves against the new weights, which would just as
easily drift again by the time it finished.

**Correction, 2026-09-02 (review finding on landing to `main`) — the
fingerprint change was the harness, not the model.** `run_ab.py`'s
`target_fingerprint()` hashes the model id plus `workflows/<arm>.yaml` and
`bridge.py` (the policy string in every manifest:
`model-id+sha256(workflow.yaml,bridge.py)[:12]`); it never sees the weights a
cloud tag serves. Recomputing it from git: `bridge.py` at `2f74f03a` (the
tree wave 9 ran on) gives `22e3ed974042` for arm A and `456965567edb` for
arm B; `bridge.py` at `aff74062` (the §2.18 fix, committed 2026-08-30T04:25Z,
19 minutes before wave 10's arm A started at 04:44Z) gives `20ace0a669f0`
and `ddf23322d15f` — exactly the four values in the reports, with both
workflow YAMLs byte-identical across that commit. The whole difference is
the `_pin_model_candidates_exclusively()` monkeypatch §2.18 added. Nothing
in this campaign shows Ollama Cloud updating `deepseek-v4-flash:0731-cloud`
between the two waves; that claim was an inference from the mismatch alone
and is withdrawn.

What stands: `analyze.py` was right to refuse the union — a bridge change
between waves is precisely the hazard `target_fingerprint()` exists to catch
(rule 2), so Run 2 (waves 8-9) and Run 3 (waves 10-11 plus the backfill)
remain separate slices. What changes: they are *harness* slices. A
provider-side weight update inside either slice would go unnoticed, because
nothing records the served model's identity (Ollama's `/api/show` digest and
`modified_at` for the tag, or the equivalent per provider). Capturing that
in the manifest is a harness change of its own and so opens a new slice; it
is proposed, not made, as of this correction. Until it exists, "check the
fingerprint before unioning" protects against harness and model-*id*
changes only, and TEST-SETUP.md / WAVE-RUNBOOK.md now say so.

### 2.22 GLM-5.3 and GLM-5.3-flash on Ollama Cloud — not viable at this campaign's scale

Tried as a fourth track (Ollama-served, same as the SUT model) after the
OpenRouter benchmarks API showed GLM-5.3 as the highest-scoring free-tier
coding model available (74.8 coding / 59.1 agentic). Three attempts, three
different failure modes, zero usable data:

1. **`ollama:glm-5.3`** (bare tag) — `model 'glm-5.3' not found (404)`.
   Ollama's cloud models need an exact tag; found via `ollama.com/library/
   glm-5.3/tags`: `glm-5.3:cloud`.
2. **`glm-5.3:cloud` at concurrency 4** — 122/204 `target_failure` (`timed
   out waiting for a concurrent request slot, 429`) plus 21 timeouts on arm
   A; arm B 204/204 errors (3x the calls per sample at the same
   concurrency compounded it further). Ollama caps concurrent slots per
   model, and GLM-5.3's cap is far below `deepseek-v4-flash:0731-cloud`'s,
   which took concurrency 4 all campaign without this class of failure.
3. **`glm-5.3:cloud` at concurrency 1** — 204/204 errors on the very first
   batch: `you (aifoundryaf) have reached your session usage limit (429)`.
   Confirmed via `ollama.com/pricing`: usage is metered in **tokens**, not
   requests, at each model's own rate — GLM-5.3 costs **~3.2-3.3x**
   `deepseek-v4-flash`'s per-token rate ($1.40/$4.40 vs $0.44/$1.32 per
   million input/output tokens), so the same call volume burns session
   quota far faster.

**Switched to `glm-5.3-flash:cloud`** on the same pricing table: cheaper
than the SUT model itself ($0.15/$0.50 vs $0.44/$1.32, ~0.34-0.38x) while
still scoring 71.5 coding / 58.2 agentic — barely behind GLM-5.3 proper.
Ran ~23 hours at concurrency 4 without erroring, but the account's own
cloud-usage dashboard showed only **39 requests** logged for
`glm-5.3-flash` in that entire window (`ollama.com` → Cloud usage →
"Models used this week") — roughly one request per 35 minutes, with
session usage sitting at a mere 21.8% (not quota-exhausted). Confirmed via
process inspection this wasn't a hung process (fresh `bridge.py`
subprocesses were spawning every few minutes, staying alive with non-zero
CPU) — the requests that did go out were each taking an extremely long
time to be served, consistent with server-side pacing/throttling on this
specific model rather than a client-side failure. **Stopped, arm A never
completed.** Neither GLM-5.3 nor GLM-5.3-flash produced usable data;
whether this throttling is specific to this account, this model, or
Ollama Cloud generally is unknown — not investigated further given the
time already sunk.

## 3. Standing caveats on every number above

1. **Oracle retrieval.** The model is told which file to fix. Full SWE-bench also
   requires finding it. **These are not leaderboard numbers.**
2. **Underpowered.** 115 paired instances with 29 discordant pairs cannot resolve
   a difference of this size; ~200 are needed at 80% power.
3. **One model, one attempt.** `attempts=1`; pass@1 hides per-case sampling noise.
4. **Contamination.** django is over half the SWE-bench set and the most
   represented Python repo in any training corpus. Cases are marked
   `contamination_risk: high`.
5. **Mutation cases are synthetic.** Real ground truth — a real test really fails
   — but not the distribution of human-written bugs.
6. **The judge contributed nothing**, by design: weight 0.0 and uncalibrated
   throughout (ADR-0007 / D-1).
7. **Served-model identity is unrecorded.** `target_fingerprint` covers the
   model *id* and the local harness (`workflows/<arm>.yaml`, `bridge.py`),
   not the weights a cloud tag serves; a provider-side update inside a slice
   would go unnoticed (§2.21 correction).

---

## 4. Artefacts

| | |
|---|---|
| Branch | `main` (agentic-runtime-platform) — the campaign branches `swe_ab_evals`/`eval_ledger` landed 2026-09 via PR #282 (squash, through wave 7's harness) and the follow-up campaign PR |
| Kit | `agentic-workflows-v2/evals/swe_ab/` |
| Reports | `reports/*.json`, one per arm per run |
| Case data | gitignored; rebuilt by `tools/mine_cases.py`, `tools/build_swebench_cases.py` |
| Environment requirements | `docs/TEST-SETUP.md` |
| Model probing procedure | `docs/MODEL-PROBE-GUIDE.md` |
| Continuing the campaign | `docs/WAVE-RUNBOOK.md` |
