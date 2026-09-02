# Wave runbook — continuing the campaign

[Kit](../README.md) · [Docs](README.md) — **operational** · prerequisite: [TEST-SETUP.md](TEST-SETUP.md) §1 · caveats: [EVIDENCE.md §3](EVIDENCE.md#3-standing-caveats-on-every-number-above)

For an agent picking this up cold. Read `TEST-SETUP.md` §1 first and confirm
preflight says `READY`.

---

## The job

Accumulate paired SWE-bench instances until the A/B can answer its question.
Each wave is ~16 instances, ~50 minutes, both arms, self-contained.

| | |
|---|---|
| Banked (closed segment, waves 1-7) | 115 paired instances |
| Banked (new segment, waves 8+9, fingerprint `22e3ed974042`) | 33 paired instances |
| Banked (new segment, waves 10+11, fingerprint `20ace0a669f0`) | 36 paired instances |
| Target | ~200 per model-identity slice (not the closed segment) |
| Current reading (closed segment) | A 55.7%, B 56.5%, B−A +0.9%, **p = 1.00** |
| Current reading (wave 8+9) | A 51.5%, B 39.4%, B−A −12.1%, **p = 0.125** |
| Current reading (wave 10+11) | A 58.3%, B 38.9%, B−A −19.4%, **p = 0.0391 — first significant reading, n still small** |

**Wave 8 opened a new segment; wave 10 opened a second one inside it.** The
harness (`run_ab.py`, `graders.py`, `rubric.py`, `swebench_graders.py`,
`analyze.py`) changed underneath waves 1-7 via a concurrent session's
`PR #282` — that's the wave-8 boundary. Between wave 9 and wave 10, Ollama
Cloud pushed a live update to `deepseek-v4-flash:0731-cloud`'s served
weights (EVIDENCE.md §2.21) — `analyze.py` itself refuses to union runs
with different `target_fingerprint`s, so wave 10 is now its own slice.
**Before unioning any new wave, check its `manifest.target_fingerprint`
against the slice you're adding it to** (`grep target_fingerprint` on the
report JSON) rather than assuming same-model-name means same model.

---

## One wave

```bash
cd C:/Users/tandf/source/agentic-runtime-platform/agentic-workflows-v2/evals/swe_ab
uv run --extra swe-ab python tools/run_wave.py --wave <N> --size 16 --prune-images
```

`<N>` = highest existing `dataset/cases.swebench.wave*.jsonl` number, plus 1.
The number is for naming only — overlap prevention comes from the builder
skipping instances that already have a case directory.

Takes ~50 min. Produces `reports/arm-a-direct-wave<N>.json` and
`reports/arm-b-review-loop-wave<N>.json`.

---

## After each wave

Union everything **in the new segment only** (wave 8 onward — never mix in
the closed segment's `swebench-c4`/`swebench-fixed`/wave1-7 reports, see the
segment-boundary note above):

```bash
uv run python analyze.py \
  --left  reports/arm-a-direct-wave8.json \
  --left  reports/arm-a-direct-wave<N>.json \
  --right reports/arm-b-review-loop-wave8.json \
  --right reports/arm-b-review-loop-wave<N>.json
```

Add one `--left`/`--right` pair per wave. Append the result to the table in
`EVIDENCE.md` §1.7: n, both arms' rates, B−A, CI, McNemar p, discordant pairs.

---

## Rules that keep waves unionable

1. **Never pass `--model`, `--concurrency` or `--timeout`.** They are pinned in
   `CAMPAIGN` in `tools/run_wave.py`. Waves union only while every wave shares an
   arm, a model and a configuration.
2. **Never change grading rules, workflows or oracles mid-campaign.** If a fix is
   needed, it starts a *new* campaign: earlier waves cannot be unioned with later
   ones. This rule exists because breaking it twice produced two fake results —
   an oracle patched while a run was in flight, and arms run at different
   concurrency.
3. **Never delete a report**, including ones known to be invalid. They are the
   evidence for why a re-run was needed.
4. **Never report a pass rate without its caveats** (`EVIDENCE.md` §3). In
   particular these are oracle-retrieval numbers and **not** SWE-bench
   leaderboard scores.

---

## Verifying a result before believing it

This campaign produced two false results that looked entirely normal in the
summary line. Both would have been caught by these checks.

**Every arm scored suspiciously high or identical** → confirm the harness
actually ran, rather than reporting `UNAVAILABLE` while a sanity check carried
the score:

```bash
uv run python -c "
import json,pathlib,collections
d=json.loads(pathlib.Path('reports/arm-a-direct-wave<N>.json').read_text(encoding='utf-8'))
print(collections.Counter((s.get('grade') or {}).get('evidence',{}).get('harness_status') for s in d['samples']))"
```

Expect mostly `completed`. Any `unavailable` means no verdict was reached.

**One repo or slice scores 0% while others are normal** → suspect the oracle,
not the model. That signature was a missing pytest, not 15 failed repairs.

**An arm's rate moves a lot between waves** → check whether anything changed
between them. If something did, the waves are not unionable.

---

## Stopping conditions

Stop and report rather than continuing if:

- preflight does not say `READY`;
- disk free drops below ~50 GB (`df -h /c`) — run with `--prune-images`;
- a wave yields fewer than ~8 cases (pools exhausted for that difficulty/repo mix
  — the mix in `WAVE_MIX` needs widening, which is a **campaign change**, not a
  wave change);
- two consecutive waves produce zero new instances.

---

## What would make the result quotable

- **~200 paired instances.** At 59 the interval is ±11.9 points around a
  dead-even point estimate; nothing smaller resolves a difference this size.
- **A difficulty split.** Wave 1 hinted the review loop may only help where the
  direct arm fails (A 41.7% there, B 58.3%). Reporting the union rate alone
  would hide that. Once n is large enough, split by the `difficulty` field in
  each case's metadata.
- **`attempts=3`.** Would separate capability from sampling noise. **This is a
  campaign change** — do not do it mid-campaign.
