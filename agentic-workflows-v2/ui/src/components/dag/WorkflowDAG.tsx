import { useMemo, useCallback } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  type Node,
  type Edge,
  type NodeTypes,
  MarkerType,
  BackgroundVariant,
  ReactFlowProvider,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import StepNode, { type StepNodeData } from "./StepNode";
import { layoutDAG } from "./dagLayout";
import { useAutoPanZoom } from "../../hooks/useAutoPanZoom";
import { usePrefersReducedMotion } from "../../hooks/usePrefersReducedMotion";
import type { DAGNode, DAGEdge, StepStatus } from "../../api/types";

const nodeTypes: NodeTypes = {
  step: StepNode,
};

interface StepLiveState {
  status: StepStatus;
  startTime?: string;
  durationMs?: number;
  modelUsed?: string;
  tokensUsed?: number;
  modelInferred?: boolean;
  error?: string | null;
}

/** True when no known step is still pending or running. */
function areAllStepsDone(stepStates: Map<string, StepLiveState>): boolean {
  for (const st of stepStates.values()) {
    if (st.status === "pending" || st.status === "running") {
      return false;
    }
  }
  return true;
}

/** A pending step becomes optimistically "running" once all its deps resolve. */
function shouldOptimisticallyRun(
  node: DAGNode,
  stepStates: Map<string, StepLiveState>
): boolean {
  const currentStatus = stepStates.get(node.id)?.status ?? "pending";
  if (currentStatus !== "pending") return false;
  return node.depends_on.every((depId) => {
    const ds = stepStates.get(depId)?.status;
    return ds === "success" || ds === "skipped";
  });
}

/**
 * Layer optimistic "running" status onto pending nodes whose dependencies have
 * all resolved, while the workflow is still in flight. Returns a new map.
 */
function computeEffectiveStepStates(
  stepStates: Map<string, StepLiveState> | undefined,
  dagNodes: DAGNode[]
): Map<string, StepLiveState> {
  const eff = new Map<string, StepLiveState>();
  if (!stepStates) return eff;

  // Start by copying all known states
  for (const [id, st] of stepStates) {
    eff.set(id, st);
  }

  const workflowStarted = stepStates.size > 0;
  const allDone = areAllStepsDone(stepStates);

  // Apply optimistic running status if workflow is running
  if (workflowStarted && !allDone) {
    for (const dn of dagNodes) {
      if (shouldOptimisticallyRun(dn, stepStates)) {
        eff.set(dn.id, {
          ...stepStates.get(dn.id),
          status: "running",
        });
      }
    }
  }
  return eff;
}

interface Props {
  dagNodes: DAGNode[];
  dagEdges: DAGEdge[];
  /** Live state overrides per step name. */
  stepStates?: Map<string, StepLiveState>;
  /** Optional traversal counts keyed by "source->target". */
  edgeCounts?: Map<string, number>;
  /** Optional set of kickback/rework edges keyed by "source->target". */
  kickbackEdges?: Set<string>;
  /** Callback when a node is clicked. */
  onNodeClick?: (stepName: string) => void;
  /**
   * When true, the upstream WebSocket stream is disconnected. Live
   * animations on running nodes/edges are paused to signal that on-screen
   * state may not match the backend.
   */
  disconnected?: boolean;
  className?: string;
}

