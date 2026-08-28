# Wave runbook — continuing the campaign

For an agent picking this up cold. Read `TEST-SETUP.md` §1 first and confirm
preflight says `READY`.

---

## The job

Accumulate paired SWE-bench instances until the A/B can answer its question.
Each wave is ~16 instances, ~50 minutes, both arms, self-contained.

| | |
|---|---|
| Banked | 47 paired instances |
| Target | ~200 (≈10 more waves) |
| Current reading | A 61.7%, B 59.6%, B−A −2.1%, **p = 1.00** |

---

## One wave

```bash
cd C:/Users/tandf/source/agentic-runtime-platform/agentic-workflows-v2/evals/swe_ab
uv run python tools/run_wave.py --wave <N> --size 16 --prune-images
```

`<N>` = highest existing `dataset/cases.swebench.wave*.jsonl` number, plus 1.
The number is for naming only — overlap prevention comes from the builder
skipping instances that already have a case directory.

Takes ~50 min. Produces `reports/arm-a-direct-wave<N>.json` and
`reports/arm-b-review-loop-wave<N>.json`.

---

## After each wave

Union everything and record the reading:

```bash
uv run python analyze.py \
  --left  reports/arm-a-direct-swebench-c4.json \
  --left  reports/arm-a-direct-wave1.json \
  --left  reports/arm-a-direct-wave<N>.json \
  --right reports/arm-b-review-loop-swebench-fixed.json \
  --right reports/arm-b-review-loop-wave1.json \
  --right reports/arm-b-review-loop-wave<N>.json
```

Add one `--left`/`--right` pair per wave. Append the result to the table in
`EVIDENCE.md` §1.3: n, both arms' rates, B−A, CI, McNemar p, discordant pairs.

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

- **~200 paired instances.** At 47 the interval is ±14 points; nothing smaller
  resolves a 2-point difference.
- **A difficulty split.** Wave 1 hinted the review loop may only help where the
  direct arm fails (A 41.7% there, B 58.3%). Reporting the union rate alone
  would hide that. Once n is large enough, split by the `difficulty` field in
  each case's metadata.
- **`attempts=3`.** Would separate capability from sampling noise. **This is a
  campaign change** — do not do it mid-campaign.
