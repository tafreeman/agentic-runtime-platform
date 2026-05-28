---
title: Workflow Reference
description: Every production workflow shipped with Agentic Runtime Platform — pattern type, agent count, typical use case, and a link to the source YAML.
tags:
  - workflow
---

# Workflow Reference

Six workflow definitions ship with the runtime today. Each is a real,
runnable YAML file under
[`agentic-workflows-v2/agentic_v2/workflows/definitions/`](https://github.com/tafreeman/agentic-runtime-platform/tree/main/agentic-workflows-v2/agentic_v2/workflows/definitions).
They are deployed alongside the runtime and exercised by the test suite, so
they double as the canonical examples for every grammar feature the engine
supports.

## At a glance

| Workflow | Pattern | Steps | Agents | Typical use case |
|----------|---------|------:|-------:|------------------|
| [`code_review`](#code_review) | Fan-out / fan-in | 5 | 5 | Multi-perspective review of a single file with synthesis |
| [`bug_resolution`](#bug_resolution) | Sequential with verification | 5 | 4 | Triage → root-cause → fix → regression check → write-up |
| [`fullstack_generation`](#fullstack_generation) | Parallel sub-DAG with rework | 8 | 6 | Generate API + frontend + tests in parallel, then review and rework |
| [`iterative_review`](#iterative_review) | Bounded loop with rework gate | 5 | 4 | Review/rework until quality gate passes or loop_max trips |
| [`conditional_branching`](#conditional_branching) | Conditional fan-out with assembly | 6 | 4 | Branch on requirements; only execute the gates that matter |
| [`test_deterministic`](#test_deterministic) | Tier-0 only (no LLM) | 3 | 2 | Smoke test for the executor itself; no provider needed |

The columns mean exactly what they appear to mean: **Steps** counts entries
under `steps:`; **Agents** counts the unique `agent:` values referenced; and
**Pattern** is the dominant control-flow shape — every workflow combines
features, but each leans on one shape more than the others.

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
- **When to reach for it:** you want multiple specialist perspectives on a
  single artifact and a synthesized verdict, not three independent reports

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
- **When to reach for it:** you have a stack trace or repro and you want a
  scored, auditable trail from observation to fix

[View YAML →](https://github.com/tafreeman/agentic-runtime-platform/blob/main/agentic-workflows-v2/agentic_v2/workflows/definitions/bug_resolution.yaml){ .md-button }

## `fullstack_generation`

The widest workflow shipped with the runtime. After an architect designs
the feature, four generators run in parallel — API, frontend, migrations,
integration tests — and feed into a tier-3 reviewer. If the reviewer
flags issues, a `developer_rework` step kicks in before the final
assembler packages the artifact bundle.

- **Pattern:** Parallel sub-DAG with rework
- **Steps:** `design_architecture` → (`generate_api` ‖ `generate_frontend` ‖ `generate_migrations` ‖ `generate_integration_tests`) → `review_code` → `developer_rework` → `assemble_feature`
- **Agents:** `tier1_assembler`, `tier1_generator`, `tier2_coder`, `tier2_tester`, `tier3_architect`, `tier3_reviewer`
- **Inputs:** `feature_spec`, `tech_stack`
- **Outputs:** `feature_package`, `review_report`, `all_code`
- **Rubric:** `fullstack_generation_v1`
- **When to reach for it:** you want to demonstrate that the runtime can
  drive a full-stack feature from spec to packaged artifact in one DAG

[View YAML →](https://github.com/tafreeman/agentic-runtime-platform/blob/main/agentic-workflows-v2/agentic_v2/workflows/definitions/fullstack_generation.yaml){ .md-button }

## `iterative_review`

Demonstrates the `loop_until:` + `loop_max:` pattern. A tier-2 coder
implements; a tier-3 reviewer scores; the loop body keeps reworking the
implementation until the score crosses a quality threshold or the
iteration count hits `loop_max`. An `escalation_notice` step fires if the
loop exits on max-iterations rather than passing the gate.

- **Pattern:** Bounded loop with rework gate
- **Steps:** `design` → `implement` → `review_rework_loop` (looped) → `escalation_notice` → `package`
- **Agents:** `tier1_assembler`, `tier2_coder`, `tier3_architect`, `tier3_reviewer`
- **When to reach for it:** the artifact has a measurable quality gate and
  you want bounded retries before paging a human

[View YAML →](https://github.com/tafreeman/agentic-runtime-platform/blob/main/agentic-workflows-v2/agentic_v2/workflows/definitions/iterative_review.yaml){ .md-button }

## `conditional_branching`

Showcases the `when:` conditional gate. After parsing requirements, the
workflow branches on input parameters — depth of review, whether
deployment readiness is in scope, whether a security scan is required.
Only the branches whose `when:` expression evaluates true run; the
assembler at the end coalesces whatever results are present.

- **Pattern:** Conditional fan-out with assembly
- **Steps:** `parse_requirements` → (`quick_review` | `deep_analysis` | `security_scan` | `deployment_readiness`)* → `assemble_report`
- **Agents:** `tier1_assembler`, `tier2_coder`, `tier3_architect`, `tier3_reviewer`
- **When to reach for it:** the same workflow shape applies to multiple
  request shapes; you want a single definition rather than four near-duplicates

[View YAML →](https://github.com/tafreeman/agentic-runtime-platform/blob/main/agentic-workflows-v2/agentic_v2/workflows/definitions/conditional_branching.yaml){ .md-button }

## `test_deterministic`

The smallest workflow: three steps with two tier-0 agents and no LLM
calls. Used by the test suite to assert the executor, contract validator,
and run recorder all work in isolation. It is also the workflow the
[Quick Start](../getting-started/quickstart.md) page asks you to run
first.

- **Pattern:** Tier-0 only (no LLM)
- **Steps:** `step1` → `step2` (plus internal probe step)
- **Agents:** `tier0_counter`, `tier0_process`
- **Inputs:** `input_text`
- **When to reach for it:** smoke-testing a fresh install before swapping
  in real provider keys

[View YAML →](https://github.com/tafreeman/agentic-runtime-platform/blob/main/agentic-workflows-v2/agentic_v2/workflows/definitions/test_deterministic.yaml){ .md-button }

## What to read next

- **[Workflow Authoring Guide](../WORKFLOW_AUTHORING.md)** — full grammar
  reference (steps, expressions, conditionals, loops, tools)
- **[Pattern Catalog](../PATTERN_CATALOG.md)** — reusable agentic patterns
  with worked examples
- **[First Workflow](../getting-started/first-workflow.md)** —
  step-by-step tutorial for writing your own definition
- **[Architecture — Runtime](../architecture-runtime.md)** — what the
  executor does with these definitions at runtime
