# ADR-017: Dataset Identifiers as Query Parameters, Not Path Segments

**Status:** Accepted
**Date:** 2026-04-22
**Related:** Epic 6 (Evaluation & Data Depth), Sprint B #4 (Dataset API HF Integration)

---

## Context

The evaluation surface exposes three dataset-aware endpoints on the FastAPI
server:

- `GET /api/eval/datasets` — list available datasets.
- `GET /api/eval/datasets/sample-list?dataset_source=…&dataset_id=…&offset=…&limit=…` — paginate summaries.
- `GET /api/eval/datasets/sample-detail?dataset_source=…&dataset_id=…&sample_index=…` — fetch full sample.

All three pass the dataset identifier as a **query parameter** (`?dataset_id=humaneval`)
rather than a **path segment** (`/api/eval/datasets/humaneval/sample-list`).

During Sprint B #4 the orchestrator flagged this as a candidate bug: the
query-param design *looks* less RESTful than `/datasets/{id}/samples`, and
the current registry uses short slug-like IDs (`humaneval`, `swe-bench-verified`)
so nothing today forces the query-param shape. Real-usage exercise against
HuggingFace confirmed the design is correct — this ADR ratifies the decision
after review so the question does not re-open in a future sprint.

---

## Decision

**Dataset identity travels on the query string, not the path, for every
evaluation endpoint that references a dataset.**

- `dataset_source` (`"repository" | "local"`) and `dataset_id` are both
  query parameters.
- The client in `ui/src/api/client.ts` constructs these URLs with
  `URLSearchParams`, which produces correctly percent-encoded pairs for any
  allowed identifier shape.
- Path segments are reserved for **resource kind** (`/eval/datasets/sample-list`),
  not **resource identity**.

---

## Rationale

### The identifiers we may need to accept

The current registry uses short aliases. Future registries we have already
scoped but not yet shipped include:

| Source | Example ID | Slashes? |
|--------|-----------|----------|
| Current registry | `humaneval` | no |
| Current registry | `swe-bench-verified` | no |
| Raw HuggingFace repo | `codeparrot/apps` | **yes** |
| Raw HuggingFace repo | `openai/openai_humaneval` | **yes** |
| GitHub gold-standard | `princeton-nlp/SWE-bench_Verified` | **yes** |

As soon as the registry accepts any Tier-B source that reuses an upstream
identifier verbatim (which is the ergonomic default — rewriting every HF ID
into a slug is friction we do not want), identifiers contain forward slashes.

### Why path segments break under slashes

1. **Reverse proxies and WAFs normalize paths inconsistently.** Azure Front
   Door, CloudFront, and nginx each handle `%2F` in path segments
   differently. Some unescape, some reject, some rewrite. Query strings have
   no such ambiguity — the `?` boundary is well-defined and `%2F` inside the
   query is transparent to every proxy we have surveyed.
2. **Framework routers split on raw slashes first.** FastAPI's router
   resolves `/eval/datasets/codeparrot/apps/sample-list` as a four-segment
   path, not a dataset-id-with-slash. Working around it requires regex
   routes (`{dataset_id:path}`) that defeat automatic OpenAPI parameter
   typing and leak into every downstream client generator.
3. **OpenAPI clients mis-encode the segment.** Generated clients for TS,
   Python, and Go all encode path params through `encodeURIComponent` by
   default — which escapes `/` to `%2F` and re-triggers the proxy
   normalization problem in step 1.

Query params sidestep all three issues with no tradeoff today (the current
registry does not exercise the slash case) and no migration cost later
(endpoints already accept the shape).

---

## Consequences

### Positive

- **Slash-safe forever.** Whenever the registry grows to accept raw
  HuggingFace or GitHub identifiers, the endpoints Just Work — no URL
  rewrites, no proxy-config audits, no client regeneration.
- **Percent-encoding is the client's problem, and the client already handles it.**
  `URLSearchParams` in the TypeScript client correctly encodes `/`, `:`, `#`,
  and Unicode. Custom path-segment escaping would duplicate that logic.
- **Endpoint surface stays uniform.** Every dataset-aware endpoint follows
  the same `?dataset_source=…&dataset_id=…` shape regardless of identifier
  content.

### Negative

- **Slightly less idiomatic-REST on the surface.** Strict REST fans prefer
  `/datasets/{id}/samples`. We accept this aesthetic cost — safety beats
  style on this axis.
- **Deep-linking relies on query strings.** Shared links embed the query
  params verbatim. Mitigated: the UI already preserves query params across
  navigation.

### Neutral

- **Caching is unaffected.** Most caches (CloudFront, Cloudflare, nginx)
  key on path + query by default; this decision does not change cache
  behavior.

---

## Alternatives Considered

### Alt 1: Path segments with regex-path-capture (`{dataset_id:path}`)

Rejected. Loses OpenAPI parameter typing, forces handler code to re-parse the
tail, and still hits the proxy-normalization problem in step 1 above.

### Alt 2: Base64url-encoded dataset IDs in path segments

Rejected. Adds ceremony on both sides (encode client, decode server), breaks
the human-readability of URLs in logs and bookmarks, and only sidesteps the
slash problem at the cost of turning every other debugging affordance off.

### Alt 3: Hybrid — path for slug IDs, query for raw HF IDs

Rejected. Two endpoint shapes for the same operation doubles the client
surface, the documentation burden, and the test matrix, for no upside over
"always query."

---

## Lineage

Builds on commit `c990538` (original `/api/eval/datasets` endpoints landing).
This ADR ratifies the existing design after Sprint B #4 review confirmed it
is correct and forward-compatible. No code changes land with this ADR — it is
a decision record only.

---

## Implementation Notes

- FastAPI route declarations: `agentic_v2/server/routes/evaluation_routes.py`
  (`list_dataset_samples`, `get_dataset_sample_detail`).
- Client: `agentic-workflows-v2/ui/src/api/client.ts` — uses
  `URLSearchParams` for dataset-endpoint URL construction.
- Integration test: `tests/server/test_evaluation_routes.py` exercises the
  query-param shape end-to-end.
