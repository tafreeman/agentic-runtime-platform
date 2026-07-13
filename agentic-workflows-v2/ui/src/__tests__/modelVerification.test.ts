import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  VERIFICATION_STORAGE_KEY,
  clearVerifications,
  getVerification,
  loadVerifications,
  recordVerification,
} from "../lib/modelVerification";

describe("modelVerification", () => {
  beforeEach(() => {
    localStorage.clear();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("starts empty and returns null for unknown models", () => {
    expect(loadVerifications()).toEqual({});
    expect(getVerification("ollama:qwen3:8b")).toBeNull();
  });

  it("records an ok outcome with an ISO timestamp", () => {
    recordVerification("ollama:qwen3:8b", "ok");

    const entry = getVerification("ollama:qwen3:8b");
    expect(entry?.status).toBe("ok");
    expect(entry?.message).toBeUndefined();
    expect(entry?.at).toMatch(/^\d{4}-\d{2}-\d{2}T/);
  });

  it("records an error outcome with the failure message", () => {
    recordVerification("openai:gpt-4o", "error", "no API key configured");

    expect(getVerification("openai:gpt-4o")).toMatchObject({
      status: "error",
      message: "no API key configured",
    });
  });

  it("keeps entries for other models when recording (read-modify-write)", () => {
    recordVerification("a:model-1", "ok");
    recordVerification("b:model-2", "error", "boom");

    const all = loadVerifications();
    expect(Object.keys(all).sort()).toEqual(["a:model-1", "b:model-2"]);
  });

  it("overwrites a previous outcome for the same model", () => {
    recordVerification("a:model-1", "error", "was down");
    recordVerification("a:model-1", "ok");

    const entry = getVerification("a:model-1");
    expect(entry?.status).toBe("ok");
    expect(entry?.message).toBeUndefined();
  });

  it("clearVerifications drops the whole registry", () => {
    recordVerification("a:model-1", "ok");

    clearVerifications();

    expect(loadVerifications()).toEqual({});
  });

  it("treats malformed JSON as an empty registry", () => {
    localStorage.setItem(VERIFICATION_STORAGE_KEY, "{not json");

    expect(loadVerifications()).toEqual({});
  });

  it("drops entries that fail the shape check instead of crashing", () => {
    localStorage.setItem(
      VERIFICATION_STORAGE_KEY,
      JSON.stringify({
        good: { status: "ok", at: "2026-07-13T00:00:00.000Z" },
        badStatus: { status: "maybe", at: "2026-07-13T00:00:00.000Z" },
        badShape: 42,
        badAt: { status: "ok", at: 123 },
      }),
    );

    expect(Object.keys(loadVerifications())).toEqual(["good"]);
  });

  it("treats a non-object payload (array) as empty", () => {
    localStorage.setItem(VERIFICATION_STORAGE_KEY, JSON.stringify([1, 2, 3]));

    expect(loadVerifications()).toEqual({});
  });

  it("survives a throwing localStorage.getItem", () => {
    const throwingGet = vi
      .spyOn(localStorage, "getItem")
      .mockImplementation(() => {
        throw new Error("storage disabled");
      });

    expect(loadVerifications()).toEqual({});
    expect(getVerification("a:model-1")).toBeNull();
    expect(throwingGet).toHaveBeenCalled();
  });

  it("survives a throwing localStorage.setItem and removeItem", () => {
    vi.spyOn(localStorage, "setItem").mockImplementation(() => {
      throw new Error("quota exceeded");
    });
    vi.spyOn(localStorage, "removeItem").mockImplementation(() => {
      throw new Error("storage disabled");
    });

    expect(() => recordVerification("a:model-1", "ok")).not.toThrow();
    expect(() => clearVerifications()).not.toThrow();
  });
});
