"""Unit tests for agentic_v2.devex.port_guard."""

from __future__ import annotations

import socket
from unittest.mock import MagicMock, patch

import pytest

from agentic_v2.devex.port_guard import check_port, guard_ports


# ---------------------------------------------------------------------------
# check_port — socket-level tests
# ---------------------------------------------------------------------------


def test_check_port_free_returns_true_and_none() -> None:
    """A port that nothing is listening on reports as free."""
    # Bind to port 0, let the OS assign an ephemeral port, then release it.
    # The released port is briefly free — check it before anything else grabs it.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as tmp:
        tmp.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        tmp.bind(("127.0.0.1", 0))
        _, ephemeral_port = tmp.getsockname()

    # Port is now closed; check it immediately.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.settimeout(0.05)
        still_free = probe.connect_ex(("127.0.0.1", ephemeral_port)) != 0

    if not still_free:
        pytest.skip(f"ephemeral port {ephemeral_port} was re-used before check")

    is_free, pid = check_port(ephemeral_port)
    assert is_free is True
    assert pid is None


def test_check_port_bound_returns_false() -> None:
    """A port held open by a server socket is reported as in use with the correct tuple shape."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        _, bound_port = server.getsockname()

        is_free, pid = check_port(bound_port)

    assert is_free is False
    # pid is int or None — both are valid (psutil may or may not be installed /
    # may lack permissions); the important contract is the bool return value.
    assert pid is None or isinstance(pid, int)


def test_check_port_bound_pid_unknown_without_psutil() -> None:
    """Without psutil, PID is None even when port is in use."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        _, bound_port = server.getsockname()

        with patch("agentic_v2.devex.port_guard._psutil", None):
            is_free, pid = check_port(bound_port)

    assert is_free is False
    assert pid is None


# ---------------------------------------------------------------------------
# guard_ports — integration of check_port + Rich output
# ---------------------------------------------------------------------------


def test_guard_ports_all_free_returns_true(capsys) -> None:
    """guard_ports returns True and prints confirmation when all ports are free."""
    with patch("agentic_v2.devex.port_guard.check_port", return_value=(True, None)):
        result = guard_ports({"backend": 8012, "frontend": 5174})

    assert result is True


def test_guard_ports_one_conflict_returns_false() -> None:
    """guard_ports returns False when at least one port is in use."""

    def _side_effect(port: int) -> tuple[bool, int | None]:
        if port == 8012:
            return False, 1234
        return True, None

    with patch("agentic_v2.devex.port_guard.check_port", side_effect=_side_effect):
        result = guard_ports({"backend": 8012, "frontend": 5174})

    assert result is False


def test_guard_ports_all_conflicts_returns_false() -> None:
    """guard_ports returns False when every port is in use."""
    with patch("agentic_v2.devex.port_guard.check_port", return_value=(False, None)):
        result = guard_ports({"backend": 8012, "frontend": 5174})

    assert result is False


def test_guard_ports_empty_dict_returns_true() -> None:
    """An empty port map has no conflicts — returns True."""
    result = guard_ports({})
    assert result is True


# ---------------------------------------------------------------------------
# _get_pid_for_port — psutil path
# ---------------------------------------------------------------------------


def test_get_pid_for_port_uses_psutil() -> None:
    """_get_pid_for_port returns the PID from psutil when available."""
    from agentic_v2.devex.port_guard import _get_pid_for_port

    mock_conn = MagicMock()
    mock_conn.laddr.port = 8012
    mock_conn.status = "LISTEN"
    mock_conn.pid = 42

    mock_psutil = MagicMock()
    mock_psutil.net_connections.return_value = [mock_conn]

    with patch("agentic_v2.devex.port_guard._psutil", mock_psutil):
        pid = _get_pid_for_port(8012)

    assert pid == 42


def test_get_pid_for_port_returns_none_without_psutil() -> None:
    """_get_pid_for_port returns None gracefully when psutil is absent."""
    from agentic_v2.devex.port_guard import _get_pid_for_port

    with patch("agentic_v2.devex.port_guard._psutil", None):
        pid = _get_pid_for_port(8012)

    assert pid is None
