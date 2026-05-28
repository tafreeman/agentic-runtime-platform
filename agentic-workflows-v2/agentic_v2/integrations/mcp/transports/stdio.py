"""Stdio transport for MCP servers running as subprocesses.

Spawns a local process and communicates via stdin/stdout using JSON-RPC.
Implements graceful shutdown with SIGINT → SIGTERM → SIGKILL escalation.
"""

import asyncio
import json
import logging
import signal
from typing import Optional

from agentic_v2.integrations.mcp.transports.base import McpTransport
from agentic_v2.integrations.mcp.types import (
    JsonRpcMessage,
    JsonRpcNotification,
    JsonRpcRequest,
    JsonRpcResponse,
)

logger = logging.getLogger(__name__)

# Subprocess cleanup timeouts (matching claude-code-main patterns)
SIGINT_TIMEOUT_SEC = 5.0
SIGTERM_TIMEOUT_SEC = 5.0
SIGKILL_TIMEOUT_SEC = 5.0


class StdioTransport(McpTransport):
    """Transport for MCP servers running as local subprocesses.

    Communicates via newline-delimited JSON over stdin/stdout. Handles
    process lifecycle with graceful shutdown escalation.
    """

    def __init__(
        self,
        command: str,
        args: Optional[list[str]] = None,
        env: Optional[dict[str, str]] = None,
    ) -> None:
        """Initialize stdio transport.

        Args:
            command: Executable command (e.g., "npx", "python", "/path/to/binary")
            args: Command arguments
            env: Extra environment variables merged into the subprocess env
        """
        super().__init__()
        self.command = command
        self.args = args or []
        self.env = env
        self._process: Optional[asyncio.subprocess.Process] = None
        self._read_task: Optional[asyncio.Task] = None

    async def start(self) -> None:
        """Spawn the subprocess and start reading from stdout.

        Raises:
            RuntimeError: If already started.
            ConnectionError: If subprocess fails to start.
        """
        if self._started:
            raise RuntimeError("Transport already started")
        if self._closed:
            raise RuntimeError("Transport is closed")

        logger.debug(f"Starting subprocess: {self.command} {' '.join(self.args)}")

        try:
            self._process = await asyncio.create_subprocess_exec(
                self.command,
                *self.args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=self.env,
            )
        except Exception as e:
            raise ConnectionError(f"Failed to spawn subprocess: {e}") from e

        self._started = True
        # Start reading stdout in background
        self._read_task = asyncio.create_task(self._read_loop())
        logger.info(f"Subprocess started: PID={self._process.pid}")

    async def send(self, message: JsonRpcMessage) -> None:
        """Send a JSON-RPC message via stdin.

        Args:
            message: JSON-RPC message (request, response, or notification)

        Raises:
            RuntimeError: If transport not started or process died.
            ConnectionError: If write fails.
        """
        self._ensure_started()

        if not self._process or not self._process.stdin:
            raise RuntimeError("Process stdin unavailable")

        try:
            # Serialize to JSON and write with newline delimiter
            payload = json.dumps(message.model_dump(exclude_none=True)) + "\n"
            self._process.stdin.write(payload.encode("utf-8"))
            await self._process.stdin.drain()
        except Exception as e:
            raise ConnectionError(f"Failed to write to subprocess: {e}") from e

    async def close(self) -> None:
        """Terminate subprocess with graceful escalation.

        Sequence: SIGINT(5s) → SIGTERM(5s) → SIGKILL(5s)
        """
        if self._closed:
            return  # Idempotent

        logger.debug("Closing stdio transport")

        if self._process:
            await self._terminate_process()

        if self._read_task and not self._read_task.done():
            self._read_task.cancel()
            try:
                await self._read_task
            except asyncio.CancelledError:
                pass

        self._emit_close()

    async def _read_loop(self) -> None:
        """Read newline-delimited JSON from stdout.

        Runs until process exits or transport closes.
        """
        if not self._process or not self._process.stdout:
            return

        try:
            while not self._closed:
                line = await self._process.stdout.readline()
                if not line:
                    # EOF: process exited
                    logger.debug("Subprocess stdout EOF")
                    break

                try:
                    data = json.loads(line.decode("utf-8").strip())
                    message = self._parse_json_rpc(data)
                    self._emit_message(message)
                except json.JSONDecodeError as e:
                    logger.warning(f"Invalid JSON from subprocess: {e}")
                    self._emit_error(ValueError(f"Invalid JSON: {e}"))
                except Exception as e:
                    logger.warning(f"Failed to parse message: {e}")
                    self._emit_error(e)

        except asyncio.CancelledError:
            logger.debug("Read loop cancelled")
        except Exception as e:
            logger.error(f"Read loop error: {e}")
            self._emit_error(e)
        finally:
            # Process died or closed
            if not self._closed:
                self._emit_close()

    def _parse_json_rpc(self, data: dict) -> JsonRpcMessage:
        """Parse raw JSON into typed JSON-RPC message.

        Args:
            data: Deserialized JSON object

        Returns:
            Typed JsonRpcMessage (request, response, or notification)
        """
        if "id" in data:
            if "method" in data:
                return JsonRpcRequest(**data)
            else:
                return JsonRpcResponse(**data)
        else:
            return JsonRpcNotification(**data)

    async def _terminate_process(self) -> None:
        """Gracefully terminate subprocess with escalation.

        Escalation strategy:
        1. SIGINT (allow 5s)
        2. SIGTERM (allow 5s)
        3. SIGKILL (force after 5s)
        """
        if not self._process:
            return

        logger.debug(f"Terminating process PID={self._process.pid}")

        # Step 1: SIGINT
        try:
            self._process.send_signal(signal.SIGINT)
            try:
                await asyncio.wait_for(self._process.wait(), timeout=SIGINT_TIMEOUT_SEC)
                logger.debug("Process exited after SIGINT")
                return
            except TimeoutError:
                logger.warning(
                    "Process did not exit after SIGINT, escalating to SIGTERM"
                )
        except ProcessLookupError:
            return  # Already dead

        # Step 2: SIGTERM
        try:
            self._process.send_signal(signal.SIGTERM)
            try:
                await asyncio.wait_for(
                    self._process.wait(), timeout=SIGTERM_TIMEOUT_SEC
                )
                logger.debug("Process exited after SIGTERM")
                return
            except TimeoutError:
                logger.warning(
                    "Process did not exit after SIGTERM, escalating to SIGKILL"
                )
        except ProcessLookupError:
            return  # Already dead

        # Step 3: SIGKILL
        try:
            self._process.kill()
            await asyncio.wait_for(self._process.wait(), timeout=SIGKILL_TIMEOUT_SEC)
            logger.warning("Process killed with SIGKILL")
        except ProcessLookupError:
            pass  # Already dead
        except TimeoutError:
            logger.error("Process did not die after SIGKILL (!)")
