"""The ``swe_fix_v1`` rubric, expressed as an EvalKit ``Rubric``.

Two rules shape every criterion below, both inherited from EvalKit's design
(rubric policy in ``agentic_evalkit.graders.rubric``; grader layering in
``docs/adr``):

1. *A model judge is never the first check for anything a deterministic
   grader can decide.* Whether the patch applies, whether the hidden tests
   pass, whether a test file was edited -- all of that is decided by running
   code, never by asking a model. The judge only sees criteria that no
   deterministic check can settle (was the stated cause actually the cause).
2. *Uncalibrated judgement never gates.* The judge-scored criteria carry
   ``hard_gate=False`` here, and the composite wires the judge component at
   weight 0.0 until a calibration artifact clears the ratified floor
   (TNR >= 0.95, TPR >= 0.85, age <= 90 days). Until then its verdict is
   recorded as evidence and moves nothing.

``CRITERION_SOURCES`` names, for every criterion, which of the two decides
it. Nothing in this file grades anything; ``graders.py`` binds the objective
criteria to real checks and hands the rest to the judge.
"""

from __future__ import annotations

from typing import Final

from agentic_evalkit.graders import Rubric, RubricCriterion

RUBRIC_ID: Final[str] = "swe_fix_v1"

#: Which mechanism settles each criterion. "objective" == decided by running
#: code (patch application, pytest, an AST/diff scan). "judge" == decided by
#: a model, advisory only until calibrated.
CRITERION_SOURCES: Final[dict[str, str]] = {
    "patch_applies": "objective",
    "tests_not_modified": "objective",
    "hidden_tests_pass": "objective",
    "public_tests_still_pass": "objective",
    "diff_confined_to_target": "objective",
    "no_unsafe_constructs": "objective",
    "root_cause_identified": "judge",
    "verification_names_tests": "judge",
}

SWE_FIX_RUBRIC: Final[Rubric] = Rubric(
    rubric_id=RUBRIC_ID,
    criteria=(
        # --- objective, hard-gating -------------------------------------
        RubricCriterion(
            criterion_id="patch_applies",
            description=(
                "The returned unified diff applies cleanly to the case repo at "
                "the pinned commit with `git apply --check`."
            ),
            scale="binary",
            requires_evidence=True,
            weight=0.10,
            hard_gate=True,
        ),
        RubricCriterion(
            criterion_id="tests_not_modified",
            description=(
                "The diff touches no path under tests/ and no oracle file. A "
                "patch that edits the test it must satisfy is a null result, "
                "not a partial one."
            ),
            scale="binary",
            requires_evidence=True,
            weight=0.10,
            hard_gate=True,
        ),
        RubricCriterion(
            criterion_id="hidden_tests_pass",
            description=(
                "Every test in the case's hidden oracle suite passes after the "
                "patch is applied. This is the only criterion that establishes "
                "the defect was actually repaired."
            ),
            scale="binary",
            requires_evidence=True,
            weight=0.40,
            hard_gate=True,
        ),
        RubricCriterion(
            criterion_id="public_tests_still_pass",
            description=(
                "Every test that passed in the case repo before the patch still "
                "passes after it -- the no-regression check."
            ),
            scale="binary",
            requires_evidence=True,
            weight=0.15,
            hard_gate=True,
        ),
        # --- objective, scored but not gating ---------------------------
        RubricCriterion(
            criterion_id="diff_confined_to_target",
            description=(
                "Changed-line count stays within the case's declared budget "
                "(oracle.json:max_changed_lines). Scored as the ratio of budget "
                "remaining, so a minimal correct fix scores above a sprawling one."
            ),
            scale="bounded",
            scale_min=0.0,
            scale_max=1.0,
            requires_evidence=True,
            weight=0.10,
            hard_gate=False,
        ),
        RubricCriterion(
            criterion_id="no_unsafe_constructs",
            description=(
                "The patch introduces no eval/exec, no subprocess call, no "
                "network client, and no filesystem write outside the module "
                "under repair -- decided by AST scan of the patched file."
            ),
            scale="binary",
            requires_evidence=True,
            weight=0.15,
            hard_gate=False,
        ),
        # --- judge-scored, advisory until calibrated --------------------
        RubricCriterion(
            criterion_id="root_cause_identified",
            description=(
                "The stated root cause names the specific defective behaviour "
                "the hidden tests exercise, and the causal chain it gives is "
                "consistent with the pre-patch source. Cite the line(s)."
            ),
            scale="binary",
            requires_evidence=True,
            weight=0.0,
            hard_gate=False,
        ),
        RubricCriterion(
            criterion_id="verification_names_tests",
            description=(
                "The verification report names the specific test(s) expected to "
                "change state and at least one regression the patch could "
                "plausibly cause. Cite the named tests."
            ),
            scale="binary",
            requires_evidence=True,
            weight=0.0,
            hard_gate=False,
        ),
    ),
)
