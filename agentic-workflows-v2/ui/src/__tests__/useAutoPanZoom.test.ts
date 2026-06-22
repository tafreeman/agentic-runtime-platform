import { renderHook, act } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  useAutoPanZoom,
  isLargeWorkflow,
  LARGE_WORKFLOW_NODE_THRESHOLD,
} from "../hooks/useAutoPanZoom";

const { fitView } = vi.hoisted(() => ({ fitView: vi.fn() }));

vi.mock("@xyflow/react", () => ({
  useReactFlow: () => ({ fitView }),
}));

interface Args {
  runningStepIds: string[];
  allDone: boolean;
  nodeCount: number;
  reducedMotion?: boolean;
}

const LARGE = 20;
const SMALL = 3;
const base: Args = {
  runningStepIds: [],
  allDone: false,
  nodeCount: LARGE,
  reducedMotion: false,
};

beforeEach(() => {
  vi.useFakeTimers();
  fitView.mockClear();
});

afterEach(() => {
  vi.runOnlyPendingTimers();
  vi.useRealTimers();
});

describe("isLargeWorkflow", () => {
  it("classifies workflows by node count", () => {
    expect(isLargeWorkflow(LARGE_WORKFLOW_NODE_THRESHOLD)).toBe(false);
    expect(isLargeWorkflow(LARGE_WORKFLOW_NODE_THRESHOLD + 1)).toBe(true);
  });
});

