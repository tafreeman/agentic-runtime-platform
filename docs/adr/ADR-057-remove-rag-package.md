# ADR-057: Remove the `agentic_v2.rag` Package (Superseded by groundkit)

**Status:** Accepted
**Date:** 2026-08-10
**Supersedes:** [ADR-035](ADR-035-rag-pipeline-architecture.md) (RAG Pipeline Architecture)
**Related:** groundkit `ADR-0001-promote-vs-rewrite` (Accepted 2026-08-10, external repo — `github.com/tafreeman/groundkit`), [ADR-032](ADR-032-extract-scoring-package.md) (extract-a-domain-out-of-ARP precedent), [ADR-023](ADR-023-executionkit-runtime-contract-relationship.md) (external-package precedent, ExecutionKit)

---

## Context

ADR-035 shipped `agentic_v2/rag/` as a well-typed, Protocol-seamed RAG library —
seventeen modules, roughly 3,900 lines, with LanceDB + LiteLLM hybrid retrieval
and Pydantic v2 contracts at every boundary. It was never wired into the
product it lived in: no server route references it, no agent auto-registers
`RAGSearchTool`/`RAGIngestTool`, and the only live entry point — the
`agentic rag` CLI group — held all state in module-level globals that reset
every process, so nothing it produced survived a restart.

A standalone repository, **groundkit**, exists to be the production-grade RAG
library ARP's package aspired to but never became. groundkit's own
`ADR-0001-promote-vs-rewrite` (Accepted 2026-08-10) ran a 9-agent fan-out
inventory over `agentic_v2/rag/` at ARP branch `relock_scope`, read every
module in full, and adversarially confirmed all eight claimed production
gaps: no persistence across processes, no directory-scale ingestion,
unimplemented LanceDB metadata filtering, Protocol-naming mismatches between
`reranking.py`/`vectorstore.py` and `protocols.py`, no retrieval-quality eval
metrics, no retrieval service API, no MCP server surface, and no retrieval
IaC. It also catalogued specific defects to fix at port time rather than
carry forward: an infinite loop in `RecursiveChunker._hard_split` on
separator-free text, a negative-score crash in `CrossEncoderReranker` against
its own `Field(ge=0.0)` contract, the silently-absorbed `_metadata_filter`
keyword, an unescaped LanceDB delete predicate, and a credential leak via
`__cause__` in `embeddings.py`. Its recorded decision is explicit: *"ARP's
`agentic_v2.rag` package is expected to be deprecated and removed once
groundkit is established, tracked as separate ARP work"* — with **no
cherry-pick** of groundkit's fixes back into this repo. This ADR is that
separate work.

Three facts, verified 2026-08-10, make this a clean removal rather than a
phased deprecation:

1. **Zero non-test consumers.** A repo-wide import scan found no caller of
   `agentic_v2.rag` outside its own CLI wiring — no server router, no agent
   resolver, no other package reaches into it.
2. **The CI job was never a required check.** `rag-extra-tests`
   (`.github/workflows/ci.yml`) — the job that installed the `lancedb`/
   `litellm` backends and ran the RAG suites against them instead of fakes —
   was `continue-on-error: true` by design (see its own comment: "a
   resolution failure in a heavy optional extra should not block an
   unrelated PR"). It was never promoted to a required branch-protection
   check, so its removal drops no enforced gate.
3. **The package counted toward the coverage gate, not around it.**
   `agentic_v2/rag/` was not listed under `[tool.coverage.run] omit` in
   `agentic-workflows-v2/pyproject.toml`; its ~14 dedicated test files were
   measured as part of the 80% gate `.claude/rules/ci.md` describes, not
   excluded from it.

ADR-035 (as amended 2026-07-28) already documents the gap between this
package's original design intent and what shipped: no retry/backoff/circuit
breaker on the embedding path, no embedding cache, no OTEL spans (only
callback events), an unimplemented `SemanticChunker`, unimplemented
ingestion-time deduplication, and the two Protocol-signature mismatches
groundkit's inventory independently confirmed. None of that backlog is
picked up here — it is superseded, not fixed in place.

---

## Decision

Remove `agentic_v2.rag` **outright — no deprecation shim, no
`DeprecationWarning` period.** The zero-non-test-consumer finding is what
makes this the right call: a shim exists to protect call sites during a
migration window, and there are none to protect. (Contrast ADR-031, where
the LangGraph adapter got a `DeprecationWarning` period because it had real
import-time consumers to warn before removal.)

This was executed on this branch (`rag_removal`) in a single commit,
`9db6129f` (`refactor(rag): remove the agentic_v2.rag package, CLI, tests,
and CI job`). Full removal scope:

- **The `agentic_v2/rag/` package** — seventeen modules: `__init__.py`,
  `chunking.py`, `config.py`, `context_assembly.py`, `contracts.py`,
  `embeddings.py`, `errors.py`, `factory.py`, `ingestion.py`, `loaders.py`,
  `memory.py`, `protocols.py`, `reranking.py`, `retrieval.py`, `tools.py`,
  `tracing.py`, `vectorstore.py`.
- **The `agentic rag` CLI group** — `agentic_v2/cli/rag_commands.py`, the
  RAG-specific helper functions in `agentic_v2/cli/helpers.py`, and the
  group's registration in `agentic_v2/cli/main.py`.
- **14 dedicated test files** — the `tests/test_rag_*.py` suites
  (`test_rag_context_assembly.py`, `test_rag_contracts.py`,
  `test_rag_embeddings.py`, `test_rag_embeddings_litellm.py`,
  `test_rag_factory.py`, `test_rag_ingestion.py`, `test_rag_memory.py`,
  `test_rag_reranking.py`, `test_rag_retrieval.py`, `test_rag_tools.py`,
  `test_rag_tracing.py`, `test_rag_vectorstore.py`), plus
  `test_vectorstore_lancedb.py`, `test_vectorstore_metadata.py`,
  `test_memory_store.py`, and `test_cli_adapter.py` — and the RAG-specific
  sections of the mixed suite `tests/test_protocol_conformance.py`.
- **The `[rag]` optional extra** in `agentic-workflows-v2/pyproject.toml`
  (`lancedb>=0.15,<1`, `litellm>=1.84,<2`).
- **`docs/rag/`** (the standalone RAG usage guide, `docs/rag/index.md`).
- **`examples/02_rag_pipeline.py`.**
- **The non-blocking `rag-extra-tests` CI job** in
  `.github/workflows/ci.yml`.

`docs/adr/ADR-035-rag-pipeline-architecture.md` and
`docs/adr/RAG-pipeline-blueprint.md` are **retained**, per this repo's
convention of not deleting superseded decision records (see, e.g., ADR-031,
ADR-016), and are updated to point here rather than rewritten.

---

## Consequences

### Positive

- ARP sheds a subsystem it never wired into the product — roughly 3,900
  lines of maintained-but-unused code — along with the transitive optional
  dependency surface (`lancedb`, `litellm`) that came with it.
- One RAG implementation going forward instead of two slowly diverging ones;
  groundkit's stricter gates (`mypy --strict` repo-wide, no
  `continue-on-error` on any job that is the sole proof of a backend) become
  the only place RAG defects get fixed.
