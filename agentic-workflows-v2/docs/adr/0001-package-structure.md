# ADR 0001 — Package Structure: Agents and Workflows in same package

Status: Accepted

Context

Many multi-agent projects separate agents and workflows across packages. Close coupling and frequent API changes between agents and workflow orchestration motivate co-location.

Decision

Keep `agents/` and `workflows/` inside the main `agentic_v2` package.

Consequences

- Easier imports and versioning
- Single install for core runtime
- Slightly larger package surface area for consumers
