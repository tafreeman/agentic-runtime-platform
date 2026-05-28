# ADR-021: JWT OIDC Authentication for API Routes

**Status:** Accepted
**Date:** 2026-05-18

## Context

The server currently protects HTTP API routes with a single shared
`AGENTIC_API_KEY` when configured. Epic 8 requires production-ready
OAuth2/OIDC bearer-token authentication while preserving the existing API-key
behavior for local development, service integrations, and rollout fallback.

FastAPI's security model treats bearer credentials as `Authorization: Bearer`
tokens, and its security helpers support optional authentication when multiple
credential mechanisms are accepted. JWT validation must be strict: verify the
signature, restrict accepted algorithms, and enforce issuer, audience, expiry,
and subject claims.

## Decision

Add an opt-in OIDC authentication middleware for `/api/*` routes, enabled by
`AGENTIC_OIDC_ENABLED=1`. The verifier validates JWTs using PyJWT with RSA
JWKS key resolution, an explicit algorithm allowlist defaulting to `RS256`, and
required `exp`, `iss`, `aud`, and `sub` claims.

`AGENTIC_API_KEY` remains supported. When OIDC is enabled, a valid legacy API
key in `Authorization: Bearer <key>` or `X-API-Key: <key>` bypasses JWT
verification as a controlled fallback. When OIDC is disabled, the existing
`APIKeyMiddleware` behavior is unchanged.

## Consequences

OIDC deployments must provide:

- `AGENTIC_OIDC_ISSUER`
- `AGENTIC_OIDC_AUDIENCE`
- `AGENTIC_OIDC_JWKS_URL`

JWKS responses are cached in-process for a short TTL. If JWKS refresh fails and
a cached key set exists, the verifier continues using the cached keys. If no
JWKS is available, JWT authentication fails closed with `503 Authentication
provider unavailable`; the legacy API-key fallback still works when configured.

The middleware stores only safe actor metadata on `request.state.auth_actor`
and logs path/IP/reason-class details without logging raw tokens or full claims.

## Alternatives Considered

- Replace API keys outright with OIDC. Rejected because the existing
  `AGENTIC_API_KEY` behavior is a documented compatibility contract.
- Accept symmetric and asymmetric JWT algorithms together. Rejected because
  mixed HS/RS allowlists increase algorithm-confusion risk.
- Fetch OIDC discovery metadata at startup. Deferred; a direct JWKS URL is
  simpler for Epic 8 and avoids startup network coupling.
