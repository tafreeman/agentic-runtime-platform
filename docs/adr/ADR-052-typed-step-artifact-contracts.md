# ADR-052: Typed Step Artifact Contracts

**Status:** Accepted
**Date:** 2026-07-14
**Related:** ADR-001 (dual execution engines), ADR-014 (wire-format
discipline), ADR-034 (path-first workflow I/O proposal)

## Context

A live `fullstack_generation` run exposed a semantic false success. The
`generate_api` response contained both an `api_code` placeholder ("see
backend_code for implementation") and a valid `backend_code` file map.
Downstream expressions used `coalesce(api_code, backend_code)`, so the first
non-null value won even though it was not code. Review and assembly then ran
without the generated backend.

The YAML loaders and both execution engines checked output key presence, not
content. Aliases were duplicated in prompts and output mappings, making key
presence an unreliable proxy for a usable artifact. Changing `coalesce()` to
inspect content would mix workflow policy into the expression language and
change every existing workflow.

## Decision

Add optional, per-step `input_contracts` and `output_contracts`. The first
supported kind is `code_artifact`, accepted only as either:

- a non-empty map of safe relative file paths to non-blank source text; or
- a complete `FILE: <relative path>` / `ENDFILE` payload.

Contracts reject missing required values, empty or hollow maps, unsafe paths,
placeholder objects, and placeholder/refusal/reference-only prose. Failures
carry structured diagnostics with the field, kind, code, and message. String
payloads are parsed with the canonical FILE/ENDFILE grammar owned by
`agentic_v2/engine/llm_output_parsing.py`; contract validation does not define
a grammar of its own, so it can never disagree with downstream extraction.

Output contracts name one canonical field and may declare migration aliases.
A valid canonical value wins. An alias is promoted only when the canonical
value is missing or invalid and the alias independently validates. Alias names
are parse-only compatibility inputs; they are not added to the model prompt.

The native executor validates contracted inputs before step invocation and
contracted outputs before success mapping. The LangChain adapter applies the
same shared validator before agent invocation, during model failover, and
before a success update. Contracted output failover rejects an invalid final
candidate instead of recording its raw prose as success.

On a contract violation the two engines deliberately keep their existing
recovery strategies: the native executor treats it like any other step error
and retries within the step's retry budget (a nondeterministic model may
produce a valid artifact on a later attempt), while the LangChain adapter
fails over to the next model candidate. Both paths fail closed once the
retry budget or candidate list is exhausted.

`fullstack_generation` adopts the contract for `backend_code` and
`backend_tests`, with `api_code` and `api_tests` as legacy aliases. Consumers
resolve canonical backend content first and validate it before invocation.
Under `AGENTIC_NO_LLM=1`, placeholder prose intentionally produces a failed
fullstack run; it is useful smoke evidence, not a generated application.

## Consequences

- Structural success now requires usable backend content in the fullstack
  workflow on both engines.
- Existing workflows remain unchanged until they opt into contracts.
- Existing checkpoints with valid legacy `api_code` content remain readable.
- Contracted generation may consume another model candidate or fail a step
  that previously appeared successful with unusable prose.
- The external event and wire formats do not change; diagnostics use existing
  step error and metadata fields.

## Alternatives considered

- **Reverse only the fullstack `coalesce()` arguments.** This fixes the
  captured ordering but still accepts a placeholder canonical value.
- **Change global `coalesce()` semantics.** Rejected because expression
  evaluation cannot infer the semantic type of arbitrary workflow values.
- **Require both canonical and alias outputs.** Rejected because duplicate
  prompt keys recreate the ambiguity and waste model output.
- **Implement ADR-034 path materialization now.** Deferred. Run-scoped storage,
  checkpoint migration, tool permissions, and event payloads are a larger
  architecture change.

## Scope boundary and follow-up

This ADR implements typed inline content validation for one artifact kind and
one production workflow. It does **not** complete ADR-034's path-first design.
ADR-034 remains Proposed until authoritative run-scoped paths, persistence,
security boundaries, and broader workflow migration are implemented and
verified.

Implementation references:

- `agentic-workflows-v2/agentic_v2/artifact_contracts.py`
- `agentic-workflows-v2/agentic_v2/engine/step.py`
- `agentic-workflows-v2/agentic_v2/langchain/graph_wiring.py`
- `agentic-workflows-v2/agentic_v2/workflows/definitions/fullstack_generation.yaml`
