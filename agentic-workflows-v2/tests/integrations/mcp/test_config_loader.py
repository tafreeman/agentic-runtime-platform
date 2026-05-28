"""Tests for MCP configuration loader.

Validates:
- Variable expansion (${VAR}, ${env:VAR}, ${input:VAR})
- Multi-source loading (user + project configs)
- Server deduplication
- Error handling for malformed configs
"""

import json
import os
import tempfile
from pathlib import Path

from agentic_v2.integrations.mcp.config import (
    McpConfigLoader,
    deduplicate_configs,
    expand_dict_variables,
    expand_variables,
    filter_enabled_configs,
    load_config_file,
    parse_server_config,
)
from agentic_v2.integrations.mcp.types import TransportType


class TestVariableExpansion:
    """Test variable expansion functionality."""

    def test_expand_simple_env_var(self):
        """Test basic ${VAR_NAME} expansion."""
        env_vars = {"TEST_VAR": "test_value"}
        result = expand_variables("${TEST_VAR}", env_vars=env_vars)
        assert result == "test_value"

    def test_expand_env_prefix(self):
        """Test ${env:VAR_NAME} expansion."""
        env_vars = {"TEST_VAR": "test_value"}
        result = expand_variables("${env:TEST_VAR}", env_vars=env_vars)
        assert result == "test_value"

    def test_expand_input_var(self):
        """Test ${input:VAR_NAME} expansion."""
        input_values = {"api_key": "secret_key"}
        result = expand_variables("${input:api_key}", input_values=input_values)
        assert result == "secret_key"

    def test_expand_missing_env_var(self):
        """Test expansion with missing env var (should leave unexpanded)."""
        result = expand_variables("${MISSING_VAR}", env_vars={})
        assert result == "${MISSING_VAR}"

    def test_expand_missing_input_var(self):
        """Test expansion with missing input var."""
        result = expand_variables("${input:MISSING}", input_values={})
        assert result == "${input:MISSING}"

    def test_expand_multiple_vars(self):
        """Test expansion with multiple variables in one string."""
        env_vars = {"HOST": "localhost", "PORT": "8080"}
        result = expand_variables("http://${HOST}:${PORT}/api", env_vars=env_vars)
        assert result == "http://localhost:8080/api"

    def test_expand_dict_variables(self):
        """Test recursive expansion in nested dicts."""
        data = {
            "url": "${BASE_URL}/api",
            "headers": {"Authorization": "Bearer ${API_TOKEN}"},
            "env": {"PATH": "/usr/bin:${HOME}/bin"},
        }
        env_vars = {
            "BASE_URL": "https://api.example.com",
            "API_TOKEN": "token123",
            "HOME": "/home/user",
        }

        result = expand_dict_variables(data, env_vars=env_vars)

        assert result["url"] == "https://api.example.com/api"
        assert result["headers"]["Authorization"] == "Bearer token123"
        assert result["env"]["PATH"] == "/usr/bin:/home/user/bin"

    def test_expand_list_values(self):
        """Test expansion in list values."""
        data = {"args": ["--port", "${PORT}", "--host", "${HOST}"]}
        env_vars = {"PORT": "3000", "HOST": "0.0.0.0"}

        result = expand_dict_variables(data, env_vars=env_vars)

        assert result["args"] == ["--port", "3000", "--host", "0.0.0.0"]


class TestServerConfigParsing:
    """Test server configuration parsing."""

    def test_parse_stdio_config(self):
        """Test parsing stdio server config."""
        server_data = {
            "type": "stdio",
            "command": "npx",
            "args": ["test-server"],
            "env": {"API_KEY": "${TEST_KEY}"},
        }
        env_vars = {"TEST_KEY": "key123"}

        config = parse_server_config("test-server", server_data, env_vars=env_vars)

        assert config is not None
        assert config.name == "test-server"
        assert config.transport_type == TransportType.STDIO
        assert config.stdio.command == "npx"
        assert config.stdio.args == ["test-server"]
        assert config.stdio.env["API_KEY"] == "key123"

    def test_parse_http_config(self):
        """Test parsing HTTP server config."""
        server_data = {
            "type": "http",
            "url": "https://api.example.com",
            "headers": {"Authorization": "Bearer ${TOKEN}"},
        }
        env_vars = {"TOKEN": "abc123"}

        config = parse_server_config("http-server", server_data, env_vars=env_vars)

        assert config is not None
        assert config.name == "http-server"
        assert config.transport_type == TransportType.WEBSOCKET
        assert config.websocket.url == "https://api.example.com"
        assert config.websocket.headers["Authorization"] == "Bearer abc123"

    def test_parse_sse_config(self):
        """Test parsing SSE server config (mapped to WebSocket)."""
        server_data = {"type": "sse", "url": "https://api.example.com/sse"}

        config = parse_server_config("sse-server", server_data)

        assert config is not None
        assert config.transport_type == TransportType.WEBSOCKET

    def test_parse_missing_command(self):
        """Test parsing fails gracefully with missing command."""
        server_data = {"type": "stdio", "args": ["test"]}

        config = parse_server_config("bad-server", server_data)

        assert config is None

    def test_parse_missing_url(self):
        """Test parsing fails gracefully with missing URL."""
        server_data = {"type": "http", "headers": {}}

        config = parse_server_config("bad-server", server_data)

        assert config is None

    def test_parse_enabled_flag(self):
        """Test parsing respects enabled flag."""
        server_data = {
            "type": "stdio",
            "command": "test",
            "enabled": False,
        }

        config = parse_server_config("disabled-server", server_data)

        assert config is not None
        assert config.enabled is False


