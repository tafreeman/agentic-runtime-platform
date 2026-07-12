"""
MCP Connection Manager - orchestrates server connections and lifecycle.

Handles connection memoization, reconnection with exponential backoff,
auth failure suppression, and capability-driven discovery.
"""

import asyncio
import hashlib
import logging
import time
from collections.abc import Callable

from agentic_v2.integrations.mcp.protocol.client import (
    McpProtocolClient,
    McpProtocolError,
)
from agentic_v2.integrations.mcp.runtime.backoff import ExponentialBackoff
from agentic_v2.integrations.mcp.transports.stdio import StdioTransport
from agentic_v2.integrations.mcp.transports.websocket import WebSocketTransport
from agentic_v2.integrations.mcp.types import (
    McpConnectionState,
    McpServerConfig,
    McpServerInfo,
    TransportType,
)

logger = logging.getLogger(__name__)

# Auth failure suppression: cache 401s for 15 minutes
AUTH_FAILURE_CACHE_DURATION = 15 * 60  # 15 minutes in seconds


def _compute_server_signature(config: McpServerConfig) -> str:
    """Compute a stable 16-char hex signature for a server config.

    Two configs with the same signature represent the same server and
    can share a connection.

    Args:
        config: Server configuration.

    Returns:
        16-character hex digest.
    """
    if config.transport_type == "stdio" and config.stdio is not None:
        args_str = ":".join(config.stdio.args or [])
        key = f"stdio:{config.stdio.command}:{args_str}"
    elif config.transport_type == "websocket" and config.websocket is not None:
        key = f"ws:{config.websocket.url}"
    else:
        key = config.model_dump_json()
    return hashlib.sha256(key.encode()).hexdigest()[:16]


class ConnectionMetadata:
    """Metadata for a managed connection."""

    def __init__(
        self,
        name: str,
        config: McpServerConfig,
        client: McpProtocolClient,
        backoff: ExponentialBackoff,
    ) -> None:
        self.name = name
        self.config = config
        self.client = client
        self.backoff = backoff
        self.state = McpConnectionState.CONNECTING
        self.server_info: McpServerInfo | None = None
        self.last_error: str | None = None
        self.auth_failure_timestamp: float | None = None

    def is_auth_suppressed(self) -> bool:
        """Check if auth failures are being suppressed (within cache window)."""
        if not self.auth_failure_timestamp:
            return False
        elapsed = time.time() - self.auth_failure_timestamp
        return elapsed < AUTH_FAILURE_CACHE_DURATION

    def record_auth_failure(self) -> None:
        """Record an auth failure timestamp."""
        self.auth_failure_timestamp = time.time()
        self.state = McpConnectionState.NEEDS_AUTH
        logger.warning(
            f"Auth failure recorded for {self.name}, suppressing retries for {AUTH_FAILURE_CACHE_DURATION}s"
        )

    def clear_auth_failure(self) -> None:
        """Clear auth failure suppression."""
        self.auth_failure_timestamp = None


