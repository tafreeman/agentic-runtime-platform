import { renderHook } from "@testing-library/react";
import { afterEach, describe, it, expect, vi } from "vitest";
import { usePrefersReducedMotion } from "../hooks/usePrefersReducedMotion";

describe("usePrefersReducedMotion", () => {
  afterEach(() => {
    // Remove any matchMedia stub so other suites see the jsdom default.
    Reflect.deleteProperty(window, "matchMedia");
    vi.restoreAllMocks();
  });

  it("returns false when matchMedia is unavailable (jsdom default)", () => {
    const { result } = renderHook(() => usePrefersReducedMotion());
    expect(result.current).toBe(false);
  });

  it("reflects a matching reduce preference", () => {
    const addEventListener = vi.fn();
    const removeEventListener = vi.fn();
    window.matchMedia = vi.fn().mockReturnValue({
      matches: true,
      addEventListener,
      removeEventListener,
    }) as unknown as typeof window.matchMedia;

    const { result, unmount } = renderHook(() => usePrefersReducedMotion());
    expect(result.current).toBe(true);
    // Subscribes to changes and cleans up on unmount.
    expect(addEventListener).toHaveBeenCalledWith("change", expect.any(Function));
    unmount();
    expect(removeEventListener).toHaveBeenCalledWith("change", expect.any(Function));
  });
});
