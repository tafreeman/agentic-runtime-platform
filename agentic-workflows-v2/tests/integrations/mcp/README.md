# MCP integration tests

This directory tests the repository's MCP client library with mocks and local
temporary files. It does not require a live MCP server.

From the repository root:

```powershell
python -m pytest agentic-workflows-v2\tests\integrations\mcp -q
```

Run one area:

```powershell
python -m pytest `
  agentic-workflows-v2\tests\integrations\mcp\test_tool_adapter.py `
  -q
```

Coverage:

| File | Behavior |
| --- | --- |
| `test_config_loader.py` | Config parsing, variables, precedence, and caching |
| `test_connection_manager.py` | Connect, reuse, retry, auth suppression, and cleanup |
| `test_protocol_client_concurrency.py` | Concurrent JSON-RPC requests |
| `test_tool_adapter.py` | Schema passthrough, content, errors, and timeouts |
| `test_error_envelope.py` | Error category and retryability contract |
| `test_output_safety.py` | Size estimates, truncation, storage, and paths |

`conftest.py` contains shared mock clients, transports, responses, and server
configurations.

When adding a test:

- use `pytest.mark.asyncio` for async behavior;
- use temporary directories for output storage;
- do not start a network server or subprocess unless the test is explicitly
  separated from the default suite;
- assert the structured error envelope, not only its display text;
- cover valid empty results separately from access or protocol failures.

The current suite does not provide live WebSocket server coverage or
end-to-end coverage against third-party MCP servers. Those tests need an
opt-in marker, bounded timeouts, and credential isolation.
