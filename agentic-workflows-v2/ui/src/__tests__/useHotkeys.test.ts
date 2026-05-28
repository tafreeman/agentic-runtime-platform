import { renderHook } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { useHotkeys } from "../hooks/useHotkeys";

function fireKey(key: string, options: Partial<KeyboardEventInit> = {}) {
  window.dispatchEvent(new KeyboardEvent("keydown", { key, bubbles: true, ...options }));
}

describe("useHotkeys", () => {
  beforeEach(() => {
    // Ensure no active input between tests
    (document.activeElement as HTMLElement | null)?.blur?.();
  });

  it("calls filter handler on 'f'", () => {
    const filter = vi.fn();
    renderHook(() => useHotkeys({ filter }));
    fireKey("f");
    expect(filter).toHaveBeenCalledOnce();
  });

  it("calls filter handler on '/'", () => {
    const filter = vi.fn();
    renderHook(() => useHotkeys({ filter }));
    fireKey("/");
    expect(filter).toHaveBeenCalledOnce();
  });

  it("calls new handler on 'n'", () => {
    const newFn = vi.fn();
    renderHook(() => useHotkeys({ new: newFn }));
    fireKey("n");
    expect(newFn).toHaveBeenCalledOnce();
  });

  it("calls next handler on 'j'", () => {
    const next = vi.fn();
    renderHook(() => useHotkeys({ next }));
    fireKey("j");
    expect(next).toHaveBeenCalledOnce();
  });

  it("calls prev handler on 'k'", () => {
    const prev = vi.fn();
    renderHook(() => useHotkeys({ prev }));
    fireKey("k");
    expect(prev).toHaveBeenCalledOnce();
  });

  it("calls escape handler on Escape", () => {
    const escape = vi.fn();
    renderHook(() => useHotkeys({ escape }));
    fireKey("Escape");
    expect(escape).toHaveBeenCalledOnce();
  });

  it("does NOT fire hotkeys when input has focus", () => {
    const filter = vi.fn();
    const input = document.createElement("input");
    document.body.appendChild(input);
    input.focus();

    renderHook(() => useHotkeys({ filter }));
    fireKey("f");
    expect(filter).not.toHaveBeenCalled();

    document.body.removeChild(input);
  });

  it("DOES fire Escape even when input has focus", () => {
    const escape = vi.fn();
    const input = document.createElement("input");
    document.body.appendChild(input);
    input.focus();

    renderHook(() => useHotkeys({ escape }));
    fireKey("Escape");
    expect(escape).toHaveBeenCalledOnce();

    document.body.removeChild(input);
  });

  it("does NOT fire hotkeys when modifier keys are held", () => {
    const filter = vi.fn();
    renderHook(() => useHotkeys({ filter }));
    fireKey("f", { ctrlKey: true });
    fireKey("f", { metaKey: true });
    expect(filter).not.toHaveBeenCalled();
  });

  it("unbinds listener on unmount", () => {
    const filter = vi.fn();
    const { unmount } = renderHook(() => useHotkeys({ filter }));
    unmount();
    fireKey("f");
    expect(filter).not.toHaveBeenCalled();
  });
});
