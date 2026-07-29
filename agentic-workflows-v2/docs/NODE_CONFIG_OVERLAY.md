# Node configuration overlay status

The repository contains an unfinished UI prototype for changing a step's model
and generation settings during a live run. It is not an active runtime
feature.

## What exists

Two frontend files define the prototype:

- `ui/src/components/live/NodeConfigOverlay.tsx`
- `ui/src/hooks/useNodeConfigUpdate.ts`

The component contains fields for model, system prompt, temperature, token
limit, top-p, and tool names. The hook can send a `node_config_update` JSON
message to the execution WebSocket.

Neither file is imported by the live page or DAG components, so the overlay is
not reachable in the current UI.

## What is missing

The server WebSocket at `/ws/execution/{run_id}` receives client text only to
keep the connection open. It does not parse `node_config_update`, validate a
configuration, send an acknowledgement, or store an override.

`WorkflowState` in `agentic_v2/langchain/state.py` has no node-override field,
and graph execution does not read live updates.

As a result, sending the prototype message has no effect on a running step or
retry. No override history is written to run metadata.

## Supported alternatives

### Set one model for a run

The workflow run API accepts `model_override` for the LangChain adapter:

```json
{
  "workflow": "code_review",
  "adapter": "langchain",
  "input_data": {
    "code_file": "src/example.py"
  },
  "model_override": "ollama:qwen3:8b"
}
```

The UI workflow detail page exposes this run-level setting. The server rejects
it for adapters other than `langchain`.

### Set a model on a workflow step

Workflow YAML supports `model_override` on a step. The value may be a concrete
model ID or the documented environment expression:

```yaml
steps:
  - name: review
    agent: tier2_reviewer
    model_override: env:REVIEW_MODEL|ollama:qwen3:8b
```

Edit and validate the workflow before starting the run.

### Set generation parameters

Use the workflow's supported step configuration and `model_params` fields
rather than the unused live overlay. Confirm the accepted fields in the
[workflow authoring guide](../../docs/WORKFLOW_AUTHORING.md) and generated
workflow schema.

## Requirements for completing the feature

A production implementation needs all of the following:

1. a versioned client message contract;
2. server-side parsing and Pydantic validation;
3. authentication and authorization for each update;
4. a defined rule for pending, running, completed, and retrying steps;
5. state propagation into both supported execution paths;
6. acknowledgement and rejection events;
7. run-log audit data without leaking prompts or secrets;
8. cleanup and multi-replica behavior;
9. UI integration and unit tests;
10. WebSocket and end-to-end tests.

Until those pieces exist, do not describe live per-node configuration as a
supported feature.
