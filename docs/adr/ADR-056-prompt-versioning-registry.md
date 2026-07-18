# ADR-056: Prompt-Versioning Registry

**Status:** Accepted
**Date:** 2026-07-17
**Related:** `agentic_v2/prompts/registry.py` (`PromptRecord`, `PromptRegistry`,
`default_registry`), `agentic_v2/prompts/__init__.py` (`load_prompt`,
`list_prompts`), `agentic_v2/engine/prompt_assembly.py`
(`load_agent_system_prompt`), `agentic_v2/scoring/judge.py`
(`JUDGE_PROMPT_TEMPLATE`, `LLMJudge.prompt_version`),
`docs/superpowers/specs/2026-07-02-evaluation-framework-design.md` §6.4-6.6

## Context

`LLMJudge.__init__` carried `prompt_version: str = "judge-v1"` as a
constructor default. That string flows into
`JudgeEvaluationResult.prompt_version`, `to_payload()["prompt_version"]`,
and the deterministic shuffle seed (`_stable_seed(candidate_output,
expected_output, self.prompt_version)`). It never changed on its own: the
judge prompt is assembled by `_build_prompt` (an f-string in
`agentic_v2/scoring/judge.py`, previously inline at roughly lines
559-568), and nothing tied the literal `"judge-v1"` tag to that prompt's
actual content. A hand-edit to the rubric instructions would silently ship
under the same reported version -- an audit flagged this as a hardcoded
tag masquerading as a version.

The same gap existed for the 7 role persona prompts. Two independent APIs
already served them with no cross-check between the two:

- `agentic_v2/prompts/__init__.py` (`load_prompt`, `list_prompts`,
  `get_prompt_path`) has no production callers -- verified by repo-wide
  search, it is exercised only by tests and referenced only in docs.
- The real consumer is
  `agentic_v2/engine/prompt_assembly.py:load_agent_system_prompt`, called
  from `agentic_v2/engine/agent_resolver.py:578`, which reads
  `prompts/<role>.md` directly by path with no fingerprinting at all.

`agents/reviewer.py` has its own inline `REVIEW_SYSTEM_PROMPT`, which is a
**different** prompt from `prompts/reviewer.md` -- the two are unrelated
strings that happen to share a role name. Wiring the registry into
`reviewer.py` was out of scope: it is a distinct output-format contract,
not a persona lookup, and touching it risks changing what the reviewer
actually returns.

Separately, the evalkit design
(`docs/superpowers/specs/2026-07-02-evaluation-framework-design.md`) specs
`GradeResult` (§6.5) as carrying "grader/model/prompt fingerprints" and
`EvalRunManifest` (§6.6) as carrying "grader/rubric versions and prompt
hashes." Nothing in ARP produced a value shaped to fill either field.

`.gitattributes` pins `* text=auto eol=lf` repo-wide, but this is a
Windows-authored change: a local editor or a `git config core.autocrlf`
misconfiguration can still reintroduce CRLF into a working tree before a
commit normalizes it back, and any future reader that opens a prompt file
in binary mode bypasses Python's own universal-newline translation
entirely. A version scheme built directly on raw file bytes would drift on
line-ending noise alone, which is not a real content change.

## Decision

Introduce `agentic_v2/prompts/registry.py`, a small content-addressed
prompt registry, and wire it into the three places that actually consume
prompt content:

- **`PromptRecord`** -- a frozen, slotted dataclass: `name`,
  `declared_version` (the human-assigned tag, e.g. `"v1"` or
  `"judge-v1"`), `content` (LF-normalized), `content_sha256`, and `source`
  (`"file:<basename>"` or `"inline:<name>"`). Two derived properties:
  `short_hash` (first 8 hex chars of the digest) and `qualified_version`
  (`f"{declared_version}@{short_hash}"`, e.g. `"judge-v1@2476efb8"`).
- **LF-normalize, then SHA-256.** `normalize_prompt_text` replaces
  `\r\n` and bare `\r` with `\n` before `compute_content_hash` hashes the
  UTF-8 bytes. A CRLF checkout of the exact same logical prompt produces
  an identical fingerprint to an LF checkout; an actual content edit
  always changes it.
- **`PromptRegistry`** -- `register_inline(name, text, *,
  declared_version)` and `register_file(name, path, *, declared_version)`
  both normalize-then-hash and return the frozen record; `get`/`get_or_none`/
  `text`/`records`/`names` are the read surface. `records()` returns an
  immutable tuple snapshot.
- **`default_registry()`** -- a cached singleton (`lru_cache(maxsize=1)`)
  that auto-registers the 7 role `.md` files
  (architect/coder/orchestrator/planner/reviewer/tester/validator) from a
  typed `PROMPT_VERSIONS` map, each currently declared `"v1"`.
