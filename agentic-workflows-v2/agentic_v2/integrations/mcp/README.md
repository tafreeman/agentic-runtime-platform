# MCP Client Integration Guide

## Overview

Production-ready Python implementation of Model Context Protocol (MCP) client for dynamically loading tools, resources, and prompts from external MCP servers.

**Status**: All 8 phases complete (transport, protocol, runtime, discovery, adapters, results, config, tests)

**Lines of Code**: 6,012 / 4,930 (122% of original estimate)

## Quick Start

### 1. Configuration

Create `.mcp.json` in your project root or `~/.mcp.json` for user-global configs:

```json
{
  "servers": {
    "filesystem": {
      "type": "stdio",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/path/to/data"],
      "enabled": true
    },
    "github": {
      "type": "http",
      "url": "https://example.invalid/mcp/",
      "headers": {
        "Authorization": "Bearer ${GITHUB_TOKEN}"
      },
      "enabled": true
    }
  }
}
```

**Variable Expansion**: Supports `${VAR_NAME}`, `${env:VAR}`, and `${input:VAR}` patterns.

### 2. Load Configuration

```python
from agentic_v2.integrations.mcp import McpConfigLoader

loader = McpConfigLoader(workspace_root="/path/to/project")
configs = loader.get_enabled()  # Only enabled servers

print(f"Loaded {len(configs)} MCP servers")
```

### 3. Connect to Servers

```python
from agentic_v2.integrations.mcp.runtime.manager import McpConnectionManager

manager = McpConnectionManager()

# Connect to all configured servers
for config in configs:
    try:
        client = await manager.connect(config.name, config)
        print(f"✅ Connected to {config.name}")
    except Exception as e:
        print(f"❌ Failed to connect to {config.name}: {e}")
```

### 4. Discover Capabilities

```python
from agentic_v2.integrations.mcp.discovery import (
    ToolDiscovery,
    ResourceDiscovery,
    PromptDiscovery,
)

tool_discovery = ToolDiscovery()
resource_discovery = ResourceDiscovery()
prompt_discovery = PromptDiscovery()

# Discover tools from a connected server (server_name first, then client)
tools = await tool_discovery.discover_tools("github", client)
print(f"Found {len(tools)} tools: {[t.name for t in tools]}")

# Discover resources
resources = await resource_discovery.discover_resources("filesystem", client)
print(f"Found {len(resources)} resources")

# Discover prompts
prompts = await prompt_discovery.discover_prompts("github", client)
print(f"Found {len(prompts)} prompts")
```

### 5. Use Tools via Adapters

```python
from agentic_v2.integrations.mcp.adapters import McpToolAdapter

# Wrap MCP tool for LLM invocation
adapter = McpToolAdapter(
    server_name="github",
    tool_descriptor=tools[0],
    client=client
)

# Execute tool (returns string, never raises)
result = await adapter.execute({"repo": "owner/repo", "issue": 123})
print(result)
```

### 6. Output Safety

```python
from agentic_v2.integrations.mcp.results import (
    ContextBudgetGuard,
    McpOutputStorage,
)

guard = ContextBudgetGuard(max_tokens=25000)

# Check if output is oversized
if guard.is_oversized(result):
    storage = McpOutputStorage(workspace_root="/path/to/project")
    file_path, rel_path = storage.save_text_output(
        result,
        server_name="github",
        tool_name="get_issue"
    )
    # Return file pointer instead of massive output
    result = storage.generate_file_pointer_message(
        rel_path,
        len(result),
        format_description="JSON"
    )
```

## Architecture

### Layer 1: Transports (Byte Streams)
- **stdio**: Subprocess with stdin/stdout (newline-delimited JSON)
- **websocket**: WebSocket with ping/pong keepalive
- **sse**: Server-Sent Events (treated as WebSocket for now)

**No JSON-RPC awareness** — transports emit raw message events.

### Layer 2: Protocol (JSON-RPC)
- Request/response correlation using `asyncio.Future`
- Timeout management (60s default, 30s for initialize)
- Notification handler registry
- Error code handling

### Layer 3: Runtime (Connection Lifecycle)
- Exponential backoff with jitter (1s → 2s → 4s → 8s → 16s → 30s max)
- Connection deduplication by signature hash
- Auth failure suppression (15-minute cooldown)
- Automatic reconnection on disconnect

### Layer 4: Discovery (Capabilities)
- LRU cache with 5-minute TTL
- Notification-based cache invalidation
- Capability checking before fetch
- Tools, resources, prompts discovery

### Layer 5: Adapters (LLM Bridge)
- **McpToolAdapter**: Wraps `tools/call` for LLM invocation
- **McpPromptAdapter**: Proxies `prompts/get` for context injection
- **McpResourceAdapter**: Meta-tools (`list_mcp_resources`, `read_mcp_resource`)

**Critical**: Schema passthrough — JSON Schema preserved verbatim, never reconstructed.