class McpConnectionManager:
    """Manages MCP server connections with lifecycle control.

    Features:
    - Connection memoization (one connection per server signature)
    - Exponential backoff on failures
    - Auth failure suppression (15-minute cache)
    - Capability-driven initialization
    - Graceful cleanup
    """

    def __init__(self) -> None:
        """Initialize connection manager."""
        self._connections: dict[str, ConnectionMetadata] = {}
        self._lock = asyncio.Lock()

    def _compute_server_signature(self, config: McpServerConfig) -> str:
        """Delegate to module-level function for testability."""
        return _compute_server_signature(config)

    async def connect(
        self,
        config_or_name: "McpServerConfig | str",
        config: "McpServerConfig | None" = None,
        force_new: bool = False,
    ) -> McpProtocolClient:
        """Connect to an MCP server (or return existing connection).

        Args:
            config_or_name: Server config (single-arg form) or server name string.
            config: Server config when config_or_name is a name string.
            force_new: Force new connection even if one exists.

        Returns:
            Connected protocol client

        Raises:
            ConnectionError: If connection fails after retries
            RuntimeError: If auth is suppressed due to recent 401
        """
        if isinstance(config_or_name, str):
            name: str = config_or_name
            if config is None:
                raise ValueError("config must be provided when name is a string")
        else:
            config = config_or_name
            name = config.name

        async with self._lock:
            signature = self._compute_server_signature(config)

            # Check for existing connection by name
            if not force_new and name in self._connections:
                metadata = self._connections[name]

                # Check auth suppression
                if metadata.is_auth_suppressed():
                    raise RuntimeError(
                        f"Auth failures suppressed for {name} (retry after {AUTH_FAILURE_CACHE_DURATION}s)"
                    )

                # Return existing if connected
                if metadata.state == McpConnectionState.CONNECTED:
                    logger.debug(f"Reusing existing connection: {name}")
                    return metadata.client

            # Create new connection
            logger.info(f"Creating new connection: {name}")
            return await self._create_connection(name, config, signature)

    async def _create_connection(
        self,
        name: str,
        config: McpServerConfig,
        signature: str,
    ) -> McpProtocolClient:
        """Create and initialize a new MCP connection.

        Args:
            name: Server name
            config: Server config
            signature: Server signature (for memoization)

        Returns:
            Connected and initialized protocol client

        Raises:
            ConnectionError: If connection fails
        """
        # Create transport based on transport_type field
        transport = self._build_transport(config)

        # Create protocol client
        client = McpProtocolClient(transport)
        backoff = ExponentialBackoff(max_attempts=5)

        # Store metadata
        metadata = ConnectionMetadata(
            name=name,
            config=config,
            client=client,
            backoff=backoff,
        )
        self._connections[name] = metadata

        # Attempt connection with backoff
        last_error: Exception | None = None

        while not backoff.is_exhausted:
            try:
                return await self._attempt_connect(client, metadata)

            except TimeoutError as e:
                last_error = e
                metadata.last_error = f"Timeout: {e}"
                retried = await self._schedule_retry(
                    metadata,
                    lambda delay: (
                        f"Connection timeout for {name}, retrying in {delay:.1f}s "
                        f"(attempt {backoff.attempt_count})"
                    ),
                )
                if not retried:
                    break

            except McpProtocolError as e:
                last_error = e
                metadata.last_error = f"Protocol error: {e}"
                self._raise_if_auth_failure(metadata, e)

                # Other protocol errors: retry with backoff
                retried = await self._schedule_retry(
                    metadata,
                    lambda delay, exc=e: (
                        f"Protocol error for {name}, retrying in {delay:.1f}s: {exc}"
                    ),
                )
                if not retried:
                    break

            except Exception as e:
                last_error = e
                metadata.last_error = f"Unexpected error: {e}"
                metadata.state = McpConnectionState.FAILED
                logger.error(f"Unexpected error connecting to {name}: {e}")
                break

        # All retries exhausted
        metadata.state = McpConnectionState.FAILED
        raise ConnectionError(
            f"Failed to connect to {name} after {backoff.attempt_count} attempts: {last_error}"
        )

    @staticmethod
    def _raise_if_auth_failure(
        metadata: ConnectionMetadata,
        error: McpProtocolError,
    ) -> None:
        """Record and re-raise as RuntimeError when the error is a 401.

        No-op for non-auth protocol errors, allowing the caller to retry.

        Raises:
            RuntimeError: If the error indicates an authentication failure.
        """
        if "401" in str(error) or "Unauthorized" in str(error):
            metadata.record_auth_failure()
            raise RuntimeError(f"Auth failure for {metadata.name}: {error}") from error

    @staticmethod
    async def _schedule_retry(
        metadata: ConnectionMetadata,
        build_log_message: Callable[[float], str],
    ) -> bool:
        """Transition to RECONNECTING and wait for the next backoff delay.

        Args:
            metadata: Connection metadata holding the backoff schedule.
            build_log_message: Factory invoked with the computed delay to
                produce the warning message logged before sleeping.

        Returns:
            ``True`` if a retry was scheduled (delay applied), ``False`` when
            the backoff is exhausted and the caller should stop retrying.
        """
        metadata.state = McpConnectionState.RECONNECTING
        delay = metadata.backoff.next_delay()
        if not delay:
            return False
        logger.warning(build_log_message(delay))
        await asyncio.sleep(delay)
        return True

    @staticmethod
    def _build_transport(
        config: McpServerConfig,
    ) -> "StdioTransport | WebSocketTransport":
        """Create the transport for a server config based on its transport_type."""
        if config.transport_type == TransportType.STDIO and config.stdio is not None:
            return StdioTransport(
                command=config.stdio.command,
                args=config.stdio.args or [],
                env=config.stdio.env or {},
            )
        if (
            config.transport_type == TransportType.WEBSOCKET
            and config.websocket is not None
        ):
            return WebSocketTransport(
                url=config.websocket.url,
                headers=config.websocket.headers or {},
            )
        raise ValueError(
            f"Unsupported or misconfigured transport: {config.transport_type}"
        )

    @staticmethod
    async def _attempt_connect(
        client: McpProtocolClient,
        metadata: ConnectionMetadata,
    ) -> McpProtocolClient:
        """Connect and perform the initialize handshake for a single attempt.

        On success, updates metadata state and returns the connected
        client.
        """
        # Start transport
        await client.connect()

        # Perform initialize handshake
        init_response = await client.initialize()
        if isinstance(init_response, dict):
            raw_info = init_response.get("serverInfo", {})
            server_info = McpServerInfo.model_validate(raw_info) if raw_info else None
        else:
            server_info = init_response
        metadata.server_info = server_info
        metadata.state = McpConnectionState.CONNECTED
        metadata.last_error = None
        metadata.backoff.reset()

        info_str = (
            f"{server_info.name} v{server_info.version}" if server_info else "unknown"
        )
        logger.info(f"Successfully connected to {metadata.name}: {info_str}")
        return client

    async def disconnect(self, name: str) -> None:
        """Disconnect from a server by name.

        Args:
            name: Server name
        """
        async with self._lock:
            # Find connection by name
            for signature, metadata in self._connections.items():
                if metadata.name == name:
                    logger.info(f"Disconnecting from {name}")
                    await metadata.client.close()
                    metadata.state = McpConnectionState.DISCONNECTED
                    del self._connections[signature]
                    return

            logger.warning(f"No connection found for {name}")

    async def disconnect_all(self) -> None:
        """Disconnect from all servers."""
        async with self._lock:
            logger.info(f"Disconnecting from {len(self._connections)} servers")

            for metadata in self._connections.values():
                try:
                    await metadata.client.close()
                except Exception as e:
                    logger.error(f"Error closing connection {metadata.name}: {e}")

            self._connections.clear()

    def get_connection(self, name: str) -> McpProtocolClient | None:
        """Get existing connection by name (if connected).

        Args:
            name: Server name

        Returns:
            Protocol client if connected, None otherwise
        """
        for metadata in self._connections.values():
            if metadata.name == name and metadata.state == McpConnectionState.CONNECTED:
                return metadata.client
        return None

    def get_connection_state(self, name: str) -> McpConnectionState | None:
        """Get connection state by name.

        Args:
            name: Server name

        Returns:
            Connection state if exists, None otherwise
        """
        for metadata in self._connections.values():
            if metadata.name == name:
                return metadata.state
        return None

    def list_connections(self) -> dict[str, tuple[McpConnectionState, str | None]]:
        """List all connections with their states.

        Returns:
            Dict mapping server name to (state, error_message)
        """
        return {
            metadata.name: (metadata.state, metadata.last_error)
            for metadata in self._connections.values()
        }
