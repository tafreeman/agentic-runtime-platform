# Examples

Minimal runnable examples for `agentic_v2`.

## Files

| File | Description | API keys? |
|------|-------------|-----------|
| `simple_agent.py` | Tiny async agent usage example | Yes |
| `workflow_run.py` | Load a built-in workflow and execute a demo run | Yes |
| `yaml_workflow.py` | Load a YAML workflow definition, validate, and execute | No |
| `custom_tool.py` | Implement a custom tool, register it, and verify protocol conformance | No |

## Run

```bash
python examples/simple_agent.py
python examples/workflow_run.py
python examples/yaml_workflow.py
python examples/custom_tool.py
```

## YAML Workflow Pattern Reference

The `workflows/definitions/` directory includes two educational workflow definitions that demonstrate advanced DAG features:

| File | Pattern | Key Features |
|------|---------|-------------|
| `../agentic_v2/workflows/definitions/conditional_branching.yaml` | `when:` conditional gates | Equality checks, `in`/`not in` membership, compound `and`/`or` expressions, conditional fan-out, `coalesce()` fallbacks |
| `../agentic_v2/workflows/definitions/iterative_review.yaml` | `loop_until:` bounded loops | Review-rework cycles, `loop_max:` bounds, self-referencing outputs across iterations, post-loop quality gates |

These require LLM API keys to execute. For a no-API-key example, see `yaml_workflow.py`.

## Notes

- `workflow_run.py` creates a temporary scratch Python file when running `code_review`. The file is cleaned up automatically at the end of the run.
- `yaml_workflow.py` and `custom_tool.py` are fully deterministic (tier-0) and require no API keys.
