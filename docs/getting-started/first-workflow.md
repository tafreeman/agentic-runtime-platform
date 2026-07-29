---
title: First workflow
description: Create, validate, and run a small YAML workflow without a model provider.
tags:
  - getting-started
  - workflow
---

# First workflow

This guide creates a two-step workflow that runs without a model. It uses the
same tier-0 agents as the repository's deterministic smoke test, so you can
focus on the YAML contract.

## 1. Create the definition

Save this file as `my-first-workflow.yaml` in the repository root:

```yaml
name: my_first_workflow
description: Process text and count the result
version: "1.0"

inputs:
  input_text:
    type: string
    description: Text to process
    required: true

outputs:
  processed_text:
    from: ${steps.process.outputs.result}
  character_count:
    from: ${steps.count.outputs.count}

steps:
  - name: process
    agent: tier0_process
    description: Process the input text
    inputs:
      text: ${inputs.input_text}
    outputs:
      result: processed_text

  - name: count
    agent: tier0_counter
    description: Count characters in the processed text
    depends_on: [process]
    inputs:
      text: ${steps.process.outputs.result}
    outputs:
      count: count_value
```

The top-level sections have distinct jobs:

| Section | Meaning |
|---|---|
| `name`, `description`, `version` | Workflow identity and human-readable context |
| `inputs` | Values callers may or must supply |
| `outputs` | Values returned from the completed workflow |
| `steps` | Work to execute and the dependencies between steps |

Each step has a unique `name` and an `agent`. `depends_on` creates a graph
edge. Here, `count` cannot run until `process` succeeds.

Expressions connect values:

- `${inputs.input_text}` reads a workflow input.
- `${steps.process.outputs.result}` reads an earlier step output.
- top-level `outputs` select the values returned in `final_output`.

The mapping under a step's `outputs` declares the public output name and its
internal context alias. Downstream expressions use the public name on the left.

## 2. Validate

```bash
agentic validate ./my-first-workflow.yaml --verbose
```

Validation checks:

- YAML syntax;
- required workflow fields;
- duplicate or missing step names;
- dependency references;
- cycles; and
- LangGraph compilation.

The final compilation check requires the `langchain` extra even if you later
run with `--adapter native`.

Expected result:

```text
OK Workflow 'my_first_workflow' is valid!
```

## 3. Create an input file

Bash:

```bash
printf '{"input_text":"hello"}\n' > /tmp/my-first-input.json
```

PowerShell:

```powershell
'{"input_text":"hello"}' |
  Set-Content -Encoding utf8 .\my-first-input.json
```

## 4. Run

Bash:

```bash
AGENTIC_NO_LLM=1 agentic run ./my-first-workflow.yaml \
  --input /tmp/my-first-input.json \
  --verbose
```

PowerShell:

```powershell
$env:AGENTIC_NO_LLM = "1"
agentic run .\my-first-workflow.yaml `
  --input .\my-first-input.json `
  --verbose
```

Expected status:

```text
Status: SUCCESS
```

The resolved output should contain the processed text and its character count.
Save the full result when you want to inspect the contract:

```bash
agentic run ./my-first-workflow.yaml \
  --input /tmp/my-first-input.json \
  --output my-first-result.json
```

## 5. Run through the native engine

The default named-workflow adapter is LangGraph. Select the native engine
explicitly:

```bash
agentic run ./my-first-workflow.yaml \
  --input /tmp/my-first-input.json \
  --adapter native
```

For this simple workflow, both adapters should return the same output.

## 6. Add a parallel branch

Steps with the same satisfied dependencies are eligible to run at the same
time. Add this step after `count`:

```yaml
  - name: second_count
    agent: tier0_counter
    description: Independently count the original input
    inputs:
      text: ${inputs.input_text}
    outputs:
      count: original_count
```

`second_count` has no dependency, so it can run at the same time as `process`.
Add its result to the top-level outputs:

```yaml
outputs:
  processed_text:
    from: ${steps.process.outputs.result}
  character_count:
    from: ${steps.count.outputs.count}
  original_character_count:
    from: ${steps.second_count.outputs.count}
```

Validate again after every graph change:

```bash
agentic validate ./my-first-workflow.yaml --verbose
```

## Common errors

### Input is missing

If the input JSON omits `input_text`, validation fails before execution.
Compare the file with the top-level `inputs` block.

### Dependency name is wrong

`depends_on` uses step names, not agent names. A dependency such as
`depends_on: [tier0_process]` is invalid unless a step is actually named
`tier0_process`.

### Output cannot be resolved

Check all three names:

1. the producer step name;
2. the step's public output name; and
3. the top-level `from` expression.

An expression for this file must use
`${steps.process.outputs.result}`, not the internal alias
`processed_text`.

### LLM-backed step returns placeholder text

Tier-1 and higher agents call a model. Under `AGENTIC_NO_LLM=1`, they receive
fixed placeholder text. That text may not satisfy JSON or typed-artifact
contracts. Use tier-0 steps while learning the graph, then configure a real
provider before testing model-dependent output.

## Next

- [Workflow authoring](../WORKFLOW_AUTHORING.md)
- [Workflow reference](../workflows/index.md)
- [Pattern catalog](../PATTERN_CATALOG.md)
- [CLI reference](../cli-reference.md)
