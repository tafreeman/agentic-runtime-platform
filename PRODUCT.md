# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users
Primary: a solo developer/operator who authors, runs, and debugs multi-step AI workflows through the dashboard, alongside the CLI and API.

## Product Purpose
Agentic Runtime Platform is a Python and React monorepo for defining, running, observing, and evaluating multi-step AI workflows. Workflows are YAML files whose steps form a DAG, run on a native engine or a LangGraph adapter. The dashboard exists to make runs inspectable: success means the operator can see what ran, what failed, and why.

## Positioning
Inspectable runs in one place: live DAG/step streaming, fail-closed approval governance for high-impact tools, and evaluation evidence, all working with no provider credential (`AGENTIC_NO_LLM=1`).

## Operating Context
Local development and demo use: `just dev` starts the FastAPI backend and Vite UI; runs stream over WebSocket. It is an inspectable development platform, not a hosted service (see docs/KNOWN_LIMITATIONS.md).

## Capabilities and Constraints
- Steps name a capability tier, never a model; routing is handled by the SmartModelRouter.
- Tools needing approval are denied when no ApprovalProvider is registered.
- Python and TypeScript share a compiled contract (Pydantic to JSON Schema to generated TS).
- UI: React 19 + Vite in `agentic-workflows-v2/ui/`.

## Evidence on Hand
Demo walkthrough (docs/DEMO.md), load evidence (docs/flagship.md), UI screenshots (docs/screenshots/). No customer testimonials or hosted-service claims exist; do not fabricate them.

## Product Principles
- Make run state legible before making it pretty.
- Fail closed and show why.
- Work credential-free; never imply a provider is required.
- Do not overclaim maturity; link limitations honestly.
