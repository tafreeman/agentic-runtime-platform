# Documentation rules

Documentation in this repository is part of the implementation. A change is
not complete when the current command, contract, or limitation remains
undocumented.

## Write for a specific task

- Start with what the reader will accomplish.
- Put prerequisites before commands that need them.
- Use one canonical command and state its working directory.
- Separate tutorials, procedures, reference material, and design explanation.
- Link to the source of truth instead of copying a large contract into several
  pages.

Use ordinary software-engineering language. Remove promotional claims,
unexplained acronyms, filler introductions, and claims such as
"production-ready" that do not define a testable condition.

## Keep claims verifiable

- Check commands with `--help` or run a safe example.
- Check routes against FastAPI registration and OpenAPI.
- Check defaults against code or committed configuration.
- State when a feature is partial, optional, process-local, or not wired into
  the default path.
- Do not turn a planned feature into present-tense documentation.
- Do not rewrite ADRs or generated reports to make current behavior look
  cleaner.

If two execution adapters behave differently, document both boundaries.

## Examples

Examples must:

- use the current import path;
- include required inputs;
- avoid live provider calls unless clearly labeled;
- check structured success or failure;
- clean up files, processes, and connections they create;
- avoid secrets and machine-specific paths.

Run executable examples when practical. If an example is currently broken,
say so or fix it before recommending it.

## Contract changes

When changing a Python wire model:

1. update the source Pydantic model;
2. regenerate committed JSON Schemas;
3. regenerate TypeScript contracts;
4. run drift tests;
5. document a breaking change in `docs/MIGRATIONS.md`.

Do not hand-edit generated TypeScript files.

## Required checks

From the repository root:

```powershell
python agentic-workflows-v2/scripts/check_docs_refs.py
python scripts/generate_doc_stats.py --check
python scripts/check-doc-drift.py
```

Build the documentation site in strict mode before a large documentation
change. Also run the tests or build for any example, schema, or UI contract
that the docs changed.

## Where changes belong

| Change | Documentation |
| --- | --- |
| Setup or first use | Root or package `README.md` |
| CLI behavior | `docs/cli-reference.md` |
| HTTP or stream contract | `docs/api-contracts-runtime.md` |
| Environment variable | `docs/configuration.md` and `.env.example` |
| Workflow syntax | `docs/WORKFLOW_AUTHORING.md` |
| Operator behavior | `docs/operations/` |
| Known gap | `docs/KNOWN_LIMITATIONS.md` |
| Architecture decision | New or superseding ADR |
| Breaking change | `docs/MIGRATIONS.md` |

Update the narrowest canonical page, then link to it from shorter package
indexes.