describe("useAutoPanZoom", () => {
  it("pans to the running step on a large workflow after the coalesce delay", () => {
    const { rerender } = renderHook((p: Args) => useAutoPanZoom(p), {
      initialProps: base,
    });

    rerender({ ...base, runningStepIds: ["b"] });
    expect(fitView).not.toHaveBeenCalled();

    act(() => {
      vi.advanceTimersByTime(150);
    });
    expect(fitView).toHaveBeenCalledWith(
      expect.objectContaining({ nodes: [{ id: "b" }] })
    );
  });

  it("follows multiple concurrent running steps with multi-node padding", () => {
    const { rerender } = renderHook((p: Args) => useAutoPanZoom(p), {
      initialProps: base,
    });

    rerender({ ...base, runningStepIds: ["b", "a"] });
    act(() => {
      vi.advanceTimersByTime(150);
    });

    expect(fitView).toHaveBeenCalledTimes(1);
    expect(fitView).toHaveBeenCalledWith(
      expect.objectContaining({
        padding: 0.2,
        nodes: expect.arrayContaining([{ id: "a" }, { id: "b" }]),
      })
    );
  });

  it("does not re-pan when the running set is unchanged across re-renders", () => {
    const running: Args = { ...base, runningStepIds: ["b"] };
    const { rerender } = renderHook((p: Args) => useAutoPanZoom(p), {
      initialProps: running,
    });

    act(() => {
      vi.advanceTimersByTime(150);
    });
    expect(fitView).toHaveBeenCalledTimes(1);
    fitView.mockClear();

    // Fresh array, identical ids — must not trigger a second pan.
    rerender({ ...base, runningStepIds: ["b"] });
    act(() => {
      vi.advanceTimersByTime(300);
    });
    expect(fitView).not.toHaveBeenCalled();
  });

  it("keeps following when re-rendered rapidly with unchanged running ids", () => {
    // Regression lock: depending on a stable key (not the array reference) means
    // a render storm with unchanged ids must NOT starve the coalesce timer.
    const running: Args = { ...base, runningStepIds: ["b"] };
    const { rerender } = renderHook((p: Args) => useAutoPanZoom(p), {
      initialProps: running,
    });

    for (let i = 0; i < 5; i++) {
      rerender({ ...base, runningStepIds: ["b"] }); // new array, same id, each tick
      act(() => {
        vi.advanceTimersByTime(100);
      });
    }

    expect(fitView).toHaveBeenCalled();
  });

  it("does not auto-follow a small workflow during execution", () => {
    const small: Args = { ...base, nodeCount: SMALL };
    const { rerender } = renderHook((p: Args) => useAutoPanZoom(p), {
      initialProps: small,
    });

    rerender({ ...small, runningStepIds: ["b"] });
    act(() => {
      vi.advanceTimersByTime(500);
    });
    expect(fitView).not.toHaveBeenCalled();
  });

  it("fits the whole graph on completion even for a small workflow", () => {
    const small: Args = { ...base, nodeCount: SMALL, runningStepIds: ["b"] };
    const { rerender } = renderHook((p: Args) => useAutoPanZoom(p), {
      initialProps: small,
    });

    act(() => {
      vi.advanceTimersByTime(200);
    });
    expect(fitView).not.toHaveBeenCalled(); // never followed per-node
    fitView.mockClear();

    rerender({ ...small, runningStepIds: [], allDone: true });
    expect(fitView).toHaveBeenCalledWith(
      expect.objectContaining({ padding: 0.15 })
    );
  });

  it("suspends auto-follow while the user is panning", () => {
    const { result, rerender } = renderHook((p: Args) => useAutoPanZoom(p), {
      initialProps: base,
    });

    act(() => {
      result.current.onMoveStart({} as MouseEvent);
    });
    rerender({ ...base, runningStepIds: ["b"] });
    act(() => {
      vi.advanceTimersByTime(500);
    });
    expect(fitView).not.toHaveBeenCalled();
  });

  it("resumes auto-follow 3s after the last manual move", () => {
    const running: Args = { ...base, runningStepIds: ["b"] };
    const { result } = renderHook((p: Args) => useAutoPanZoom(p), {
      initialProps: running,
    });

    act(() => {
      vi.advanceTimersByTime(150);
    });
    fitView.mockClear();

    act(() => {
      result.current.onMoveStart({} as MouseEvent);
      result.current.onMoveEnd({} as MouseEvent);
    });

    act(() => {
      vi.advanceTimersByTime(2999);
    });
    expect(fitView).not.toHaveBeenCalled();

    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(fitView).toHaveBeenCalledWith(
      expect.objectContaining({ nodes: [{ id: "b" }] })
    );
  });

  it("ignores programmatic moves (null event)", () => {
    const running: Args = { ...base, runningStepIds: ["b"] };
    const { result } = renderHook((p: Args) => useAutoPanZoom(p), {
      initialProps: running,
    });

    act(() => {
      vi.advanceTimersByTime(150);
    });
    fitView.mockClear();

    act(() => {
      result.current.onMoveStart(null);
      result.current.onMoveEnd(null);
      vi.advanceTimersByTime(3000);
    });
    expect(fitView).not.toHaveBeenCalled();
  });

  it("frames the whole graph on completion", () => {
    const running: Args = { ...base, runningStepIds: ["b"] };
    const { rerender } = renderHook((p: Args) => useAutoPanZoom(p), {
      initialProps: running,
    });

    act(() => {
      vi.advanceTimersByTime(150);
    });
    fitView.mockClear();

    rerender({ ...base, runningStepIds: [], allDone: true });
    expect(fitView).toHaveBeenCalledWith(
      expect.objectContaining({ padding: 0.15 })
    );
  });

  it("does not fit-all on completion while the user is panning", () => {
    const running: Args = { ...base, runningStepIds: ["b"] };
    const { result, rerender } = renderHook((p: Args) => useAutoPanZoom(p), {
      initialProps: running,
    });

    act(() => {
      vi.advanceTimersByTime(150);
    });
    fitView.mockClear();

    act(() => {
      result.current.onMoveStart({} as MouseEvent); // user takes over
    });
    rerender({ ...base, runningStepIds: [], allDone: true });
    expect(fitView).not.toHaveBeenCalled(); // manual control wins
  });

  it("uses zero animation duration when reduced motion is preferred", () => {
    const reduced: Args = { ...base, reducedMotion: true };
    const { rerender } = renderHook((p: Args) => useAutoPanZoom(p), {
      initialProps: reduced,
    });

    rerender({ ...reduced, runningStepIds: ["b"] });
    act(() => {
      vi.advanceTimersByTime(150);
    });
    expect(fitView).toHaveBeenCalledWith(
      expect.objectContaining({ duration: 0 })
    );
  });

  it("clears timers on unmount", () => {
    const running: Args = { ...base, runningStepIds: ["b"] };
    const { result, unmount } = renderHook((p: Args) => useAutoPanZoom(p), {
      initialProps: running,
    });

    act(() => {
      result.current.onMoveStart({} as MouseEvent);
      result.current.onMoveEnd({} as MouseEvent);
    });
    unmount();
    fitView.mockClear();

    act(() => {
      vi.advanceTimersByTime(5000);
    });
    expect(fitView).not.toHaveBeenCalled();
  });
});
