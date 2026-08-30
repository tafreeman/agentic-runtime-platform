# Sub-agent prompt — run the next waves

[Kit](../README.md) · [Docs](README.md) — **operational**, paste-ready · the procedure it follows: [WAVE-RUNBOOK.md](WAVE-RUNBOOK.md)

Paste the block below to a Sonnet sub-agent. It is self-contained: no context
from the originating session is needed.

---

```
You are continuing a running A/B experiment. Everything you need is on disk.

WORKING DIRECTORY
C:/Users/tandf/source/agentic-runtime-platform/agentic-workflows-v2/evals/swe_ab

READ FIRST, IN THIS ORDER
1. docs/TEST-SETUP.md      — requirements, preflight, isolation, current state
2. docs/WAVE-RUNBOOK.md    — the procedure you will follow
3. docs/EVIDENCE.md §3     — caveats that must accompany any number you report

THE EXPERIMENT
Two ARP workflows repair the same SWE-bench Verified defects, graded by the
official SWE-bench Docker harness. Arm A (swe_fix_direct) is one coder step;
Arm B (swe_fix_review_loop) is five steps with an adversarial regression review.
Same model, same inputs, same rubric. The question is whether Arm B's extra
steps buy more resolved instances than they cost.

Banked: 47 paired instances. Arm A 61.7%, Arm B 59.6%, McNemar p = 1.00.
Target: ~200 paired instances. Each wave adds ~16 and takes ~50 minutes.

YOUR TASK
Run waves 2 through 5, one at a time, and report the union after each.

  # preflight — do not proceed unless this prints READY
  uv run python -c "import sys; sys.path.insert(0,'.'); \
    from container_harness import container_preflight; print(container_preflight() or 'READY')"

  # one wave (N = highest existing dataset/cases.swebench.wave*.jsonl + 1)
  uv run python tools/run_wave.py --wave N --size 16 --prune-images

  # union every wave so far — one --left/--right pair per report
  uv run python analyze.py \
    --left  reports/arm-a-direct-swebench-c4.json \
    --left  reports/arm-a-direct-wave1.json \
    --left  reports/arm-a-direct-waveN.json \
    --right reports/arm-b-review-loop-swebench-fixed.json \
    --right reports/arm-b-review-loop-wave1.json \
    --right reports/arm-b-review-loop-waveN.json

After each wave, append a row to the table in docs/EVIDENCE.md §1.3:
n, both arms' rates, B−A, the 95% CI, McNemar p, and the discordant-pair counts.

HARD RULES
1. Never pass --model, --concurrency or --timeout to run_wave.py. They are pinned
   in CAMPAIGN inside the module. Waves can be combined only while every wave
   shares an arm, a model and a configuration.
2. Never change workflows, graders, oracles or case-building logic. If something
   looks wrong, STOP and report it. A mid-campaign fix invalidates every earlier
   wave — this has already happened twice and produced two fake results.
3. Never delete a report, including one you believe is invalid.
4. Never report a pass rate without noting: oracle retrieval (not a leaderboard
   number), underpowered at this n, one model, one attempt, django-heavy and
   contamination-prone.

VERIFY BEFORE BELIEVING — two false results have already occurred here
- If an arm scores suspiciously high, or both arms score identically, confirm the
  harness actually ran. Count harness_status across the report's samples; expect
  mostly "completed". Any "unavailable" means no verdict was reached and the
  number is meaningless.
- If one repo or slice scores 0% while others look normal, suspect the oracle,
  not the model.
- A summary line saying "passed=N" is not evidence the benchmark ran. Check the
  per-sample evidence.

STOP AND REPORT IF
- preflight does not print READY;
- free disk on C: drops below ~50 GB;
- a wave yields fewer than 8 cases;
- two consecutive waves add no new instances;
- any result surprises you — surprise is usually a defect in the harness, not a
  discovery about the models. That has been true every time so far in this
  campaign.

REPORT AT THE END
- The union table across all waves you ran.
- The current McNemar p and confidence interval.
- Anything you stopped for, with the evidence.
- Do not draw a conclusion about which arm is better unless p < 0.05. If it is
  not significant, say the interval is the result.
```

---

## Notes for whoever dispatches this

- Sonnet is sufficient: the work is procedural, and the judgement calls are
  pre-decided in the runbook.
- Four waves is ~3.5 hours wall-clock. The agent is mostly waiting, so background
  the work and let it report per wave.
- The agent should **not** be given authority to change the campaign. Every
  interesting failure in this campaign came from something changing mid-flight;
  the rules above are the accumulated cost of that.
