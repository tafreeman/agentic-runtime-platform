# Workflow authoring guide

This guide explains how to write, validate, and run a YAML workflow.

## Overview

Workflows are YAML files that define steps and the dependencies between them.
Each step runs either deterministic Python or a model-backed agent. A step can
read workflow inputs and the outputs of earlier steps. The executor runs a step
as soon as its dependencies are complete, up to its concurrency limit.

Workflow definitions live in:

```
agentic-workflows-v2/agentic_v2/workflows/definitions/*.yaml
```

At runtime:

1. `WorkflowLoader` parses the YAML and builds the dependency graph.
2. `WorkflowRunner` checks required inputs and allowed enum values.
3. The executor schedules steps, dependencies, conditions, and bounded loops.
4. `ExpressionEvaluator` resolves `${...}` references.
5. The runner maps step results to the workflow's declared outputs.

---

## Workflow structure

A workflow YAML file has these top-level keys:

| Key | Required | Description |
|---|---|---|
| `name` | No | Workflow identifier; defaults to the filename |
| `version` | No | Version string; defaults to `"1.0"` |
| `description` | No | Short explanation of the workflow |
| `inputs` | No | Input parameter declarations |
| `outputs` | No | Mappings from step results to workflow outputs |
| `steps` | Yes | Non-empty list of executable steps |
| `capabilities` | No | Input/output name lists for dataset-workflow compatibility matching |
| `evaluation` | No | Inline rubric for scoring workflow quality |
| `experimental` | No | Boolean flag; when `true`, the workflow is hidden from `list_workflows()` by default |
| `_templates` | No | YAML anchor definitions for DRY step templates (ignored by loader) |
| `tools` | No | Workflow-level tool declarations (tool type, tier) |

### Minimal skeleton

```yaml
name: my_workflow
description: A short description of what this workflow does
version: "1.0"

inputs:
  topic:
    type: string
    description: The research topic
    required: true

steps:
  - name: step_one
    agent: tier2_coder
    description: Generate code from the topic
    inputs:
      topic: ${inputs.topic}
    outputs:
      code: generated_code

outputs:
  code:
    from: ${steps.step_one.outputs.code}
```

---

## Input declarations

Each key under `inputs:` declares a workflow parameter. The loader validates supplied values at runtime and applies defaults.

```yaml
inputs:
  feature_spec:
    type: string                     # string | number | object | array
    description: Natural language description of the feature
    required: true                   # default: true

  review_depth:
    type: string
    enum: [quick, standard, deep]    # constrain to allowed values
    default: standard                # applied when caller omits this input

  config:
    type: object
    description: Configuration object
    default:
      frontend: react
      backend: fastapi

  seed_urls:
    type: array
    description: Optional URLs to seed retrieval
    required: false
    default: []
```

`type` is descriptive metadata; the runner does not enforce it. Shipped
definitions use values such as `string`, `integer`, `number`, `object`, and
`array`. Runtime input validation enforces required values and `enum`
constraints.

---

## Output declarations

Each key under `outputs:` maps a workflow-level output name to a `from:` expression that resolves against step results.

```yaml
outputs:
  # Simple: single expression
  review:
    from: ${steps.review_code.outputs.review}

  # Optional outputs resolve to null without error when the source step was skipped
  summary:
    from: ${steps.generate_summary.outputs.summary}
    optional: true

  # Composite: map of expressions assembled into a single dict
  all_code:
    from:
      backend: ${coalesce(steps.rework.outputs.backend, steps.generate.outputs.backend)}
      frontend: ${steps.generate.outputs.frontend}
```

---

## Step definition

Each entry in `steps:` defines a DAG node. The required and optional fields are:

