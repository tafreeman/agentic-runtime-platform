# MCP client library

This package implements a Model Context Protocol client for Python code in the
runtime package. It can load server configuration, connect over stdio or
WebSocket, discover capabilities, call tools, and control output size.

It is not wired into the default CLI or server startup path. Import and manage
it explicitly when building an MCP-enabled integration.

## Supported transports

| Configuration type | Current behavior |
| --- | --- |
| `stdio` | Starts a subprocess and exchanges JSON-RPC messages |
| `ws` | Connects to a `ws://` or `wss://` endpoint |
| `http` or `sse` | Parsed as WebSocket configuration; not a native HTTP/SSE transport |

Do not configure an HTTP or SSE endpoint unless it is also compatible with
the WebSocket client. `McpSSEConfig` exists as a type, but the connection
manager does not build an SSE transport.

## Configuration

The loader reads:

1. the user file `~/.mcp.json`;
2. the workspace file `.mcp.json`.

Workspace entries replace user entries with the same server name.

```json
{
  "servers": {
    "workspace_files": {
      "type": "stdio",
      "command": "npx",
      "args": [
        "-y",
        "@modelcontextprotocol/server-filesystem",
        "C:\\work\\allowed-data"
      ],
      "enabled": true
    },
    "remote_ws": {
      "type": "ws",
      "url": "wss://mcp.example.com/socket",
      "headers": {
        "Authorization": "Bearer ${MCP_TOKEN}"
      },
      "enabled": false
    }
  }
}
```

Variable expansion accepts `${NAME}`, `${env:NAME}`, and `${input:NAME}`.
Missing values remain unexpanded and produce a warning. Do not commit tokens
or other credentials to `.mcp.json`.

Load enabled configurations:

```python
from agentic_v2.integrations.mcp import McpConfigLoader

loader = McpConfigLoader(workspace_root=r"C:\work\project")
configs = loader.get_enabled()
```

Invalid server entries are logged and skipped. Check the returned list instead
of assuming every configured server loaded.

## Connect and discover tools

```python
from agentic_v2.integrations.mcp.adapters import McpToolAdapter
from agentic_v2.integrations.mcp.discovery import ToolDiscovery
from agentic_v2.integrations.mcp.runtime.manager import McpConnectionManager

manager = McpConnectionManager()
discovery = ToolDiscovery()

try:
    config = configs[0]
    client = await manager.connect(config)
    tools = await discovery.discover_tools(config.name, client)

    adapter = McpToolAdapter(
        server_name=config.name,
        tool_descriptor=tools[0],
        client=client,
    )
    result_text = await adapter.execute({"path": "README.md"})
finally:
    await manager.disconnect_all()
```

Discovery checks the capabilities returned by the initialize handshake.
Tool, resource, and prompt lists use a five-minute cache. Register each
discovery service's notification handlers if the server can announce list
changes.

## Tool result contract

`McpToolAdapter`:

- prefixes the local name as `mcp_<server>_<tool>`;
- preserves the server's input JSON Schema;
- applies a 120-second default call timeout;
- formats text, image metadata, and resource content;
- distinguishes a valid empty result from an error;
- converts protocol and tool failures into model-facing error text.

Use `execute_envelope()` when the caller needs structured error fields:

```python
envelope = await adapter.execute_envelope(arguments)
if envelope.is_error:
    print(envelope.error_category, envelope.is_retryable)
```

The adapter catches call failures so they can be returned to a model. Connection
and discovery methods can still raise; handle them at the integration
boundary.

## Resources and prompts

The discovery package also provides:

- `ResourceDiscovery.discover_resources()` and `read_resource()`;
- `PromptDiscovery.discover_prompts()` and `get_prompt()`;
- `McpResourceAdapter` meta-tools for listing and reading resources;
- `McpPromptAdapter` for retrieving a configured prompt.

Treat all remote content as untrusted input. A server capability declaration
does not establish source trust or authorize a tool action.

## Large outputs

`ContextBudgetGuard` estimates size at roughly four characters per token. Its
default limit is 25,000 tokens and can be changed with
`MAX_MCP_OUTPUT_TOKENS`.

`McpOutputStorage` can save large text or binary results below
`.temp/mcp-outputs/` and return a workspace-relative pointer. The caller must
invoke these helpers; `McpToolAdapter` does not automatically move every large
result to disk.

Output files may contain sensitive remote data. Apply workspace access
controls and an explicit retention policy.

## Package layout

| Directory | Responsibility |
| --- | --- |
| `transports/` | Stdio and WebSocket I/O |
| `protocol/` | JSON-RPC requests, responses, notifications, and timeouts |
| `runtime/` | Connection lifecycle, retry backoff, and auth suppression |
| `discovery/` | Tools, resources, and prompts |
| `adapters/` | Model-facing capability wrappers |
| `results/` | Context limits and disk-backed output |
| `config.py` | `.mcp.json` parsing and variable expansion |
| `error_envelope.py` | Structured tool-result failures |

## Test

From the repository root:

```powershell
python -m pytest agentic-workflows-v2/tests/integrations/mcp -q
```

The tests use mocks and local fixtures. Add an explicit opt-in boundary before
introducing tests that start external servers or use credentials.
