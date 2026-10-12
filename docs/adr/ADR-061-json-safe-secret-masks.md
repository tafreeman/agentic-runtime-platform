# ADR-061: Secret Masks End at a JSON String Terminator

**Status:** Accepted
**Date:** 2026-10-12
**Related:** `agentic_v2/middleware/detectors/secrets.py` (`SecretDetector`),
`agentic_v2/middleware/response_sanitizer.py`,
`agentic_v2/langchain/response_sanitization.py`,
`agentic_v2/engine/llm_output_parsing.py`, [ADR-046](ADR-046-response-entropy-masking.md)

## Context

`ResponseSanitizer` masks secrets in model replies **before** step outputs are
parsed, on both engines. Four `SecretDetector` patterns end their value with an
unbounded non-whitespace run (`\S{8,}`, `\S{16,}`, `\S{20,}`, `\S+@\S+`), and
masking replaces the whole match.

Most structured replies are JSON, and inside a JSON string the run does not
stop at the end of the secret. In a reviewer finding's
`"code_before": "...;Password=postgres\"",` the `env_secret` match is
`Password=postgres\"",`. That match covers the escaped quote, the string's
closing quote and the member's comma. Masking it left
`"...;[REDACTED:env_variable]` followed by the next member, so the reply no
longer parsed. On 2026-10-11 four `fullstack_generation` runs lost their whole
`review_report` this way. PR #377 made the parser repair this damage, but
only for the review report, and only by recognising the damaged lines from
their shape. Every other JSON step output stays exposed.

The `connection_string` pattern also missed the scheme spellings that generated
code uses most: `postgresql://`, driver suffixes (`postgresql+asyncpg://`,
`mysql+pymysql://`), `mongodb+srv://` and `rediss://`. Credentials in those
URLs reached step outputs unmasked.

## Decision

1. **Detection is unchanged.** The same patterns produce the same matches and
   the same findings.
2. **The masked span ends before the first unescaped `"` in the match, when the
   text up to that quote is still a full match of the same pattern.** Inside a
   JSON string the first unescaped quote is the terminator, so the mask can no
   longer remove it. The replacement text has no quotes or backslashes, and a
   quote preceded by an even number of backslashes leaves no escape sequence
   split. The masked JSON therefore still parses.
3. **When the text before that quote is too short to match the pattern, the
   span stays as matched.** Examples are a quoted value in plain text, where
   the first quote opens the value, and a short value followed by another
   member in compact JSON. No detection masks less than the pattern
   requires.
4. **`connection_string` accepts** `mongodb(+srv)`, `postgres(ql)`, `mysql`,
   `mariadb` and `redis(s)`, each with an optional `+driver` suffix.

The finding's `location` reports the shortened span, so `scan` and
`scan_and_mask` stay consistent.

## Consequences

- JSON replies keep their structure after masking: pretty-printed and compact,
  fenced or inside `<<<ARTIFACT>>>` blocks. The masked value still reads
  `[REDACTED:<category>]`.
- In JSON-encoded text, the characters after the terminator are no longer
  masked. They are the closing quote, the comma and, in compact JSON, the next
  member. None of them is part of the secret.
- In plain text, a secret that contains a raw `"` after its first 8 (or 16, or
  20) characters keeps its tail after that quote visible. Such a value cannot
  occur inside a JSON string, where the quote would be escaped. It is accepted
  as rare.
- A compact JSON reply in which a short value is followed directly by another
  member is still corrupted, as before. Ending the mask at that quote would
  mask fewer characters than the pattern requires.
- Credentials in the newly covered connection URLs are masked and classified
  `REDACTED`.

## Alternatives considered

- **Exclude quotes from the value run** (`[^\s"]{8,}`). Rejected: a secret that
  opens with a quote, or contains one, would stop matching altogether and leak
  in full.
- **Trim trailing quote, comma and bracket characters from every match.**
  Rejected: this keeps the JSON valid only when the run ends at whitespace.
  Compact JSON stays corrupted, and secrets that end in those characters lose
  them from the mask.
- **Parse first, then mask each string value.** Rejected for now. The native
  client masks every response, tool-loop turns included, before any parser
  sees it. Reordering that is a larger change to the response path than this
  defect needs.
- **Leave the sanitizer alone and rely on the parser repair from PR #377.**
  Rejected: that repair is limited to `review_report`, and it has to guess
  from line shapes where a masked string ended.