### Layer 6: Results (Output Safety)
- Token counting (4-char-per-token heuristic, tiktoken-ready)
- Truncation with clear messaging
- Disk-backed storage for oversized outputs
- File pointer generation with workspace-relative paths

### Layer 7: Configuration (Loading & Parsing)
- VS Code `.mcp.json` format support
- Multi-source loading (user-global + project-local)
- Variable expansion (`${VAR}`, `${env:VAR}`, `${input:VAR}`)
- Server deduplication by name

## Configuration Schema

The `.mcp.json` file uses the `servers` key at the top level:

```json
{
  "servers": {
    "<server_name>": {
      "type": "stdio | http | sse",
      "command": "(stdio only) executable name",
      "args": ["(stdio only) command arguments"],
      "env": {"(stdio only) KEY": "VALUE"},
      "url": "(http/sse only) server URL",
      "headers": {"(http/sse only) Header": "Value"},
      "enabled": true
    }
  }
}
```

Python Pydantic models:

```python
class McpServerConfig(BaseModel):
    name: str                                    # Server name/identifier
    enabled: bool = True                         # Whether server is enabled
    transport_type: TransportType                # "stdio" | "ws" | "sse" | "http"
    stdio: Optional[McpStdioConfig] = None       # Stdio transport config
    websocket: Optional[McpWebSocketConfig] = None  # WebSocket transport config
    sse: Optional[McpSSEConfig] = None           # SSE transport config

class McpStdioConfig(BaseModel):
    type: Literal[TransportType.STDIO]
    command: str
    args: List[str] = []
    env: Optional[Dict[str, str]] = None

class McpWebSocketConfig(BaseModel):
    type: Literal[TransportType.WEBSOCKET]
    url: str                                     # ws:// or wss://
    headers: Optional[Dict[str, str]] = None

class McpSSEConfig(BaseModel):
    type: Literal[TransportType.SSE]
    url: str                                     # https://
    headers: Optional[Dict[str, str]] = None
```

## Environment Variables

- `MAX_MCP_OUTPUT_TOKENS`: Max tokens for tool outputs (default: 25,000)
- `GITHUB_TOKEN`: GitHub PAT for GitHub MCP server
- `DATABASE_URL`: Connection string for database servers
- Any custom vars referenced in configs via `${VAR_NAME}`

## Error Handling

All layers implement **defensive programming**:
- Transport errors → emit `on_error`, never crash
- Protocol timeouts → return error, cancel pending requests
- Tool execution → catch all exceptions, return friendly error strings
- Config parsing → skip invalid servers, log warnings

**Never crash the orchestrator or LLM context.**

## Testing (Phase 8 — Complete)

Target: 80% branch coverage

Test files (`tests/integrations/mcp/`):
- `conftest.py` — Shared fixtures and mocks
- `test_config_loader.py` — Variable expansion, deduplication, caching
- `test_tool_adapter.py` — Schema passthrough, error handling, timeouts
- `test_output_safety.py` — Token counting, truncation, disk storage
- `test_connection_manager.py` — Backoff, reconnection, signature deduplication

## Known Limitations

- SSE transport not fully implemented (mapped to WebSocket)
- No HTTP transport (only WebSocket for remote servers)
- Token counting uses 4-char heuristic (not tiktoken yet)
- No UI integration for `${input:VAR}` prompts (requires caller to provide dict)
- No connection pooling (one connection per server)
- `McpPromptAdapter.get_content()` creates a new `PromptDiscovery()` instance per call
- Not yet integrated into main orchestrator (`tools/registry.py`, `core/orchestrator.py`)

## Roadmap

- ✅ Phase 1: Transports (stdio, WebSocket) — 739 LOC
- ✅ Phase 2: Protocol (JSON-RPC correlation) — 528 LOC
- ✅ Phase 3: Runtime (connection manager) — 457 LOC
- ✅ Phase 4: Discovery (capabilities) — 451 LOC
- ✅ Phase 5: Adapters (tool/prompt/resource) — 601 LOC
- ✅ Phase 6: Output safety (truncation, storage) — 607 LOC
- ✅ Phase 7: Configuration (loading, expansion) — 998 LOC
- ✅ Phase 8: Testing (75-80% coverage) — 1,631 LOC
- ⏳ Phase 9: Integration with orchestrator

## Troubleshooting

For issues or questions:
1. Check logs (set `logging.DEBUG` for verbose output)
2. Review error messages (always descriptive)
3. Validate `.mcp.json` syntax (use JSON linter)
4. Check environment variables:
   - **Linux/macOS**: `printenv | grep MCP`
   - **Windows (PowerShell)**: `Get-ChildItem Env:MCP*` or `Get-ChildItem Env: | Where-Object Name -like '*MCP*'`
   - **Windows (cmd)**: `set MCP`
5. Verify `websockets` and `cachetools` are installed: `pip show websockets cachetools`
6. File issue with logs and config snippet
