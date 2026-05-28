# Workflows

This document describes built-in workflow definitions in `agentic_v2/workflows/definitions` and how to add new ones.

## Built-In Definitions

| Workflow | Purpose | Typical inputs |
| --- | --- | --- |
| `bug_resolution` | Triage, root-cause, fix, and verification | `bug_report`, `code_file`, `resolution_depth` |
| `code_review` | Automated multi-step code review | `code_file`, `review_depth` |
| `conditional_branching` | Conditional step execution with `when:` gates | `input_text`, `category` |
| `fullstack_generation` | Parallel feature generation across backend/frontend | `feature_spec`, `tech_stack` |
| `iterative_review` | Bounded review-rework cycles with `loop_until:`/`loop_max:` | `code_file`, `review_depth` |
| `test_deterministic` | Deterministic no-LLM smoke workflow | `input_text` |

## Workflow Structure

Each workflow is YAML with:
- Metadata (`name`, `description`, `version`)
- Capabilities (`inputs`, `outputs`)
- Input schema
- Step DAG (`steps` with `depends_on`, `when`, `inputs`, `outputs`)
- Optional evaluation rubric/profile metadata

The YAML workflow definition is the source of truth for authoring. Native DAG
execution lives under `agentic_v2/engine/`; LangGraph support compiles or
bridges these same workflow definitions through `agentic_v2/langchain/` and
`agentic_v2/adapters/langchain/`.

## Run a Workflow

```bash
agentic validate code_review
agentic run code_review --dry-run
agentic run code_review --input input.json --output output.json
```

## Authoring Guidelines

- Keep step names explicit and stable.
- Use `depends_on` for deterministic execution order.
- Keep expressions (`${...}`) readable and minimal.
- Prefer explicit step outputs over large implicit context.
- Add evaluation criteria for production-facing workflows.

## Adding a New Workflow

1. Add a YAML file in `agentic_v2/workflows/definitions/`.
2. Define clear `inputs` and `outputs`.
3. Ensure graph validity with `agentic validate <workflow>`.
4. Add tests in `tests/test_workflow_loader.py` and relevant integration tests.
5. Document the new workflow in this file and `README.md`.