| Field | Required | Type | Description |
|---|---|---|---|
| `name` | Yes | string | Unique step identifier within this workflow |
| `agent` | Yes | string | Agent name in `tier{N}_{role}` format (e.g. `tier2_coder`) |
| `description` | No | string | What this step does; model-backed steps receive it as task context |
| `inputs` | No | mapping | Maps step-local input names to values or `${...}` expressions |
| `outputs` | No | mapping | Maps step output keys to context variable names |
| `input_contracts` | No | mapping | Validates opted-in step inputs before invocation |
| `output_contracts` | No | mapping | Validates and normalizes opted-in outputs before success |
| `depends_on` | No | list | Step names that must complete before this step runs |
| `when` | No | string | Boolean `${...}` expression; step runs only if `true` |
| `tools` | No | list | Explicit tool allowlist (omit for tier-default tools) |
| `prompt_file` | No | string | Override persona prompt file (relative to `prompts/`) |
| `model_override` | No | string | Pin a specific model, e.g. `gemini:gemini-2.5-flash` |
| `loop_until` | No | string | `${...}` expression; step re-executes until `true` |
| `loop_max` | No | integer | Max loop iterations (default: 3) |

### Complete annotated example

```yaml
steps:
  - name: review_code                        # unique step ID
    agent: tier3_reviewer                    # LLM tier 3, reviewer role
    description: >-                          # multiline YAML string
      Review all generated code for correctness,
      security, and style compliance.
    prompt_file: reviewer.md                 # optional persona override
    tools: [file_read, grep, code_analysis]  # explicit tool allowlist
    depends_on: [generate_api, generate_frontend]  # wait for both
    when: ${inputs.review_depth} != 'quick'  # conditional execution
    inputs:
      backend: ${steps.generate_api.outputs.api_code}
      frontend: ${steps.generate_frontend.outputs.ui_code}
    outputs:
      review_report: code_review             # stored in context as "code_review"
      suggested_fixes: fixes
```

### Typed artifact contracts

Step input/output mappings normally enforce names only. For generated code,
opt into semantic validation with `input_contracts` and `output_contracts`:

```yaml
steps:
  - name: generate_api
    agent: tier2_coder
    description: >-
      Generate the API. Return backend_code as a non-empty
      relative-path-to-source file map.
    outputs:
      backend_code: backend_code
    output_contracts:
      backend_code:
        kind: code_artifact
        required: true
        aliases: [api_code]  # parse-only checkpoint migration alias

  - name: review_code
    agent: tier3_reviewer
    depends_on: [generate_api]
    inputs:
      backend: ${coalesce(
        steps.generate_api.outputs.backend_code,
        steps.generate_api.outputs.api_code
      )}
    input_contracts:
      backend:
        kind: code_artifact
        required: true
    outputs:
      review_report: review_report
```

`code_artifact` accepts a non-empty mapping of safe relative file paths to
non-blank source strings, or one or more complete `FILE`/`ENDFILE` blocks. It
rejects absolute/traversal paths, empty content, placeholders, refusals, and
reference-only prose.

Use one canonical output name in `outputs`. A contract alias is read only for
legacy response/checkpoint compatibility and is not requested from the model.
A valid canonical value always wins; an alias is promoted only if the
canonical value is absent or invalid and the alias validates independently.
Put the canonical expression first in downstream `coalesce()` calls. The
contract, not `coalesce()`, decides whether content is usable.

Contracts are optional, so workflows without them retain key-only behavior.
Currently `code_artifact` is the only supported kind. This inline content
contract does not implement the run-scoped path materialization proposed by
[ADR-034](adr/ADR-034-path-first-workflow-io-contracts.md); see
[ADR-052](adr/ADR-052-typed-step-artifact-contracts.md) for the bounded
decision.

### Agent naming convention

Agent names follow the pattern `tier{N}_{role}`:

| Tier | Behavior | Token limit | Example agents |
|---|---|---|---|
| `tier0` | Deterministic Python (no LLM call) | 0 | `tier0_parser` |
| `tier1` | Lightweight LLM | 4,096 | `tier1_linter`, `tier1_assembler` |
| `tier2` | Balanced LLM | 8,192 | `tier2_coder`, `tier2_reviewer` |
| `tier3` | Strong LLM | 16,384 | `tier3_architect`, `tier3_reviewer` |
| `tier4` | Heavy LLM | 16,384 | (hypothetical, e.g. `tier4_writer`) |
| `tier5` | Maximum capability | 32,768 | (hypothetical, e.g. `tier5_synthesizer`) |

The resolver recognizes the `tier4_` and `tier5_` prefixes, but no shipped workflow currently uses a tier-4 or tier-5 agent.

The role suffix (e.g. `coder`, `reviewer`) maps to a persona prompt file in `agentic_v2/prompts/{role}.md`. If no matching file exists, the loader falls back to `prompts/default.md`; since no `default.md` ships with the runtime, the agent then runs without a persona prompt — only the engine's inline output-format instructions.

---

## Expression language

The engine supports `${...}` expressions for variable references, the
`coalesce()` function, and conditions. `ExpressionEvaluator` accepts only a
small set of expression elements and rejects imports, arbitrary function calls,
and access to names that start with `__`.

### Variable references

Reference workflow inputs and step outputs using dotted paths:

```yaml
# Workflow inputs
topic: ${inputs.topic}

# Step outputs (most common form)
ast: ${steps.parse_code.outputs.ast}

# Nested access
status: ${steps.review_code.outputs.review_report.overall_status}
```

### The `coalesce()` function

Returns the first non-null argument -- essential for conditional/bounded workflows where some steps may have been skipped:

```yaml
# Pick the latest available evidence, falling back through rounds
evidence: ${coalesce(
  steps.round3.outputs.evidence,
  steps.round2.outputs.evidence,
  steps.round1.outputs.evidence
)}
```

### Boolean logic in `when:` conditions

The `when:` field accepts boolean expressions. Steps with a `when:` that evaluates to `false` are skipped.

```yaml
# Equality / inequality
when: ${inputs.review_depth} != 'quick'

# List membership
when: ${steps.review_code.outputs.overall_status} not in ['APPROVED', 'APPROVED_WITH_NOTES']

# Boolean operators (and, or, not)
when: ${inputs.max_rounds} >= 2 and not ${steps.audit_round1.outputs.gate_passed}

# Compound conditions
when: >-
  ${steps.review_r1.outputs.overall_status} not in ['APPROVED', 'APPROVED_WITH_NOTES']
  and ${steps.review_r2.outputs.overall_status} not in ['APPROVED', 'APPROVED_WITH_NOTES']
```

### Null-safe chaining

When a step is skipped (its `when:` evaluated to `false`), accessing its outputs does not raise an error. The engine uses a `_NullSafe` sentinel that:

- Returns `_NullSafe()` for any attribute access (allows deep chaining)
- Evaluates to `False` in boolean context
- Equals `None` in comparisons
- Is filtered out by `coalesce()` (treated as null)

This means expressions like `${steps.skipped_step.outputs.some_value}` safely resolve to `None` instead of crashing.

### Supported operators

| Category | Operators |
|---|---|
| Comparison | `==`, `!=`, `<`, `<=`, `>`, `>=` |
| Membership | `in`, `not in` |
| Boolean | `and`, `or`, `not` |
| Arithmetic | `+`, `-`, `*`, `/`, `%` |
| Identity | `is`, `is not` |

### Expression restrictions

The evaluator parses each expression and rejects elements outside its
allowlist. In particular:

- No imports or module access
- No function calls except `coalesce()`
- No attribute assignment
- No lambda, comprehension, or generator expressions
- Built-in Python functions are not available

---

## Execution patterns

### Sequential (depends_on chaining)

Steps run one after another. Each step waits for its dependency to complete.

