"""Shared fixtures for ledger tests.

Fixture names are prefixed `ledger_` deliberately: `tests/` directories in
this repo have no `__init__.py` in several places, so identically named
fixtures/conftest modules across unrelated packages can collide via
`sys.modules` / pytest's fixture namespace. A unique prefix keeps this
package's fixtures from shadowing (or being shadowed by) anyone else's.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator

import pytest

from ledger import SCHEMA_PATH


@pytest.fixture
def ledger_conn() -> Iterator[sqlite3.Connection]:
    """An in-memory sqlite3 connection with the ledger schema applied."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
    try:
        yield conn
    finally:
        conn.close()
