import { useMemo, useCallback } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  type Node,
  type Edge,
  type NodeTypes,
  type Connection,
  MarkerType,
  BackgroundVariant,
  Position,
  ReactFlowProvider,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import StepNode, {
  STEP_NODE_ESTIMATED_HEIGHT,
  STEP_NODE_WIDTH,
  type StepNodeData,
} from "./StepNode";
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
  /** Callback when an edge is clicked (id is "source->target"). */
  onEdgeClick?: (edgeId: string) => void;
  /**
   * Callback when the user draws a new connection between node handles.
   * Providing this makes nodes connectable (editor mode).
   */
  onConnect?: (source: string, target: string) => void;
  /** Highlight this node as the current selection (editor mode). */
  selectedNodeId?: string | null;
  /** Highlight this edge ("source->target") as the current selection. */
  selectedEdgeId?: string | null;
  /** Show declarative edge labels (what data flows along each edge). */
  showEdgeLabels?: boolean;
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
  onEdgeClick,
  onConnect,
  selectedNodeId = null,
  selectedEdgeId = null,
  showEdgeLabels = false,
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
        persona: dn.persona ?? null,
        model: dn.model ?? null,
        status: live?.status ?? "pending",
        startTime: live?.startTime,
        durationMs: live?.durationMs,
        modelUsed: live?.modelUsed,
        tokensUsed: live?.tokensUsed,
        modelInferred: live?.modelInferred,
        error: live?.error,
        disconnected,
        selected: dn.id === selectedNodeId,
      };

      return {
        id: dn.id,
        type: "step" as const,
        position: { x: pos?.x ?? 0, y: pos?.y ?? 0 },
        // Pre-measure dimension hints: without them @xyflow/react keeps
        // nodes visibility:hidden until a ResizeObserver/rAF measurement
        // cycle completes, which throttled headless CI runners can starve
        // indefinitely (nodes present in the DOM but hidden for the whole
        // assertion window — the PR #203 e2e flake). Real measurements
        // replace the estimated height as soon as the cycle does run.
        initialWidth: STEP_NODE_WIDTH,
        initialHeight: STEP_NODE_ESTIMATED_HEIGHT,
        // Pre-measure handle geometry (same SSR contract): edges only draw
        // from measured handle bounds unless these are supplied, so without
        // them the degraded window renders disconnected nodes. Mirrors
        // StepNode's actual handles: 6x6, target top-center, source
        // bottom-center.
        handles: [
          {
            type: "target" as const,
            position: Position.Top,
            x: STEP_NODE_WIDTH / 2 - 3,
            y: -3,
            width: 6,
            height: 6,
          },
          {
            type: "source" as const,
            position: Position.Bottom,
            x: STEP_NODE_WIDTH / 2 - 3,
            y: STEP_NODE_ESTIMATED_HEIGHT - 3,
            width: 6,
            height: 6,
          },
        ],
        data: data as unknown as Record<string, unknown>,
      };
    });
  }, [dagNodes, positions, effectiveStepStates, disconnected, selectedNodeId]);

  const edges: Edge[] = useMemo(() => {
    return dagEdges.map((de) => {
      const edgeId = de.id ?? `${de.source}->${de.target}`;
      const sourceState = effectiveStepStates.get(de.source);
      const targetState = effectiveStepStates.get(de.target);
      const traversalCount = edgeCounts?.get(edgeId) ?? 0;
      const isKickback = kickbackEdges?.has(edgeId) ?? false;
      const isSelected = edgeId === selectedEdgeId;

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
      if (isSelected) {
        strokeColor = "rgb(var(--b-clay))";
      }

      // Traversal counts (live view) win over declarative labels (editor view).
      let label: string | undefined;
      if (traversalCount > 0) {
        label = String(traversalCount);
      } else if (showEdgeLabels) {
        label = de.label ?? "order";
      }

      return {
        id: edgeId,
        source: de.source,
        target: de.target,
        type: "smoothstep" as const,
        animated,
        className: isActiveEdge ? "dag-edge--active" : undefined,
        label,
        labelStyle: {
          fill: isKickback ? "#be95ff" : "#c6c6c6",
          fontSize: traversalCount > 0 ? 11 : 9,
          fontWeight: 600,
        },
        labelBgStyle: {
          fill: isKickback ? "rgba(88, 28, 135, 0.75)" : "rgba(17, 24, 39, 0.75)",
          fillOpacity: 1,
        },
        labelBgPadding: [6, 2] as [number, number],
        labelBgBorderRadius: 4,
        style: {
          stroke: strokeColor,
          strokeWidth: isSelected ? 2 : 1,
          strokeDasharray,
        },
        markerEnd: {
          type: MarkerType.ArrowClosed,
          color: strokeColor,
          width: 14,
          height: 14,
        },
      };
    });
  }, [
    dagEdges,
    edgeCounts,
    kickbackEdges,
    effectiveStepStates,
    disconnected,
    selectedEdgeId,
    showEdgeLabels,
  ]);

  const handleNodeClick = useCallback(
    (_: React.MouseEvent, node: Node) => {
      onNodeClick?.(node.id);
    },
    [onNodeClick]
  );

  const handleEdgeClick = useCallback(
    (_: React.MouseEvent, edge: Edge) => {
      onEdgeClick?.(edge.id);
    },
    [onEdgeClick]
  );

  const handleConnect = useCallback(
    (connection: Connection) => {
      if (connection.source && connection.target) {
        onConnect?.(connection.source, connection.target);
      }
    },
    [onConnect]
  );

  return (
    <div className={`h-full w-full ${className}`}>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        onNodeClick={handleNodeClick}
        onEdgeClick={onEdgeClick ? handleEdgeClick : undefined}
        onConnect={onConnect ? handleConnect : undefined}
        nodesConnectable={Boolean(onConnect)}
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
