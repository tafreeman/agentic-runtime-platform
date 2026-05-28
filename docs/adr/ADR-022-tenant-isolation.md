# ADR-022: Tenant-Scoped Run and Dataset Isolation

**Status:** Accepted
**Date:** 2026-05-18

## Context

Epic 8 adds production authentication, audit logging, and integrity controls to
the runtime. Once multiple organizations can share one deployment, authenticated
identity alone is not enough: every data access path must resolve a tenant scope
and use that scope when reading or writing persisted runtime data.

The current server stores workflow run logs under `runs/` and materialized
dataset inputs under run-adjacent helper directories. That flat layout is
compatible with single-tenant local development, but it makes cross-tenant data
exposure too easy if a route accepts a run identifier or dataset path without a
tenant boundary.

## Decision

Introduce a request-level `TenantContext` in `agentic_v2.core.tenant`.
FastAPI routes resolve it with `Depends(get_tenant_context)`.

Tenant resolution order:

1. OIDC-authenticated requests use safe tenant or organization claims copied to
   `request.state.user` by the OIDC middleware.
2. When OIDC is inactive, `X-Tenant-ID` is accepted as a compatibility header.
3. If neither signal is present, the request uses the `default` tenant.

Run persistence is tenant-scoped as `runs/{tenant_id}/...` for all server write,
list, and detail paths. The default tenant can still read legacy root-level
`runs/*.json` files so existing local/dev data remains accessible.

Local dataset discovery and sample loading are tenant-scoped as
`datasets/{tenant_id}/...` when routes execute with a tenant context. The
default tenant additionally keeps the historical repository fixture locations
for compatibility. Repository-backed benchmark datasets remain shared catalog
metadata, while tenant-owned local JSON datasets are isolated by path root.

Add an explicit migration helper,
`migrate_legacy_tenant_storage(...)`, to move legacy root run and dataset files
into the default tenant layout when an operator is ready.

## Consequences

Routes that list or load run records now resolve a tenant before touching disk.
A tenant can request only files in its own run directory, with path traversal
checks still applied against the storage root.

OIDC middleware stores only limited actor metadata and tenant/org claim values
needed for scoping. It does not store or log raw tokens.

Audit logging can include `tenant_id` on data access events, allowing
cross-tenant access reviews without expanding audit scope beyond E8-2.

Existing direct `RunLogger(runs_dir=...)` usage remains flat for tests and
library callers. Server code opts into tenant scoping via `RunLogger.for_tenant`.

## Alternatives Considered

- Put `tenant_id` only inside run JSON records. Rejected because routes would
  still have to scan shared storage before authorization decisions.
- Require OIDC for all tenant scoping. Rejected because local development and
  API-key deployments need a controlled compatibility path.
- Automatically migrate legacy files at startup. Rejected because implicit file
  moves are risky in production; operators should run migration deliberately.
