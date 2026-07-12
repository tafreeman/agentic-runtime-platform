import { beforeEach, describe, expect, it, vi } from "vitest";
import { sendChat } from "../api/client";
import type { ChatRequest, ChatStreamEvent } from "../api/types";

const REQUEST: ChatRequest = {
  model: "openrouter:meta-llama/llama-3.1-8b-instruct:free",
  messages: [{ role: "user", content: "hi" }],
  temperature: 0.2,
};

/**
 * Minimal streaming Response stub: replays the given chunks through a
 * reader so frame-buffering across chunk boundaries is exercised for real.
 */
function makeStreamResponse(chunks: readonly string[]): Response {
  const encoder = new TextEncoder();
  const pending = chunks.map((chunk) => encoder.encode(chunk));
  let index = 0;
  const reader = {
    read: (): Promise<{ done: boolean; value: Uint8Array | undefined }> => {
      const value = pending[index];
      index += 1;
      return value === undefined
        ? Promise.resolve({ done: true, value: undefined })
        : Promise.resolve({ done: false, value });
    },
  };
  return {
    ok: true,
    status: 200,
    body: { getReader: () => reader },
  } as unknown as Response;
}

async function collectEvents(
  options: { signal?: AbortSignal } = {},
): Promise<ChatStreamEvent[]> {
  const events: ChatStreamEvent[] = [];
  await sendChat(REQUEST, (event) => events.push(event), options);
  return events;
}

describe("sendChat", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  it("POSTs to /api/chat and emits frames in order across chunk boundaries", async () => {
    const fetchSpy = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      makeStreamResponse([
        // The second frame is split mid-JSON across the chunk boundary to
        // prove the buffer is carried between reads.
        'data: {"type":"token","delta":"Hel"}\n\ndata: {"type":"tok',
        'en","delta":"lo"}\n\ndata: {"type":"done","model":"m"}\n\n',
      ]),
    );

    const controller = new AbortController();
    const events = await collectEvents({ signal: controller.signal });

    expect(events).toEqual([
      { type: "token", delta: "Hel" },
      { type: "token", delta: "lo" },
      { type: "done", model: "m" },
    ]);
    expect(fetchSpy).toHaveBeenCalledWith(
      "http://localhost:3000/api/chat",
      expect.objectContaining({
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(REQUEST),
        signal: controller.signal,
      }),
    );
  });

  it("flushes a final frame that arrives without a trailing separator", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      makeStreamResponse(['data: {"type":"token","delta":"tail"}']),
    );

    const events = await collectEvents();

    expect(events).toEqual([{ type: "token", delta: "tail" }]);
  });

  it("skips malformed frames with a warning and keeps streaming", async () => {
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      makeStreamResponse([
        "data: {not json}\n\n",
        'data: {"type":"done","model":"m"}\n\n',
      ]),
    );

    const events = await collectEvents();

    expect(events).toEqual([{ type: "done", model: "m" }]);
    expect(warnSpy).toHaveBeenCalled();
  });

  it("parses CRLF-delimited frames from a line-ending-normalizing proxy", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      makeStreamResponse([
        // Full CRLF framing, with the CRLF pair split across a chunk
        // boundary and a spec-legal "data:" line without the space.
        'data: {"type":"token","delta":"Hel"}\r\n\r\ndata:{"type":"token","delta":"lo"}\r',
        '\n\r\ndata: {"type":"done","model":"m"}\r\n\r\n',
      ]),
    );

    const events = await collectEvents();

    expect(events).toEqual([
      { type: "token", delta: "Hel" },
      { type: "token", delta: "lo" },
      { type: "done", model: "m" },
    ]);
  });

  it("ignores non-data frames such as SSE comments/keepalives", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      makeStreamResponse([
        ": keepalive\n\n",
        'data: {"type":"done","model":"m"}\n\n',
      ]),
    );

    const events = await collectEvents();

    expect(events).toEqual([{ type: "done", model: "m" }]);
  });

  it("rejects with the canonical API error shape on a non-OK response", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: false,
      status: 502,
      text: () => Promise.resolve("bad gateway"),
    } as Response);

    await expect(sendChat(REQUEST, () => undefined)).rejects.toThrow(
      "API 502: bad gateway",
    );
  });

  it("rejects when the response has no readable body", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue({
      ok: true,
      status: 200,
      body: null,
    } as unknown as Response);

    await expect(sendChat(REQUEST, () => undefined)).rejects.toThrow(
      /no readable body/,
    );
  });
});
