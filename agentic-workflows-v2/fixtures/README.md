# Runtime fixtures

These files are committed examples used for documentation, manual inspection,
and tests. They are not a directory of current run history.

| File | Purpose |
| --- | --- |
| `example_code_review_run.json` | A saved `code_review` run envelope showing workflow, step, timing, dataset, model, token, and output fields. |
| `multi_agent_codegen_e2e_input.json` | Input payload for the full-stack multi-agent end-to-end scenario. |

Treat fixture values as test data. A successful status in a fixture does not
prove that the current code reproduces that result.

## Generated run files

`RunLogger` writes normal execution records under
`agentic-workflows-v2/runs/`. Tenant-scoped server requests use a tenant
subdirectory. Run files are ignored by Git because they are generated,
environment-specific, and may contain prompts, outputs, file content, model
names, timing data, or errors.

Before sharing a run:

1. remove credentials, personal data, proprietary input, and sensitive model
   output;
2. remove unstable timestamps and identifiers when they are not relevant;
3. state whether a real model, mock, or `AGENTIC_NO_LLM=1` produced it; and
4. record the command and commit used to generate it.

For scored committed results, use
[`datasets/default/`](../../datasets/default/README.md). Those files have a
separate update and validation contract.
