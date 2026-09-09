# Campaign closeout — ARP SWE-fix A/B, 2026-09

[Kit](../README.md) · [Docs](README.md) — **closeout**, written 2026-09-05 to
record the campaign as closed. Read this before extending any number in
[EVIDENCE.md](EVIDENCE.md) or starting a new wave.

> **This campaign is closed.** No more waves run under `swe_ab`'s current
> `CAMPAIGN` pinning. A new benchmark, dataset, model, `attempts=3`, or
> difficulty-split redesign is a **new campaign**, per
> [BEST-PRACTICES.md §1](BEST-PRACTICES.md#1-design-the-comparison-so-a-delta-is-attributable)
> and [WAVE-RUNBOOK.md rule 2](WAVE-RUNBOOK.md#rules-that-keep-waves-unionable) —
> neither permits grafting a change onto a live comparison.

---

## 0. Housekeeping note — the README headline is stale, this document is not a fix for it

[`README.md`](../README.md) (file mtime 2026-08-28, unchanged since) still
banners **47 paired SWE-bench instances, B−A −2.1%, p = 1.00**. That figure is
the sum of set-1-matched (35) + wave 1 (12) — a mid-Run-1 checkpoint. It
predates waves 2–7, the hard-rated difficulty slice, the entire post-`PR #282`
segment (Run 2, Run 3), the NIM track, the OpenRouter/minimax track, and the
GLM-5.3 attempts. Every other doc in this kit that narrates results —
`EVIDENCE.md`, `BEST-PRACTICES.md`, `WAVE-RUNBOOK.md`, `TEST-SETUP.md`,
`PROVIDERS.md`, `SUBAGENT-PROMPT.md` — carries a 2026-09-02 mtime (the `PR
#282` + follow-up landing to `main`) and reflects the fuller record below.
**Treat `EVIDENCE.md` and `WAVE-RUNBOOK.md` as authoritative over `README.md`**
until someone refreshes the README's banner and "Three case sets, one answer"
table. This closeout does not edit `README.md` — out of scope for this
task — it only records that the gap exists so a future analyst doesn't
silently inherit the stale number.

---

## 1. Final state — the numbers, as segmented on disk

Per [BEST-PRACTICES.md §1](BEST-PRACTICES.md), a harness or workflow change
mid-comparison starts a new segment; segments do not union. The campaign
produced several, none individually reaching the ~200-paired-instance target.

| segment | n | Arm A | Arm B | B−A | McNemar p | note |
|---|---|---|---|---|---|---|
| **Run 1 — closed**, pre-`PR #282` harness, waves 1-7 + hand-built | 115 | 64/115 = 55.7% | 65/115 = 56.5% | +0.9% | **1.0000** | largest, cleanest slice; 29 discordant pairs (14 A-only, 15 B-only) |
| Run 1, hard-rated slice — entire available hard, single-file population | 20 | 5/20 = 25.0% | 3/20 = 15.0% | −10.0% | 0.7266 | 95% CI [−35.0%, +15.0%]; population cannot grow under current case format |
| Run 2 — post-merge harness, fingerprint `22e3ed974042`, waves 8-9 | 33 | 17/33 = 51.5% | 13/33 = 39.4% | −12.1% | 0.1250 | 95% CI [−24.2%, −3.0%]; own slice, not unioned with Run 1 |
| Run 3 — fingerprint `20ace0a669f0`, waves 10-11 | 36 | 21/36 = 58.3% | 14/36 = 38.9% | **−19.4%** | **0.0391** | 95% CI [−33.3%, −5.6%]; first (only) significant reading in the campaign, at n still far below the power target |
| Run 3 backfill — Arm A only, n=168 | 168 | 94/168 = 56.0% (as-graded); 94/125 = 75.2% conditional on a patch being emitted | — no Arm B report exists — | — | — | single-arm capability/harness-health run; produces **no paired verdict**; see §3 |
| NIM track (`nvidia:deepseek-ai/deepseek-v4-flash-0731`) | 16 | 8/16 = 50.0% | 8/16 = 50.0% | 0.0% | 1.0000 | 95% CI [−18.8%, +18.8%]; exact tie, own segment (different provider) |
| NIM 204-instance backfill, Arm A only | 204 | 26/204 = 12.7% real pass, 103/204 = 50.5% timed out | not run | — | — | degraded free endpoint; not a capability reading (§1.8) |
| OpenRouter minimax-m3 track | 204 | 59/204 = 28.9% | 50/204 = 24.5% | −4.4% | 0.2892 | 95% CI [−11.8%, +2.9%]; clean run, 57 discordant pairs |
| GLM-5.3 / GLM-5.3-flash (Ollama Cloud) | 204×3 attempts | — | — | — | — | **non-viable**: 404/quota/throttling across three configurations, zero usable data (§2.22) |

The **four standing caveats** (BEST-PRACTICES.md §8 / EVIDENCE.md §3) bind to
every row above, without exception:

1. **Oracle retrieval, not a leaderboard number.** The model is told which
   file to fix.
2. **Underpowered.** No segment above reaches the ~200-paired-instance target;
   even Run 1's 115 (the largest) needs ~200 to resolve a difference at this
   scale — see [BEST-PRACTICES.md §2](BEST-PRACTICES.md#2-build-the-case-set-for-discrimination-not-for-a-good-looking-number)'s
   power table.
3. **One model, one attempt.** `attempts=1` throughout; pass@1 hides
   per-case sampling noise.
4. **Contamination-prone.** django is the dominant repo in every SWE-bench
   slice; cases carry `contamination_risk: high`.

---

## 2. The decision this campaign supports

**No detectable difference between direct and review-loop orchestration at
this model/n.** Run 1 — the largest, cleanest, pre-merge slice (n=115,
p=1.0000) — is a dead heat, and Arm B costs 3–6× per case for it. **Do not
adopt the review loop wholesale.**

The three smaller post-merge segments (Run 2, Run 3, and to a lesser extent
the minimax track) all point the same direction — Arm A ahead — with Run 3
crossing p<0.05 at n=36. This is worth noting, not worth re-litigating: every
one of those segments is smaller and less powered than Run 1 already was, and
the campaign's own caution (EVIDENCE §1.7) is that "a single further wave
could move the point estimate substantially, the way wave 1's early lead for
the direct arm didn't survive more instances." Treat the directional
consistency as a mild prior for a follow-on campaign to test at power, not as
a finding that overturns "no detectable difference."

**The one thing worth carrying forward: the open, untested hypothesis that
the review loop may help specifically where the direct arm fails.** Wave 1's
harder instances went A 41.7% / B 58.3% (EVIDENCE §1.3) — the single slice,
anywhere in the whole campaign, where Arm B led. This is untested at adequate
power. Two partial, inconclusive attempts to probe it exist and should not be
read as answering it:

- The hard-rated slice (§1.4, n=20 — the entire available hard, single-file
  population) points the *opposite* direction (B −10.0%, p=0.7266,
  non-significant) — but it measures SWE-bench's own difficulty label, a
  different thing from "instances where the direct arm happens to fail,"
  per EVIDENCE.md's own caution not to read the two as confirming or
  refuting each other.
- The Run 3 backfill (`docs/results/2026-08-30-run3-backfill-168.md` §3)
  found the unconditional difficulty gradient is real (Cochran–Armitage
  p=0.005) but is substantially carried by Arm A's own failure-to-emit-a-patch
  rate rather than by wrong fixes — conditioning on emission, the gradient
  is no longer statistically distinguishable. This is single-arm evidence
  (no Arm B counterpart) and cannot speak to the review-loop question
  directly, but it complicates any future difficulty-split design: a naive
  per-difficulty split must control for patch-emission rate, not just pass
  rate.

---

## 3. What's explicitly NOT resolved / deferred to a next campaign

Verbatim from `README.md`'s "Deliberately not built" list, corrected where
this closeout found the state had moved since:

- **Calibration labelled set** — still not built. Needed before the judge's
  weight can leave 0.0 (ADR-0007/D-1: TNR ≥ 0.95, TPR ≥ 0.85, age ≤ 90d on
  the Wilson lower bound). The judge remains uncalibrated and advisory
  throughout every segment above.
- **`attempts=3`** — still not built. Would separate capability from sampling
  noise; explicitly flagged in both `README.md` and `WAVE-RUNBOOK.md` as a
  *campaign* change that must not be made mid-campaign.
- **Per-difficulty split — corrected: partially attempted, not resolved.**
  The README's original framing ("needed, and needs n≈200") undersells what
  happened: §1.4's hard-rated slice *is* a difficulty split, run against the
  entire available hard, single-file population (n=20 — not a sample, the
  whole population under the current one-file case format). It cannot grow
  without redesigning the case builder and both workflows to hand the model
  more than one file (the 25 hard multi-file instances are off-limits under
  oracle retrieval's current single-file contract). The open hypothesis
  (review loop helps where direct fails) remains untested at adequate power
  either way.
- **In-flight progress visibility** — still not built. `run_ab.py` prints
  only at the end; `EvalRunner.run(event_sink=…)` (exists at
  `agentic_evalkit/runner.py:220`, already used by the EvalKit CLI) is the
  proper fix and is explicitly ARP-improvements F6 — belongs to the eval kit,
  not ARP.
- **Run 3's backfill never reached a paired ~200.** Not previously listed
  anywhere as a gap — found in this closeout's audit. Arm A's backfill ran
  (168 instances, `reports/arm-a-direct-run3backfill.json`); no
  `arm-b-review-loop-run3backfill.json` was ever produced, so Run 3 has no
  paired verdict past wave 10-11's n=36. A next campaign resuming this track
  would need to run Arm B over the same 168-instance pool under Run 3's
  fingerprint before any backfilled union is quotable.
- **Served-model identity is unrecorded** (EVIDENCE §3 caveat 7 / §2.21).
  `target_fingerprint` hashes the model id and local harness, not the weights
  a cloud tag actually serves; a provider-side update inside a slice would go
  unnoticed. Proposed, not implemented.

From [`ARP-IMPROVEMENTS-PROMPT.md`](ARP-IMPROVEMENTS-PROMPT.md) — a live work
order against **agentic-runtime-platform**, unaddressed as of this closeout:

- **F1 (high, costs money).** ARP's failover walks into paid providers on a
  contract miss; `model_override` only prepends, the paid fallback chain
  still follows. Only working control is deleting paid credentials from the
  child environment — a workaround in the eval kit, not a fix in ARP.
- **F2.** ARP's discovery covers 4 of 7 serving paths on this machine (misses
  Lemonade, Docker Model Runner, Foundry Local); no cost-lane concept exists,
  so a cost-aware routing decision isn't possible even in principle. NIM's
  free-endpoint list is curated by hand for this campaign only.
- **F3.** No `verify=True` completion-based health check; a model that lists
  is not a model that answers (empty reasoning-token responses, cold-start
  timeouts, load failures all currently misread as available/unavailable).
- **F4.** Every `price_in`/`price_out` in the model registry is `null` —
  ARP cannot estimate run cost itself.
- **F5.** `model_override` promises confinement to one model and doesn't
  deliver it; silent substitution is invisible without inspecting
  `attempted_models`.
- **F7.** No shared vocabulary or shared discovery code across the
  portfolio — ARP, the eval kit, and EvalKit each hand-roll their own
  probing, and the same wrong assumption ("Lemonade is on :8000") was made
  twice for lack of one.

---

## 4. Where the evidence lives

A future analyst should be able to re-derive every number above without
re-running anything:

| what | where |
|---|---|
| Full incident/defect log, results tables, standing caveats | [`EVIDENCE.md`](EVIDENCE.md) — §1 for results, §2 for defects, §3 for caveats |
| Per-set/per-wave write-ups | [`docs/results/`](results/): `2026-08-27-mutations-50.md`, `2026-08-27-mutations-132.md`, `2026-08-28-swebench-35.md`, `2026-08-30-run3-backfill-168.md` |
| Raw run reports, one per arm per run/wave | `reports/*.json` — inventoried in [EVIDENCE.md §1.6](EVIDENCE.md#16-every-report-on-disk) (42 files as regenerated 2026-09-02); never delete one, including the two marked *invalid* (rule 3) |
| Case-set documentation | [`dataset/CASES.md`](../dataset/CASES.md) |
| Per-wave/per-set case indices | `dataset/cases.swebench*.jsonl` (`wave1`–`wave11`, `full`, `hard-slice`, `nim1`, `nim-backfill`, `run3-backfill`) |
| Case directories — the actual source of truth | `dataset/cases/`, `dataset/swebench_cases/` (gitignored; rebuilt by `tools/mine_cases.py`, `tools/build_swebench_cases.py`) |
| Paired-analysis tool | [`analyze.py`](../analyze.py) — McNemar exact, paired bootstrap CI, Wilson intervals; reproduces every table in §1 above from the reports already on disk |
| Operational procedure, if a next campaign resumes this track | [`WAVE-RUNBOOK.md`](WAVE-RUNBOOK.md), [`TEST-SETUP.md`](TEST-SETUP.md) |

---

## 5. Closure

**This campaign is closed.** Its question — does ARP's review-loop workflow
repair more defects than a single coder call, at equal model and equal
input — has a settled interim answer (no detectable difference, Run 1,
n=115, p=1.0000) and an unsettled follow-on hypothesis (conditional benefit
on hard instances) that no segment here reached adequate power to test.

Per BEST-PRACTICES.md's own rule against grafting a change onto a live
comparison: **no further waves run under `swe_ab`'s current `CAMPAIGN`
pinning.** Any of the following opens a **new** campaign, with its own
segment boundary and its own accumulation from zero — none of it unions with
anything recorded above:

- a calibrated judge promoted off weight 0.0;
- `attempts=3`;
- a redesigned case format supporting multi-file instances (needed for a
  real per-difficulty split past n=20);
- a different model, provider, or benchmark;
- any change to the workflows, oracles, grader, or rubric.
