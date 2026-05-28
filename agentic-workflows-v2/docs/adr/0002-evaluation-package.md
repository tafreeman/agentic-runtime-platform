# ADR 0002 — Evaluation as a Separate Optional Package

Status: Accepted

Context

Evaluation tooling often has heavy dependencies and different release cadence. Consumers of `agentic_v2` may not need evaluation code.

Decision

Provide `agentic-v2-eval` as an optional package with a clear interface for batch and streaming evaluation.

Consequences

- Smaller core runtime footprint
- Optional dependency management for heavy libraries
- Slightly more complexity for cross-package integration
