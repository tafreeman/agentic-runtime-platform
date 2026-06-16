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

Residual DNS-rebinding risk
---------------------------
This guard resolves names in userspace and pins connections to a validated
address (``validate_url_pinned`` + the aiohttp ``GuardedResolver`` and the
httpx request-target rewrite in the tool layers) so the HTTP client cannot
re-resolve to a different IP between the check and the connect. That closes the
common rebinding window, but it is **defense-in-depth, not a complete
boundary**: pinning depends on the resolver returning the same answer the guard
validated, and OS-level resolver caching is outside this module's control. For
threat models that include attacker-controlled DNS, pair this guard with a
network-layer egress control (egress firewall / service-mesh authorization /
``NetworkPolicy``). See ``docs/KNOWN_LIMITATIONS.md`` §4.4 and
``docs/operations/security-hardening.md`` §10.
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
        or addr.is_multicast
    )


def _parse_ip_literal(
    hostname: str,
) -> ipaddress.IPv4Address | ipaddress.IPv6Address | None:
    """Parse *hostname* as an IP literal, including legacy IPv4 forms.

    ``ipaddress.ip_address`` rejects the alternative IPv4 representations the
    OS resolver happily accepts (decimal ``2852039166``, octal, hex, short
    forms) — an attacker can use those to slip past string-based IP checks
    while the HTTP client still connects to the intended address.  Fall back
    to ``socket.inet_aton``, which implements the same legacy parsing as the
    platform resolver, so every form normalises to the same address object.

    Returns ``None`` when *hostname* is not an IP literal in any form.
    """
    try:
        return ipaddress.ip_address(hostname)
    except ValueError:
        pass
    try:
        return ipaddress.IPv4Address(socket.inet_aton(hostname))
    except (OSError, ValueError):
        return None


def _is_metadata_address(
    addr: ipaddress.IPv4Address | ipaddress.IPv6Address,
) -> bool:
    """Return True if *addr* (canonicalised) is a known metadata endpoint IP."""
    if str(addr) in _METADATA_HOSTS:
        return True
    if isinstance(addr, ipaddress.IPv6Address) and addr.ipv4_mapped is not None:
        return str(addr.ipv4_mapped) in _METADATA_HOSTS
    return False


def _check_always_blocked(hostname: str) -> str | None:
    """Return an error string if *hostname* hits an always-blocked rule, else None."""
    hn = hostname.lower()

    # Metadata hostnames
    if hn in _METADATA_HOSTS:
        return f"Access to metadata endpoint '{hostname}' is blocked."

    # Metadata IPs expressed as literals — including legacy decimal/octal/hex
    # forms (e.g. 2852039166 == 169.254.169.254) which the OS resolver accepts.
    addr = _parse_ip_literal(hn)
    if addr is not None and _is_metadata_address(addr):
        return f"Access to metadata endpoint '{hostname}' is blocked."

    return None


def _check_ip_literal(hostname: str) -> str | None:
    """If *hostname* is an IP literal, return error string if restricted, else None.

    Returns ``None`` when the hostname is not an IP literal (caller must do DNS).
    """
    addr = _parse_ip_literal(hostname)
    if addr is None:
        return None  # not an IP literal — caller handles DNS

    if _is_restricted_address(addr):
        return (
            f"Access to private/reserved/loopback IP address '{hostname}' is blocked."
        )
    return ""  # empty string = "is an IP literal, and it passed"


def check_resolved_address(ip_str: str, *, block_private: bool) -> str | None:
    """Check one RESOLVED IP address against the guard rules.

    Used at connect time (e.g. by the aiohttp guarded resolver) so the address
    the HTTP client actually dials is validated — not just the one seen during
    pre-request validation.  This is what defeats DNS rebinding: a domain that
    returns a public address to the pre-check and a private/metadata address
    at connect time is caught here.

    Metadata endpoint IPs are blocked unconditionally; private/loopback/
    link-local/reserved/multicast/unspecified are blocked when *block_private*.

    Returns an error string if blocked, else ``None``.
    """
    try:
        addr = ipaddress.ip_address(ip_str)
    except ValueError:
        return f"Unparseable resolved address '{ip_str}' is blocked."

    if _is_metadata_address(addr):
        return f"Resolved address '{ip_str}' is a metadata endpoint and is blocked."
    if block_private and _is_restricted_address(addr):
        return (
            f"Resolved address '{ip_str}' is a private/reserved address "
            f"and is blocked."
        )
    return None


def _resolve_and_collect(
    hostname: str, *, block_private: bool
) -> tuple[str | None, list[str]]:
    """Resolve *hostname* via DNS; block if ANY address fails the guard.

    Returns ``(error, validated_ips)``.  ``error`` is set (and the list empty)
    on block or resolution failure; otherwise the deduplicated resolved
    addresses are returned so callers can PIN the connection to one of them
    instead of letting the HTTP client re-resolve (DNS-rebinding defence).
    """
    try:
        results = socket.getaddrinfo(hostname, None)
    except socket.gaierror as exc:
        return (
            f"Host '{hostname}' could not be resolved "
            f"(DNS lookup failed: {exc.strerror}). Request blocked (fail-closed).",
            [],
        )

    ips: list[str] = []
    for _family, _type, _proto, _canonname, sockaddr in results:
        raw_ip = str(sockaddr[0])
        err = check_resolved_address(raw_ip, block_private=block_private)
        if err:
            return (
                f"Host '{hostname}' resolves to a private/reserved address "
                f"and is blocked.",
                [],
            )
        if raw_ip not in ips:
            ips.append(raw_ip)
    return None, ips