```yaml
steps:
  - name: parse
    agent: tier0_parser
    description: Parse the input code
    inputs:
      file_path: ${inputs.code_file}
    outputs:
      ast: parsed_ast

  - name: analyze
    agent: tier1_analyzer
    description: Analyze code complexity
    depends_on: [parse]
    inputs:
      ast: ${steps.parse.outputs.ast}
    outputs:
      report: complexity_report

  - name: summarize
    agent: tier2_summarizer
    description: Produce human-readable summary
    depends_on: [analyze]
    inputs:
      report: ${steps.analyze.outputs.report}
    outputs:
      summary: final_summary
```

Execution: `parse` -> `analyze` -> `summarize`

### Fan-out / fan-in (parallel steps merging)

Multiple steps with the same dependency run in parallel. A downstream step waits for all of them.

```yaml
steps:
  - name: design
    agent: tier3_architect
    description: Design the system architecture
    inputs:
      spec: ${inputs.feature_spec}
    outputs:
      api_spec: api_design
      db_schema: database_schema
      components: frontend_components

  # These three run IN PARALLEL (all depend only on design)
  - name: generate_api
    agent: tier2_coder
    description: Generate backend API
    depends_on: [design]
    inputs:
      api_spec: ${steps.design.outputs.api_spec}
    outputs:
      api_code: backend_code

  - name: generate_frontend
    agent: tier2_coder
    description: Generate frontend components
    depends_on: [design]
    inputs:
      components: ${steps.design.outputs.components}
    outputs:
      ui_code: frontend_code

  - name: generate_migrations
    agent: tier1_generator
    description: Generate database migrations
    depends_on: [design]
    inputs:
      schema: ${steps.design.outputs.db_schema}
    outputs:
      migrations: db_migrations

  # Fan-in: waits for ALL parallel steps
  - name: integrate
    agent: tier2_tester
    description: Generate integration tests
    depends_on: [generate_api, generate_frontend, generate_migrations]
    inputs:
      backend: ${steps.generate_api.outputs.api_code}
      frontend: ${steps.generate_frontend.outputs.ui_code}
      migrations: ${steps.generate_migrations.outputs.migrations}
    outputs:
      tests: integration_tests
```

Execution:

```
design ──┬── generate_api ────────┐
         ├── generate_frontend ───┤── integrate
         └── generate_migrations ─┘
```

### Bounded iteration (loop_until + loop_max)

A step re-executes until a condition is met or the iteration cap is reached. Used for QA rework loops.

```yaml
- name: qa_rework_loop
  agent: tier2_coder
  description: Run tests, review, and rework until passing
  depends_on: [build_verify]
  loop_until: >-
    ${steps.qa_rework_loop.outputs.review_report.overall_status} in ['APPROVED']
    and ${steps.qa_rework_loop.outputs.overall_test_status} in ['PASS']
  loop_max: 2
  inputs:
    backend: ${steps.implement_backend.outputs.backend_code}
    tests: ${steps.scaffold_tests.outputs.test_stubs}
  outputs:
    backend_code: qa_backend
    review_report: qa_review
    overall_test_status: qa_status
```

### Conditional execution (when: expressions)

Steps with a `when:` condition are skipped (status = `SKIPPED`) when the condition evaluates to `false`. Downstream steps that depend on a skipped step still run -- the skipped step's outputs resolve to `None`.

```yaml
# Only run deep analysis when depth is not "quick"
- name: regression_check
  agent: tier1_analyzer
  description: Analyze the fix for regressions
  depends_on: [generate_fix]
  when: ${inputs.resolution_depth} != 'quick'
  inputs:
    fix: ${steps.generate_fix.outputs.fix}
  outputs:
    regression_risks: regression_risks

# Conditional rework: only if review did NOT approve
- name: developer_rework
  agent: tier2_coder
  description: Rework code from review feedback
  depends_on: [review_code]
  when: ${steps.review_code.outputs.overall_status} not in ['APPROVED', 'APPROVED_WITH_NOTES']
  inputs:
    backend: ${steps.generate_api.outputs.api_code}
    review_report: ${steps.review_code.outputs.raw_response}
  outputs:
    backend_code: reworked_backend
```

