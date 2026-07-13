import { beforeEach, describe, expect, it, vi } from "vitest";
import { getModelRankings, startAutorank } from "../api/client";
import type { ModelRankingsResponse } from "../api/rankings";

const READY: ModelRankingsResponse = {
  status: "ready",
  ranked_with: "gemini:gemini-2.5-pro",
  grounded: true,
  updated_at: "2026-07-10T00:00:00Z",
  error: null,
  families: { "qwen3-coder": { score: 87, reasoning: "strong local coder" } },
};

describe("rankings API client", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("getModelRankings fetches /api/models/rankings", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      json: () => Promise.resolve(READY),
    } as Response);

    const result = await getModelRankings();
    expect(result.status).toBe("ready");
    expect(result.families["qwen3-coder"]?.score).toBe(87);
    expect(fetch).toHaveBeenCalledWith(
      "http://localhost:3000/api/models/rankings",
      undefined,
    );
  });

  it("startAutorank POSTs a null model and force=false by default", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      status: 200,
      json: () => Promise.resolve(READY),
    } as Response);

    const result = await startAutorank();
    // Fresh cache short-circuit: the 200 body is the full GET payload.
    expect(result.status).toBe("ready");
    const [url, init] = (fetch as ReturnType<typeof vi.fn>).mock
      .calls[0] as [string, RequestInit];
    expect(url).toBe("http://localhost:3000/api/models/autorank");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({
      model: null,
      force: false,
    });
  });

  it("startAutorank forwards an explicit ranker model and the force flag", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      status: 202,
      json: () =>
        Promise.resolve({ status: "started", ranked_with: "gh:openai/gpt-4o" }),
    } as Response);

    const result = await startAutorank("gh:openai/gpt-4o", true);
    expect(result).toEqual({
      status: "started",
      ranked_with: "gh:openai/gpt-4o",
    });
    const [, init] = (fetch as ReturnType<typeof vi.fn>).mock.calls[0] as [
      string,
      RequestInit,
    ];
    expect(JSON.parse(init.body as string)).toEqual({
      model: "gh:openai/gpt-4o",
      force: true,
    });
  });

  it("normalizes 409 (job already running) instead of throwing", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: false,
      status: 409,
      json: () => Promise.resolve({ detail: "ranking already in flight" }),
    } as Response);

    const result = await startAutorank(undefined, true);
    expect(result).toEqual({
      status: "already-running",
      detail: "ranking already in flight",
    });
  });

  it("falls back to a generic detail when the 409 body is malformed", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: false,
      status: 409,
      json: () => Promise.reject(new Error("not json")),
    } as Response);

    const result = await startAutorank();
    expect(result).toEqual({
      status: "already-running",
      detail: "a ranking job is already running",
    });
  });

  it("throws the canonical API error on 503 (no-LLM mode)", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: false,
      status: 503,
      text: () => Promise.resolve("placeholder scores would be garbage"),
    } as Response);

    await expect(startAutorank()).rejects.toThrow(
      "API 503: placeholder scores would be garbage",
    );
  });
});
