"""Shared SSRF URL guard for all outbound-HTTP paths.

Single authoritative implementation consumed by:
- agentic_v2/tools/builtin/http_ops.py  (aiohttp, async)
- agentic_v2/langchain/tools.py          (httpx, sync)

Design decisions
----------------
* Always blocked (regardless of flag): non-http/https schemes; known cloud
  metadata endpoints by hostname and IP literal.
* When ``agentic_block_private_ips`` is True (default): private, loopback,
  link-local, reserved, and unspecified IPv4/IPv6 addresses.  IP-literal
  hostnames are checked directly; DNS names are resolved via
  ``socket.getaddrinfo`` and ALL returned addresses must pass — if any
  single address is restricted the request is blocked.
* DNS resolution failure → fail-closed (the host would be unreachable anyway,
  and failing open would invite DNS-rebinding tricks).
* IPv4-mapped IPv6 (``::ffff:127.0.0.1``) is normalised to its IPv4 equivalent
  before the address-category check so the mapping cannot bypass the guard.

Async callers: use ``validate_url_async`` which runs the blocking
``getaddrinfo`` call in a thread via ``asyncio.to_thread``.
Sync callers: use ``validate_url`` which calls ``getaddrinfo`` directly.
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import urlparse

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_ALLOWED_SCHEMES: frozenset[str] = frozenset({"http", "https"})

# Metadata endpoints always blocked regardless of the private-IP flag.
# Covers AWS/Azure/GCP (169.254.169.254), GCP hostname, Alibaba ECS
# (100.100.100.200), and the AWS IPv6 metadata address (fd00:ec2::254).
_METADATA_HOSTS: frozenset[str] = frozenset(
    {
        "169.254.169.254",
        "fd00:ec2::254",
        "100.100.100.200",
        "metadata.google.internal",
        "metadata",
    }
)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _is_restricted_address(addr: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Return True if *addr* is in a category that must never be reached."""
    # Normalise IPv4-mapped IPv6 so ::ffff:127.0.0.1 hits the loopback check.
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
        addr = addr.ipv4_mapped
    return bool(
        addr.is_private
        or addr.is_loopback
        or addr.is_link_local
        or addr.is_reserved
        or addr.is_unspecified
    )


def _check_always_blocked(hostname: str) -> str | None:
    """Return an error string if *hostname* hits an always-blocked rule, else None."""
    hn = hostname.lower()

    # Metadata hostnames
    if hn in _METADATA_HOSTS:
        return f"Access to metadata endpoint '{hostname}' is blocked."

    # Metadata IPs expressed as literals
    try:
        addr = ipaddress.ip_address(hn)
        if hn in _METADATA_HOSTS or str(addr) in _METADATA_HOSTS:
            return f"Access to metadata endpoint '{hostname}' is blocked."
    except ValueError:
        pass  # not an IP literal

    return None


def _check_ip_literal(hostname: str) -> str | None:
    """If *hostname* is an IP literal, return error string if restricted, else None.

    Returns ``None`` when the hostname is not an IP literal (caller must do DNS).
    """
    try:
        addr = ipaddress.ip_address(hostname)
    except ValueError:
        return None  # not an IP literal — caller handles DNS

    if _is_restricted_address(addr):
        return (
            f"Access to private/reserved/loopback IP address '{hostname}' is blocked."
        )
    return ""  # empty string = "is an IP literal, and it passed"


def _resolve_and_check(hostname: str) -> str | None:
    """Resolve *hostname* via DNS; block if ANY address is restricted.

    Returns error string on block/failure, or None when all addresses pass.
    """
    try:
        results = socket.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        return (
            f"Host '{hostname}' could not be resolved "
            f"(DNS lookup failed: {exc.strerror}). Request blocked (fail-closed)."
        )

    for _family, _type, _proto, _canonname, sockaddr in results:
        raw_ip = sockaddr[0]
        try:
            addr = ipaddress.ip_address(raw_ip)
        except ValueError:
            continue
        if _is_restricted_address(addr):
            return (
                f"Host '{hostname}' resolves to a private/reserved address "
                f"and is blocked."
            )
    return None


# ---------------------------------------------------------------------------
# Public sync API
# ---------------------------------------------------------------------------


def validate_url(url: str, *, block_private: bool) -> str | None:
    """Validate *url* for SSRF safety (synchronous).

    Args:
        url: The URL to validate.
        block_private: When True, private/loopback/reserved addresses are blocked
            in addition to the always-blocked metadata endpoints.

    Returns:
        An error string if the URL is blocked, or ``None`` if it is allowed.
    """
    try:
        parsed = urlparse(url)
    except Exception:
        return "Invalid URL: could not be parsed."

    if parsed.scheme not in _ALLOWED_SCHEMES:
        return (
            f"URL scheme '{parsed.scheme}' is not allowed. "
            "Only http and https are permitted."
        )

    hostname = parsed.hostname or ""
    if not hostname:
        return "Invalid URL: no hostname."

    # Always-blocked metadata endpoints
    metadata_err = _check_always_blocked(hostname)
    if metadata_err:
        return metadata_err

    if not block_private:
        return None

    # IP literal path
    ip_result = _check_ip_literal(hostname)
    if ip_result is None:
        # Hostname is a DNS name — resolve and check
        return _resolve_and_check(hostname)
    if ip_result:
        # Non-empty string = blocked
        return ip_result
    # ip_result == "" → literal IP, passed
    return None


# ---------------------------------------------------------------------------
# Public async API
# ---------------------------------------------------------------------------


async def validate_url_async(url: str, *, block_private: bool) -> str | None:
    """Validate *url* for SSRF safety (asynchronous).

    DNS resolution is run in a thread via ``asyncio.to_thread`` so the event
    loop is not blocked.

    Args:
        url: The URL to validate.
        block_private: When True, private/loopback/reserved addresses are blocked
            in addition to the always-blocked metadata endpoints.

    Returns:
        An error string if the URL is blocked, or ``None`` if it is allowed.
    """
    try:
        parsed = urlparse(url)
    except Exception:
        return "Invalid URL: could not be parsed."

    if parsed.scheme not in _ALLOWED_SCHEMES:
        return (
            f"URL scheme '{parsed.scheme}' is not allowed. "
            "Only http and https are permitted."
        )

    hostname = parsed.hostname or ""
    if not hostname:
        return "Invalid URL: no hostname."

    # Always-blocked metadata endpoints (no I/O needed)
    metadata_err = _check_always_blocked(hostname)
    if metadata_err:
        return metadata_err

    if not block_private:
        return None

    # IP literal — no I/O needed
    ip_result = _check_ip_literal(hostname)
    if ip_result is not None:
        # Non-empty = blocked; empty = passed
        return ip_result if ip_result else None

    # DNS name — offload blocking getaddrinfo to a thread
    return await asyncio.to_thread(_resolve_and_check, hostname)
