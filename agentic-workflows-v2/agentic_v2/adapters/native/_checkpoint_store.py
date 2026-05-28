"""SQLite-backed checkpoint store for workflow execution persistence.

Provides :class:`CheckpointStore`, a lightweight async wrapper around the
stdlib ``sqlite3`` module that records per-step completion state.  All
blocking I/O is offloaded via ``asyncio.to_thread`` so the event loop is
never stalled.

The database is created lazily on the first write, so read-only workflows
incur zero filesystem overhead.

Schema::

    CREATE TABLE IF NOT EXISTS checkpoints (
        thread_id     TEXT NOT NULL,
        workflow_name TEXT NOT NULL,
        step_name     TEXT NOT NULL,
        status        TEXT NOT NULL,
        output_data   TEXT NOT NULL,
        created_at    TEXT NOT NULL,
        PRIMARY KEY (thread_id, step_name)
    );
"""

from __future__ import annotations

import asyncio
import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_CREATE_TABLE_SQL = """\
CREATE TABLE IF NOT EXISTS checkpoints (
    thread_id     TEXT NOT NULL,
    workflow_name TEXT NOT NULL,
    step_name     TEXT NOT NULL,
    status        TEXT NOT NULL,
    output_data   TEXT NOT NULL,
    created_at    TEXT NOT NULL,
    PRIMARY KEY (thread_id, step_name)
);
"""

_UPSERT_SQL = """\
INSERT OR REPLACE INTO checkpoints
    (thread_id, workflow_name, step_name, status, output_data, created_at)
VALUES
    (?, ?, ?, ?, ?, ?)
"""

_SELECT_SQL = """\
SELECT step_name, status, output_data, workflow_name, created_at
FROM checkpoints
WHERE thread_id = ?
"""

_DELETE_SQL = """\
DELETE FROM checkpoints WHERE thread_id = ?
"""


class CheckpointStore:
    """Async SQLite checkpoint store for workflow step results.

    All database operations are executed on a background thread via
    ``asyncio.to_thread`` to avoid blocking the async event loop.
    The database file and table are created lazily on the first
    :meth:`write` call.

    Args:
        db_path: Filesystem path for the SQLite database file.
    """

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._initialized = False

    def _get_connection(self) -> sqlite3.Connection:
        """Open a new connection to the SQLite database.

        Each call creates a fresh connection because ``sqlite3.Connection``
        objects are not safe to share across threads.
        """
        return sqlite3.connect(str(self._db_path))

    def _ensure_table(self) -> None:
        """Create the checkpoints table if it does not exist (sync)."""
        if self._initialized:
            return
        conn = self._get_connection()
        try:
            conn.execute(_CREATE_TABLE_SQL)
            conn.commit()
            self._initialized = True
            logger.debug("Checkpoint table ensured at %s", self._db_path)
        finally:
            conn.close()

    def _write_sync(
        self,
        thread_id: str,
        workflow_name: str,
        step_name: str,
        status: str,
        output_data: dict[str, Any],
    ) -> None:
        """Synchronous write — called from a background thread."""
        self._ensure_table()
        serialized = json.dumps(output_data, default=str)
        now = datetime.now(timezone.utc).isoformat()
        conn = self._get_connection()
        try:
            conn.execute(
                _UPSERT_SQL,
                (thread_id, workflow_name, step_name, status, serialized, now),
            )
            conn.commit()
            logger.debug(
                "Checkpoint written: thread=%s step=%s status=%s",
                thread_id,
                step_name,
                status,
            )
        finally:
            conn.close()

    def _read_sync(self, thread_id: str) -> dict[str, dict[str, Any]]:
        """Synchronous read — called from a background thread."""
        if not self._initialized and not self._db_path.exists():
            return {}
        self._ensure_table()
        conn = self._get_connection()
        try:
            cursor = conn.execute(_SELECT_SQL, (thread_id,))
            rows = cursor.fetchall()
        finally:
            conn.close()

        result: dict[str, dict[str, Any]] = {}
        for step_name, status, output_json, workflow_name, created_at in rows:
            result[step_name] = {
                "status": status,
                "output_data": json.loads(output_json),
                "workflow_name": workflow_name,
                "created_at": created_at,
            }
        return result

    def _clear_sync(self, thread_id: str) -> None:
        """Synchronous clear — called from a background thread."""
        if not self._initialized and not self._db_path.exists():
            return
        self._ensure_table()
        conn = self._get_connection()
        try:
            conn.execute(_DELETE_SQL, (thread_id,))
            conn.commit()
            logger.debug("Checkpoints cleared for thread=%s", thread_id)
        finally:
            conn.close()

    async def write(
        self,
        thread_id: str,
        workflow_name: str,
        step_name: str,
        status: str,
        output_data: dict[str, Any],
    ) -> None:
        """Persist a checkpoint row for a completed step.

        Uses ``INSERT OR REPLACE`` for idempotent writes — re-executing a
        step simply overwrites the previous checkpoint.

        Args:
            thread_id: Unique identifier for the execution thread.
            workflow_name: Human-readable workflow name.
            step_name: Name of the step that completed.
            status: Step status string (e.g. ``"success"``).
            output_data: Step output dictionary (serialized as JSON).
        """
        await asyncio.to_thread(
            self._write_sync,
            thread_id,
            workflow_name,
            step_name,
            status,
            output_data,
        )

    async def read(self, thread_id: str) -> dict[str, dict[str, Any]]:
        """Load all checkpoint rows for a given thread.

        Args:
            thread_id: Execution thread to look up.

        Returns:
            Mapping of ``{step_name: {status, output_data, workflow_name,
            created_at}}``.  Returns an empty dict if no checkpoints exist.
        """
        return await asyncio.to_thread(self._read_sync, thread_id)

    async def clear(self, thread_id: str) -> None:
        """Remove all checkpoint rows for a given thread.

        Args:
            thread_id: Execution thread whose checkpoints should be deleted.
        """
        await asyncio.to_thread(self._clear_sync, thread_id)