- The 80%-coverage-gated subset of `agentic_v2` shrinks by the RAG package
  and its ~14 test files. The percentage the gate reports going forward
  measures a smaller, fully product-connected surface — this is a change in
  what is measured, not a lowered bar.

### Negative / migration

- **`pip install agentic-workflows-v2[rag]` no longer resolves** — the extra
  is gone from `pyproject.toml`.
- Anyone constructing `agentic_v2.rag.tools.RAGSearchTool` /
  `RAGIngestTool` directly (no evidence any production code did) must
  migrate to groundkit once it ships a public release. groundkit is
  pre-v0.1.0 as of this ADR's date, so there is a gap between this removal
  and a consumable replacement; ARP carries no interim shim across that gap
  — the zero-non-test-consumer finding is what makes that acceptable.
- The `agentic rag` CLI group has no ARP-side replacement. groundkit's own
  MCP server surface (the port destination named for `tools.py` in its
  ADR-0001) is the intended replacement path, not an ARP CLI.
- Fixes recorded against `agentic_v2/rag/` — the ADR-035 Negative list and
  groundkit ADR-0001's port-time hazard list (the `_hard_split` infinite
  loop, the negative cross-encoder score crash, the silent metadata-filter
  no-op, the `NoOpReranker` keyword mismatch, the unescaped LanceDB delete
  predicate, the `__cause__` credential leak) — do not get fixed in ARP.
  They are fixed at groundkit's port time instead, per the no-cherry-pick
  decision in groundkit ADR-0001.

---

## Alternatives considered

- **Deprecate in place with a `DeprecationWarning` period** (the ADR-031
  LangGraph-adapter pattern). Rejected: that pattern protects import-time
  consumers during a migration window. The repo-wide scan found none, so a
  warning period would elapse silently, delaying cleanup for no protected
  caller.
- **Keep `agentic_v2.rag` and let groundkit duplicate the surface.**
  Rejected: two RAG implementations invite the same behavioral-divergence
  risk ADR-031 raised about running two execution engines, for a package
  groundkit's own inventory already found unwired and defect-bearing. It
  also keeps `lancedb`/`litellm` in ARP's optional-dependency tree for no
  consumer.
- **Cherry-pick groundkit's fixes back into ARP's copy instead of removing
  it.** Rejected — this was the owner's decision recorded in groundkit
  ADR-0001 itself ("no cherry-pick ... tracked as separate ARP work"), not a
  choice remade here. ARP and groundkit are peers under the portfolio's
  composition rules, not a library-and-consumer pair.
- **Leave the `rag-extra-tests` CI job in place, pointing at a deleted
  package.** Rejected: it would fail immediately (`pip install -e
  "agentic-workflows-v2/[dev,rag]"` has nothing to install) and, being
  `continue-on-error`, would report green while proving nothing.

---

## Implementation

Executed on this branch (`rag_removal`) in a single commit, `9db6129f`
(`refactor(rag): remove the agentic_v2.rag package, CLI, tests, and CI job`)
— see that commit for the exact file list (41 files changed, 2 insertions,
10,506 deletions). This is a complete cut; no follow-up removal work is
expected in ARP. Migration guidance for RAG functionality is: adopt
groundkit once it reaches v0.1.0.
