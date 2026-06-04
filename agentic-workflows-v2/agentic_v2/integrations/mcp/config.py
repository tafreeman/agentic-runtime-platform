"""MCP Configuration Loader.

Loads MCP server configurations from:
1. Project-local: .mcp.json (workspace root)
2. User-global: ~/.mcp.json (user home directory)

Supports VS Code MCP config format with ${input:VAR} and ${env:VAR} expansion.
"""

import hashlib
import json
import logging
import os
import re
from pathlib import Path
from typing import Any

from agentic_v2.integrations.mcp.types import (
    McpServerConfig,
    McpStdioConfig,
    McpWebSocketConfig,
    TransportType,
)

logger = logging.getLogger(__name__)

# Pattern for variable expansion: ${input:var_name} or ${env:var_name} or ${VAR_NAME}
VAR_EXPANSION_PATTERN = re.compile(
    r"\$\{(?:input:)?(?:env:)?([A-Za-z_][A-Za-z0-9_]*)\}"
)


def expand_variables(
    value: str,
    env_vars: dict[str, str] | None = None,
    input_values: dict[str, str] | None = None,
) -> str:
    """Expand ${VAR_NAME}, ${env:VAR_NAME}, and ${input:VAR_NAME} in strings.

    Args:
        value: String with potential variables
        env_vars: Environment variables dict (defaults to current process env)
        input_values: Input values from user prompts

    Returns:
        Expanded string
    """
    if not isinstance(value, str):
        return value

    env_vars = env_vars or dict(os.environ)  # env-pass: subprocess env
    input_values = input_values or {}

    def replacer(match: re.Match) -> str:
        var_name = match.group(1)
        original = match.group(0)

        # Check if it's an input: prefix
        if original.startswith("${input:"):
            result = input_values.get(var_name)
            if result is not None:
                return result
            logger.warning(
                f"Input variable '{var_name}' not provided, leaving unexpanded"
            )
            return original

        # Check if it's an env: prefix or bare ${VAR}
        result = env_vars.get(var_name)
        if result is not None:
            return result

        logger.warning(
            f"Environment variable '{var_name}' not found, leaving unexpanded"
        )
        return original

    return VAR_EXPANSION_PATTERN.sub(replacer, value)


