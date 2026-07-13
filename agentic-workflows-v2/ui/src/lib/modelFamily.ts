/**
 * Model-family normalization — the shared key of /api/models/rankings.
 *
 * Mirrors the backend implementation EXACTLY (the ranking cache is keyed by
 * family, so both sides must agree byte-for-byte). The contract, in order:
 *   1. lowercase the id;
 *   2. if the segment before the first ':' is a known provider prefix,
 *      drop it and the ':';
 *   3. drop any org path up to and including the last '/';
 *   4. keep only the part before the next ':' (drops size/quant tags).
 *
 * The contract examples live verbatim in __tests__/modelFamily.test.ts —
 * any change here must keep that table (and the backend twin) green.
 */

/** Provider prefixes recognized by rule 2 (must match the backend list). */
const KNOWN_PROVIDER_PREFIXES: ReadonlySet<string> = new Set([
  "ollama",
  "openai",
  "nvidia",
  "gh",
  "gemini",
  "anthropic",
  "claude",
  "openrouter",
  "onnx",
  "lmstudio",
  "local",
  "local-api",
  "notebooklm",
]);

/** Normalize a model id to its ranking family key. */
export function normalizeFamily(id: string): string {
  const lowered = id.toLowerCase();
  const firstColon = lowered.indexOf(":");
  const prefixDropped =
    firstColon !== -1 &&
    KNOWN_PROVIDER_PREFIXES.has(lowered.slice(0, firstColon))
      ? lowered.slice(firstColon + 1)
      : lowered;
  const lastSlash = prefixDropped.lastIndexOf("/");
  const orgDropped =
    lastSlash === -1 ? prefixDropped : prefixDropped.slice(lastSlash + 1);
  const nextColon = orgDropped.indexOf(":");
  return nextColon === -1 ? orgDropped : orgDropped.slice(0, nextColon);
}
