import { describe, expect, it } from "vitest";
import { apiErrorMessage, apiErrorText } from "../components/common/apiErrorText";
import { formatApiError } from "../lib/apiErrors";

describe("apiErrorText", () => {
  it("keeps the server detail a gateway summary would otherwise drop", () => {
    const err = new Error("API 502: load rejected");
    expect(apiErrorMessage(err)).toBe(
      "The API server isn't responding (HTTP 502). Details: load rejected.",
    );
    expect(apiErrorText(err)).toBe(
      "The API server isn't responding (HTTP 502). Details: load rejected. Start it with `just dev`, then retry.",
    );
  });

  it("does not repeat a detail the summary already contains", () => {
    expect(apiErrorText(new Error("API 409: pack exists"))).toBe(
      "pack exists. Fix the input and try again.",
    );
    expect(apiErrorText(new Error("API 500: boom"))).toBe(
      "The API failed (HTTP 500): boom. Check the API server log, then retry.",
    );
  });

  it("describes network failures without a status", () => {
    expect(apiErrorText(new TypeError("Failed to fetch"))).toBe(
      "Can't reach the API server. Start it with `just dev`, then retry.",
    );
  });

  it("is the lib formatter under its legacy name", () => {
    expect(apiErrorText).toBe(formatApiError);
  });

  it("leaves sentence punctuation alone", () => {
    expect(apiErrorMessage(new Error("Already done!"))).toBe("Already done!");
  });
});
