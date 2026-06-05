"""Packaging-level contract tests for optional extras.

These tests protect install-time assumptions that CI and contributors rely on,
especially the documented promise that ``agentic-workflows-v2[server]``
includes WebSocket support.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

PYPROJECT_PATH = Path(__file__).resolve().parent.parent / "pyproject.toml"
WEBSOCKET_RUNTIME_PREFIXES = (
    "uvicorn[standard]",
    "websockets",
    "wsproto",
)


def _optional_dependencies() -> dict[str, list[str]]:
    pyproject_text = PYPROJECT_PATH.read_text(encoding="utf-8")
    pyproject = tomllib.loads(pyproject_text)
    return pyproject["project"]["optional-dependencies"]


def test_server_extra_includes_websocket_support() -> None:
    """The server extra must install a WebSocket-capable ASGI stack.

    ADR 0003 documents that ``[server]`` provides FastAPI plus WebSocket
    support. Without one of these runtime packages, Uvicorn responds to WS
    upgrades with 404/"Unsupported upgrade request", which breaks the
    streaming UI and CI Playwright gate.
    """
    server_dependencies = _optional_dependencies()["server"]

    assert any(
        dependency.lower().startswith(WEBSOCKET_RUNTIME_PREFIXES)
        for dependency in server_dependencies
    )
