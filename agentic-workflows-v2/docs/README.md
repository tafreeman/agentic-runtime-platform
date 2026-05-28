# Documentation Index

This directory is the primary documentation hub for `agentic-workflows-v2`.

## Start Here

- `../README.md`: project overview, install, quick start
- `tutorials/getting_started.md`: first runnable example
- `DEVELOPMENT.md`: local setup and day-to-day commands

## Core Guides

- `ARCHITECTURE.md`: system architecture and runtime flow
- `WORKFLOWS.md`: built-in workflows and authoring conventions

- `API_REFERENCE.md`: exported Python API and HTTP routes

## Tutorials

- `tutorials/getting_started.md`
- `tutorials/building_workflow.md`
- `tutorials/creating_agent.md`

## Design, Governance, and History

- `DOCS_BEST_PRACTICES.md`: research-backed documentation standards used in this repo
- `REPO_MAP.md`: practical map of active package areas
- `adr/`: architecture decision records

## Coverage Matrix

| Area | Primary docs |
| --- | --- |
| Runtime package (`agentic_v2/`) | `ARCHITECTURE.md`, `API_REFERENCE.md` |
| Workflow definitions | `WORKFLOWS.md`, `tutorials/building_workflow.md` |
| API + UI runtime | `README.md`, `DEVELOPMENT.md`, `API_REFERENCE.md` |

| Contribution process | `../CONTRIBUTING.md`, `../.github/PULL_REQUEST_TEMPLATE.md` |
| Security and support | `../SECURITY.md`, `../SUPPORT.md`, `../CODE_OF_CONDUCT.md` |

## Documentation Maintenance

Run docs path validation after docs edits:

```bash
python scripts/check_docs_refs.py
```

When adding behavior, also update the docs in the same pull request.
