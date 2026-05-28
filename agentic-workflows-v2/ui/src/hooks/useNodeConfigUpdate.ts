import { useCallback, useEffect, useRef } from "react";

interface NodeConfig {
  model?: string;
  system_prompt?: string;
  temperature?: number;
  max_tokens?: number;
  top_p?: number;
  tool_names?: string[];
}

interface UseNodeConfigUpdateOptions {
  runId: string | null;
}

/**
 * Hook for sending node configuration updates to the backend via WebSocket.
 * Uses relative WebSocket URL so Vite proxy can forward to backend.
 */
export function useNodeConfigUpdate({ runId }: UseNodeConfigUpdateOptions) {
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Initialize WebSocket connection
  useEffect(() => {
    if (!runId) return;

    const connectWs = () => {
      try {
        // Use relative URL so Vite proxy can forward it through /ws
        // When in dev: ws://localhost:5174/ws/execution/{runId}
        // Vite proxy rewrites to: ws://localhost:8012/ws/execution/{runId}
        const wsUrl = `/ws/execution/${runId}`;
        const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
        const fullUrl = `${protocol}//${window.location.host}${wsUrl}`;
        
        wsRef.current = new WebSocket(fullUrl);

        wsRef.current.onopen = () => {
          console.log("WebSocket connected for node config updates");
          // Clear any pending reconnect timeout
          if (reconnectTimeoutRef.current) {
            clearTimeout(reconnectTimeoutRef.current);
            reconnectTimeoutRef.current = null;
          }
        };

        wsRef.current.onerror = (error) => {
          console.error("WebSocket error:", error);
        };

        wsRef.current.onclose = () => {
          console.log("WebSocket closed, will attempt reconnect in 3s");
          // Attempt reconnect after 3 seconds
          reconnectTimeoutRef.current = setTimeout(() => {
            connectWs();
          }, 3000);
        };
      } catch (error) {
        console.error("Failed to connect WebSocket:", error);
      }
    };

    connectWs();

    return () => {
      if (wsRef.current) {
        wsRef.current.close();
      }
      if (reconnectTimeoutRef.current) {
        clearTimeout(reconnectTimeoutRef.current);
      }
    };
  }, [runId]);

  const updateNodeConfig = useCallback(
    (stepName: string, config: NodeConfig) => {
      if (!wsRef.current || wsRef.current.readyState !== WebSocket.OPEN) {
        console.warn("WebSocket not connected, cannot send config update");
        return;
      }

      const message = {
        type: "node_config_update",
        step_name: stepName,
        config,
      };

      try {
        wsRef.current.send(JSON.stringify(message));
        console.log(`Sent config update for ${stepName}:`, config);
      } catch (error) {
        console.error("Failed to send config update:", error);
      }
    },
    []
  );

  return { updateNodeConfig };
}
