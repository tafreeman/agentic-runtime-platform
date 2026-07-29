# Runtime examples

Run these files from the repository root after installing
`agentic-workflows-v2`.

| File | Provider needed | Current status |
| --- | --- | --- |
| `custom_tool.py` | No | Runs a deterministic tool and its error path |
| `yaml_workflow.py` | No | Runs, but logs a null `code_file` input warning |
| `workflow_run.py` | Usually | Loads a shipped workflow and may call its configured models |
| `mcp_integration_example.py` | External MCP server | Demonstrates explicit MCP client setup |
| `simple_agent.py` | No | Broken: its class does not implement the current `BaseAgent` abstract methods |

Start with the verified deterministic tool example:

```powershell
python agentic-workflows-v2\examples\custom_tool.py
```

The YAML example also completes without a provider:

```powershell
python agentic-workflows-v2\examples\yaml_workflow.py
```

Its current context setup does not match the workflow input mapping, so the
runtime warns that `code_file` is null. Do not use that file as the authoring
reference for input mapping; use the repository
[workflow authoring guide](../../docs/WORKFLOW_AUTHORING.md).

## Provider-backed workflow

`workflow_run.py` selects a shipped workflow, creates temporary input for
`code_review`, and runs the native DAG directly. Confirm model configuration
and expected provider calls before running it:

```powershell
python agentic-workflows-v2\examples\workflow_run.py
```

## MCP example

`mcp_integration_example.py` is not part of server startup. It reads a local
file named **.mcp.json**, connects to enabled external servers, discovers
capabilities, and creates adapters explicitly.

The included [MCP configuration example](mcp_config_example.json) contains
placeholder endpoints and paths. Copy only the entries you need into a local
file named **.mcp.json**, replace the placeholders, and keep credentials in
environment variables.

The current MCP connection manager implements stdio and WebSocket transports.
Entries declared as `http` or `sse` are mapped to the WebSocket client rather
than a native HTTP/SSE transport.

## Shipped YAML patterns

The runtime definitions include:

- [Conditional branching](../agentic_v2/workflows/definitions/conditional_branching.yaml)
  for `when` expressions;
- [Iterative review](../agentic_v2/workflows/definitions/iterative_review.yaml)
  for bounded `loop_until` and `loop_max` review;
- [Consensus review](../agentic_v2/workflows/definitions/consensus_review.yaml)
  for repeated review and agreement.

List all current definitions instead of relying on a hard-coded count:

```powershell
agentic list workflows
```
