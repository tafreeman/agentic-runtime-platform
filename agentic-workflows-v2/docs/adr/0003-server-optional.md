# ADR 0003 — Server as Optional Install

Status: Accepted

Context

Not all users want a running HTTP server; core library should be usable without FastAPI. Some users want a lightweight server for integration and demos.

Decision

Offer server functionality as an optional extra (`agentic_v2[server]`) with FastAPI and WebSocket support.

Consequences

- Keeps core install minimal
- Enables quick demos and integrations when opted in
- Requires extra CI checks for optional extras