/* ── Inner component (rendered inside ReactFlowProvider) ── */
function WorkflowDAGInner({
  dagNodes,
  dagEdges,
  stepStates,
  edgeCounts,
  kickbackEdges,
  onNodeClick,
  disconnected = false,
  className = "",
}: Readonly<Props>) {
  const reducedMotion = usePrefersReducedMotion();

  const positions = useMemo(
    () => layoutDAG(dagNodes, dagEdges),
    [dagNodes, dagEdges]
  );

  const effectiveStepStates = useMemo(
    () => computeEffectiveStepStates(stepStates, dagNodes),
    [stepStates, dagNodes]
  );

  // Find all currently-running steps
  const runningStepIds = useMemo(() => {
    const ids: string[] = [];
    for (const [id, state] of effectiveStepStates) {
      if (state.status === "running") ids.push(id);
    }
    return ids;
  }, [effectiveStepStates]);

  // True once no known step is still pending or running.
  const allDone = useMemo(() => {
    if (effectiveStepStates.size === 0) return false;
    for (const [, state] of effectiveStepStates) {
      if (state.status === "running" || state.status === "pending") return false;
    }
    return true;
  }, [effectiveStepStates]);

  // Auto pan/zoom: follow execution on large workflows, yield to manual
  // pan/zoom, and resume ~3s after the user stops interacting.
  const { onMoveStart, onMoveEnd } = useAutoPanZoom({
    runningStepIds,
    allDone,
    nodeCount: dagNodes.length,
    reducedMotion,
  });

  const nodes = useMemo(() => {
    return dagNodes.map((dn) => {
      const pos = positions.find((p) => p.id === dn.id);
      const live = effectiveStepStates.get(dn.id);

      const data: StepNodeData = {
        label: dn.id,
        agent: dn.agent ?? null,
        description: dn.description ?? "",
        tier: dn.tier ?? null,
        status: live?.status ?? "pending",
        startTime: live?.startTime,
        durationMs: live?.durationMs,
        modelUsed: live?.modelUsed,
        tokensUsed: live?.tokensUsed,
        modelInferred: live?.modelInferred,
        error: live?.error,
        disconnected,
      };

      return {
        id: dn.id,
        type: "step" as const,
        position: { x: pos?.x ?? 0, y: pos?.y ?? 0 },
        data: data as unknown as Record<string, unknown>,
      };
    });
  }, [dagNodes, positions, effectiveStepStates, disconnected]);

  const edges: Edge[] = useMemo(() => {
    return dagEdges.map((de) => {
      const edgeId = `${de.source}->${de.target}`;
      const sourceState = effectiveStepStates.get(de.source);
      const targetState = effectiveStepStates.get(de.target);
      const traversalCount = edgeCounts?.get(edgeId) ?? 0;
      const isKickback = kickbackEdges?.has(edgeId) ?? false;

      // Theme-aware design-token colors (CSS vars resolve per active theme).
      const defaultColor = "rgb(var(--b-line))"; // pending/idle edge
      let strokeColor = defaultColor;
      let animated = false;
      let strokeDasharray: string | undefined;
      const isActiveEdge =
        sourceState?.status === "success" &&
        targetState?.status === "running" &&
        !disconnected;

      if (isKickback && traversalCount > 0) {
        strokeColor = "rgb(var(--b-purple))";
        strokeDasharray = "3 3";
      } else if (sourceState?.status === "success" && targetState?.status === "running" && !disconnected) {
        animated = true;
      } else if (sourceState?.status === "success") {
        strokeColor = "rgb(var(--b-green))"; // completed
      } else if (sourceState?.status === "running") {
        strokeColor = "rgb(var(--b-clay))"; // running source
      } else if (sourceState?.status === "failed") {
        strokeColor = "rgb(var(--b-red) / 0.5)"; // failed source, faint
      }

      return {
        id: edgeId,
        source: de.source,
        target: de.target,
        type: "smoothstep" as const,
        animated,
        className: isActiveEdge ? "dag-edge--active" : undefined,
        label: traversalCount > 0 ? String(traversalCount) : undefined,
        labelStyle: {
          fill: isKickback ? "#e9d5ff" : "#d1d5db",
          fontSize: 11,
          fontWeight: 600,
        },
        labelBgStyle: {
          fill: isKickback ? "rgba(88, 28, 135, 0.75)" : "rgba(17, 24, 39, 0.75)",
          fillOpacity: 1,
        },
        labelBgPadding: [6, 2],
        labelBgBorderRadius: 4,
        style: { stroke: strokeColor, strokeWidth: 1, strokeDasharray },
        markerEnd: {
          type: MarkerType.ArrowClosed,
          color: strokeColor,
          width: 14,
          height: 14,
        },
      };
    });
  }, [dagEdges, edgeCounts, kickbackEdges, effectiveStepStates, disconnected]);

  const handleNodeClick = useCallback(
    (_: React.MouseEvent, node: Node) => {
      onNodeClick?.(node.id);
    },
    [onNodeClick]
  );

  return (
    <div className={`h-full w-full ${className}`}>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        onNodeClick={handleNodeClick}
        onMoveStart={onMoveStart}
        onMoveEnd={onMoveEnd}
        fitView
        fitViewOptions={{ padding: 0.2 }}
        proOptions={{ hideAttribution: true }}
        minZoom={0.2}
        maxZoom={2}
      >
        <Background
          variant={BackgroundVariant.Dots}
          gap={20}
          size={1}
          color="rgb(var(--b-line-soft))"
        />
        <Controls showInteractive={false} className="dag-controls" />
      </ReactFlow>
    </div>
  );
}

/* ── Wrapper providing ReactFlowProvider ── */
export default function WorkflowDAG(props: Readonly<Props>) {
  return (
    <ReactFlowProvider>
      <WorkflowDAGInner {...props} />
    </ReactFlowProvider>
  );
}
