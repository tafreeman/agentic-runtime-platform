import { afterEach, describe, expect, it, vi } from "vitest";
import { isApplePlatform, paletteShortcutKeys } from "../lib/platform";

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("isApplePlatform", () => {
  it("prefers User-Agent Client Hints when present", () => {
    expect(isApplePlatform({ userAgentData: { platform: "macOS" }, platform: "Win32" })).toBe(true);
    expect(isApplePlatform({ userAgentData: { platform: "Windows" }, platform: "MacIntel" })).toBe(false);
  });

  it("falls back to the legacy navigator.platform", () => {
    expect(isApplePlatform({ platform: "MacIntel" })).toBe(true);
    expect(isApplePlatform({ platform: "iPhone" })).toBe(true);
    expect(isApplePlatform({ platform: "iPad" })).toBe(true);
    expect(isApplePlatform({ platform: "Win32" })).toBe(false);
    expect(isApplePlatform({ platform: "Linux x86_64" })).toBe(false);
  });

  it("falls back when the client-hint platform is empty", () => {
    expect(isApplePlatform({ userAgentData: { platform: "" }, platform: "MacIntel" })).toBe(true);
  });

  it("is false when nothing is reported (SSR / jsdom)", () => {
    expect(isApplePlatform({})).toBe(false);
    expect(isApplePlatform(undefined)).toBe(false);
  });

  it("reads the global navigator by default", () => {
    vi.spyOn(navigator, "platform", "get").mockReturnValue("MacIntel");
    expect(isApplePlatform()).toBe(true);

    vi.spyOn(navigator, "platform", "get").mockReturnValue("Win32");
    expect(isApplePlatform()).toBe(false);
  });

  it("is false without a navigator global", () => {
    vi.stubGlobal("navigator", undefined);
    expect(isApplePlatform()).toBe(false);
  });
});

describe("paletteShortcutKeys", () => {
  it("names the platform's modifier key", () => {
    expect(paletteShortcutKeys({ platform: "MacIntel" })).toEqual(["⌘", "K"]);
    expect(paletteShortcutKeys({ platform: "Win32" })).toEqual(["Ctrl", "K"]);
  });
});
