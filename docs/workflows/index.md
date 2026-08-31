---
title: Workflow reference
description: Every workflow definition shipped with Agentic Runtime Platform — pattern type, agent count, typical use case, and a link to the source YAML.
tags:
  - workflow
---

# Workflow reference

The runtime ships example workflows and deterministic test fixtures. Each
workflow is a runnable YAML file under
[`agentic-workflows-v2/agentic_v2/workflows/definitions/`](https://github.com/tafreeman/agentic-runtime-platform/tree/main/agentic-workflows-v2/agentic_v2/workflows/definitions).
Use these files as examples for the workflow features they demonstrate. The
[Workflow Authoring Guide](../WORKFLOW_AUTHORING.md) is the complete syntax
reference.

## At a glance

| Workflow | Pattern | Steps | Agents | Typical use case |
|----------|---------|------:|-------:|------------------|
| [`app_improvement_review`](#app_improvement_review) | Evidence-based fan-out / challenge / decision | 11 | 10 | Score an existing app and compare incremental improvement with clean-sheet alternatives |
| [`code_review`](#code_review) | Fan-out / fan-in | 5 | 5 | Multi-perspective review of a single file with synthesis |
| [`bug_resolution`](#bug_resolution) | Sequential with verification | 5 | 4 | Triage → root-cause → fix → regression check → write-up |
| [`fullstack_generation`](#fullstack_generation) | Parallel sub-DAG with rework | 8 | 6 | Generate API + frontend + tests in parallel, then review and rework |
| [`iterative_review`](#iterative_review) | Bounded loop with rework gate | 5 | 4 | Review/rework until quality gate passes or loop_max trips |
| [`conditional_branching`](#conditional_branching) | Conditional fan-out with assembly | 6 | 4 | Branch on requirements; only execute the gates that matter |
| [`consensus_review`](#consensus_review) | Ensemble with majority vote | 5 | 3 | Three independent reviewers vote; summarize only on agreement |
| [`test_deterministic`](#test_deterministic) | Tier-0 placeholder path | 2 | 2 | Smoke test for the executor; no external provider needed in no-LLM mode |
| [`test_workflow`](#test_workflow) | Tier-0 placeholder path | 2 | 2 | Fixture for server and evaluation tests |

**Steps** counts entries under `steps:`. **Agents** counts unique `agent:`
values. **Pattern** names the main control-flow shape.

## `app_improvement_review`

Builds a shared, evidence-cited inventory of an existing application, then
runs six independent reviews in parallel: architecture, product/UX,
reliability/security, delivery/maintainability, performance/cost, and a
clean-sheet rethink. A challenge step removes unsupported claims and preserves
disagreements before the workflow calculates a weighted current-state score,
ranks changes, and produces a phased roadmap with success metrics and kill
criteria. Repository inspection is restricted to read-only tools.

- **Pattern:** Evidence baseline → six-way fan-out → challenge → score → roadmap
- **Steps:** `inventory_app` → (`architecture_lens` ‖ `product_ux_lens` ‖
  `reliability_security_lens` ‖ `delivery_maintainability_lens` ‖
  `performance_cost_lens` ‖ `reinvention_lens`) → `challenge_analysis` →
  `score_and_prioritize` → `build_roadmap` → `assemble_report`
- **Agents:** 10 agent roles across tiers 2 and 3
- **Inputs:** `app_path`, plus optional context, goal, change appetite, and score weights
- **Outputs:** current state, scorecard, recommended direction, ranked changes,
  roadmap, rethink options, evidence gaps, and a complete decision report
- **Rubric:** `app_improvement_review_v1`
- **Use it for:** deciding whether to improve, restructure, or rethink an
  existing application before implementation begins

Run it against the current directory with an input file:

```json
{
  "app_path": ".",
  "app_context": "Internal app used by support engineers",
  "improvement_goal": "Reduce time-to-resolution without weakening controls",
  "change_appetite": "balanced"
}
```

```powershell
agentic validate app_improvement_review
agentic run app_improvement_review --input .\app-review-input.json --output .\app-review-result.json
```

[View YAML →](https://github.com/tafreeman/agentic-runtime-platform/blob/main/agentic-workflows-v2/agentic_v2/workflows/definitions/app_improvement_review.yaml){ .md-button }

## `code_review`

Multi-tier code review with a fan-out / fan-in shape. The first step
parses the source file; three downstream steps run in parallel — style,
complexity, and a tier-2 reviewer; the final step is a tier-2 summarizer
that consolidates the three reviews into a single report.

- **Pattern:** Fan-out / fan-in
- **Steps:** `parse_code` → (`style_check` ‖ `complexity_analysis` ‖ `review_code`) → `generate_summary`
- **Agents:** `tier0_parser`, `tier1_analyzer`, `tier1_linter`, `tier2_reviewer`, `tier2_summarizer`
- **Inputs:** `code_file`, `review_depth`
- **Outputs:** `review`, `summary`
- **Rubric:** `code_review_v1`
- **Use it for:** combining several reviews of one file into one report

[View YAML →](https://github.com/tafreeman/agentic-runtime-platform/blob/main/agentic-workflows-v2/agentic_v2/workflows/definitions/code_review.yaml){ .md-button }

## `bug_resolution`

End-to-end defect resolution: triage classifies the bug, root-cause
analysis isolates the failing module, the fix step generates a code patch,
the regression-check step proposes targeted tests, and the verification
step writes the human-readable report.

- **Pattern:** Sequential with verification
- **Steps:** `triage` → `root_cause_analysis` → `generate_fix` → `regression_check` → `generate_verification`
- **Agents:** `tier0_parser`, `tier1_analyzer`, `tier2_reviewer`, `tier2_summarizer`
- **Inputs:** `bug_report`, `code_file`, `resolution_depth`
- **Outputs:** `root_cause`, `fix`, `verification_report`
- **Rubric:** `bug_resolution_v1`
- **Use it for:** tracing a reported defect through diagnosis, a proposed fix,
  regression checks, and a final report

[View YAML →](https://github.com/tafreeman/agentic-runtime-platform/blob/main/agentic-workflows-v2/agentic_v2/workflows/definitions/bug_resolution.yaml){ .md-button }

## `fullstack_generation`

After an architecture step, four generators run in parallel for the API,
frontend, migrations, and integration tests. A reviewer checks their output.
A rework step handles review findings before the final assembly step packages
the result.

- **Pattern:** Parallel sub-DAG with rework
- **Steps:** `design_architecture` → (`generate_api` ‖ `generate_frontend` ‖ `generate_migrations` ‖ `generate_integration_tests`) → `review_code` → `developer_rework` → `assemble_feature`
- **Agents:** `tier1_assembler`, `tier1_generator`, `tier2_coder`, `tier2_tester`, `tier3_architect`, `tier3_reviewer`
- **Inputs:** `feature_spec`, `tech_stack`
- **Outputs:** `feature_package`, `review_report`, `all_code`
- **Rubric:** `fullstack_generation_v1`
- **Use it for:** testing a full-stack generation flow with parallel work,
  review, rework, and packaging

[View YAML →](https://github.com/tafreeman/agentic-runtime-platform/blob/main/agentic-workflows-v2/agentic_v2/workflows/definitions/fullstack_generation.yaml){ .md-button }

## `iterative_review`

Demonstrates `loop_until:` and `loop_max:`. The review step runs again until
it approves the work or reaches the configured round limit. An
`escalation_notice` step runs when the loop ends without approval.

- **Pattern:** Bounded loop with rework gate
- **Steps:** `design` → `implement` → `review_rework_loop` (looped) → `escalation_notice` → `package`
- **Agents:** `tier1_assembler`, `tier2_coder`, `tier3_architect`, `tier3_reviewer`
- **Inputs:** `feature_spec`, `max_review_rounds`
- **Outputs:** `final_package`, `review_history`
- **Use it for:** limiting review and rework to a known number of rounds

[View YAML →](https://github.com/tafreeman/agentic-runtime-platform/blob/main/agentic-workflows-v2/agentic_v2/workflows/definitions/iterative_review.yaml){ .md-button }

## `conditional_branching`

Demonstrates the `when:` condition. After parsing requirements, the workflow
chooses a quick or thorough review path. Production targets also run a
deployment-readiness step. The final step combines the outputs from whichever
branches ran.

- **Pattern:** Conditional fan-out with assembly
- **Steps:** `parse_requirements` → (`quick_review` | `deep_analysis` | `security_scan` | `deployment_readiness`)* → `assemble_report`
- **Agents:** `tier1_assembler`, `tier2_coder`, `tier3_architect`, `tier3_reviewer`
- **Inputs:** `feature_spec`, `review_depth`, `target_env`
- **Outputs:** `analysis_report`
- **Use it for:** selecting steps from input values without maintaining
  several similar workflow files

[View YAML →](https://github.com/tafreeman/agentic-runtime-platform/blob/main/agentic-workflows-v2/agentic_v2/workflows/definitions/conditional_branching.yaml){ .md-button }

## `consensus_review`

Three tier-2 reviewers answer the same prompt in parallel. A deterministic
tier-0 agent selects the majority verdict. The final summary runs only when
the vote meets the `min_agreement` threshold, which defaults to `0.66`.

- **Pattern:** Ensemble with majority vote
- **Steps:** (`reviewer_a` ‖ `reviewer_b` ‖ `reviewer_c`) → `vote` →
  `summarize` (gated on `meets_threshold`)
- **Agents:** `tier0_consensus`, `tier2_reviewer`, `tier2_summarizer`
- **Inputs:** `code_file`, `min_agreement`
- **Outputs:** `verdict`, `agreement`, `summary` (optional)
- **Use it for:** requiring agreement from several independent reviews before
  producing a summary

[View YAML →](https://github.com/tafreeman/agentic-runtime-platform/blob/main/agentic-workflows-v2/agentic_v2/workflows/definitions/consensus_review.yaml){ .md-button }

## `test_deterministic`

The smallest workflow has two steps with two tier-0 agents. In the current
native execution path, those agents still pass through the model-client loop.
With `AGENTIC_NO_LLM=1`, the loop returns placeholder values without calling an
external provider. The fixture is used to exercise the executor, contract
validator, and run recorder. It is also the workflow the
[Quick Start](../getting-started/quickstart.md) page asks you to run
first.

- **Pattern:** Tier-0 placeholder path
- **Steps:** `step1` → `step2`
- **Agents:** `tier0_counter`, `tier0_process`
- **Inputs:** `input_text` (required)
- **Outputs:** `processed_text`, `step_count`
- **Use it for:** checking a fresh installation without provider credentials

[View YAML →](https://github.com/tafreeman/agentic-runtime-platform/blob/main/agentic-workflows-v2/agentic_v2/workflows/definitions/test_deterministic.yaml){ .md-button }

## `test_workflow`

A test fixture that mirrors `test_deterministic` — the same two tier-0
steps (process, then count) — but with `input_text` optional and
defaulting to an empty string, so server and evaluation tests can run it
with no inputs at all.

- **Pattern:** Tier-0 only (no LLM)
- **Steps:** `step1` → `step2`
- **Agents:** `tier0_counter`, `tier0_process`
- **Inputs:** `input_text` (optional, default `""`)
- **Outputs:** `processed_text`, `step_count`
- **Use it for:** server and evaluation tests that need no input or provider
  credentials

[View YAML →](https://github.com/tafreeman/agentic-runtime-platform/blob/main/agentic-workflows-v2/agentic_v2/workflows/definitions/test_workflow.yaml){ .md-button }

## What to read next

- **[Workflow Authoring Guide](../WORKFLOW_AUTHORING.md)** — full grammar
  reference (steps, expressions, conditionals, loops, tools)
- **[Pattern Catalog](../PATTERN_CATALOG.md)** — reusable agentic patterns
  with worked examples
- **[First Workflow](../getting-started/first-workflow.md)** —
  step-by-step tutorial for writing your own definition
- **[Architecture — Runtime](../architecture-runtime.md)** — what the
  executor does with these definitions at runtime
