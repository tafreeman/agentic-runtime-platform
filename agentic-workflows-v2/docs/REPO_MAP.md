# Repository Map

This is a practical map of the repository for maintainers and contributors.

## Top-Level

| Path | Notes |
| --- | --- |
| `agentic_v2/` | Core Python package |
| `ui/` | Frontend application |
| `backend/` | Minimal backend prototype scaffold |
| `docs/` | Documentation hub |
| `tests/` | Backend tests |
| `examples/` | Standalone examples |
| `scripts/` | Utility and automation scripts |
| `fixtures/` | Fixture artifacts for docs and tests |

## `agentic_v2/` Package

| Module area | Purpose |
| --- | --- |
| `agents/` | Agent classes, orchestration roles, implementations |
| `cli/` | `agentic` command-line interface |
| `config/` | Default model/agent/eval config |
| `contracts/` | Typed schemas and message contracts |
| `engine/` | Native DAG primitives and step execution runtime |
| `evaluation/` | Normalization and scoring helpers |
| `integrations/` | External integration adapters (LangChain, tracing) |
| `langchain/` | LangChain/LangGraph compilation and workflow integration |
| `models/` | Model routing and backend adapters |
| `prompts/` | Role prompts used by higher-tier agents |
| `server/` | FastAPI app, routes, and streaming adapters |
| `tools/` | Tool registry + built-in tools |
| `workflows/` | Source-of-truth YAML loader/runner and workflow definitions |

## Coverage Notes

This map is intentionally high-level. For deeper ownership questions, start with
the package docs above, then inspect the tests listed beside the target module.
