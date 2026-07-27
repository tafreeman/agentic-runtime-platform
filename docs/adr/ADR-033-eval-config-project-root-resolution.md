# ADR-033: Defensive Import-Time Project-Root Resolution in the Scoring Eval-Config Loader

**Status:** Accepted
**Date:** 2026-06-17
**Related:** `agentic-workflows-v2/agentic_v2/scoring/eval_config.py`
(`_resolve_project_root`); follow-on to the scoring extraction
([ADR-032](ADR-032-extract-scoring-package.md)); review feedback on PR #101

---

## Context

When the scoring/judge domain was extracted into `agentic_v2.scoring`
(ADR-032), the evaluation-YAML loader moved with it into a new
`scoring/eval_config.py`. That module resolves the project root once, at import
time -- `_PROJECT_ROOT` is a module-level constant -- by walking up from
`__file__` to find the directory containing both `agentic_v2/` and
`pyproject.toml`.

The original resolver indexed `this_file.parents[2]` and `parents[3]`
unconditionally and used `parents[2]` as its final fallback. That is correct for
the two layouts we ship: the normal layout puts the package root at `parents[2]`
(`agentic_v2/scoring/eval_config.py`), and a `src/` layout puts it at
`parents[3]`. But because the access is unconditional and runs at *import* time,
an install or checkout whose path has fewer than four ancestors (an unusually
shallow root, a vendored/zipapp layout, some CI scratch dirs) would raise
`IndexError` the moment the module is imported -- turning a path-shape edge case
into a hard startup crash of anything that imports the scoring package.

Review on PR #101 surfaced this: a module-level computation that can raise on an
environment we don't control is a latent import-time failure, not a runtime one
you can catch near a call site.

## Decision

Make the parent-index access defensive while keeping behavior identical for the
layouts we actually support.

- Compute `parents = this_file.parents` once, then build the candidate list as
  `[parents[i] for i in (2, 3) if len(parents) > i]` -- only indices that exist
  are considered.
- Change the final fallback from the unconditional `parents[2]` to
  `candidates[0] if candidates else this_file.parent`, so resolution degrades to
  the deepest *available* ancestor instead of indexing past the end.

In the normal and `src/` layouts the candidate list and resolution result are
unchanged; the guard only affects pathologically shallow paths, where the module
now imports successfully and resolves to the best available root rather than
crashing.

### What I decided vs. what the assistant proposed

The reviewer flagged the `IndexError` risk; the fix is small enough that the
mechanical change is uninteresting. The decision that mattered was *where* to
absorb the failure. I chose to keep root resolution at import time (the
`_PROJECT_ROOT` constant is load-bearing for cheap, repeated config lookups) and
make it total over all path shapes, rather than the alternative of deferring
resolution to first use and wrapping call sites in try/except. Keeping it eager
preserves the existing contract -- config path is known at import -- and confines
the fix to one function. The assistant implemented the comprehension;
the "stay eager, make the function total" call is mine.

## Consequences

- Importing `agentic_v2.scoring` can no longer raise `IndexError` from
  project-root resolution, regardless of how shallow the install path is.
- Supported layouts (normal, `src/`) are bit-for-bit unchanged -- no behavioral
  risk to production or CI.
- Resolution remains eager and module-level, so the per-call config-lookup cost
  is unchanged.
- The fallback is now explicit and self-documenting (deepest available ancestor),
  which is easier to reason about than the previous fixed-index fallback.
