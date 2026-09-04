# Runtime package documentation

Start with the package [README](../README.md) for installation and a first
command.

## Guides in this directory

| Page | Purpose |
| --- | --- |
| [Architecture](ARCHITECTURE.md) | Package boundaries and request paths |
| [API reference](API_REFERENCE.md) | Python, CLI, HTTP, and stream surfaces |
| [Workflows](WORKFLOWS.md) | Shipped workflows and their inputs |
| [Model layer](MODEL_LAYER.md) | Model identifiers, routing, and clients |
| [Node configuration overlay](NODE_CONFIG_OVERLAY.md) | Per-step model overrides |
| [Repository map](REPO_MAP.md) | Directory ownership |
| [Development](../DEVELOPMENT.md) | Setup, tests, and generated files |

Tutorials:

- [Getting started](tutorials/getting_started.md)
- [Building a workflow](tutorials/building_workflow.md)
- [Creating an agent](tutorials/creating_agent.md)

The repository-level [documentation site](../../docs/index.md) is the
canonical operator and contributor guide. It covers configuration, deployment,
security, evaluation, troubleshooting, and known limitations.

## Historical documents

The `adr/` directory records decisions as they were made. Do not rewrite an
accepted ADR to describe newer behavior. Add a superseding ADR or current
guide instead.

## Validate changes

From the repository root:

```powershell
python agentic-workflows-v2/scripts/check_docs_refs.py
python scripts/generate_doc_stats.py --check
python scripts/check-doc-drift.py
```

When a Python wire contract changes, regenerate and test its TypeScript mirror
as described in [runtime data contracts](../../docs/data-models-runtime.md).
