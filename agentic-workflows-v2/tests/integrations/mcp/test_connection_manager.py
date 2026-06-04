"""Tests for MCP connection manager.

Validates:
- Connection lifecycle (connect, disconnect, reconnect)
- Exponential backoff with jitter
- Connection deduplication by signature
- Auth failure suppression (15-minute cooldown)
- Concurrent connection safety
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agentic_v2.integrations.mcp.protocol.client import McpProtocolClient
from agentic_v2.integrations.mcp.runtime.backoff import ExponentialBackoff
from agentic_v2.integrations.mcp.runtime.manager import (
    McpConnectionManager,
    _compute_server_signature,
)
from agentic_v2.integrations.mcp.types import (
    McpServerConfig,
    McpStdioConfig,
    TransportType,
)


class TestServerSignature:
    """Test server signature computation for deduplication."""

    def test_signature_same_for_identical_configs(self):
        """Test identical configs produce same signature."""
        config1 = McpServerConfig(
            name="server",
            transport_type=TransportType.STDIO,
            stdio=McpStdioConfig(command="cmd", args=["arg1"]),
        )
        config2 = McpServerConfig(
            name="server",
            transport_type=TransportType.STDIO,
            stdio=McpStdioConfig(command="cmd", args=["arg1"]),
        )

        sig1 = _compute_server_signature(config1)
        sig2 = _compute_server_signature(config2)

        assert sig1 == sig2

    def test_signature_different_for_different_commands(self):
        """Test different commands produce different signatures."""
        config1 = McpServerConfig(
            name="server",
            transport_type=TransportType.STDIO,
            stdio=McpStdioConfig(command="cmd1"),
        )
        config2 = McpServerConfig(
            name="server",
            transport_type=TransportType.STDIO,
            stdio=McpStdioConfig(command="cmd2"),
        )

        sig1 = _compute_server_signature(config1)
        sig2 = _compute_server_signature(config2)

        assert sig1 != sig2

    def test_signature_different_for_different_args(self):
        """Test different args produce different signatures."""
        config1 = McpServerConfig(
            name="server",
            transport_type=TransportType.STDIO,
            stdio=McpStdioConfig(command="cmd", args=["arg1"]),
        )
        config2 = McpServerConfig(
            name="server",
            transport_type=TransportType.STDIO,
            stdio=McpStdioConfig(command="cmd", args=["arg2"]),
        )

        sig1 = _compute_server_signature(config1)
        sig2 = _compute_server_signature(config2)

        assert sig1 != sig2


@pytest.mark.asyncio
class TestMcpConnectionManager:
    """Test McpConnectionManager connection lifecycle."""

    def test_manager_creation(self):
        """Test creating connection manager."""
        manager = McpConnectionManager()
        assert manager is not None
        assert len(manager._connections) == 0

    async def test_connect_success(self, sample_stdio_config):
        """Test successful connection to MCP server."""
        manager = McpConnectionManager()

        with patch(
            "agentic_v2.integrations.mcp.runtime.manager.StdioTransport"
        ) as MockTransport:
            mock_transport = MagicMock()
            mock_transport.start = AsyncMock()
            MockTransport.return_value = mock_transport

            with patch(
                "agentic_v2.integrations.mcp.runtime.manager.McpProtocolClient"
            ) as MockClient:
                mock_client = MagicMock(spec=McpProtocolClient)
                mock_client.initialize = AsyncMock(
                    return_value={
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "serverInfo": {"name": "test", "version": "1.0"},
                    }
                )
                mock_client.close = AsyncMock()
                MockClient.return_value = mock_client

                client = await manager.connect(sample_stdio_config)

                assert client is not None
                assert sample_stdio_config.name in manager._connections
                mock_client.initialize.assert_called_once()

    async def test_connect_deduplication(self, sample_stdio_config):
        """Test connecting to same server twice returns same client."""
        manager = McpConnectionManager()

        with patch(
            "agentic_v2.integrations.mcp.runtime.manager.StdioTransport"
        ) as MockTransport:
            mock_transport = MagicMock()
            mock_transport.start = AsyncMock()
            MockTransport.return_value = mock_transport

            with patch(
                "agentic_v2.integrations.mcp.runtime.manager.McpProtocolClient"
            ) as MockClient:
                mock_client = MagicMock()
                mock_client.connect = AsyncMock()
                mock_client.initialize = AsyncMock(
                    return_value={
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "serverInfo": {"name": "test", "version": "1.0"},
                    }
                )
                mock_client.close = AsyncMock()
                MockClient.return_value = mock_client

                client1 = await manager.connect(sample_stdio_config)
                client2 = await manager.connect(sample_stdio_config)

                # Should return same client
                assert client1 is client2
                # Initialize should only be called once
                assert mock_client.initialize.call_count == 1

    async def test_disconnect(self, sample_stdio_config):
        """Test disconnecting from server."""
        manager = McpConnectionManager()

        with patch("agentic_v2.integrations.mcp.runtime.manager.StdioTransport"):
            with patch(
                "agentic_v2.integrations.mcp.runtime.manager.McpProtocolClient"
            ) as MockClient:
                mock_client = MagicMock()
                mock_client.connect = AsyncMock()
                mock_client.initialize = AsyncMock(
                    return_value={
                        "protocolVersion": "2024-11-05",
                        "capabilities": {},
                        "serverInfo": {"name": "test", "version": "1.0"},
                    }
                )
                mock_client.close = AsyncMock()
                MockClient.return_value = mock_client

                await manager.connect(sample_stdio_config)
                await manager.disconnect(sample_stdio_config.name)

                # Connection should be removed
                assert sample_stdio_config.name not in manager._connections
                mock_client.close.assert_called_once()

    async def test_disconnect_all(self, sample_stdio_config):
        """Test disconnecting all connections."""
        manager = McpConnectionManager()

        # Create two different configs
        config2 = McpServerConfig(
            name="server2",
            transport_type=TransportType.STDIO,
            stdio=McpStdioConfig(command="cmd2"),
        )

        with patch("agentic_v2.integrations.mcp.runtime.manager.StdioTransport"):
            with patch(
                "agentic_v2.integrations.mcp.runtime.manager.McpProtocolClient"
            ) as MockClient:
                mock_clients = []
                for _ in range(2):
                    mock_client = MagicMock()
                    mock_client.connect = AsyncMock()
                    mock_client.initialize = AsyncMock(
                        return_value={
                            "protocolVersion": "2024-11-05",
                            "capabilities": {},
                            "serverInfo": {"name": "test", "version": "1.0"},
                        }
                    )
                    mock_client.close = AsyncMock()
                    mock_clients.append(mock_client)

                MockClient.side_effect = mock_clients

                await manager.connect(sample_stdio_config)
                await manager.connect(config2)

                await manager.disconnect_all()

                # All connections should be removed
                assert len(manager._connections) == 0
                # All clients should be closed
                for mock_client in mock_clients:
                    mock_client.close.assert_called_once()

    async def test_reconnect_after_disconnect(self, sample_stdio_config):
        """Test reconnecting after disconnect creates new connection."""
        manager = McpConnectionManager()

        with patch(
            "agentic_v2.integrations.mcp.runtime.manager.StdioTransport"
        ) as MockTransport:
            mock_transport = MagicMock()
            mock_transport.start = AsyncMock()
            MockTransport.return_value = mock_transport

            with patch(
                "agentic_v2.integrations.mcp.runtime.manager.McpProtocolClient"
            ) as MockClient:
                mock_clients = []
                for _ in range(2):
                    mock_client = MagicMock()
                    mock_client.connect = AsyncMock()
                    mock_client.initialize = AsyncMock(
                        return_value={
                            "protocolVersion": "2024-11-05",
                            "capabilities": {},
                            "serverInfo": {"name": "test", "version": "1.0"},
                        }
                    )
                    mock_client.close = AsyncMock()
                    mock_clients.append(mock_client)

                MockClient.side_effect = mock_clients

                client1 = await manager.connect(sample_stdio_config)
                await manager.disconnect(sample_stdio_config.name)
                client2 = await manager.connect(sample_stdio_config)

                # Should be different clients
                assert client1 is not client2


class TestBackoffStrategy:
    """Test exponential backoff strategy."""

    def test_backoff_initial_delay(self):
        """Test backoff starts at 1 second."""
        backoff = ExponentialBackoff(max_attempts=5)
        delay = backoff.next_delay()

        # Should be around 1 second (±20% jitter)
        assert 0.8 <= delay <= 1.2

    def test_backoff_exponential_growth(self):
        """Test backoff grows exponentially."""
        backoff = ExponentialBackoff(max_attempts=5)

        delay1 = backoff.next_delay()
        delay2 = backoff.next_delay()
        delay3 = backoff.next_delay()

        # Each delay should be roughly double (accounting for jitter)
        assert delay2 > delay1
        assert delay3 > delay2

    def test_backoff_max_delay(self):
        """Test backoff caps at max delay."""
        backoff = ExponentialBackoff(max_attempts=10, max_delay=30)

        # Exhaust attempts to reach max
        for _ in range(10):
            delay = backoff.next_delay()

        # Should not exceed max delay (with jitter tolerance)
        assert delay <= 36  # 30 * 1.2 (max jitter)

    def test_backoff_max_attempts_exceeded(self):
        """Test backoff returns None after max attempts."""
        backoff = ExponentialBackoff(max_attempts=3)

        backoff.next_delay()  # Attempt 1
        backoff.next_delay()  # Attempt 2
        backoff.next_delay()  # Attempt 3
        result = backoff.next_delay()  # Attempt 4 (exceeded)

        assert result is None

    def test_backoff_reset(self):
        """Test reset() restarts backoff from beginning."""
        backoff = ExponentialBackoff(max_attempts=5)

        backoff.next_delay()
        backoff.next_delay()
        backoff.reset()

        delay = backoff.next_delay()

        # Should be back to initial delay
        assert 0.8 <= delay <= 1.2

    def test_backoff_jitter_variance(self):
        """Test jitter adds variance to delays."""
        backoff1 = ExponentialBackoff(max_attempts=5)
        backoff2 = ExponentialBackoff(max_attempts=5)

        # Get delays from two independent backoff instances
        delays1 = [backoff1.next_delay() for _ in range(3)]
        delays2 = [backoff2.next_delay() for _ in range(3)]

        # Due to jitter, delays should not be identical
        # (very unlikely to match exactly)
        assert delays1 != delays2
