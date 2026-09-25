# Pre-registration: does a deterministic gate beat a model gate?

**Status:** draft, not yet run. Written before any arm executes.
**Date:** 2026-09-08

Written in advance because this campaign has twice discovered its binding
constraint after spending: three GLM-5.3 launches produced zero usable data,
and the hard-slice hypothesis turned out to have zero eligible instances
(all 25 undrawn hard instances are multi-file patches, which the single-file
eval contract cannot present). Fixing the design first costs nothing and
removes the obvious objection to whatever this finds.

---

## 1. The question

The completed A/B established that a five-step LLM review loop performs
*worse* than a single direct pass (80/146 vs 65/146, McNemar exact
p = 0.0315). That result has a confound: Arm B changed two things at once --
it added **more attempts** and it added **a review**. The measured -10.3pp
cannot be attributed to either.

The thesis under test says something narrower: a check with an explicit
acceptance criterion and *different failure modes from the generator* is
what makes a verification boundary work -- not the mere presence of a second
look. That predicts a deterministic check should beat a model check, and
both should beat no check, with the retry budget held constant.

## 2. Arms

Four arms, identical instances, **exactly one regeneration permitted in every
arm that regenerates at all**. The only variable is what decides whether to
regenerate.

| arm | design | regenerates when |
|---|---|---|
| A0 | direct, single pass | never (already collected, n=146) |
| A1 | direct + deterministic gate | `SourceSanityGrader.gate_ok` is false |
| A2 | direct + model gate | an LLM judge rejects the output |
| A3 | direct + blind retry | always (control) |

**A3 is the arm that makes this interpretable.** Without it, any A1 gain is
indistinguishable from "a second attempt helps." A3 is not a straw man; it is
the null this experiment exists to beat.

The deterministic gate is not new code. `SourceSanityGrader` (`graders.py`)
already computes five checks -- returned non-empty, parses as Python,
differs from the broken file, not truncated, no test-name shortcut -- and
already sets `gate_ok = all(checks)`. Today it only *scores*. The change is
to let it *gate*.

## 3. Predictions, stated before the run

If the thesis holds:

- **A1 > A3** -- the deterministic gate beats blind retry. This is the
  primary hypothesis. A1 ~= A3 falsifies it: the gate would be buying nothing
  a coin flip does not.
- **A1 > A2** -- the deterministic check beats the model check.
- **A3 >= A0** -- retrying at all is weakly positive, or neutral.

If the thesis is wrong, the most likely shape is A1 ~= A2 ~= A3 > A0:
"more attempts help, the kind of check does not."

## 4. Primary outcome and test

**Primary:** McNemar exact test on A1 vs A3, paired over shared instances,
alpha = 0.05, two-sided. Everything else is secondary and reported as such.

**Secondary:** A1 vs A2; A3 vs A0; the rescue/break decomposition per arm
(of the cases where the arm's first pass failed, what fraction did the second
attempt fix; of the cases it solved, what fraction did the second attempt
break).

Operational failures (error, timeout, unavailable) are excluded pairwise
under ADR-0008, never counted as task failures.

## 5. Stopping rule

**All four arms run to n=146. Analysed once, after the last arm completes.**

No interim peeking drives a stop decision. No arm is extended because it
"nearly" reached significance. If the primary test returns p >= 0.05 the
result is "not resolved at this n", which is reported as-is and not repaired
by adding instances.

Power note, computed in advance: at n=146 with the discordance rate observed
in the completed A/B (~30%), the primary test detects a 10pp difference with
roughly 80% power. A smaller true effect will not be resolvable here and
that is accepted before starting.

## 6. What would make this invalid

Named in advance so they cannot be rationalised afterwards:

- **Arms on different builds.** Every arm must run on one
  `code_fingerprint` and one `environment_fingerprint`. The completed A/B
  needed `--allow-runtime-drift`; this one must not.
- **Unequal retry budgets.** If A1 retries once and A2 retries twice, the
  comparison measures budget, not check quality.
- **A gate that reads the oracle.** `SourceSanityGrader` checks the returned
  file against the *broken* file and the failing test *name*. It must never
  consult hidden tests or the gold patch -- that would leak the answer into
  the gate and inflate A1.
- **Judge calibration.** A2's judge gates a real decision, so under EvalKit's
  own rule an uncalibrated judge gates nothing. Either calibrate it against a
  labelled set first, or report A2 as advisory-only and drop it from the
  primary comparison.

## 7. Cost

~$5 and ~3 hours for the three new arms at the measured throughput
(Arm A median 187 s/case; ~92 s/sample wall at concurrency 4). Cost is not a
constraint on this design and should not be used to justify trimming A3.
