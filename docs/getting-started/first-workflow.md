---
title: Your first workflow
description: Author a two-step DAG from scratch — YAML grammar, contracts, validation, and execution explained.
tags:
  - getting-started
  - workflow
---

# Your first workflow

Writes a custom workflow from an empty file to a successful run. The
result is a small two-step DAG — `summarize` then `review` — that covers
every piece of the YAML grammar you'll need for real work.

## Anatomy of a workflow

Every workflow is a YAML document with top-level `name`, `description`,
`version`, `inputs`, `outputs`, and `steps` keys:

```yaml
name: my_first_workflow
description: A two-step example - summarize an input, then review the summary.
version: "1.0"

inputs:
  task:
    type: string
    description: The text to summarize
    required: true

outputs:
  summary:
    from: ${steps.summarize.outputs.summary}
  review:
    from: ${steps.review.outputs.review}

steps:
  - name: summarize
    agent: tier1_summarizer
    description: Produce a one-paragraph summary of the input task.
    inputs:
      task: ${inputs.task}
    outputs:
      summary: task_summary

  - name: review
    agent: tier2_reviewer
    description: Review the summary for accuracy and clarity.
    depends_on: [summarize]
    inputs:
      summary: ${steps.summarize.outputs.summary}
    outputs:
      review: summary_review
```

The top-level blocks:

- **`inputs`** — the workflow's input schema. Each entry declares a `type`,
  a `description`, and optionally `required: true` or a `default`.
- **`outputs`** — the workflow's final artifact. Each entry maps an output
  name to a `from:` expression that pulls a value out of a step
  (`optional: true` marks outputs that a skipped step may not produce).

Each step requires:

- **`name`** — a unique identifier within the workflow
- **`agent`** — the agent that runs this step. The name follows the
  tier-prefix convention used by every shipped workflow:
  `tier0_*` agents are deterministic (no LLM), `tier1_*` route to a fast
  model, `tier2_*` route to a capable model. The suffix (`summarizer`,
  `reviewer`, …) names the role.
- **`description`** — human-readable purpose; surfaces in the UI and traces
- **`depends_on`** — list of step names that must complete before this step
  is eligible to run; the executor uses this to compute the topological
  order (omit it, as `summarize` does, for entry steps)
- **`inputs`** — a mapping of names to value expressions; expressions can
  reference workflow inputs (`${inputs.*}`) or earlier step outputs
  (`${steps.<name>.outputs.<field>}`)
- **`outputs`** — a mapping from the output name downstream steps reference
  to an alias used internally (for example `summary: task_summary`). This
  is a name→alias mapping, not a type declaration — compare
  `code_review.yaml`, where `review: code_review` is consumed downstream as
  `${steps.review_code.outputs.review}`.

## Step 1 — Create the file

Save the YAML above as
`agentic-workflows-v2/agentic_v2/workflows/definitions/my_first_workflow.yaml`.

The runtime auto-discovers any `*.yaml` file in this directory at startup.
There is no central registry to update.

## Step 2 — Validate the definition

```bash
cd agentic-workflows-v2
agentic validate my_first_workflow
```

`validate` runs two tiers of checks:

1. **Structural lint** — YAML syntax, step shape, and dependency
   references (no extras required)
2. **Graph compilation** — the definition is loaded into the workflow
   config model and compiled through LangGraph to catch graph-level errors
   such as cycles (this tier requires the `langchain` extra:
   `pip install -e ".[langchain]"`)

A successful run prints:

```
OK Workflow 'my_first_workflow' is valid!
```

Errors include the offending step and the field that failed; fix and
re-run. Add `--verbose` to print the step, input, and output counts plus
the execution plan.

## Step 3 — About agents and personas

You do not need to author a prompt file for this workflow. The tier prefix
in the agent name (`tier1_`, `tier2_`) selects the model tier, and in
`AGENTIC_NO_LLM=1` mode the placeholder backend answers for any LLM-backed
agent.

For richer behavior, the runtime ships seven agent personas as markdown
files under `agentic-workflows-v2/agentic_v2/prompts/`: `architect`,
`coder`, `orchestrator`, `planner`, `reviewer`, `tester`, and `validator`.
See the persona-authoring section of [ONBOARDING.md](../ONBOARDING.md) for
the required sections and an example of adding your own.

## Step 4 — Run the workflow

The `--input` flag expects a JSON **file path**. Create a small input file first:

```bash
# Linux/macOS
echo '{"task": "Explain how the DAG executor schedules parallel steps."}' > /tmp/first-workflow-input.json
export AGENTIC_NO_LLM=1
agentic run my_first_workflow --input /tmp/first-workflow-input.json
```

```powershell
# Windows PowerShell
'{"task": "Explain how the DAG executor schedules parallel steps."}' | Out-File -Encoding utf8 first-workflow-input.json
$env:AGENTIC_NO_LLM = "1"
agentic run my_first_workflow --input first-workflow-input.json
```

You should see `Status: SUCCESS` and, with `--verbose`, both steps
(`summarize`, `review`) marked `success` in the step results table. Two
no-LLM caveats are expected and harmless here:

- Each LLM-backed step reports a `raw_response` output — the placeholder
  backend returns a fixed string rather than the structured JSON a real
  model would produce.
- The CLI warns `Output 'summary' could not be resolved` (and likewise for
  `review`), because the named step outputs cannot be extracted from the
  unstructured placeholder. With a real provider key the outputs resolve
  normally.

If the run reports `SUCCESS`, the DAG executor, contract validator, and
agent resolution are all working as expected.

## Step 5 — Try a parallel branch

To prove the parallel-dispatch story, add a second downstream step:

```yaml
  - name: tone_check
    agent: tier1_analyzer
    description: Independent tone evaluation, runs in parallel with review.
    depends_on: [summarize]
    inputs:
      summary: ${steps.summarize.outputs.summary}
    outputs:
      tone: tone_report
```

`review` and `tone_check` both depend only on `summarize`, so the executor
dispatches them concurrently. Re-run with `agentic run --verbose` — the
execution plan shows both steps at the same level, and their wall-clock
times overlap even though the plan order is deterministic.

## Going further

- **Conditional gates.** Add a `when:` expression to skip a step based on
  an upstream output. See `conditional_branching.yaml` for the canonical
  example.
- **Loops.** Use `loop_until:` and `loop_max:` to repeat a step until a
  predicate holds. See `iterative_review.yaml`.
- **Tool calls.** Allowlist a built-in tool on a step with the `tools:`
  key. The default policy is DENY for high-risk tools (shell, git,
  file_delete) — explicit allowlists are required.
- **Fan-in.** Multiple `depends_on` entries cause the executor to wait
  for all listed steps; their outputs become available in the input
  expression namespace.

The full grammar reference is in the
[Workflow authoring guide](../WORKFLOW_AUTHORING.md), and the production
workflows in [Workflow reference](../workflows/index.md) are the best
real-world examples to study next.
