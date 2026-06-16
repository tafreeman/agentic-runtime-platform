# ADR-030: SSRF Guard Pins the Connection Target in Both Modes

**Status:** Accepted
**Date:** 2026-06-15
**Related:** `agentic_v2/security/url_guard.py`, `agentic_v2/langchain/tools.py`
(`_http_get_with_redirect_guard`)

---

## Context

The SSRF guard protects the LangChain `http_get` tool's redirect-following path.
To defeat DNS rebinding (a TOCTOU gap between validation and connection), the
guard resolves a DNS-name host once and pins the connection to the validated IP:
the request URL host is rewritten to that IP, the original hostname travels in
the `Host` header and (for https) the `sni_hostname` extension, so the TLS
handshake and certificate verification still use the real hostname.

This pinning was gated on `agentic_block_private_ips`. When that flag is OFF —
the documented local-dev opt-out (`AGENTIC_BLOCK_PRIVATE_IPS=0` in `.env.example`,
used to reach localhost LLM endpoints) — `_validate_url_core` resolved the host
only to screen for cloud-metadata addresses and then returned **no** pinned IP,
so the HTTP client re-resolved the hostname at connect time. A rebinding domain
could therefore pass the always-on metadata screen with a public address and then
have the client connect to a metadata/private address. The metadata block — which
is meant to hold in **both** modes — was defeatable by rebinding whenever the
private-IP guard was opted out.

## Decision

Decouple connection pinning from the private-IP policy. `_validate_url_core` now
returns a pinned IP for any DNS-name host that resolves to a usable address in
**both** modes, reusing the resolution already performed for the metadata screen.
`block_private` continues to govern only whether private/loopback/reserved
addresses are *rejected*; it no longer governs *whether the connection is pinned*.
IP-literal hosts (nothing to resolve) and resolution failures still yield no pin.

## Consequences

- The always-on cloud-metadata block can no longer be bypassed by DNS rebinding
  in the opt-out path — the connect target is locked to the address screened.
- The opt-out use case is preserved: private/localhost addresses remain reachable
  (the guard is still off); the connection is simply pinned to the screened
  address (e.g. `localhost` → `127.0.0.1`).
- No extra DNS lookups: the opt-out branch already called `getaddrinfo` for the
  metadata screen; the resolved address is now reused for pinning.
- Round-robin / multi-A-record hosts are pinned to one address per request
  (IPv4 preferred), matching the existing block-on behavior.
- Regression covered by
  `tests/test_ssrf_guard.py::TestDnsRebinding::test_optout_mode_still_pins_to_checked_address`.