class TestConfigFileLoading:
    """Test configuration file loading."""

    def test_load_valid_config_file(self):
        """Test loading valid .mcp.json file."""
        config_data = {
            "servers": {
                "test-server": {
                    "type": "stdio",
                    "command": "npx",
                    "args": ["test"],
                }
            }
        }

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(config_data, f)
            temp_path = f.name

        try:
            configs = load_config_file(temp_path)
            assert len(configs) == 1
            assert configs[0].name == "test-server"
        finally:
            os.unlink(temp_path)

    def test_load_nonexistent_file(self):
        """Test loading non-existent file returns empty list."""
        configs = load_config_file("/nonexistent/path/.mcp.json")
        assert configs == []

    def test_load_invalid_json(self):
        """Test loading invalid JSON returns empty list."""
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write("{invalid json")
            temp_path = f.name

        try:
            configs = load_config_file(temp_path)
            assert configs == []
        finally:
            os.unlink(temp_path)

    def test_load_missing_servers_key(self):
        """Test loading config without 'servers' key."""
        config_data = {"other_key": "value"}

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(config_data, f)
            temp_path = f.name

        try:
            configs = load_config_file(temp_path)
            assert configs == []
        finally:
            os.unlink(temp_path)


class TestConfigDeduplication:
    """Test server configuration deduplication."""

    def test_deduplicate_by_name(self):
        """Test deduplication keeps last occurrence of each name."""
        from agentic_v2.integrations.mcp.types import (
            McpServerConfig,
            McpStdioConfig,
            TransportType,
        )

        config1 = McpServerConfig(
            name="server1",
            transport_type=TransportType.STDIO,
            stdio=McpStdioConfig(command="cmd1"),
        )
        config2 = McpServerConfig(
            name="server2",
            transport_type=TransportType.STDIO,
            stdio=McpStdioConfig(command="cmd2"),
        )
        config3 = McpServerConfig(
            name="server1",  # Duplicate name
            transport_type=TransportType.STDIO,
            stdio=McpStdioConfig(command="cmd3"),
        )

        configs = [config1, config2, config3]
        deduplicated = deduplicate_configs(configs)

        assert len(deduplicated) == 2
        # config3 should override config1
        server1 = next(c for c in deduplicated if c.name == "server1")
        assert server1.stdio.command == "cmd3"


class TestEnabledFiltering:
    """Test enabled server filtering."""

    def test_filter_enabled_only(self):
        """Test filtering returns only enabled servers."""
        from agentic_v2.integrations.mcp.types import (
            McpServerConfig,
            McpStdioConfig,
            TransportType,
        )

        configs = [
            McpServerConfig(
                name="enabled1",
                transport_type=TransportType.STDIO,
                stdio=McpStdioConfig(command="cmd"),
                enabled=True,
            ),
            McpServerConfig(
                name="disabled",
                transport_type=TransportType.STDIO,
                stdio=McpStdioConfig(command="cmd"),
                enabled=False,
            ),
            McpServerConfig(
                name="enabled2",
                transport_type=TransportType.STDIO,
                stdio=McpStdioConfig(command="cmd"),
                enabled=True,
            ),
        ]

        enabled = filter_enabled_configs(configs)

        assert len(enabled) == 2
        assert all(c.enabled for c in enabled)


class TestMcpConfigLoader:
    """Test high-level McpConfigLoader class."""

    def test_loader_caches_configs(self):
        """Test loader caches configs after first load."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / ".mcp.json"
            config_data = {"servers": {"test": {"type": "stdio", "command": "test"}}}
            config_path.write_text(json.dumps(config_data))

            loader = McpConfigLoader(workspace_root=tmpdir)

            # First load
            configs1 = loader.load()
            # Second load (should use cache)
            configs2 = loader.load()

            assert configs1 is configs2  # Same object reference

    def test_loader_force_reload(self):
        """Test force reload bypasses cache."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / ".mcp.json"
            config_data = {"servers": {"test": {"type": "stdio", "command": "test"}}}
            config_path.write_text(json.dumps(config_data))

            loader = McpConfigLoader(workspace_root=tmpdir)

            configs1 = loader.load()
            configs2 = loader.load(force_reload=True)

            # Different objects (reloaded)
            assert configs1 is not configs2
            assert len(configs1) == len(configs2)

    def test_loader_get_by_name(self):
        """Test get_by_name retrieves specific config."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / ".mcp.json"
            config_data = {
                "servers": {
                    "server1": {"type": "stdio", "command": "cmd1"},
                    "server2": {"type": "stdio", "command": "cmd2"},
                }
            }
            config_path.write_text(json.dumps(config_data))

            loader = McpConfigLoader(workspace_root=tmpdir)

            config = loader.get_by_name("server1")

            assert config is not None
            assert config.name == "server1"

    def test_loader_clear_cache(self):
        """Test clear_cache forces reload on next access."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_path = Path(tmpdir) / ".mcp.json"
            config_data = {"servers": {"test": {"type": "stdio", "command": "test"}}}
            config_path.write_text(json.dumps(config_data))

            loader = McpConfigLoader(workspace_root=tmpdir)

            configs1 = loader.load()
            loader.clear_cache()
            configs2 = loader.load()

            # Different objects after cache clear
            assert configs1 is not configs2