### DAG (complex dependency graphs)

Real workflows combine all patterns. The shipped `fullstack_generation` workflow, for example, uses:

- A sequential setup stage (`design_architecture` runs first, with no dependencies)
- Fan-out (`generate_api`, `generate_frontend`, and `generate_migrations` all depend only on `design_architecture` and run in parallel)
- Staged fan-in (`generate_integration_tests` waits on `generate_api` + `generate_frontend`; `review_code` waits on all four generation steps)
- A conditional rework pass (`developer_rework` runs only `when:` the review's `overall_status` is not `'APPROVED'`)
- `coalesce()` throughout its inputs and outputs to fall back across alternate output keys and skipped steps

---

## Advanced features

### YAML anchors for DRY templates

Use YAML anchors (`&name`) and merge keys (`<<: *name`) to avoid repeating agent/tool configurations across similar steps. The loader ignores the `_templates` top-level key; PyYAML resolves merges before the dict reaches Python.

```yaml
_templates:
  retrieval_step: &retrieval_step
    agent: tier2_researcher
    tools: [web_search, http_get, context_store]

  verify_step: &verify_step
    agent: tier3_reviewer
    tools: [web_search, http_get, context_store]

steps:
  - <<: *retrieval_step
    name: retrieval_round1
    description: Gather evidence (round 1)
    depends_on: [plan_round1]
    inputs:
      search_plan: ${steps.plan_round1.outputs.search_plan}
    outputs:
      evidence: evidence_round1

  - <<: *retrieval_step
    name: retrieval_round2
    description: Gather evidence (round 2)
    depends_on: [plan_round2]
    inputs:
      search_plan: ${steps.plan_round2.outputs.search_plan}
    outputs:
      evidence: evidence_round2
```

Each step inherits `agent` and `tools` from the anchor but defines its own `name`, `description`, `depends_on`, `inputs`, and `outputs`.

### Inline evaluation rubrics

Workflows can embed scoring rubrics for automated quality assessment. Each criterion defines a 1-5 scale, weight, and critical floor. This excerpt is taken from the shipped `code_review.yaml` (the full file declares four criteria — `correctness_rubric`, `code_quality`, `efficiency`, `documentation` — whose weights sum to 1.0):

```yaml
evaluation:
  rubric_id: code_review_v1
  scoring_profile: B
  criteria:
    - name: correctness_rubric
      definition: Review output correctness and requirement alignment.
      evidence_required:
        - Requirement-to-review mapping
        - No contradiction with code facts
      scale:
        "1": Major requirement failures
        "2": Multiple significant errors
        "3": Minimum acceptable correctness
        "4": Accurate with minor issues
        "5": Fully correct and robust
      weight: 0.35
      critical_floor: 0.70
      formula_id: zero_one

    - name: code_quality
      definition: Quality and actionability of code feedback.
      evidence_required:
        - Specific issues identified
      scale:
        "1": No useful quality feedback
        "2": Limited quality feedback
        "3": Basic actionable feedback
        "4": Strong actionable feedback
        "5": Comprehensive high-value feedback
      weight: 0.30
      critical_floor: 0.80
      formula_id: zero_one
```

**Rules:**
- Criterion weights must sum to 1.0 (+/- 0.01).
- `critical_floor` must be in `[0.0, 1.0]`.
- `formula_id` must be a registered normalization formula (e.g. `zero_one`).

### Agent tier and model override

The agent tier is inferred from the `tier{N}_` prefix in the agent name. To pin a specific model for a step, use `model_override`:

```yaml
- name: review_code
  agent: tier3_reviewer
  model_override: env:REVIEW_MODEL|gemini:gemini-2.5-flash
  description: Review generated code with a pinned model
```

The `model_override` format supports environment variable resolution with a fallback:

```
env:ENV_VAR_NAME|provider:model_name
```

If the environment variable is set, its value is used. Otherwise, the fallback after `|` is used.

### Tool allowlisting per step

By default, a step can use all tools available at its tier level. To restrict to specific tools, use the `tools:` field:

```yaml
- name: retrieval
  agent: tier2_researcher
  tools: [web_search, http_get, context_store]  # only these three
  # ...

- name: analysis
  agent: tier3_analyst
  tools: [context_store]  # read-only access to context
  # ...
```

Omitting `tools:` allows all tools at or below the step's tier. Setting `tools: []` disables all tools.

### Prompt file override

Override the default persona prompt (derived from the agent role) with a specific Markdown file:

```yaml
- name: implement_shared
  agent: tier2_coder
  prompt_file: reviewer.md   # uses prompts/reviewer.md instead of prompts/coder.md
```

### Capabilities metadata

The `capabilities` block lists the workflow's input/output names for compatibility matching with datasets:

```yaml
capabilities:
  inputs: [feature_spec, tech_stack]
  outputs: [feature_package, review_report, all_code]
```

This is used by the evaluation framework to match workflows to compatible datasets.

---

## Validation

Validate a workflow YAML file before running it:

```bash
agentic validate <workflow_name>
```

The validation pipeline checks:

1. YAML syntax and the top-level mapping.
2. At least one executable step for a non-experimental workflow.
3. Step names and resolvable agents.
4. Dependency names and dependency cycles.
5. Artifact-contract configuration.
6. Evaluation weights, floors, and normalization formula names.

Programmatic validation:

```python
from agentic_v2.workflows.loader import WorkflowLoader

loader = WorkflowLoader()
workflow = loader.load("my_workflow")
workflow.dag.validate()  # raises on structural errors
```

---

## Examples

### Example 1: Simple 2-step sequential

A minimal workflow that parses a code file and produces a complexity report.

```yaml
name: simple_analysis
description: Parse a code file and report its complexity metrics
version: "1.0"

inputs:
  code_file:
    type: string
    description: Path to the source file to analyze
    required: true

steps:
  - name: parse
    agent: tier0_parser
    description: Parse and extract code structure
    inputs:
      file_path: ${inputs.code_file}
    outputs:
      ast: parsed_ast
      metrics: code_metrics

  - name: report
    agent: tier1_analyzer
    description: Produce a human-readable complexity report
    depends_on: [parse]
    inputs:
      ast: ${steps.parse.outputs.ast}
      metrics: ${steps.parse.outputs.metrics}
    outputs:
      report: complexity_report

outputs:
  report:
    from: ${steps.report.outputs.report}
```

### Example 2: 3-step fan-out with merge

Three specialist agents analyze a codebase in parallel, then a synthesis step merges their findings.

```yaml
name: parallel_review
description: Run security, performance, and style analysis in parallel then merge
version: "1.0"

inputs:
  code_file:
    type: string
    description: Path to the source file
    required: true

steps:
  - name: parse
    agent: tier0_parser
    description: Parse the source file
    inputs:
      file_path: ${inputs.code_file}
    outputs:
      ast: parsed_ast

  - name: security_scan
    agent: tier2_reviewer
    description: Analyze code for security vulnerabilities
    depends_on: [parse]
    tools: [file_read, grep]
    inputs:
      ast: ${steps.parse.outputs.ast}
    outputs:
      findings: security_findings

  - name: perf_analysis
    agent: tier2_reviewer
    description: Identify performance bottlenecks
    depends_on: [parse]
    tools: [file_read, code_analysis]
    inputs:
      ast: ${steps.parse.outputs.ast}
    outputs:
      findings: perf_findings

  - name: style_check
    agent: tier1_linter
    description: Check code style and formatting
    depends_on: [parse]
    inputs:
      ast: ${steps.parse.outputs.ast}
    outputs:
      issues: style_issues

  - name: synthesize
    agent: tier2_summarizer
    description: Merge all analysis results into a unified report
    depends_on: [security_scan, perf_analysis, style_check]
    inputs:
      security: ${steps.security_scan.outputs.findings}
      performance: ${steps.perf_analysis.outputs.findings}
      style: ${steps.style_check.outputs.issues}
    outputs:
      report: unified_report

outputs:
  report:
    from: ${steps.synthesize.outputs.report}
```

### Example 3: Bounded review cycle with conditional rework

A code generation workflow with up to 2 review-rework passes. If the first review approves, no rework happens. Otherwise, rework is applied and a second review runs. The final assembly always picks the best available code via `coalesce()`.

```yaml
name: codegen_with_review
description: Generate code with bounded review cycle (max 2 passes)
version: "1.0"

inputs:
  feature_spec:
    type: string
    description: Feature description
    required: true

steps:
  # Phase 1: Generate
  - name: generate
    agent: tier2_coder
    description: Generate code from the feature spec
    inputs:
      spec: ${inputs.feature_spec}
    outputs:
      code: generated_code

  # Phase 2: Review pass 1
  - name: review_pass1
    agent: tier3_reviewer
    description: Review generated code (pass 1)
    depends_on: [generate]
    inputs:
      code: ${steps.generate.outputs.code}
    outputs:
      review_report: review_r1
      suggested_fixes: fixes_r1

  # Phase 3: Conditional rework (only if not approved)
  - name: rework
    agent: tier2_coder
    description: Apply fixes from review feedback
    depends_on: [review_pass1]
    when: ${steps.review_pass1.outputs.overall_status} not in ['APPROVED', 'APPROVED_WITH_NOTES']
    inputs:
      code: ${steps.generate.outputs.code}
      review_report: ${steps.review_pass1.outputs.review_report}
      fixes: ${steps.review_pass1.outputs.suggested_fixes}
    outputs:
      code: reworked_code

  # Phase 4: Review pass 2 (only if rework happened)
  - name: review_pass2
    agent: tier3_reviewer
    description: Re-review after rework (pass 2)
    depends_on: [rework]
    when: ${steps.review_pass1.outputs.overall_status} not in ['APPROVED', 'APPROVED_WITH_NOTES']
    inputs:
      code: ${coalesce(steps.rework.outputs.code, steps.generate.outputs.code)}
      previous_review: ${steps.review_pass1.outputs.review_report}
    outputs:
      review_report: review_r2

  # Phase 5: Final assembly (always runs)
  - name: assemble
    agent: tier1_assembler
    description: Assemble the final deliverable from best available code
    depends_on: [review_pass1, review_pass2]
    inputs:
      code: ${coalesce(steps.rework.outputs.code, steps.generate.outputs.code)}
      review: ${coalesce(steps.review_pass2.outputs.review_report, steps.review_pass1.outputs.review_report)}
    outputs:
      package: final_package

outputs:
  package:
    from: ${steps.assemble.outputs.package}
  review_status:
    from: ${coalesce(steps.review_pass2.outputs.review_report, steps.review_pass1.outputs.review_report)}
    optional: true
```

Execution flow:

```
generate -> review_pass1 ─┬─ [APPROVED]     -> assemble
                          └─ [NOT APPROVED] -> rework -> review_pass2 -> assemble
```

---

## Quick reference

### Running a workflow

```bash
# CLI
agentic run <workflow_name> --input params.json
agentic validate <workflow_name>
agentic list workflows

# Python
from agentic_v2.workflows.runner import run_workflow

result = await run_workflow("code_review", code_file="main.py")
```

### Checklist for new workflows

- [ ] `name` matches the YAML filename (recommended for clear CLI output)
- [ ] Every step has `name`, `agent`, `description`, `inputs`, `outputs`
- [ ] All `depends_on` targets are valid step names
- [ ] No dependency cycles
- [ ] `when:` conditions use valid `${...}` expression syntax
- [ ] `coalesce()` is used wherever a step may have been skipped
- [ ] Evaluation criterion weights sum to 1.0 (if `evaluation:` is present)
- [ ] Validated with `agentic validate <workflow_name>` before committing
