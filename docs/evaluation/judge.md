---
title: LLM-as-judge
description: How Agentic Runtime Platform uses LLMs to score artifacts — the two judge systems, scoring scales, prompt design, bias mitigation, and how to write evaluatable prompts.
tags:
  - evaluation
---

# LLM-as-judge

Agentic Runtime Platform uses two complementary LLM-as-judge systems depending on the context:

1. **`LLMJudge`** (in `agentic-workflows-v2`) — the runtime judge used for production workflow evaluation. Scores on a 1–5 Likert scale per criterion, includes positional-bias mitigation, and exposes a `GET /api/runs/{filename}/evaluation` endpoint.

2. **Eval-package evaluators** (`LLMEvaluator`, `QualityEvaluator`, `StandardEvaluator`, `PatternEvaluator` in `agentic-v2-eval`) — standalone evaluators used by the CLI and batch/streaming runners. These use a discrete choice model (1–5 → 0.0–1.0) or a 0–10 JSON scoring scheme.

Both systems are described here. For production workflow scoring, see also [Production gating](gating.md).

---

## System 1: runtime `LLMJudge`

### What it scores

`LLMJudge` (at `agentic-workflows-v2/agentic_v2/scoring/judge.py`) scores a **candidate output** against an **expected output** on a set of named criteria. Each criterion is defined by:

- `name` — criterion identifier (e.g., `"correctness"`)
- `definition` — human-readable description of what this criterion measures
- `scale` — dict mapping score values to anchor descriptions (e.g., `{"1": "Major failures", "5": "Excellent"`)

The judge returns a normalized score per criterion and an overall score, all on the [0.0, 1.0] scale (internally uses a 1–5 Likert scale that is then normalized).

### Scoring scale

Raw scores from the judge are on the 1–5 Likert scale. These are normalized to [0.0, 1.0] via `normalize_score(raw, "likert_1_5")`:

| Raw Score | Normalized Score | Interpretation |
|-----------|-----------------|----------------|
| 1 | 0.00 | Very poor / Major failures |
| 2 | 0.25 | Poor / Significant issues |
| 3 | 0.50 | Acceptable / Meets minimum |
| 4 | 0.75 | Good / Minor issues only |
| 5 | 1.00 | Excellent / Fully meets criteria |

The overall score is the mean of all criterion normalized scores.

The final `score` field in the evaluation payload is `normalized_score * 100.0` (0–100 scale for human readability).

### Prompt design

The judge prompt is assembled by `_build_prompt()` with this structure:

```
You are a strict rubric judge. Return ONLY valid JSON.
Schema: {"criteria":[{"name":"...","score":1-5,"evidence":"..."}]}
mode: single | pairwise

rubric:
- criterion_name
  definition: ...
  anchors: 1:..., 5:...
[... more criteria ...]

EXPECTED OUTPUT:
{expected_output}

CANDIDATE OUTPUT:
{candidate_output}

Score each criterion on anchored 1..5 scale.
```

The system message is `"Return strict JSON only for rubric scoring."` Temperature is clamped to [0.0, 0.1] regardless of what the caller requests.

### Positional bias mitigation

LLM judges are susceptible to positional bias — a tendency to favor content presented first (or last) in a prompt. `LLMJudge` mitigates this with two mechanisms:

**1. Deterministic criterion shuffling.** Before building the prompt, criteria are shuffled using a deterministic seed derived from `sha256(candidate_output || expected_output || prompt_version)`. The first 8 hex digits of the digest are used as a 32-bit integer seed for `random.Random`. This ensures the same inputs always produce the same shuffled order (reproducibility) while breaking any systematic first/last position advantage across different candidate outputs.

**2. Pairwise consistency check** (optional). When `pairwise_reference_output` is provided to `evaluate()`, the judge is called twice: once with the original presentation order, and once with `candidate_output` and `pairwise_reference_output` swapped. `check_swapped_order_consistency()` flags criteria where the absolute score delta between the two presentations exceeds `max_delta=1.0`. Inconsistent criteria are recorded in `JudgeEvaluationResult.inconsistency_reasons`.

### Output schema validation

