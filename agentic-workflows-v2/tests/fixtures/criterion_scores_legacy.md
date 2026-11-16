# Legacy scoring fixtures

`criterion_scores_legacy.json` records 12 results from the old scorer at the
commit recorded in the file. Tests read these values without importing the old
package. Keep the expected values unchanged when changing the new scorer.

To reproduce them in a checkout of the recorded commit with the old package
installed, use each stored rubric and values with this calculation:

```python
from dataclasses import asdict
from agentic_v2_eval.scorer import Scorer

for case in fixture["cases"]:
    assert case["expected"] == asdict(Scorer(case["rubric"]).score(case["values"]))
```

The fixtures cover missing scores, clamping, empty rubrics, zero weights,
unequal ranges, zero-width ranges, duplicate names and ignored entries.
