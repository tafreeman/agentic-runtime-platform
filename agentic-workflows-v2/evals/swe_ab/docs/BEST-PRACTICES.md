# Benchmarking agentic workflows — practices earned the hard way

[Kit](../README.md) · [Docs](README.md) — **findings**, the transferable guide · every incident cited here is recorded in [EVIDENCE.md §2](EVIDENCE.md#2-defects-found-and-fixed)

What this campaign learned about measuring one agentic workflow against another
so the number survives being questioned. Every rule below is here because
breaking it cost something real; the incident is named, and the full record is
in [EVIDENCE.md §2](EVIDENCE.md#2-defects-found-and-fixed).

This campaign produced **two results that were entirely artefact** and looked
completely normal in the summary line, plus **one grader that reported 5/5
passed on a benchmark that never ran**. None of the three was caught by reading
the output more carefully. They were caught by checks that assume the harness
is wrong until it proves otherwise, which is what most of this guide is.

> **The one-sentence version.** A benchmark number is a claim about a system;
> everything here is about making the claim attributable, cheap to audit, and
> hard to overstate.

---

## 1. Design the comparison so a delta is attributable

**Hold everything constant except the thing under test.** Same model id, same
temperature, same seed, same inputs, same rubric, same concurrency, same
timeout policy. Arm A and Arm B here differ in exactly one dimension —
orchestration depth — so a score delta has one candidate explanation.

The two failures on this axis were both mine and both invalidated a run:

- **Arms ran at different concurrency** (A at 1, B at 4). Re-run at 4 before
  anything was quoted. *(EVIDENCE §2.7)*
- **The grading rules changed mid-run.** A genuine oracle bug was fixed while
  Arm B was in flight, so B was graded with a working oracle and A was not.
  It produced an apparent 7.6-point win for B that was pure artefact.
  *(EVIDENCE §2.6)*

> **Rule: never change grading rules, workflows, oracles, or run settings while
> a comparison is running — however good the reason.** A mid-flight fix does not
> improve the run, it ends it. The fix starts a *new* campaign whose results
> cannot be unioned with the old ones.

**Pin campaign settings in code, not in flags.** `--model`, `--concurrency` and
`--timeout` are deliberately not exposed by `tools/run_wave.py`; they live in a
`CAMPAIGN` constant. A setting that can be passed will eventually be passed
differently. A wave that needs different settings is a different experiment.

### Two workflows are two systems, and the tooling should say so

`agentic-evalkit compare` **refuses** this comparison:

```
[incompatible_runs] runs '68265114…' and 'ed558dd1…' are not comparable:
target name differs: 'arp-swe_fix_direct' != 'arp-swe_fix_review_loop'
```

That is correct. `target_name` and `target_fingerprint` are non-waivable
provenance (ADR-0015): two different systems are not two versions of one system.

**Do not give both arms the same target name to get past the gate.** That
launders the exact difference under measurement, and it is the specific failure
mode the provenance gate exists to prevent. The honest substitute is a paired
analysis over the shared `sample_id`s — per-case outcome, McNemar on the
discordant pairs, bootstrap CI on the paired difference — which is the same
arithmetic minus the same-system assumption. That is `analyze.py`.

---

## 2. Build the case set for discrimination, not for a good-looking number

**A ceiling is not a result.** The first two case sets scored 96% and 94.7% for
both arms. At that level the set cannot separate two competent orchestrations no
matter how many cases you add — tripling from 50 to 132 moved the point estimate
2 points and changed nothing. Only moving to SWE-bench Verified (68.6%) created
room to discriminate.

> If both arms are above ~90%, you are measuring the case set, not the system.
> Add difficulty, not volume.

**Ground truth is a test that runs, never a string that matches.** No grading
path compares output to a gold patch; two different correct patches must both
score 1.0. `reference` in every case row is deliberately `null`.

**Mine cases, don't author them.** An authored bug is one you already know how
to describe, and the description leaks the answer into the prompt. A real
`fix(...)` commit carries the symptom (the failing test) separately from the
cause (the diff) — exactly the split the eval needs. See
[../dataset/CASES.md](../dataset/CASES.md).

**Verify every case reproduces before the run.** All 132 mutation cases were
replayed to confirm the named test actually fails at the parent commit. A case
that does not reproduce is scored as a model failure forever.

**Mark contamination and report split by it.** django is 54% of the SWE-bench
set and the most represented Python repo in any training corpus. Cases carry
`contamination_risk`; a score carried by `high` cases is not evidence of
capability.

**Know what your n can detect before you run it.**

| paired cases | detectable difference at 80% power |
|---|---|
| 12 | ~35 pp — directional only |
| 30 | ~22 pp — weak evidence |
| 60 | ~15 pp |
| ~200 | ~8 pp — what this campaign's question actually needs |

At 59 paired instances with 14 discordant pairs, differences at this scale are
not resolvable. **The interval is the result, not the point estimate.**

---

## 3. Cost control is environmental, not configurable

**ARP walks into paid providers on its own.** When a step's output misses its
declared contract, `_invoke_with_failover` walks the tier chain; the first probe
of this campaign reached Anthropic and returned a billing error. There is no
configuration flag that disables it, and `model_override` only *prepends* to the
candidate list — the paid fallbacks still follow it. *(EVIDENCE §2.5)*

> **Rule: make the paid path unreachable, not merely un-preferred.**
> `run_ab.py` deletes every paid credential from the child environment before
> spawning the bridge. A provider without a key cannot be called at all — free
> by construction, not by policy.

The credentials removed: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`,
`GITHUB_TOKEN`, `OPENROUTER_API_KEY`, `AZURE_OPENAI_API_KEY`,
`AZURE_FOUNDRY_API_KEY`, `CLAUDE_CODE_OAUTH_TOKEN`.

This is a workaround for a platform gap, not a design. The proper fix — a cost
lane on every registered model and a ceiling the candidate resolver enforces —
is written up in [ARP-IMPROVEMENTS-PROMPT.md](ARP-IMPROVEMENTS-PROMPT.md).

**Never print an API key.** Load it inside the subprocess that needs it and emit
only results.

---

## 4. Probe the environment; assume nothing about it

Three assumptions were wrong on this machine, each costing an hour or a result.

**A listening port is not the service you think.** Lemonade serves on `:13305`;
`:8000` belongs to an unrelated `Manager` process. Probing 8000 returns nothing
and looks exactly like Lemonade being down.

**Listing is not loading.** `muse-glimmer` appears in Docker Model Runner's
model list and fails at load with `unknown model architecture`. Always complete
one real chat call before counting a model as available.

**An empty response is not a failure.** Reasoning models spend the token budget
on internal reasoning before emitting content, and return `done_reason: length`
with empty text. Four NIM models looked dead for this reason. Set `think: false`
or raise `max_tokens` before concluding anything.

**A capability that allocates may still have no kernel.** `float8_e4m3fn`
tensors allocate fine on this GPU while `_scaled_mm` raises, and `torch._int_mm`
**segfaults the process** rather than raising. Test the operation, not the
allocation, and isolate each probe in its own process.

Procedure: [MODEL-PROBE-GUIDE.md](MODEL-PROBE-GUIDE.md). Snapshot:
[MODEL-INVENTORY-2026-08-27.md](MODEL-INVENTORY-2026-08-27.md).

---

## 5. Isolate the run from everything it could damage

Given file tools, `tier2_coder` answered a repair task by calling `file_write`
on `src/agentic_evalkit/stats/compare.py` — relative to the inherited working
directory, i.e. the live checkout. ARP's fail-closed approval governance denied
it. *(EVIDENCE §2.4)*

Both fixes were kept, because either alone is one mistake from a modified repo:

| risk | control |
|---|---|
| Agent writing into a live repo | every workflow step declares `tools: []`; the bridge `chdir`s to a sandbox first |
| Paid provider billed by failover | paid credentials deleted from the child env |
| Mutation left in a real checkout | mining and grading run in throwaway git worktrees |
| One repo's grading colliding with another's | one worktree per source repo, each with its own lock |
| Benchmark source committed into the repo | case directories gitignored and rebuilt by the builder |

**A hard kill can defeat the worktree restore.** After any interrupted run:
`git -C <worktree> checkout -- .`

---

## 6. Grade so that "we don't know" can never become "pass"

The worst defect in this campaign: **a floor check reported 5/5 passed on a
benchmark that never ran.** The SWE-bench harness returned `UNAVAILABLE` on all
five instances; `CompositeGrader` excludes ABSTAIN/ERROR/UNAVAILABLE from its
weighted mean — correct for an advisory component, catastrophic for the
authoritative one — so the cheap sanity check alone carried the score.
*(EVIDENCE §2.1)*

> **Rule: the authoritative grader must sequence explicitly, and its inability
> to run must be its own outcome.** `SwebenchGrader` replaced the composite:
> sanity failure → FAIL; harness cannot run → **UNAVAILABLE, never PASS**;
> harness ran → its verdict.

**Operational failure is not task failure.** Timeouts, errors and cancels never
count against the system under test (ADR-0008). Two of Arm B's three losses at
n=50 were timeouts, not wrong repairs — reporting them as failures would have
been a straightforward misread. Report a verdict-only row alongside the raw one.

**An oracle that cannot run scores everything as failure.** memoryctl's cases
carried a bare `python -m pytest`, which resolves against the PATH of whoever
runs it. The miner ran under system Python 3.13 (has pytest); the grader runs
under `uv run`, whose managed 3.12.11 does not. All 15 cases failed with "No
module named pytest" — 0/15 while every other repo sat at 93–95%.
*(EVIDENCE §2.2)*

> **Rule: absolute interpreters in every oracle command.** And when a run never
> reaches a verdict, return `UNAVAILABLE` rather than `resolved=False`.

**Ask for the artefact, not a representation of it.** The first contract asked
for a unified diff; models produce malformed diffs often enough that the run
would have measured diff-formatting skill. Both arms now return the complete
corrected file and the harness computes the diff. Likewise the source arrives
**inline**, byte-identical to both arms — passing a path made the result depend
on whether the agent had working file tools.

**Watch for a step that can echo its own input.** Arm B ran all five steps,
diagnosed the bug correctly, and returned the file byte-identical to the
original on 6 of 35 instances. `revise_repair` held both the draft *and* the
untouched `source_code` with the instruction "if the review raised no risks,
return the draft unchanged" — ambiguous about which input to echo. Removing
`source_code` from that step took Arm B from 18 to 21 resolved.
*(EVIDENCE §2.3)*

> Five steps of correct reasoning were being binned by one ambiguous word. If a
> step must not echo something, do not put it in that step's context.

**An uncalibrated judge gates nothing.** The rubric judge sits at weight 0.0
throughout, by design. Under ADR-0007 / D-1 a judge may hold a hard gate only
under full calibration clearing TNR ≥ 0.95 / TPR ≥ 0.85 / age ≤ 90 days on the
**Wilson lower bound**, not the point estimate. A judge on a free 8–30B model is
emphatically uncalibrated. Use a different model family from the system under
test regardless — a model scoring its own family's output is a known
self-preference bias.

---

## 7. Verify before believing — especially good news

Both fake results in this campaign would have been caught by these three checks,
and neither was caught by reading the summary line.

**If an arm scores suspiciously high, or both arms score identically, confirm
the harness actually ran.** A summary line saying `passed=N` is not evidence the
benchmark executed. Count the per-sample harness status:

```bash
uv run python -c "
import json,pathlib,collections
d=json.loads(pathlib.Path('reports/arm-a-direct-waveN.json').read_text(encoding='utf-8'))
print(collections.Counter((s.get('grade') or {}).get('evidence',{}).get('harness_status') for s in d['samples']))"
```

Expect mostly `completed`. Any `unavailable` means no verdict was reached and
the number is meaningless.

**If one repo or slice scores 0% while the others look normal, suspect the
oracle, not the model.** That signature was a missing pytest, not 15 failed
repairs.

**If an arm's rate moves a lot between waves, check whether anything changed
between them.** If something did, the waves are not unionable.

> **Surprise is usually a defect in the harness, not a discovery about the
> models.** That has been true every single time in this campaign. Treat an
> interesting result as a bug report against your own tooling until it survives
> the checks above.

---

## 8. Report the number with its caveats bound to it

Four caveats travel with every figure this campaign produced, and a number
quoted without them is a different, stronger claim than the evidence supports:

1. **Oracle retrieval.** The model is told which file to fix. Full SWE-bench also
   requires finding it. **These are not leaderboard numbers.**
2. **Underpowered.** 59 paired instances with 14 discordant pairs cannot resolve
   a difference of this size.
3. **One model, one attempt.** `attempts=1`; pass@1 hides per-case sampling
   noise. Report pass@1 and pass@3 side by side when you can.
4. **Contamination-prone.** django-heavy; cases marked `contamination_risk`.

**Report cost next to accuracy.** Arm B costs 3.0–5.9× per case, and the ratio
grows with file size because it re-emits the whole file twice. A workflow that
wins by 3 points at 4× the tokens has lost. Cost is not a footnote to the
accuracy number; it is half the result.

**Do not draw a conclusion the statistics do not support.** If p ≥ 0.05, the
interval is the answer, and "no detectable difference" is a real finding — it is
not a failed experiment. Equally, "no difference on this set" is not "the
technique does not work": on defects a competent model one-shots, a review loop
has nothing left to add and costs 3× to discover that. The informative test is
defects the direct arm actually fails.

---

## 9. Make the campaign resumable by an agent that was not there

State lives on disk; nothing depends on a session staying alive.

**Non-overlap should be a property of the data, not of bookkeeping.** Wave 1 at
offset 0 drew exactly the instances the hand-built set already used — an hour of
work adding zero evidence. The fix was not better offset tracking: the builder
now skips any instance that already has a case directory, so waves cannot
overlap regardless of the wave number passed. *(EVIDENCE §2.10)*

**The directories are the source of truth; the index is derived.** An
`--append` patch silently failed and one mining pass overwrote `cases.jsonl`,
dropping 50 mined rows. The case directories survived, and
`tools/rebuild_index.py` now regenerates the index from them idempotently.
*(EVIDENCE §2.8)*

**Never delete a report, including one known to be invalid.** The two invalid
reports here are the evidence for why the matched pair had to be re-run.
Deleting them erases the record of the correction.

**Bound every subprocess by a measured baseline, not a flat ceiling.** Mutating
a comparison inside a retry loop makes a suite *hang* rather than fail; under a
flat 150 s ceiling each such candidate cost the full timeout and one mining pass
produced 1 case in 20 minutes. Bounding at 10× the module's measured baseline
and skipping hangs explicitly took the next pass to 37 cases. *(EVIDENCE §2.9)*

**Write the handoff prompt as part of the campaign, not after it.**
[SUBAGENT-PROMPT.md](SUBAGENT-PROMPT.md) is self-contained, states the hard
rules, names the stopping conditions, and forbids the agent from changing the
campaign — because every interesting failure here came from something changing
mid-flight.

**Known gap: progress within a wave is not observable.** `run_ab.py` prints only
at the end; the current workaround is counting spilled artifacts. Wiring
`EvalRunner.run(event_sink=…)` — the API exists at
`agentic_evalkit/runner.py:220` and the EvalKit CLI already uses it — to a
progress log is the proper fix and is not yet done.

---

## Pre-flight checklist for the next campaign

Before the first case runs:

- [ ] One variable differs between arms; everything else is pinned in code.
- [ ] Campaign settings are constants, not CLI flags.
- [ ] Paid credentials are removed from the child environment — verified by
      checking the child's env, not by reading the config.
- [ ] Every serving path probed with a real completion, not a model list.
- [ ] Reasoning models have `think:false` or a raised token budget.
- [ ] Every workflow step declares `tools: []`; the runner `chdir`s to a sandbox.
- [ ] Every oracle command names an absolute interpreter.
- [ ] The authoritative grader returns UNAVAILABLE — never PASS — when it cannot
      run, and that outcome is distinguishable in the report.
- [ ] Every case verified to reproduce.
- [ ] `contamination_risk` recorded per case.
- [ ] Target n chosen from the power table for the effect size you care about.
- [ ] The judge's weight is 0.0 unless calibration evidence clears the floor.

After each run, before quoting anything:

- [ ] Per-sample harness status counted; `unavailable` count is zero or explained.
- [ ] No slice at 0% that could be an oracle failure.
- [ ] Nothing changed between the arms or between the waves being unioned.
- [ ] Operational failures separated from task failures.
- [ ] Cost and wall-clock reported next to accuracy.
- [ ] The four standing caveats attached to the number.
- [ ] If p ≥ 0.05, the interval is reported as the result.
