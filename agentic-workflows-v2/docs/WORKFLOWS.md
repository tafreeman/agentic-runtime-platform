# Built-in workflows

The runtime loads its built-in workflow definitions from
`agentic_v2/workflows/definitions/`. Each definition is a YAML file that
declares inputs, steps, dependencies, conditions, loops, and outputs.

The repository-level [workflow reference](../../docs/workflows/index.md)
explains every definition in more detail.

## Definitions

| Workflow | Purpose | Inputs |
| --- | --- | --- |
| `bug_resolution` | Move from a bug report through diagnosis, a proposed fix, regression checks, and a report | `bug_report`, `code_file`, `resolution_depth` |
| `code_review` | Run several reviews of one file and combine the results | `code_file`, `review_depth` |
| `conditional_branching` | Select quick, thorough, security, and deployment checks with `when:` conditions | `feature_spec`, `review_depth`, `target_env` |
| `consensus_review` | Collect three independent verdicts and require a configurable level of agreement | `code_file`, `min_agreement` |
| `fullstack_generation` | Generate API, frontend, migration, and test artifacts in parallel, then review and package them | `feature_spec`, `tech_stack` |
| `iterative_review` | Repeat review and rework up to a configured limit | `feature_spec`, `max_review_rounds` |
| `test_deterministic` | Check the executor with two tier-0 agents and placeholder output in no-LLM mode | `input_text` |
| `test_workflow` | Provide a zero-input placeholder fixture for server and evaluation tests | `input_text` is optional |

## Validate and run

Run these commands from an activated development environment:

```powershell
agentic validate code_review
agentic run code_review --dry-run
agentic run code_review --input .\input.json --output .\result.json
```

`--input` accepts a path to a JSON file. A named workflow uses the
`langchain` adapter unless `--adapter native` is supplied.

## Add a workflow

1. Add a YAML file to `agentic_v2/workflows/definitions/`.
2. Declare the public inputs and outputs.
3. Give every step a stable name and explicit dependencies.
4. Keep `when:` expressions and loop limits small enough to review easily.
5. Run `agentic validate <workflow-name>`.
6. Add loader tests and behavior tests under `tests/`.
7. Update this table and `../../docs/workflows/index.md`.

See [Workflow Authoring](../../docs/WORKFLOW_AUTHORING.md) for the supported
schema and expression syntax.
