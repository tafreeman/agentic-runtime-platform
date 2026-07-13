import { describe, expect, it } from "vitest";
import { normalizeFamily } from "../lib/modelFamily";

// The shared wire-contract examples, VERBATIM — the same pairs are asserted
// on the backend so the two normalizers can never drift apart. Do not edit
// an expectation here without changing the contract on both sides.
const CONTRACT_EXAMPLES: ReadonlyArray<readonly [string, string]> = [
  ["ollama:qwen3-coder:30b", "qwen3-coder"],
  ["nvidia:deepseek-ai/deepseek-v4-flash", "deepseek-v4-flash"],
  ["openai:01-ai/yi-large", "yi-large"],
  ["gh:openai/gpt-4o", "gpt-4o"],
  ["anthropic:claude-sonnet-4-6", "claude-sonnet-4-6"],
  // No known provider prefix: rule 2 skips, rules 3-4 still apply.
  ["hf.co/lmstudio-community/qwen3.6-27b-gguf:q8_0", "qwen3.6-27b-gguf"],
];

describe("normalizeFamily", () => {
  it.each(CONTRACT_EXAMPLES)("normalizes %s -> %s", (id, family) => {
    expect(normalizeFamily(id)).toBe(family);
  });

  it("lowercases before matching the provider prefix", () => {
    expect(normalizeFamily("Ollama:Qwen3-Coder:30B")).toBe("qwen3-coder");
  });

  it("passes a bare family id through unchanged", () => {
    expect(normalizeFamily("qwen3-coder")).toBe("qwen3-coder");
  });

  it("drops a provider prefix even without a size tag", () => {
    expect(normalizeFamily("ollama:llama3")).toBe("llama3");
  });

  it("drops multi-segment org paths up to the last slash", () => {
    expect(normalizeFamily("openrouter:org/suborg/model-x:free")).toBe(
      "model-x",
    );
  });
});