def expand_dict_variables(
    data: dict[str, Any],
    env_vars: dict[str, str] | None = None,
    input_values: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Recursively expand variables in a dictionary.

    Args:
        data: Dictionary to process
        env_vars: Environment variables
        input_values: Input values from prompts

    Returns:
        Dictionary with expanded values
    """
    result = {}

    for key, value in data.items():
        if isinstance(value, str):
            result[key] = expand_variables(value, env_vars, input_values)
        elif isinstance(value, dict):
            result[key] = expand_dict_variables(value, env_vars, input_values)
        elif isinstance(value, list):
            result[key] = [
                (
                    expand_variables(item, env_vars, input_values)
                    if isinstance(item, str)
                    else item
                )
                for item in value
            ]
        else:
            result[key] = value

    return result


def parse_server_config(
    server_name: str,
    server_data: dict[str, Any],
    env_vars: dict[str, str] | None = None,
    input_values: dict[str, str] | None = None,
) -> McpServerConfig | None:
    """Parse a single server configuration from VS Code MCP format.

    Args:
        server_name: Name/ID of the server
        server_data: Server configuration dict
        env_vars: Environment variables for expansion
        input_values: Input values for ${input:VAR} expansion

    Returns:
        McpServerConfig or None if parsing fails
    """
    try:
        # Expand variables in the entire config
        expanded = expand_dict_variables(server_data, env_vars, input_values)

        # Determine transport type
        transport_str = expanded.get("type", "stdio").lower()

        if transport_str == "stdio":
            command = expanded.get("command")
            if not command:
                logger.warning(f"Server '{server_name}' missing 'command' field")
                return None

            stdio_config = McpStdioConfig(
                command=command,
                args=expanded.get("args", []),
                env=expanded.get("env", {}),
            )

            return McpServerConfig(
                name=server_name,
                transport_type=TransportType.STDIO,
                stdio=stdio_config,
                enabled=expanded.get("enabled", True),
            )

        elif transport_str == "http":
            url = expanded.get("url")
            if not url:
                logger.warning(f"Server '{server_name}' missing 'url' field")
                return None

            ws_config = McpWebSocketConfig(
                url=url,
                headers=expanded.get("headers", {}),
            )

            return McpServerConfig(
                name=server_name,
                transport_type=TransportType.WEBSOCKET,
                websocket=ws_config,
                enabled=expanded.get("enabled", True),
            )

        elif transport_str == "sse":
            # SSE (Server-Sent Events) - treat as WebSocket for now
            url = expanded.get("url")
            if not url:
                logger.warning(f"Server '{server_name}' missing 'url' field")
                return None

            ws_config = McpWebSocketConfig(
                url=url,
                headers=expanded.get("headers", {}),
            )

            return McpServerConfig(
                name=server_name,
                transport_type=TransportType.WEBSOCKET,
                websocket=ws_config,
                enabled=expanded.get("enabled", True),
            )

        else:
            logger.warning(
                f"Server '{server_name}' has unsupported transport type: {transport_str}"
            )
            return None

    except Exception as e:
        logger.error(f"Failed to parse server '{server_name}': {e}")
        return None


def load_config_file(
    file_path: str,
    env_vars: dict[str, str] | None = None,
    input_values: dict[str, str] | None = None,
) -> list[McpServerConfig]:
    """Load MCP configuration from a JSON file.

    Args:
        file_path: Path to .mcp.json file
        env_vars: Environment variables for expansion
        input_values: Input values for ${input:VAR} expansion

    Returns:
        List of parsed server configurations
    """
    if not os.path.exists(file_path):
        logger.debug(f"Config file not found: {file_path}")
        return []

    try:
        with open(file_path, encoding="utf-8") as f:
            data = json.load(f)

        servers_data = data.get("servers", {})
        if not isinstance(servers_data, dict):
            logger.warning(f"Invalid 'servers' structure in {file_path}")
            return []

        configs = []
        for server_name, server_data in servers_data.items():
            config = parse_server_config(
                server_name, server_data, env_vars, input_values
            )
            if config:
                configs.append(config)

        logger.info(f"Loaded {len(configs)} server configs from {file_path}")
        return configs

    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in {file_path}: {e}")
        return []
    except Exception as e:
        logger.error(f"Failed to load config from {file_path}: {e}")
        return []


def load_all_configs(
    workspace_root: str | None = None,
    user_home: str | None = None,
    env_vars: dict[str, str] | None = None,
    input_values: dict[str, str] | None = None,
) -> list[McpServerConfig]:
    """Load MCP configurations from all standard locations.

    Priority order:
    1. Project-local: <workspace>/.mcp.json
    2. User-global: ~/.mcp.json

    Args:
        workspace_root: Workspace root directory (defaults to cwd)
        user_home: User home directory (defaults to ~)
        env_vars: Environment variables for expansion
        input_values: Input values for ${input:VAR} expansion

    Returns:
        Deduplicated list of server configurations
    """
    workspace_root = workspace_root or os.getcwd()
    user_home = user_home or str(Path.home())

    all_configs = []

    # Load user-global config first (lower priority)
    user_config_path = os.path.join(user_home, ".mcp.json")
    user_configs = load_config_file(user_config_path, env_vars, input_values)
    all_configs.extend(user_configs)

    # Load project-local config (higher priority)
    project_config_path = os.path.join(workspace_root, ".mcp.json")
    project_configs = load_config_file(project_config_path, env_vars, input_values)
    all_configs.extend(project_configs)

    # Deduplicate by name (project configs override user configs)
    deduplicated = deduplicate_configs(all_configs)

    logger.info(
        f"Loaded {len(deduplicated)} unique MCP server configs "
        f"({len(user_configs)} user, {len(project_configs)} project)"
    )

    return deduplicated


def deduplicate_configs(
    configs: list[McpServerConfig],
) -> list[McpServerConfig]:
    """Deduplicate server configurations by name.

    Later configs (project-local) override earlier ones (user-global).

    Args:
        configs: List of server configurations

    Returns:
        Deduplicated list (preserves last occurrence of each name)
    """
    seen: dict[str, McpServerConfig] = {}

    for config in configs:
        seen[config.name] = config

    return list(seen.values())


def filter_enabled_configs(
    configs: list[McpServerConfig],
) -> list[McpServerConfig]:
    """Filter to only enabled server configurations.

    Args:
        configs: List of server configurations

    Returns:
        List of enabled configurations
    """
    enabled = [c for c in configs if c.enabled]
    logger.info(
        f"Filtered to {len(enabled)} enabled servers (out of {len(configs)} total)"
    )
    return enabled


def get_server_signatures(
    configs: list[McpServerConfig],
) -> dict[str, str]:
    """Generate unique signatures for each server config.

    Used by McpConnectionManager for deduplication.

    Args:
        configs: List of server configurations

    Returns:
        Dict mapping server name to signature hash
    """
    signatures = {}
    for config in configs:
        # Compute signature based on transport config
        if config.stdio:
            key = f"stdio:{config.stdio.command}:{':'.join(config.stdio.args)}"
        elif config.websocket:
            key = f"ws:{config.websocket.url}"
        elif config.sse:
            key = f"sse:{config.sse.url}"
        else:
            # Fallback to full config serialization
            key = f"{config.transport_type}:{config.model_dump_json()}"

        signatures[config.name] = hashlib.sha256(key.encode()).hexdigest()[:16]

    return signatures


class McpConfigLoader:
    """High-level configuration loader with caching and validation.

    Example:
        loader = McpConfigLoader(workspace_root="/path/to/project")
        configs = loader.load()
        enabled_configs = loader.get_enabled()
    """

    def __init__(
        self,
        workspace_root: str | None = None,
        user_home: str | None = None,
        env_vars: dict[str, str] | None = None,
        input_values: dict[str, str] | None = None,
    ) -> None:
        """Initialize config loader.

        Args:
            workspace_root: Project workspace root
            user_home: User home directory
            env_vars: Environment variables for expansion
            input_values: Input values for ${input:VAR} expansion
        """
        self.workspace_root = workspace_root or os.getcwd()
        self.user_home = user_home or str(Path.home())
        self.env_vars = env_vars or dict(os.environ)  # env-pass: subprocess env
        self.input_values = input_values or {}
        self._cached_configs: list[McpServerConfig] | None = None

    def load(self, force_reload: bool = False) -> list[McpServerConfig]:
        """Load all configurations (with caching).

        Args:
            force_reload: Force reload from disk (ignore cache)

        Returns:
            List of server configurations
        """
        if self._cached_configs is not None and not force_reload:
            return self._cached_configs

        self._cached_configs = load_all_configs(
            self.workspace_root,
            self.user_home,
            self.env_vars,
            self.input_values,
        )
        return self._cached_configs

    def get_enabled(self, force_reload: bool = False) -> list[McpServerConfig]:
        """Get only enabled server configurations.

        Args:
            force_reload: Force reload from disk

        Returns:
            List of enabled configurations
        """
        all_configs = self.load(force_reload)
        return filter_enabled_configs(all_configs)

    def get_by_name(self, name: str) -> McpServerConfig | None:
        """Get a specific server configuration by name.

        Args:
            name: Server name

        Returns:
            Server configuration or None
        """
        configs = self.load()
        for config in configs:
            if config.name == name:
                return config
        return None

    def clear_cache(self) -> None:
        """Clear cached configurations (force reload on next access)."""
        self._cached_configs = None