`validate_judge_structured_output()` validates the judge's JSON response before processing. It checks:

- `criteria` is a non-empty list
- Each criterion entry has `name` (non-empty string), `score` (numeric, 1–5), and `evidence` (string)
- If `expected_criteria` is provided, all names must be present

Validation failures raise `ValueError` with a description of each error. The call chain in `evaluate()` is:

```
_build_prompt() → _invoke_prompt() → validate_judge_structured_output() → [optional pairwise check] → JudgeEvaluationResult
```

### Calibration drift detection

`evaluate_calibration_set(judge, fixtures, tolerance)` runs the judge on a list of human-labeled fixtures and computes mean absolute error (MAE) between judge-assigned and human-assigned raw scores. If MAE exceeds `tolerance` (default 0.5), `within_tolerance=False` is returned.

```python
from agentic_v2.scoring.judge import LLMJudge, evaluate_calibration_set

judge = LLMJudge(model="gh:openai/gpt-4o")

result = evaluate_calibration_set(
    judge=judge,
    fixtures=[
        {
            "candidate_output": "Paris is the capital of France.",
            "expected_output": "Paris",
            "criteria": [{"name": "correctness", "definition": "...", "scale": {"1": "wrong", "5": "correct"}}],
            "human_scores": {"correctness": 5.0},
        }
    ],
    tolerance=0.5,
)
print(result)
# {"samples": 1, "mae": 0.0, "within_tolerance": True, "tolerance": 0.5}
```

### Sync/async bridge

`LLMJudge.evaluate()` is synchronous. Internally it calls `_run_coro_sync(coro)` to bridge to the async LLM client:

- If no event loop is running: uses `asyncio.run(coro)`.
- If an event loop is already active (e.g., inside a FastAPI request handler): spawns a daemon thread with its own `asyncio.run()` to avoid nested-loop errors. A `threading.Event` is used for synchronization.

---

## System 2: eval-package evaluators

The four evaluators in `agentic-v2-eval` use a simpler choice-extraction model rather than strict JSON schema validation.

### `LLMEvaluator` — choice-anchored scoring

**Scoring model:** 5-point discrete scale extracted from free-text LLM output.

```python
STANDARD_CHOICES = [
    Choice("1", 0.0),    # Very poor
    Choice("2", 0.25),   # Poor
    Choice("3", 0.5),    # Acceptable
    Choice("4", 0.75),   # Good
    Choice("5", 1.0),    # Excellent
]
```

**Score extraction algorithm:**

1. Strip and lowercase the full response.
2. Split into lines. Take the last line.
3. Exact match: if the last line equals a choice label (e.g., `"4"`), return that choice's score.
4. Containment match: if no exact match, scan the last three lines. Return the first choice whose label appears as a substring.
5. If no match: return `score=0.0`, `passed=False`.

Temperature is hardcoded to 0.0 for determinism.

**Why choice-extraction rather than JSON:** The five-point choice model is simpler to implement and more robust to minor response format variations than strict JSON parsing. The last-line convention is easy for LLMs to follow consistently, and the containment fallback handles cases where the model adds a trailing word.

**Return dict:**

```python
{
    "score": 0.75,           # Normalized 0–1
    "passed": True,          # score > 0
    "label": "4",            # Matched choice label
    "details": "Matched choice: 4",
    "raw_response": "...",   # Full LLM response for debugging
}
```

On LLM exception:

```python
{
    "score": 0.0,
    "passed": False,
    "error": "Connection timeout",
    "details": "Exception during execution",
}
```

### `QualityEvaluator` — five-dimension output quality

Each of the five dimensions (Coherence, Fluency, Relevance, Groundedness, Similarity) uses the same 5-point choice extraction scheme as `LLMEvaluator`. The prompts are loaded from `rubrics/quality.yaml` at module import time.

**Template variables by dimension:**

| Dimension | Required Variables | Optional |
|-----------|-------------------|----------|
| Coherence | `{{input}}`, `{{completion}}` | — |
| Fluency | `{{completion}}` | — |
| Relevance | `{{input}}`, `{{completion}}` | — |
| Groundedness | `{{context}}`, `{{completion}}` | — |
| Similarity | `{{expected}}`, `{{completion}}` | — |

