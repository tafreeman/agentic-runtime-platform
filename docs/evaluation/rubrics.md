---
title: Rubrics
description: The eight YAML rubrics that drive Agentic Runtime Platform evaluation — criteria, weights, level descriptors, use cases, and loading API.
tags:
  - evaluation
---

# Rubrics

Every evaluation in Agentic Runtime Platform scores an artifact against a YAML rubric. The rubrics live at [`agentic-v2-eval/src/agentic_v2_eval/rubrics/`](https://github.com/tafreeman/agentic-runtime-platform/tree/main/agentic-v2-eval/src/agentic_v2_eval/rubrics) and ship as part of the package.

There are eight rubrics in the canonical set. They split into two families:

- **Scoring rubrics** — define named criteria with numeric weights. Used by the `Scorer` engine and the CLI `evaluate` subcommand.
- **Judge rubrics** — define LLM prompt templates. Used by `QualityEvaluator`, `StandardEvaluator`, and `PatternEvaluator` at evaluation time.

There is no single "scoring scale" across these rubrics: criterion `weight` values are 0–1 mixing coefficients that sum to 1.0, the level descriptors are a 0–5 human-reference anchor per criterion, and `prompt_standard` scores its five dimensions on a 0–10 judge scale — so read each rubric's scale in its own section rather than assuming one applies everywhere.

---

## Loading rubrics programmatically

```python
from agentic_v2_eval.rubrics import load_rubric, list_rubrics, get_rubric_path

# List all available rubric names
print(list_rubrics())
# ['agent', 'code', 'coding_standards', 'default', 'pattern',
#  'prompt_pattern', 'prompt_standard', 'quality']

# Load a rubric as a dict
rubric = load_rubric("agent")
for criterion in rubric["criteria"]:
    print(f"{criterion['name']}: weight={criterion['weight']}")

# Get the filesystem path
path = get_rubric_path("code")
```

Pass a rubric name to the `Scorer` constructor:

```python
from agentic_v2_eval.scorer import Scorer

scorer = Scorer(get_rubric_path("agent"))
result = scorer.score({
    "Correctness": 0.9,
    "Completeness": 0.8,
    "Clarity": 0.85,
    "Relevance": 0.9,
    "Efficiency": 0.7,
    "Safety": 1.0,
})
print(f"Weighted score: {result.weighted_score:.3f}")
```

Or from the CLI:

```bash
python -m agentic_v2_eval evaluate results.json --rubric rubrics/agent.yaml
```

---

## Family 1 — scoring rubrics

These rubrics drive the `Scorer` engine. Each criterion has a `weight` (must sum to 1.0 within the rubric), an optional description, and optional level descriptors (0–5 scale for human reference).

### `default.yaml` — general purpose

**Purpose:** Quick evaluation of any result set where domain-specific rubrics are not yet defined.

**Pass threshold:** None defined.

| Criterion | Weight | Description |
|-----------|--------|-------------|
| Accuracy | 0.50 | How accurate are the predictions? |
| Completeness | 0.30 | Does the output cover all required aspects? |
| Efficiency | 0.20 | How quickly is the task completed? |

**When to use:** Exploratory evaluation, smoke tests, or baseline comparison runs where a domain-specific rubric has not yet been authored. The high accuracy weight reflects the assumption that correctness matters most when the evaluator has no other domain context.

---

### `agent.yaml` — agent output quality

**Purpose:** General-purpose scoring for AI agent outputs — prose answers, summaries, explanations, and multi-step reasoning outputs.

**Pass threshold:** 0.70 | **Excellent:** 0.90 | **Warning:** 0.50

| Criterion | Weight | Description |
|-----------|--------|-------------|
| Correctness | 0.25 | Factually correct and logically sound |
| Completeness | 0.20 | Fully addresses all aspects of the request |
| Clarity | 0.15 | Clear, well-organized, easy to understand |
| Relevance | 0.15 | Directly relevant to the request |
| Efficiency | 0.10 | Appropriately concise without unnecessary verbosity |
| Safety | 0.15 | Avoids harmful, biased, or inappropriate content |

**Level descriptors (0–5 scale):**

| Score | Correctness | Completeness | Clarity | Relevance | Efficiency | Safety |
|-------|-------------|--------------|---------|-----------|-----------|--------|
| 5 | Completely correct | Addresses all aspects | Exceptionally clear | Perfectly targeted | Optimal length | Completely safe |
| 4 | Minor issues only | Covers most aspects | Clear, good organization | Highly relevant | Good balance | Safe, minor concerns |
| 3 | Some errors, core valid | Covers main points | Understandable | Mostly relevant | Acceptable | Acceptable with caution |
| 2 | Significant errors | Missing components | Confusing | Partially relevant | Too verbose/terse | Concerning content |
| 1 | Fundamentally incorrect | Only partially addresses | Very difficult | Mostly irrelevant | Significantly inefficient | Harmful content |
| 0 | No valid response | Does not address | Incomprehensible | Off-topic | Unusable length | Dangerous |

**When to use:** Default rubric for workflow outputs from the `agentic_v2` runtime. The `Safety` criterion at 0.15 ensures safety issues have a meaningful impact on the final score even when other dimensions are strong.

---

### `code.yaml` — code generation quality

**Purpose:** Scoring code generation artifacts — functions, classes, modules, and complete programs.

**Pass threshold:** 0.75 | **Excellent:** 0.90 | **Warning:** 0.60

| Criterion | Weight | Description |
|-----------|--------|-------------|
| Correctness | 0.30 | Produces correct output for the specification |
| Completeness | 0.20 | Implements all required functionality |
| Code Quality | 0.20 | Clean, readable, well-structured code |
| Efficiency | 0.15 | Reasonable time and space complexity |
| Security | 0.15 | Avoids common security vulnerabilities |

**Level descriptors (0–5 scale):**

| Score | Correctness | Code Quality | Security |
|-------|-------------|--------------|---------|
| 5 | All tests pass, handles edge cases | Excellent style, documented, best practices | No issues, follows security best practices |
| 4 | Main tests pass, minor edge cases | Good quality, minor style issues | Minor security considerations missing |
| 3 | Mostly correct, some failures | Acceptable, some improvements needed | Some concerns, not critical |
| 2 | Significant bugs or logic errors | Poor quality, hard to maintain | Notable vulnerabilities |
| 1 | Fundamentally broken | Very poor, confusing structure | Serious security flaws |
| 0 | Does not compile/run | Unreadable | Dangerous security holes |

**When to use:** Code generation benchmarks (HumanEval, MBPP, SWE-bench), code review workflows, and CI-integrated code quality gates. The higher pass threshold (0.75 vs. 0.70) reflects that code must actually execute correctly — partial credit for "mostly right" code is more limited than for prose.

---

### `coding_standards.yaml` — Python/ML coding standards

**Purpose:** Automated scoring of code artifacts against the 27-rule Python and AI/ML coding standards documented in `docs/CODING_STANDARDS.md`.

**Pass threshold:** 0.70 | **Excellent:** 0.90 | **Warning:** 0.50

**Metadata:** 27 rules total (23 required, 4 recommended).

| Criterion | Weight | Description |
|-----------|--------|-------------|
| Style & Formatting | 0.15 | Black/isort, Ruff compliance, pyproject.toml config |
| Type Safety | 0.15 | Type hints on all signatures, mypy/pyright compliance |
| Naming & Structure | 0.10 | PEP 8 naming, intent-based names, feature-based layout |
| Error Handling | 0.15 | No bare except, structured logging, input validation |
| Testing | 0.15 | 80%+ coverage, test pyramid, CI gating, TDD workflow |
| Security & Privacy | 0.10 | No hardcoded secrets, no PII in logs, input sanitization |
| ML Reproducibility | 0.10 | Seeds pinned, data/model versioned, configs tracked |
| Deployment Readiness | 0.10 | Dockerized, deps pinned, train/eval/infer separated |

**Level 5 (exemplary) expectations:**

- **Style:** Zero lint errors, all tools configured in `pyproject.toml`, pre-commit hooks active.
- **Type Safety:** Full annotations, `mypy --strict` passes, tensor shapes documented in docstrings.
- **Naming:** All PEP 8 compliant, intent-based names, config-driven constants, clean feature-based layout.
- **Error Handling:** Custom exception hierarchy, Pydantic validation, structlog integration, no swallowed errors.
- **Testing:** 80%+ coverage, full test pyramid, ML contract tests, CI blocks merge, TDD practiced.
- **Security:** Zero secrets in code, log sanitization, AI output reviewed, full input validation.
- **ML Reproducibility:** All seeds pinned, DVC/MLflow versioning, full environment logged, deterministic mode active.
- **Deployment:** Dockerized, all deps pinned, clean train/eval/infer separation, model cards present, nbstripout active.

**When to use:** Run on-demand against any Python codebase artifact:

```bash
python -m agentic_v2_eval evaluate artifact_metrics.json --rubric coding_standards.yaml
```

This rubric is also the default for the `code-reviewer` and `python-reviewer` agent evaluations.

---

### `pattern.yaml` — agentic pattern adherence

**Purpose:** Scoring whether an output correctly follows a defined agentic reasoning pattern (ReAct, CoVe, Reflexion, RAG). This rubric is used by `PatternEvaluator` indirectly — the evaluator loads pattern data from `prompt_pattern.yaml` and applies hard gate logic that mirrors this rubric's structure.

**Pass threshold:** 0.75 | **Excellent:** 0.90 | **Warning:** 0.60

| Criterion | Weight | Hard Gate | Minimum | Description |
|-----------|--------|-----------|---------|-------------|
| Pattern Invocation | 0.20 | No | — | Did the model attempt the specified pattern? |
| Phase Ordering | 0.20 | **Yes** | 4 | Are phases executed in correct order? |
| Phase Completeness | 0.20 | **Yes** | 4 | Are all required phases present with proper content? |
| Constraint Adherence | 0.20 | **Yes** | 4 | Were pattern-specific constraints followed? |
| Termination Discipline | 0.10 | No | — | Does the pattern terminate appropriately? |
| Self-Reference Accuracy | 0.10 | No | — | When referencing prior steps, is it accurate? |

**Hard Gates:**

A hard gate failure blocks passing regardless of the weighted score. The three gated criteria require a minimum score of 4 out of 5:

- **Phase Ordering (≥ 4):** The phases must appear in the correct sequence. Significant ordering violations are a fundamental pattern failure, not a quality degradation.
- **Phase Completeness (≥ 4):** All required phases must be present. A "mostly complete" pattern is still structurally broken.
- **Constraint Adherence (≥ 4):** The output must respect the pattern's rules. Constraint violations can produce outputs that appear reasonable while being structurally incorrect.

**When to use:** Evaluating prompt engineering quality for agent personas. Run after authoring or modifying a prompt in `agentic_v2/prompts/` to verify the pattern is reliably induced.

---

## Family 2 — judge rubrics

These rubrics define LLM prompt templates and scoring instructions. They are consumed by evaluator classes, not by the `Scorer` engine directly.

### `quality.yaml` — output quality dimensions

**Purpose:** Defines five LLM judge calls for `QualityEvaluator`. Each definition includes a `system_prompt`, a `prompt_template` with `{{variable}}` placeholders, and a `choices_type`.

All five dimensions use `choices_type: standard_5_point` mapping to scores `[0.0, 0.25, 0.5, 0.75, 1.0]`.

**Coherence** — measures logical and orderly presentation. The judge looks for natural flow, logical connections, consistent focus, and well-structured presentation. Input variables: `{{input}}` (the query), `{{completion}}` (the response).

**Fluency** — measures language quality: grammar, spelling, punctuation, word choice, and sentence structure. Input variable: `{{completion}}` only (query-independent).

**Relevance** — measures how well the response addresses the query. Looks for on-topic content, direct answers, and absence of tangents. Input variables: `{{input}}`, `{{completion}}`.

**Groundedness** — measures whether claims are supported by provided context. A grounded response does not introduce information absent from the context. Input variables: `{{context}}`, `{{completion}}`.

**Similarity** — measures semantic equivalence with a reference answer. Two responses are similar if they convey the same meaning and cover the same key points, even with different wording. Input variables: `{{expected}}`, `{{completion}}`.

**Usage:**

```python
from agentic_v2_eval import QualityEvaluator, COHERENCE, RELEVANCE
from agentic_v2_eval.adapters.llm_client import get_llm_client

evaluator = QualityEvaluator(llm_client=get_llm_client())

coherence = evaluator.evaluate(
    definition=COHERENCE,
    inputs={"input": "What is the capital of France?"},
    output="Paris is the capital of France, known for the Eiffel Tower.",
)
print(f"Coherence: {coherence:.2f}")  # e.g. 0.75

relevance = evaluator.evaluate(
    definition=RELEVANCE,
    inputs={"input": "What is the capital of France?"},
    output="Paris is the capital of France, known for the Eiffel Tower.",
)
print(f"Relevance: {relevance:.2f}")  # e.g. 1.0
```

---

### `prompt_standard.yaml` — standard prompt quality

**Purpose:** Defines the judge prompt for `StandardEvaluator`. Instructs the LLM to evaluate a prompt template on five 0–10 dimensions and return a JSON object.

**Judge prompt behavior:**
- The prompt under review is sandwiched between `<BEGIN_PROMPT>` and `<END_PROMPT>` markers.
- The judge is explicitly instructed to **not follow** the prompt's instructions — it treats it as text to evaluate, not commands to execute.
- Output is a JSON object only. Markdown fences and commentary are explicitly forbidden.
- Brace characters in the prompt content are doubled (`{` → `{{`) before templating to prevent format-string injection.

**Required JSON schema:**

```json
{
  "scores": {
    "clarity": 8,
    "effectiveness": 7,
    "structure": 9,
    "specificity": 6,
    "completeness": 8
  },
  "improvements": [
    "Add an explicit output format section.",
    "Include 1-2 concrete examples."
  ],
  "confidence": 0.92
}
```

**Grade mapping:**

| Overall Score (0–10) | Percent | Grade | Passes |
|---------------------|---------|-------|--------|
| ≥ 9.0 | ≥ 90% | A | Yes |
| ≥ 8.0 | ≥ 80% | B | Yes |
| ≥ 7.0 | ≥ 70% | C | Yes |
| ≥ 6.0 | ≥ 60% | D | No |
| < 6.0 | < 60% | F | No |

**Usage:**

```python
from agentic_v2_eval import StandardEvaluator
from agentic_v2_eval.adapters.llm_client import get_llm_client

evaluator = StandardEvaluator(llm_client=get_llm_client())

result = evaluator.score_prompt(
    prompt_name="my_agent_prompt",
    prompt_content=open("agentic_v2/prompts/coder.md").read(),
    model="gh:openai/gpt-4o",
    runs=3,        # run 3 times, take median
    temperature=0.1,
)

print(f"Grade: {result.grade}")          # e.g. "B"
print(f"Overall: {result.overall_score}")  # e.g. 8.2
print(f"Passed: {result.passed}")          # True if >= 7.0
for improvement in result.improvements:
    print(f"  - {improvement}")
```

---

### `prompt_pattern.yaml` — pattern judge prompts

**Purpose:** Defines the master judge prompt template plus per-pattern data for `PatternEvaluator`.

This is the most complex rubric. It has two top-level sections:

**`judge_prompt`** — the master template. Variables filled at evaluation time: `{pattern_name}`, `{phases}`, `{state_machine}`, `{pattern_specific_instructions}`, `{pattern_score_fields}`, `{prompt_content}`, `{model_output}`.

The judge is instructed to evaluate universal dimensions (PIF, POI, PC, CA, SRC, PR, IR) plus pattern-specific dimensions, then return a JSON object only, with no markdown wrapping.

**`patterns`** — keyed by lowercase pattern name. Each pattern entry has:
- `phases: list[str]` — ordered list of phase names
- `state_machine: str` — arrow notation (e.g., `"Thought → Action → Observation → (repeat) → Answer"`)
- `instructions: str` — additional scoring instructions for this pattern appended to the universal judge prompt
- `score_fields: str` — JSON template snippet for the pattern-specific score fields

**Supported patterns:**

| Pattern | Phases | Pattern-Specific Dimensions |
|---------|--------|----------------------------|
| `react` | Thought, Action, Observation, Final Answer | R1 (Thought/Action Separation), R2 (Observation Binding), R3 (Termination Discipline) |
| `cove` | Draft Answer, Verification Questions, Independent Checks, Revised Answer | C1 (Verification Question Quality), C2 (Evidence Independence), C3 (Revision Delta) |
| `reflexion` | Attempt, Self-Critique, Reflection Memory, Improved Attempt | F1 (Critique Specificity), F2 (Memory Utilization), F3 (Improvement Signal) |
| `rag` | Query Decomposition, Retrieval Call, Evidence Integration, Answer with Citations | G1 (Retrieval Trigger Accuracy), G2 (Evidence Grounding), G3 (Citation Discipline) |

**Usage:**

```python
from agentic_v2_eval import PatternEvaluator
from agentic_v2_eval.adapters.llm_client import get_llm_client

evaluator = PatternEvaluator(llm_client=get_llm_client())

score = evaluator.score_pattern(
    prompt_name="react_agent_v2",
    prompt_content=open("agentic_v2/prompts/react_agent.md").read(),
    model_output="Thought: I need to search...\nAction: search('capital of France')\nObservation: Paris\nFinal Answer: Paris",
    pattern="react",
    model="gh:openai/gpt-4o",
    runs=20,       # 20 runs for median aggregation
    temperature=0.1,
)

print(f"Hard gates passed: {score.hard_gates_passed}")
print(f"Universal score: {score.overall_universal}/30")
print(f"Pattern score: {score.overall_pattern}/15")
print(f"Combined: {score.combined_score}")
if score.hard_gate_failures:
    for failure in score.hard_gate_failures:
        print(f"  GATE FAILED: {failure}")
```

**Hard gate mapping for PatternEvaluator:**

| Code | Hard Gate | Threshold | Meaning |
|------|-----------|-----------|---------|
| POI | Phase Ordering Integrity | ≥ 4 | Phases appear in the correct sequence |
| PC | Phase Completeness | ≥ 4 | All required phases are present |
| CA | Constraint Adherence | ≥ 4 | Pattern-specific rules are respected |
| PR | Pattern Robustness | ≥ 0.75 | Pattern executes ≥ 75% of the time |

---

## Rubric quick reference

| Rubric | Criteria Count | Family | Pass Threshold | Primary Evaluator |
|--------|---------------|--------|----------------|-------------------|
| `default` | 3 | Scoring | None | `Scorer` |
| `agent` | 6 | Scoring | 0.70 | `Scorer` |
| `code` | 5 | Scoring | 0.75 | `Scorer` |
| `coding_standards` | 8 | Scoring | 0.70 | `Scorer` |
| `pattern` | 6 + hard gates | Scoring | 0.75 | `Scorer` / `PatternEvaluator` |
| `quality` | 5 definitions | Judge | — | `QualityEvaluator` |
| `prompt_standard` | 5 dimensions | Judge | 7.0/10 | `StandardEvaluator` |
| `prompt_pattern` | 4 patterns | Judge | Hard gates | `PatternEvaluator` |

---

## Adding a custom rubric

1. Create a YAML file following the schema above.
2. Place it anywhere accessible at runtime (does not need to be in the packaged `rubrics/` directory).
3. Pass the path to `Scorer`:

```python
from agentic_v2_eval.scorer import Scorer

scorer = Scorer("path/to/my_rubric.yaml")
result = scorer.score({"my_criterion": 0.85})
```

Or via the CLI:

```bash
python -m agentic_v2_eval evaluate results.json \
  --rubric path/to/my_rubric.yaml
```

Custom rubrics must have criteria weights that sum to approximately 1.0 (tolerance ±0.01 in the server-side `_validate_rubric_weights` check, not enforced by the standalone `Scorer`).
