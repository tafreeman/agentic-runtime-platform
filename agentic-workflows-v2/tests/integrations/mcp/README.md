# MCP Integration Tests

Comprehensive test suite for the MCP client integration.

## Running Tests

```bash
# Run all MCP tests
pytest tests/integrations/mcp/ -v

# Run specific test file
pytest tests/integrations/mcp/test_config_loader.py -v

# Run with coverage
pytest tests/integrations/mcp/ --cov=agentic_v2.integrations.mcp --cov-report=html

# Run tests matching pattern
pytest tests/integrations/mcp/ -k "test_variable_expansion"
```

## Test Files

### conftest.py
Shared pytest fixtures:
- `mock_transport` - Mock transport for protocol tests
- `sample_stdio_config` - Sample server configuration
- `sample_*_response` - Mock server responses
- `mock_protocol_client` - Pre-initialized mock client

### test_config_loader.py
Configuration loading and parsing tests:
- Variable expansion (`${VAR}`, `${env:VAR}`, `${input:VAR}`)
- Multi-source config merging (user + project)
- Server deduplication by name
- Error handling for malformed JSON
- Enabled/disabled filtering
- McpConfigLoader caching behavior

### test_tool_adapter.py
Tool adapter and execution tests:
- Schema passthrough preservation
- Tool execution with various content types
- Error handling (returns strings, never raises)
- Timeout enforcement
- Content block parsing (text, image, resource)
- Namespace collision prevention

### test_output_safety.py
Output safety and context protection tests:
- Token counting and estimation
- Text truncation with clear messaging
- Content block truncation
- Disk-backed storage for oversized outputs
- File pointer generation
- Path sanitization and security
- Automatic cleanup of old files

### test_connection_manager.py
Connection lifecycle and management tests:
- Connection establishment and initialization
- Connection deduplication by signature
- Disconnect and cleanup
- Reconnection after failure
- Backoff strategy (exponential with jitter)
- Concurrent connection safety

## Coverage Targets

- **Minimum**: 80% branch coverage
- **Critical paths**: 100% coverage
  - Connection initialization
  - Tool execution
  - Error handling
  - Timeout enforcement
  - Variable expansion
  - Schema passthrough

## Test Patterns

### Async Tests
All async tests use `@pytest.mark.asyncio`:
```python
@pytest.mark.asyncio
async def test_something_async():
    result = await some_async_function()
    assert result is not None
```

### Mock Transports
Use `mock_transport` fixture for protocol tests:
```python
def test_with_mock_transport(mock_transport):
    client = McpProtocolClient(mock_transport)
    # Test protocol behavior
```

### Temporary Files
Use `tempfile` for file system tests:
```python
with tempfile.TemporaryDirectory() as tmpdir:
    storage = McpOutputStorage(workspace_root=tmpdir)
    # Test file operations
```

## Known Test Gaps (TODO)

- [ ] WebSocket transport tests
- [ ] Full end-to-end integration tests
- [ ] Discovery service cache invalidation tests
- [ ] Resource adapter meta-tool tests
- [ ] Prompt adapter tests
- [ ] Error recovery scenario tests
- [ ] Concurrent request handling tests

## CI Integration

Tests run automatically on:
- Pull requests
- Commits to main branch
- Pre-merge validation

Failure blocks merge.
