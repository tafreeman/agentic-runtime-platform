import { useMemo, useCallback, useEffect, useRef } from "react";
import {
  ReactFlow,
  Background,
  Controls,
  type Node,
  type Edge,
  type NodeTypes,
  MarkerType,
  BackgroundVariant,
  useReactFlow,
  ReactFlowProvider,
} from "@xyflow/react";
import "@xyflow/react/dist/style.css";

import StepNode, { type StepNodeData } from "./StepNode";
import { layoutDAG } from "./dagLayout";
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

/* ── Inner component (has access to useReactFlow) ── */
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
  const { fitView } = useReactFlow();
  const prevRunningStrRef = useRef<string | null>(null);
  const userInteractedRef = useRef(false);
  const interactionCountRef = useRef(0);
  const interactionTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  const positions = useMemo(
    () => layoutDAG(dagNodes, dagEdges),
    [dagNodes, dagEdges]
  );

  const effectiveStepStates = useMemo(() => {
    const eff = new Map<string, StepLiveState>();
    if (!stepStates) return eff;
    
    // Start by copying all known states
    for (const [id, st] of stepStates) {
      eff.set(id, st);
    }
    
    const workflowStarted = stepStates.size > 0;
    
    // Check if we're technically all done with known states
    let allDone = true;
    for (const st of stepStates.values()) {
      if (st.status === "pending" || st.status === "running") {
        allDone = false;
        break;
      }
    }

    // Apply optimistic running status if workflow is running
    if (workflowStarted && !allDone) {
      for (const dn of dagNodes) {
        const currentLive = stepStates.get(dn.id);
        const currentStatus = currentLive?.status ?? "pending";
        
        if (currentStatus === "pending") {
          const depsResolved = dn.depends_on.every(depId => {
            const ds = stepStates.get(depId)?.status;
            return ds === "success" || ds === "skipped";
          });
          
          if (depsResolved) {
            eff.set(dn.id, {
              ...currentLive,
              status: "running",
            });
          }
        }
      }
    }
    return eff;
  }, [stepStates, dagNodes]);

  // Find all currently-running steps
  const runningStepIds = useMemo(() => {
    const ids: string[] = [];
    for (const [id, state] of effectiveStepStates) {
      if (state.status === "running") ids.push(id);
    }
    return ids;
  }, [effectiveStepStates]);

  // Auto-pan / fitView to the running node(s) when changed
  useEffect(() => {
    const runningStr = [...runningStepIds].sort().join(",");
    if (!runningStr || runningStr === prevRunningStrRef.current) return;
    if (userInteractedRef.current) return; // respect manual navigation

    prevRunningStrRef.current = runningStr;

    // Small delay provides visual grace if multiple nodes start simultaneously
    const timerId = setTimeout(() => {
      if (userInteractedRef.current) return;
      fitView({
        nodes: runningStepIds.map((id) => ({ id })),
        duration: 800,
        padding: runningStepIds.length === 1 ? 0.35 : 0.2,
        minZoom: 0.8,
        maxZoom: 1.15,
      });
    }, 150);

    return () => clearTimeout(timerId);
  }, [runningStepIds, fitView]);

  // When workflow completes (no running step and we had one before), zoom to fit all
  const allDone = useMemo(() => {
    if (effectiveStepStates.size === 0) return false;
    for (const [, state] of effectiveStepStates) {
      if (state.status === "running" || state.status === "pending") return false;
    }
    return true;
  }, [effectiveStepStates]);

  useEffect(() => {
    if (allDone && prevRunningStrRef.current) {
      prevRunningStrRef.current = null;
      userInteractedRef.current = false;
      fitView({ padding: 0.15, duration: 800 });
    }
  }, [allDone, fitView]);

  // Track user interaction — pause auto-pan for 5s after multiple manual moves
  const handleMoveEnd = useCallback((event: any) => {
    // Only flag manual user interactions.
    // Programmatic pans (via fitView/setCenter) send null/undefined events
    if (!event) return;

    interactionCountRef.current += 1;

    // Require more than one interaction event within a short window to take over
    if (interactionCountRef.current >= 2) {
      userInteractedRef.current = true;
    }

    if (interactionTimerRef.current) clearTimeout(interactionTimerRef.current);
    
    // If they successfully took over, pause auto-pan for 5s.
    // If it was just an accidental single click/move, reset the counter after 2s.
    const timeoutDuration = userInteractedRef.current ? 5000 : 2000;
    
    interactionTimerRef.current = setTimeout(() => {
      userInteractedRef.current = false;
      interactionCountRef.current = 0;
    }, timeoutDuration);
  }, []);

  // Clear any pending interaction timeout on unmount
  useEffect(() => {
    return () => {
      if (interactionTimerRef.current) {
        clearTimeout(interactionTimerRef.current);
        interactionTimerRef.current = null;
      }
    };
  }, []);

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

      // Design token colors
      let strokeColor = "#2c2c36"; // b-bg2 — pending/dark
      let animated = false;
      let strokeDasharray: string | undefined;
      const isActiveEdge =
        sourceState?.status === "success" &&
        targetState?.status === "running" &&
        !disconnected;

      if (isKickback && traversalCount > 0) {
        strokeColor = "#c084fc"; // b-purple
        strokeDasharray = "3 3";
      } else if (sourceState?.status === "success" && targetState?.status === "running" && !disconnected) {
        strokeColor = "#d97757"; // b-clay — active/running edge
        animated = true;
      } else if (sourceState?.status === "success") {
        strokeColor = "#4ade80"; // b-green — completed
      } else if (sourceState?.status === "running") {
        strokeColor = "#d97757"; // b-clay — running source
      } else if (sourceState?.status === "failed") {
        strokeColor = "rgba(248,113,113,0.5)"; // b-red faint
      } else if (!sourceState || sourceState.status === "pending") {
        strokeColor = "#2c2c36"; // dark — not yet reached
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
        onMoveEnd={handleMoveEnd}
        fitView
        fitViewOptions={{ padding: 0.2 }}
        proOptions={{ hideAttribution: true }}
        minZoom={0.2}
        maxZoom={2.0}
      >
        <Background variant={BackgroundVariant.Dots} gap={20} size={1} color="#1a1a28" />
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