def _resolve_and_check(hostname: str) -> str | None:
    """Resolve *hostname* via DNS; block if ANY address is restricted."""
    err, _ips = _resolve_and_collect(hostname, block_private=True)
    return err


# ---------------------------------------------------------------------------
# Public sync API
# ---------------------------------------------------------------------------


def _validate_url_core(
    url: str, *, block_private: bool
) -> tuple[str | None, str | None]:
    """Shared validation core returning ``(error, pinned_ip)``.

    ``pinned_ip`` is set whenever the hostname is a DNS name that resolves to a
    usable address — in BOTH modes — and is the validated address the caller
    should dial instead of re-resolving in the HTTP client.  *block_private*
    governs only whether private/loopback/reserved addresses are *rejected*; it
    does not govern pinning.  ``pinned_ip`` is ``None`` for an IP-literal host
    (nothing to resolve) or when resolution fails.
    """
    try:
        parsed = urlparse(url)
    except Exception:
        return "Invalid URL: could not be parsed.", None

    if parsed.scheme not in _ALLOWED_SCHEMES:
        return (
            f"URL scheme '{parsed.scheme}' is not allowed. "
            "Only http and https are permitted.",
            None,
        )

    hostname = parsed.hostname or ""
    if not hostname:
        return "Invalid URL: no hostname.", None

    # Always-blocked metadata endpoints
    metadata_err = _check_always_blocked(hostname)
    if metadata_err:
        return metadata_err, None

    if not block_private:
        # Metadata endpoints are blocked even when the private-IP guard is
        # opted out — but a DNS name pointing at a metadata IP would otherwise
        # sail through, since the string/literal checks above never resolve.
        # Resolve once, screen against the metadata list, and PIN the connection
        # to the screened address: re-resolving in the HTTP client would let a
        # rebinding domain pass this metadata screen (public IP) and then serve
        # a metadata/private address to the connect.  Pinning closes that window
        # in the opt-out path too — private IPs stay permitted (the guard is
        # off), but the connect target is the address we actually checked.
        # Best-effort: resolution failure falls through (the operator disabled
        # the guard; the request itself will fail on an unresolvable host).
        if _parse_ip_literal(hostname) is not None:
            return None, None  # IP literal — dialled directly, no DNS to pin.
        try:
            infos = socket.getaddrinfo(hostname, None, proto=socket.IPPROTO_TCP)
        except (socket.gaierror, OSError):
            return None, None
        resolved_ips: list[str] = []
        for info in infos:
            resolved = _parse_ip_literal(str(info[4][0]))
            if resolved is None:
                continue
            if _is_metadata_address(resolved):
                return (
                    f"Host '{hostname}' resolves to a metadata endpoint "
                    "and is blocked.",
                    None,
                )
            resolved_ips.append(str(resolved))
        if not resolved_ips:
            return None, None
        # Prefer IPv4 to minimise breakage on hosts without a routable IPv6 path.
        return None, sorted(resolved_ips, key=lambda ip: ":" in ip)[0]

    # IP literal path — client dials the literal directly, no DNS to pin.
    ip_result = _check_ip_literal(hostname)
    if ip_result == "":
        return None, None  # literal IP, passed
    if ip_result:
        return ip_result, None  # literal IP, blocked

    # Hostname is a DNS name — resolve once, validate every address, and
    # return one for the caller to pin the connection to.
    err, ips = _resolve_and_collect(hostname, block_private=block_private)
    if err:
        return err, None
    if not ips:
        return (
            f"Host '{hostname}' yielded no usable addresses. "
            "Request blocked (fail-closed).",
            None,
        )
    # Prefer IPv4 to minimise breakage on hosts without a routable IPv6 path.
    pinned = sorted(ips, key=lambda ip: ":" in ip)[0]
    return None, pinned


def validate_url(url: str, *, block_private: bool) -> str | None:
    """Validate *url* for SSRF safety (synchronous).

    Args:
        url: The URL to validate.
        block_private: When True, private/loopback/reserved addresses are blocked
            in addition to the always-blocked metadata endpoints.

    Returns:
        An error string if the URL is blocked, or ``None`` if it is allowed.
    """
    error, _pinned = _validate_url_core(url, block_private=block_private)
    return error


def validate_url_pinned(
    url: str, *, block_private: bool
) -> tuple[str | None, str | None]:
    """Validate *url* and return a pinned IP for the connection (synchronous).

    Same checks as :func:`validate_url`, but when the hostname is a DNS name the
    address validated here is also the one the caller should CONNECT to — in
    BOTH modes.  Re-resolving in the HTTP client would let a rebinding domain
    serve a public address to the check and a private/metadata one to the
    connect — pinning closes that gap (single ``getaddrinfo`` per hop).  The
    *block_private* flag controls only whether private addresses are rejected,
    not whether the connection is pinned.

    Returns:
        ``(error, pinned_ip)``.  ``error`` is an error string when blocked
        (``pinned_ip`` is ``None``).  ``pinned_ip`` is a validated address to
        dial when the host is a DNS name that resolved; ``None`` when no pinning
        is needed (IP-literal host) or resolution failed.
    """
    return _validate_url_core(url, block_private=block_private)


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
