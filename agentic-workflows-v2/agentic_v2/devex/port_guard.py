"""Port availability checker for local development services.

Cross-platform implementation using :mod:`socket` for detection and
:mod:`psutil` (optional) for PID resolution.  Degrades gracefully when
psutil is not installed — conflicts are still reported, just without the
owning PID.
"""

from __future__ import annotations

import socket
from typing import Optional

try:
    import psutil as _psutil
except ImportError:
    _psutil = None  # type: ignore[assignment]

DEFAULT_PORTS: dict[str, int] = {
    "backend": 8012,
    "frontend": 5174,
}


def _get_pid_for_port(port: int) -> Optional[int]:
    """Return the PID of the process listening on *port*, or None."""
    if _psutil is None:
        return None
    _psutil_errors: tuple[type[Exception], ...] = (PermissionError, AttributeError)
    if _psutil is not None:
        _psutil_errors = (*_psutil_errors, _psutil.Error)
    try:
        for conn in _psutil.net_connections(kind="inet"):
            if conn.laddr.port == port and conn.status == "LISTEN":
                return conn.pid
    except _psutil_errors:
        pass
    return None


def check_port(port: int) -> tuple[bool, Optional[int]]:
    """Check whether *port* is available on localhost.

    Returns:
        (True, None)       — port is free
        (False, pid)       — port is bound; pid is the owner or None if unknown
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.1)
        result = sock.connect_ex(("127.0.0.1", port))
        if result == 0:
            return False, _get_pid_for_port(port)
        return True, None


def guard_ports(ports: dict[str, int]) -> bool:
    """Check all *ports* and print a status report.

    Returns:
        True  — all ports are free
        False — one or more ports are in use
    """
    from rich.console import Console

    console = Console()
    all_free = True

    for name, port in ports.items():
        is_free, pid = check_port(port)
        if is_free:
            console.print(f"  [green]OK[/green]  {name} port {port} is free")
        else:
            all_free = False
            pid_info = f" (PID {pid})" if pid is not None else " (PID unknown)"
            console.print(
                f"  [red]!![/red]  {name} port {port} is in use{pid_info} -- "
                f"stop the process or choose a different port"
            )

    return all_free
