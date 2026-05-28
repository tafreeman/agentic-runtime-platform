# ADR-018: API Rate Limiting and Per-IP Auth Throttle

**Status:** Accepted
**Date:** 2026-05-14
**Implements:** Sprint 1, item S1-2
**Related:** `agentic_v2/server/auth.py`, `agentic_v2/server/app.py`

---

## Context

The runtime server originally had no application-layer rate limiting, and the API-contracts doc deferred this to the reverse-proxy tier. In reverse-proxy-free or constrained production deployments, the server may process a large number of automated workflow-run requests without an upstream rate-limiting layer. Two risks emerged:

1. **Resource exhaustion under bursty traffic.** A misconfigured client loop or a runaway automation job can saturate the FastAPI event loop. Without a rate gate, the server degrades for all callers while a single bad actor consumes capacity.

2. **Authentication enumeration.** The existing API-key middleware using `secrets.compare_digest()` prevents timing attacks, but an unconstrained attacker can fire unlimited `401`-producing probes without penalty. The window for offline dictionary attacks or credential stuffing against the single shared key is unbounded.

Both risks can be mitigated at the ingress / API-gateway layer, but the platform needs to be safe in its undecorated single-process form. A lightweight in-process solution covers the common case without adding infrastructure dependencies.

---

## Decision

Implement two complementary in-process controls:

### 1. Global per-IP rate limit via `slowapi`

- **Library:** `slowapi` (FastAPI-compatible `limits`-backed rate-limiter).
- **Default limit:** `60/minute` per source IP, expressed as the string `"60/minute"`.
- **Configuration:** `AGENTIC_RATE_LIMIT_DEFAULT` environment variable overrides the default at startup.
- **Response on breach:** `429 Too Many Requests` with a `Retry-After` header set to the next window boundary.
- **Granularity:** Applied at the outermost middleware layer, before auth and sanitization. The public paths (`/api/health`, `/docs`, `/openapi.json`, `/redoc`) are exempt.
- **Storage:** In-process memory. No Redis or external store.

### 2. Per-IP auth throttle via `AuthThrottle`

- **Class:** `AuthThrottle` in `agentic_v2/server/auth.py`.
- **Mechanism:** Sliding-window counter per source IP. On every `401 Unauthorized` response, the IP's failure count is incremented. When the count reaches the threshold within the window, subsequent requests from that IP receive `429 Too Many Requests` with a `Retry-After` header for the lockout duration.
- **Default thresholds:**
  - Window: 60 seconds (`AGENTIC_AUTH_LOCKOUT_WINDOW_SECONDS`)
  - Failure threshold: 5 (AGENTIC_AUTH_LOCKOUT_THRESHOLD)
  - Lockout duration: 300 seconds (`AGENTIC_AUTH_LOCKOUT_DURATION_SECONDS`)
- **Reset:** A successful `200` from a protected endpoint resets the failure counter for that IP.
- **Storage:** In-process dictionary. No external store.

Both controls are **in-process only**. In a multi-replica deployment, each replica tracks its own counters independently — there is no shared state across instances. Cluster-wide rate limiting is explicitly deferred to Sprint 2.

---

## Consequences

### Positive

- Single-process and small-cluster deployments are protected against both resource exhaustion and auth-enumeration without any infrastructure dependency.
- The `slowapi` integration is a thin wrapper over the `limits` library; adding a Redis backend in Sprint 2 is a one-line config change.
- `AuthThrottle` is a pure-Python class; its counter store can be swapped for a Redis client in Sprint 2 with no interface changes.
- All thresholds are configurable via environment variables — operators can tune for their environment without code changes.

### Negative

- **Multi-replica limitation.** In an N-replica deployment, the effective per-IP limits are N times the configured limit. A caller can bypass throttling by distributing requests across replicas. See [`KNOWN_LIMITATIONS.md`](../KNOWN_LIMITATIONS.md) §4.3 and §4.4.
- **Memory growth.** The `AuthThrottle` counter map grows with the number of unique IPs seen. In practice, expired windows should be evicted; confirm eviction logic is active before deploying at internet scale.
- **No persistent state across restarts.** A server restart resets all counters; an attacker who triggers a restart (or times one) resets their throttle window.

---

## Alternatives Considered

| Alternative | Disposition |
|---|---|
| **Redis-backed shared counters (Sprint 2 plan)** | Correct solution for multi-replica; deferred because it introduces an infrastructure dependency. Sprint 2 will wire `slowapi`'s Redis limiter and a Redis-backed `AuthThrottle` store. |
| **WAF / ingress-layer rate limiting** | Correct for internet-exposed production; out of scope for the application layer. Operators should layer this on top; the in-process controls are a defense-in-depth backstop. |
| **nginx `limit_req` / `limit_conn`** | Viable but not portable — requires nginx in the deployment stack. The platform cannot assume it. |
| **No rate limiting; rely on reverse proxy only** | The prior approach. Rejected because the platform is often deployed without a full reverse-proxy stack in early environments. |

---

## Implementation References

- Rate-limit middleware setup: `agentic_v2/server/app.py`
- Auth throttle class: `agentic_v2/server/auth.py` (`AuthThrottle`)
- Environment variables: AGENTIC_RATE_LIMIT_DEFAULT, AGENTIC_AUTH_LOCKOUT_WINDOW_SECONDS, AGENTIC_AUTH_LOCKOUT_THRESHOLD, AGENTIC_AUTH_LOCKOUT_DURATION_SECONDS
- Known limitations: [`KNOWN_LIMITATIONS.md`](../KNOWN_LIMITATIONS.md) §4.3, §4.4

---

## Review Cadence

Re-evaluate when:

- Sprint 2 Redis migration lands — update this ADR to Superseded or amend the Consequences section.
- The platform is deployed to a target with more than one replica in steady state.
- An auth-enumeration incident in the wild demonstrates that the in-process threshold is inadequate.
