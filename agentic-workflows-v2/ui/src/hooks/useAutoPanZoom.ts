import { useCallback, useEffect, useRef } from "react";
import { useReactFlow } from "@xyflow/react";

/**
 * Per-node auto-follow only engages above this node count. Smaller graphs fit
 * on screen whole, so chasing a single running node just yanks the view around
 * for no benefit.
 *
 * This threshold is the primary UX knob for the feature. Tune it here, or swap
 * the whole policy in {@link isLargeWorkflow} (e.g. compare laid-out bounds to
 * the viewport instead of counting nodes).
 */
export const LARGE_WORKFLOW_NODE_THRESHOLD = 6;

/**
 * Whether a workflow is large enough that the viewport should actively follow
 * the running step(s) during execution.
 */
export function isLargeWorkflow(nodeCount: number): boolean {
  return nodeCount > LARGE_WORKFLOW_NODE_THRESHOLD;
}

/** Hand auto-follow back this long after the user's last manual pan/zoom. */
const INACTIVITY_RESUME_MS = 3000;
/** Coalesce near-simultaneous step starts before panning. */
const FOLLOW_COALESCE_MS = 150;
/** fitView animation duration when motion is allowed. */
const FOLLOW_DURATION_MS = 800;

const FIT_ALL_PADDING = 0.15;
const SINGLE_NODE_PADDING = 0.35;
const MULTI_NODE_PADDING = 0.2;
const FOLLOW_MIN_ZOOM = 0.8;
const FOLLOW_MAX_ZOOM = 1.15;

interface AutoPanZoomArgs {
  /** ids of steps currently running — the follow target. */
  runningStepIds: string[];
  /** true once no step is pending or running. */
  allDone: boolean;
  /** total nodes in the graph; drives the large-workflow gate. */
  nodeCount: number;
  /** when true, pans are instant rather than animated. */
  reducedMotion?: boolean;
}

export interface AutoPanZoomHandlers {
  onMoveStart: (event: MouseEvent | TouchEvent | null) => void;
  onMoveEnd: (event: MouseEvent | TouchEvent | null) => void;
}

function sortedKey(ids: string[]): string {
  return [...ids].sort((a, b) => a.localeCompare(b)).join(",");
}

/**
 * Drives "follow the running step" auto pan/zoom on a ReactFlow canvas while
 * yielding to manual navigation: any manual pan/zoom takes control, and control
 * is handed back {@link INACTIVITY_RESUME_MS} after the user stops interacting.
 *
 * Returns ReactFlow `onMoveStart` / `onMoveEnd` handlers to spread onto the
 * `<ReactFlow>` element. Must be called inside a `ReactFlowProvider`.
 */
export function useAutoPanZoom({
  runningStepIds,
  allDone,
  nodeCount,
  reducedMotion = false,
}: AutoPanZoomArgs): AutoPanZoomHandlers {
  const { fitView } = useReactFlow();

  const userControllingRef = useRef(false);
  const resumeTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const coalesceTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Key of the running set we have most recently *applied* (panned to). Used to
  // skip a redundant pan when the running set is unchanged.
  const followedKeyRef = useRef<string | null>(null);
  // Guards the completion fit-all so it fires once per completion.
  const completedFitRef = useRef(false);

  // Stable, primitive follow target. Depending on this (rather than the
  // runningStepIds array reference) means the follow effect re-runs only when
  // the running set actually changes — not on every parent re-render — so the
  // coalesce timer is never reset out from under itself during a render storm.
  const runningKey = sortedKey(runningStepIds);

  // Snapshot the latest inputs so deferred timers read fresh values, not the
  // values captured when the timer was scheduled.
  const latestRef = useRef({ runningStepIds, allDone, nodeCount, reducedMotion });
  latestRef.current = { runningStepIds, allDone, nodeCount, reducedMotion };

  const followNow = useCallback(() => {
    const {
      runningStepIds: ids,
      allDone: done,
      nodeCount: count,
      reducedMotion: reduced,
    } = latestRef.current;
    const duration = reduced ? 0 : FOLLOW_DURATION_MS;

    if (done) {
      followedKeyRef.current = null;
      void fitView({ padding: FIT_ALL_PADDING, duration });
      return;
    }
    if (!isLargeWorkflow(count) || ids.length === 0) return;
    followedKeyRef.current = sortedKey(ids);
    void fitView({
      nodes: ids.map((id) => ({ id })),
      duration,
      padding: ids.length === 1 ? SINGLE_NODE_PADDING : MULTI_NODE_PADDING,
      minZoom: FOLLOW_MIN_ZOOM,
      maxZoom: FOLLOW_MAX_ZOOM,
    });
  }, [fitView]);

  // Follow the running step(s) as the set changes — unless the user is in
  // control or the workflow is small enough to fit on screen whole.
  useEffect(() => {
    if (!runningKey || runningKey === followedKeyRef.current) return;
    if (userControllingRef.current || !isLargeWorkflow(nodeCount)) return;

    if (coalesceTimerRef.current) clearTimeout(coalesceTimerRef.current);
    coalesceTimerRef.current = setTimeout(() => {
      if (!userControllingRef.current) followNow();
    }, FOLLOW_COALESCE_MS);

    return () => {
      if (coalesceTimerRef.current) clearTimeout(coalesceTimerRef.current);
    };
  }, [runningKey, nodeCount, followNow]);

  // Frame the whole graph once the run completes — for every workflow size, not
  // just large ones. Skipped while the user is actively panning; the resume
  // timer re-attempts the fit once they yield control.
  useEffect(() => {
    if (!allDone) {
      completedFitRef.current = false;
      return;
    }
    if (completedFitRef.current || userControllingRef.current) return;
    completedFitRef.current = true;
    followNow();
  }, [allDone, followNow]);

  // Manual pan/zoom begins — the user takes control.
  const onMoveStart = useCallback((event: MouseEvent | TouchEvent | null) => {
    if (!event) return; // programmatic pan (fitView) sends a null event
    userControllingRef.current = true;
    if (resumeTimerRef.current) clearTimeout(resumeTimerRef.current);
  }, []);

  // Manual pan/zoom ends — hand control back after a quiet period.
  const onMoveEnd = useCallback(
    (event: MouseEvent | TouchEvent | null) => {
      if (!event) return; // programmatic pan (fitView) sends a null event
      if (resumeTimerRef.current) clearTimeout(resumeTimerRef.current);
      resumeTimerRef.current = setTimeout(() => {
        userControllingRef.current = false;
        // Don't force-reset the viewport after the run completes — the user
        // may be panning around to inspect finished nodes. Only resume
        // auto-following while there is still live execution to track.
        if (!latestRef.current.allDone || !completedFitRef.current) {
          followNow();
        }
      }, INACTIVITY_RESUME_MS);
    },
    [followNow]
  );

  // Clear any pending timers on unmount.
  useEffect(() => {
    return () => {
      if (resumeTimerRef.current) clearTimeout(resumeTimerRef.current);
      if (coalesceTimerRef.current) clearTimeout(coalesceTimerRef.current);
    };
  }, []);

  return { onMoveStart, onMoveEnd };
}