The `completion` variable is automatically set from the `output` argument to `evaluate()`. All other variables are passed via the `inputs` dict.

```python
from agentic_v2_eval import QualityEvaluator, GROUNDEDNESS
from agentic_v2_eval.adapters.llm_client import get_llm_client

evaluator = QualityEvaluator(llm_client=get_llm_client())

score = evaluator.evaluate(
    definition=GROUNDEDNESS,
    inputs={
        "context": "The Eiffel Tower is located in Paris, France.",
        "completion": "The Eiffel Tower is in Paris.",
    },
    output="The Eiffel Tower is in Paris.",
)
print(score)  # 1.0 (fully grounded)
```

**Choosing an override model:**

```python
score = evaluator.evaluate(
    definition=COHERENCE,
    inputs={"input": "Explain quantum entanglement."},
    output=long_response,
    model_override="anthropic:claude-3-5-haiku",
)
```

### `StandardEvaluator` — prompt quality grading (0–10)

Unlike the 5-point choice model, `StandardEvaluator` uses a structured JSON response. The judge prompt explicitly instructs the LLM to return a JSON object with:

- `scores`: dict of five dimensions, each 0–10
- `improvements`: list of actionable suggestions
- `confidence`: float 0.0–1.0

**Multi-run aggregation:**

When `runs > 1`, scores are aggregated via **median** across all successful runs. Up to 5 unique improvement suggestions are collected from all runs (insertion-order deduplicated).

The `confidence` field in `StandardScore` is the median confidence across runs. A low confidence (< 0.7) indicates the judge was uncertain — the score should be treated with less weight.

**Input truncation:**

Prompts longer than 18,000 characters are truncated before being sent to the judge:
- First 16,000 characters preserved
- Last 1,000 characters preserved
- Gap replaced with `[...TRUNCATED... tail of prompt follows]`

This preserves the prompt header (most important for structure evaluation) and the prompt footer (often contains output format instructions).

### `PatternEvaluator` — structural pattern conformance

This evaluator scores whether an output follows one of four agentic reasoning patterns. It returns `PatternScore` — a rich dataclass with 17 fields capturing universal and pattern-specific dimensions, hard gate results, run statistics, and failure descriptions.

**Judge output format:**

```json
{
  "universal_scores": {
    "PIF": 4,
    "POI": 5,
    "PC": 5,
    "CA": 4,
    "SRC": 3,
    "PR": 0.9,
    "IR": 4
  },
  "pattern_scores": {
    "R1": 5,
    "R2": 4,
    "R3": 4
  },
  "failures": [],
  "confidence": 0.95
}
```

**Score aggregation:**

All scores are aggregated via `statistics.median` across `runs` invocations. The `_aggregate_scores()` helper processes a list of score dicts, collecting all values per key and computing the median. Keys absent from some runs are still included if they appear in any run.

**Hard gate evaluation:**

Hard gates are evaluated on the **aggregated medians**, not per-run. The four gates checked are:

```python
if universal.get("POI", 0) < 4:
    hard_gates_passed = False
    hard_failures.append("Phase Ordering Integrity < 4")
if universal.get("PC", 0) < 4:
    hard_gates_passed = False
    hard_failures.append("Phase Completeness < 4")
if universal.get("CA", 0) < 4:
    hard_gates_passed = False
    hard_failures.append("Constraint Adherence < 4")
if universal.get("PR", 0) < 0.75:
    hard_gates_passed = False
    hard_failures.append("Pattern Robustness < 0.75")
```

Note that PR is compared against 0.75 (a proportion), not 4 (an integer scale). This is different from the 0–5 scale used for POI/PC/CA.

---

## Research gating

When the eval framework is used for **deep research pipelines** (Profile E workflows), two additional thresholds govern whether research output is accepted:

- `coverage_score >= 0.80` — the research must cover at least 80% of the expected scope.
- `source_quality_score >= 0.80` — the sources cited must meet quality standards.

These are enforced as hard gates within `score_workflow_result_impl` for Profile E scoring. See [Production gating](gating.md) for the full production gating specification.

