---
title: Your First Workflow
description: Author a two-step DAG from scratch — YAML grammar, contracts, validation, and execution explained.
tags:
  - getting-started
  - workflow
---

# Your First Workflow

This page walks through writing a custom workflow from an empty file to a
successful run. The result is a small two-step DAG — `summarize` then
`grade` — that demonstrates every piece of the YAML grammar you'll need
for real work.

By the end you will have:

- A workflow definition under `agentic-workflows-v2/agentic_v2/workflows/definitions/`
- A passing `agentic validate` run
- A successful `agentic run` against the deterministic backend
- A clear picture of how steps, agents, contracts, and tools fit together

## Anatomy of a workflow

Every workflow is a YAML document with four top-level keys:

```yaml
name: my_first_workflow
description: A two-step example — summarize an input, then score the summary.
version: "1.0"

steps:
  - name: summarize
    agent: summarizer
    description: Produce a one-paragraph summary of the input task.
    depends_on: []
    inputs:
      task: "${input.task}"
    outputs:
      summary: string

  - name: grade
    agent: grader
    description: Score the summary against the rubric.
    depends_on: [summarize]
    inputs:
      summary: "${steps.summarize.outputs.summary}"
    outputs:
      score: number
      rationale: string
```

Each step requires:

- **`name`** — a unique identifier within the workflow
- **`agent`** — the persona that runs this step (resolved from
  `agentic_v2/prompts/<agent>.md`)
- **`description`** — human-readable purpose; surfaces in the UI and traces
- **`depends_on`** — list of step names that must complete before this step
  is eligible to run; the executor uses this to compute the topological order
- **`inputs`** — a mapping of names to value expressions; expressions can
  reference workflow inputs (`${input.*}`) or earlier step outputs
  (`${steps.<name>.outputs.<field>}`)
- **`outputs`** — a typed schema declaring the keys and types this step
  promises to produce; the executor validates the agent response against
  this schema before downstream steps run

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

`validate` runs three checks:

1. **Schema validation** — the YAML matches the workflow Pydantic model
2. **DAG validation** — `depends_on` references resolve, and the graph is
   acyclic
3. **Contract preflight** — every input expression resolves against the
   declared upstream outputs

A successful run prints `Workflow 'my_first_workflow' is valid.` Errors
include the offending step and the field that failed; fix and re-run.

## Step 3 — Author the personas

Each agent referenced by `agent:` must have a persona file at
`agentic-workflows-v2/agentic_v2/prompts/<agent>.md`. Create two minimal
personas:

```markdown
<!-- agentic_v2/prompts/summarizer.md -->
# Summarizer


## Expertise
Concise paraphrasing of structured tasks into one short paragraph.

## Boundaries
- Do not invent facts not present in the input.
- Do not include lists, code blocks, or markdown formatting.

## Critical rules
- Output JSON with a single `summary` key.
- The summary must be one paragraph and at most three sentences.

## Output format
```json
{ "summary": "..." }
```

```markdown
<!-- agentic_v2/prompts/grader.md -->
# Grader

## Expertise
Rubric-based evaluation of short prose against a quality rubric.

## Boundaries
- Score only the supplied summary; do not infer about the original input.
- Do not edit or rewrite the summary.

## Critical rules
- Output JSON with `score` (0.0–1.0) and `rationale` (one sentence).
- A summary that introduces facts not in scope must score below 0.5.

## Output format
```json
{ "score": 0.0, "rationale": "..." }
```

These personas are the same files used by the LLM router when a real
provider is wired up. In `AGENTIC_NO_LLM=1` mode, the placeholder backend
returns deterministic JSON that conforms to the declared output schema.

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

You should see two steps in the timeline (`summarize`, `grade`), each
marked `succeeded`, followed by a final artifact containing both the
summary and the score. If the run record lands in `runs/<run-id>/`, the
DAG executor, contract validator, and persona resolver are all working as
expected.

## Step 5 — Try a parallel branch

To prove the parallel-dispatch story, add a second downstream step:

```yaml
  - name: tone_check
    agent: grader
    description: Independent tone evaluation, runs in parallel with grade.
    depends_on: [summarize]
    inputs:
      summary: "${steps.summarize.outputs.summary}"
    outputs:
      tone: string
      confidence: number
```

`grade` and `tone_check` both depend only on `summarize`, so the executor
will dispatch them concurrently. Re-run with `agentic run` and inspect
`timeline.json` — the two steps will overlap in wall-clock time even
though their start order is deterministic.

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
[Workflow Authoring Guide](../WORKFLOW_AUTHORING.md), and the production
workflows in [Workflow Reference](../workflows/index.md) are the best
real-world examples to study next.