- **Three call sites, three roles:**
  - `agentic_v2/prompts/__init__.py:load_prompt` resolves through
    `default_registry().get_or_none(stem)` first, falling back to a
    direct file read (preserving the `FileNotFoundError` contract) for
    any name the default registry doesn't carry. The now-redundant
    `lru_cache` on `load_prompt` is dropped -- the registry itself is the
    cache.
  - `agentic_v2/engine/prompt_assembly.py:load_agent_system_prompt`'s
    role-lookup branch resolves through the same `default_registry()`
    before falling back to its pre-existing direct file read, so the
    engine's actual persona-prompt consumer and the legacy `load_prompt`
    API report identical content and identical fingerprints for the same
    role.
  - `agentic_v2/scoring/judge.py` extracts the static scaffold of
    `_build_prompt` into a module-level `JUDGE_PROMPT_TEMPLATE` (the
    dynamic per-call pieces -- rubric text, mode, candidate/expected
    output, swapped-order note, reference block -- are filled in via
    `.format()`, producing byte-identical output to the prior f-string).
    At import time the template is registered inline (`name="judge"`,
    `declared_version="judge-v1"`) in a registry **dedicated to the
    judge module**, not the shared `default_registry()` -- keeping the
    default registry's name set exactly the 7 personas.
    `LLMJudge.__init__`'s `prompt_version` parameter becomes `str | None
    = None`; `None` resolves to the registered `qualified_version`
    (`"judge-v1@<8-hex>"`). A caller that passes an explicit
    `prompt_version` still gets that literal back verbatim -- the three
    existing explicit-override test sites keep passing unchanged.
- **Drift is detectable-by-construction, not runtime-enforced.** A golden
  fingerprint test (`tests/golden/prompt_fingerprints.json`, generated by
  running `default_registry()` + the judge module's registration, never
  hand-written) fails CI the moment any of the 8 fingerprints change
  unexpectedly. There is no new runtime warn/raise path on prompt drift --
  the registry does not judge whether a change is "safe," it just makes
  every change visible in a reviewable diff.
- **Fingerprints stay out of `contracts/` this slice.** `qualified_version`
  is not added to `StepResult`, the manifest, or any Pydantic wire-format
  type. Surfacing it on those types -- which the evalkit spec's
  `GradeResult`/`EvalRunManifest` fields (§6.5-6.6) are shaped to receive
  -- is a named future slice, not bundled into this one, so the
  `wire-format-drift` gate has nothing new to regenerate here.

## Consequences

- `prompt_version` can no longer silently lie about whether a prompt
  changed: the default value is now a function of the prompt's actual
  content, for both the judge prompt and (via `load_agent_system_prompt`
  and `load_prompt`) the 7 role personas.
- The registry's `qualified_version` values are exactly shaped to
  populate the evalkit spec's `GradeResult`/`EvalRunManifest`
  prompt-fingerprint fields once that wiring slice happens -- no format
  translation needed.
- No new runtime dependency, no wire-format/contract change, and no
  behavior change to prompt *content* -- `_build_prompt`'s templated
  output is verified byte-identical to the pre-refactor f-string, and
  `load_agent_system_prompt`'s registered-role branch returns the same
  text `prompts/<role>.md` always contained (now LF-normalized, which
  Python's own text-mode file reads already did on non-Windows CI
  runners in practice).
- **The default judge `prompt_version` string changes shape**: callers
  that did not explicitly pass `prompt_version` (the three production
  call sites in `server/execution.py` and `server/routes/runs.py`, all of
  which construct `LLMJudge()`/`LLMJudge(model=...)` with no
  `prompt_version` argument) now get `"judge-v1@<8-hex>"` instead of the
  bare `"judge-v1"` literal. Because `prompt_version` feeds
  `_stable_seed`, the criterion-shuffle order on that default path shifts
  accordingly -- an accepted, cosmetic consequence (shuffle order was
  never a stability guarantee) rather than a behavior regression. One
  documentation example (`docs/evaluation/gating.md`) is updated to an
  illustrative qualified-version placeholder to match.
- Two prompt-loading APIs still coexist
  (`agentic_v2.prompts.load_prompt` and
  `agentic_v2.engine.prompt_assembly.load_agent_system_prompt`) --
  unifying them into one was out of scope; this slice makes them agree on
  content and fingerprint without merging their call signatures.

## Alternatives considered

- **Hash the raw file/string bytes directly, no normalization.** Rejected:
  a CRLF-vs-LF checkout difference (Windows editor, `core.autocrlf`
  misconfiguration, or a binary-mode read bypassing Python's own
  universal-newline translation) would register as a content change even
  though nothing meaningful changed, producing false drift-detection
  noise that would train reviewers to ignore the golden-fingerprint
  failures.
- **Runtime fail/warn on prompt drift** (e.g., raise or log a warning
  the moment a computed hash disagrees with a stored expectation at
  request time). Rejected: that couples prompt content review to
  production request handling and would turn an intentional, reviewed
  prompt edit into a live failure or noisy warning on every subsequent
  call until some separate "accept new hash" step ran. A golden test
  reviewed and committed alongside the content change is the right
  place to gate this, not the request path.
- **Register the judge prompt as `prompts/judge.md` in the shared
  registry.** Rejected: the judge prompt is assembled from a template
  plus per-call dynamic content (rubric, mode, outputs) -- it isn't a
  static persona file, and adding it to `default_registry()` would grow
  the "7 role names" invariant to 8 for no consumer that needs it there.
  A dedicated registry instance in `scoring/judge.py` keeps the concerns
  separate while still using the same `PromptRecord`/hashing machinery.
- **Add `qualified_version`/prompt hashes to `StepResult` or the run
  manifest now**, ahead of the evalkit integration that actually consumes
  them. Rejected: that's a `contracts/` wire-format change requiring the
  `wire-format-drift` regeneration (TS types + JSON schemas) for a
  consumer that doesn't exist yet in-tree. Left as a named future slice
  once the evalkit bridge is ready to read the field.
- **Wire the registry into `agents/reviewer.py`'s inline
  `REVIEW_SYSTEM_PROMPT`.** Rejected: that constant is a different prompt
  from `prompts/reviewer.md` (confirmed by reading both), governing a
  different agent's output-format contract. Swapping it for the
  registry-backed `prompts/reviewer.md` content would silently change
  what that agent is instructed to produce -- a behavior change
  disguised as a versioning refactor.
