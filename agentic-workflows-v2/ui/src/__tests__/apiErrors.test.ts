import { describe, expect, it } from "vitest";
import {
  API_START_HINT,
  apiErrorMessage,
  describeApiError,
  describeStreamError,
  formatApiError,
} from "../lib/apiErrors";

describe("describeApiError", () => {
  it("treats an empty-body proxy 502 as an unreachable API with a start hint", () => {
    const d = describeApiError(new Error("API 502: "));
    expect(d).toMatchObject({ status: 502, unreachable: true, remedy: API_START_HINT });
    expect(d.summary).toMatch(/isn't responding \(HTTP 502\)/);
    expect(d.detail).toBeUndefined();
  });

  it.each([
    [503, ""],
    [504, "down"],
  ])("treats gateway status %i as unreachable", (status, body) => {
    expect(describeApiError(new Error(`API ${status}: ${body}`)).unreachable).toBe(true);
  });

  it("treats a 503 with a server-supplied detail as an application error, not an outage", () => {
    const d = describeApiError(new Error('API 503: {"detail":"settings store is not writable"}'));
    expect(d).toMatchObject({ status: 503, unreachable: false, detail: "settings store is not writable" });
    expect(d.summary).toMatch(/settings store is not writable/);
    expect(d.remedy).not.toBe(API_START_HINT);
  });

  it("treats a fetch TypeError as unreachable", () => {
    const d = describeApiError(new TypeError("Failed to fetch"));
    expect(d.unreachable).toBe(true);
    expect(d.summary).toMatch(/can't reach the api/i);
  });

  it("surfaces a FastAPI JSON detail for 4xx validation failures", () => {
    const d = describeApiError(
      new Error('API 422: {"detail":"dataset \'local-smoke\' has no samples"}'),
    );
    expect(d).toMatchObject({ status: 422, unreachable: false });
    expect(d.summary).toBe("dataset 'local-smoke' has no samples");
    expect(d.remedy).toMatch(/fix the input/i);
  });

  it("stringifies structured JSON details", () => {
    const d = describeApiError(new Error('API 400: {"detail":[{"loc":["x"]}]}'));
    expect(d.detail).toBe('[{"loc":["x"]}]');
  });

  it("keeps plain-text bodies and truncates long ones", () => {
    expect(describeApiError(new Error("API 409: pack exists")).summary).toBe("pack exists");
    const long = "x".repeat(300);
    expect(describeApiError(new Error(`API 400: ${long}`)).detail).toHaveLength(201);
  });

  it("falls back to a status-only summary when a 4xx has no body", () => {
    expect(describeApiError(new Error("API 403: ")).summary).toMatch(/rejected \(HTTP 403\)/);
  });

  it("describes 404s and 500s with their own remedies", () => {
    expect(describeApiError(new Error("API 404: ")).summary).toMatch(/not found/i);
    expect(describeApiError(new Error('API 404: {"detail":"no run"}')).summary).toBe(
      "Not found: no run",
    );
    const fiveHundred = describeApiError(new Error("API 500: boom"));
    expect(fiveHundred.summary).toBe("The API failed (HTTP 500): boom");
    expect(fiveHundred.remedy).toMatch(/server log/i);
    expect(describeApiError(new Error("API 500: ")).summary).toBe("The API failed (HTTP 500).");
  });

  it("passes through non-API errors and handles non-Error values", () => {
    expect(describeApiError(new Error("stream closed")).summary).toBe("stream closed");
    expect(describeApiError("plain string").summary).toBe("plain string");
    expect(describeApiError(undefined).summary).toBe("Something went wrong.");
  });
});

describe("formatApiError", () => {
  it("joins summary and remedy into one line", () => {
    expect(formatApiError(new Error("API 502: "))).toBe(
      `The API server isn't responding (HTTP 502). ${API_START_HINT}`,
    );
  });

  it("punctuates a bare server detail before the remedy", () => {
    expect(formatApiError(new Error("API 409: pack exists"))).toBe(
      "pack exists. Fix the input and try again.",
    );
    expect(formatApiError(new Error("API 500: boom"))).toBe(
      "The API failed (HTTP 500): boom. Check the API server log, then retry.",
    );
  });

  it("keeps the server detail a gateway summary would otherwise drop", () => {
    expect(formatApiError(new Error("API 504: model warming up"))).toBe(
      `The API server isn't responding (HTTP 504). Details: model warming up. ${API_START_HINT}`,
    );
  });

  it("does not double-punctuate truncated or already-punctuated text", () => {
    expect(apiErrorMessage(new Error("Already done!"))).toBe("Already done!");
    const long = "x".repeat(300);
    expect(apiErrorMessage(new Error(`API 400: ${long}`))).toBe(`${"x".repeat(200)}…`);
  });

  it("falls back to a generic sentence for unknown values", () => {
    expect(formatApiError(undefined)).toBe(
      "Something went wrong. Retry; if it keeps failing, check the API server log.",
    );
  });
});

describe("describeStreamError", () => {
  it("explains a lost connection with data validity and the retry behaviour", () => {
    const d = describeStreamError(
      "connection lost — the live stream stopped responding",
      "connection",
      { hasSteps: true },
    );
    expect(d.summary).toBe("Lost the live connection to this run.");
    expect(d.validity).toMatch(/may be out of date/);
    expect(d.remedy).toMatch(/about 30 seconds/);
    expect(d.remedy).toMatch(/keeps going on the server/);
    expect(d.canReconnect).toBe(true);
    // The raw socket text is not surfaced at all.
    expect(d.detail).toBeUndefined();
  });

  it("says nothing arrived when a connection drops before any step", () => {
    const d = describeStreamError("x", "connection", { hasSteps: false });
    expect(d.validity).toMatch(/No updates arrived/);
  });

  it("separates a scoring failure from the run's valid results", () => {
    const d = describeStreamError("Evaluation failed: judge missing", "server", {
      hasSteps: true,
    });
    expect(d.summary).toBe("Scoring failed after the run finished.");
    expect(d.validity).toMatch(/still valid/);
    expect(d.detail).toBe("judge missing");
    expect(d.canReconnect).toBe(false);
  });

  it("keeps a generic server error's text only as bounded detail", () => {
    const long = "x".repeat(400);
    const d = describeStreamError(long, "server", { hasSteps: false });
    expect(d.summary).toBe("The run stopped with a server error.");
    expect(d.validity).toMatch(/No steps completed/);
    expect(d.remedy).toMatch(/API server log/);
    expect(d.detail?.length).toBeLessThanOrEqual(301);
  });
});