---

## How to write evaluatable prompts

### For `StandardEvaluator`

The judge scores five dimensions. Design your prompts to maximize scores in each:

**Clarity (0–10):** Write unambiguous instructions. Avoid conflicting directives. Define technical terms inline if they might be misinterpreted.

**Effectiveness (0–10):** Include explicit constraints and edge cases. State what "success" looks like. The judge asks: "Will this prompt reliably produce correct output?"

**Structure (0–10):** Use clear sections. Number steps when ordering matters. Put the output format specification at the end, close to where the model will start writing.

**Specificity (0–10):** Use actionable, measurable constraints ("respond in no more than 3 sentences") rather than vague directives ("be concise"). Define success criteria the model can verify for itself.

**Completeness (0–10):** Include all required context. Add examples when the format is non-obvious. Specify error handling when the task might fail.

### For `PatternEvaluator`

The judge checks whether the prompt reliably induces a specific pattern. Design pattern prompts to:

1. **Name the pattern explicitly** — the model should know it is expected to follow ReAct / CoVe / Reflexion / RAG structure.
2. **Define the phases** — enumerate the phases in order. Use the same phase names the evaluator expects.
3. **Specify transition conditions** — for ReAct, when does a Thought become an Action? When does the loop terminate?
4. **Include a worked example** (optional but high-impact) — one complete example of the pattern applied to a simple case helps the model understand the expected format before encountering a hard instance.
5. **Add negative constraints** — explicitly prohibit skipping phases or reordering steps to prevent the model from taking shortcuts.

**Example structure for a ReAct prompt:**

```markdown
You are an agent that reasons and acts using the ReAct pattern.

## Phase Structure
For each task, follow these phases in order:
1. **Thought**: Analyze the task. What do you know? What do you need to find out?
2. **Action**: Invoke exactly one tool call (format: `tool_name(argument)`).
3. **Observation**: Record the tool's result verbatim.
4. Repeat Thought/Action/Observation until you have sufficient information.
5. **Final Answer**: Provide the definitive answer. Do not loop after this.

## Constraints
- Never skip the Observation phase after an Action.
- Never include analysis inside the Action phase.
- Terminate the loop as soon as the answer is available.
```

### For `QualityEvaluator`

Design your prompts and expected outputs so the five quality dimensions are independently measurable:

- **Coherence:** Structure the output so it flows logically. Use transitional phrases.
- **Fluency:** Ensure grammatically correct output by including grammar instructions if the model tends to produce informal text.
- **Relevance:** Include a clear question or task statement that the output should answer directly.
- **Groundedness:** Provide context in the `context` variable. Instruct the model to cite sources.
- **Similarity:** Use reference outputs that are precisely correct — not overly verbose — to get meaningful similarity scores.

---

## Integrating the judge into a custom evaluation

```python
from agentic_v2_eval import Scorer, QualityEvaluator, COHERENCE, RELEVANCE
from agentic_v2_eval.runners.batch import BatchRunner
from agentic_v2_eval.reporters.html import generate_html_report
from agentic_v2_eval.adapters.llm_client import get_llm_client
from pathlib import Path

# Set up evaluators
llm = get_llm_client()
quality_eval = QualityEvaluator(llm_client=llm)
scorer = Scorer(Path("agentic-v2-eval/src/agentic_v2_eval/rubrics/agent.yaml"))

# Define evaluation function
def evaluate_one(test_case):
    output = test_case["output"]
    query = test_case["query"]

    coherence = quality_eval.evaluate(COHERENCE, inputs={"input": query}, output=output)
    relevance = quality_eval.evaluate(RELEVANCE, inputs={"input": query}, output=output)

    scoring_result = scorer.score({"Correctness": test_case.get("correctness", 0.0)})

    return {
        "query": query,
        "coherence": coherence,
        "relevance": relevance,
        "rubric_score": scoring_result.weighted_score,
    }

# Run batch evaluation
runner = BatchRunner(evaluator=evaluate_one)
batch_result = runner.run(test_cases)

# Report
generate_html_report(batch_result.results, "evaluation_report.html")
```
