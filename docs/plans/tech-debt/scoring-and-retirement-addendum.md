# Architecture: scoring and removal of the old evaluation package

Status: proposed architecture. The changes below are not yet implemented.

Related decision: `docs/adr/ADR-042-agentic-evalkit-adoption.md`.
Delivery steps: [G1 and G2](../2026-09-10-tech-debt-workflow.md).

## Problem

Agentic Runtime Platform (ARP) runs workflows and scores their results.
Agentic EvalKit evaluates completed runs. ARP still depends on an older
evaluation package for its required quality check.

ARP and EvalKit handle missing scores differently. With two equally weighted
criteria, one scoring 1 and the other missing:

| System | Calculation | Result |
| --- | --- | --- |
| ARP | Keep both criteria in the total weight | 0.5 |
| EvalKit | Use only the criterion with a usable score | 1.0 |

Neither calculation can replace the other without changing behavior.

## Decision

ARP will own the calculation used by its required quality check. That check
must run without EvalKit or the old evaluation package installed.

Keep both scoring rules. Tests must confirm the example above and cases where
both systems should produce the same result, such as complete valid scores.

A missing score is not evidence of poor output. Keep it marked as missing even
when ARP's calculation gives it no contribution. The required check rejects
missing criteria. Runtime step scoring keeps its existing evidence requirements.
Text being present is not enough to award a score.

## Components and interfaces

Add `agentic_v2/scoring/criterion_aggregation.py`:

```python
@dataclass(frozen=True)
class CriterionSpec:
    name: str
    weight: float = 1.0
    min_value: float = 0.0
    max_value: float = 1.0

@dataclass(frozen=True)
class CriterionScoreSummary:
    total_score: float
    weighted_score: float
    criterion_scores: Mapping[str, float]
    missing_criteria: tuple[str, ...]

class CriterionScorer:
    def __init__(self, rubric_data: Mapping[str, Any]) -> None: ...
    def score(self, values: Mapping[str, float]) -> CriterionScoreSummary: ...
    def validate_results(self, values: Mapping[str, float]) -> list[str]: ...

def parse_criteria(rubric_data: Mapping[str, Any]) -> tuple[CriterionSpec, ...]: ...

def score_criterion_values(
    criteria: tuple[CriterionSpec, ...], values: Mapping[str, float]
) -> CriterionScoreSummary: ...
```

A rubric is a list of criteria, their weights, and allowed score ranges.
The scorer accepts a loaded rubric. Reading files remains the caller's job.
Copy input mappings and expose read-only result mappings.

Preserve these existing results:

- `criterion_scores` contains supplied scores limited to their allowed ranges.
- `total_score` averages normalized scores over all criteria.
- `weighted_score` divides the weighted sum by all criterion weights.
- `missing_criteria` lists absent names in rubric order, including zero-weight
  criteria. A zero total weight produces a weighted score of zero.

Before replacing the old scorer, save expected results for duplicate names,
zero-width ranges, defaults and calculation order. Preserve supported behavior;
do not combine this replacement with changes to those rules.

## Input and output rules

The required check must fail when input is malformed or contains NaN or
infinity. Validate these inputs before calculating a score.

For valid inputs, keep the current scores, exit codes and JSON fields.
Write `missing_criteria` as a JSON array, as it is today.

Runtime scoring keeps an unavailable result when evidence is missing or invalid:
score and pass remain null, and the result is excluded from averages.
Do not turn an execution error into a judgment about output quality.

## Migration

1. Save expected results from the old scorer, including its source commit.
   The replacement tests must run without importing the old package.
2. Update `scripts/eval_gate.py` to use the new scorer and the existing bundled
   rubric loader. Keep its threshold, missing-score rejection and required
   `eval-golden-gate` CI check.
3. Update `evalkit_bridge.score_criteria(...) -> float` to use the same
   calculation after converting the rubric through EvalKit. Keep its public
   signature and its error when the optional EvalKit dependency is absent.
4. Merge the replacement when authorized and confirm the required check passes
   on main. Only then remove the old evaluation package.
5. Remove old imports, test dependencies, workspace entries, build settings and
   CI installation steps. Delete unused `models/llm.py` rather than relocating
   its unused interface. Keep ARP's bundled rubrics.
6. Record the completed replacement and removed dependencies in ADR-042.

## Verification

Test complete, partially missing, entirely missing, zero and out-of-range
scores; empty rubrics; zero weights; unequal ranges; and the missing-score
example above. Test invalid numbers separately from valid score calculations.

A partially scored result must fail the required check even if its numeric
score exceeds the threshold. Runtime output without evidence must not receive
an automatic 0.7 score.

Install the built ARP package in a clean environment without either evaluation
package. Run the required check and load the bundled rubrics. Test the optional
EvalKit integration separately. A passing test in the development workspace
alone does not prove the old dependency was removed.
