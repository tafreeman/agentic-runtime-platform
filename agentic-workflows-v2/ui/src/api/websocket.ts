import type { ExecutionEvent } from "./types";

export type EventHandler = (event: ExecutionEvent) => void;

/**
 * Creates a WebSocket connection to the execution stream for a run.
 * Automatically reconnects on disconnect (up to maxRetries).
 */
export function connectExecutionStream(
  runId: string,
  onEvent: EventHandler,
  options: { maxRetries?: number; retryDelayMs?: number; pathPrefix?: string } = {}
): { close: () => void } {
  // maxRetries=5, retryDelayMs=1000 → exponential sequence: 1s, 2s, 4s, 8s, 16s (31s total)
  const { maxRetries = 5, retryDelayMs = 1000, pathPrefix = "execution" } = options;
  let ws: WebSocket | null = null;
  let retries = 0;
  let closed = false;

  function connect() {
    if (closed) return;

    // In dev, VITE_API_PROXY_TARGET points directly at the backend. Connect
    // to it directly so the WebSocket upgrade doesn't pass through the Vite
    // proxy (which drops the upgrade and forwards a plain HTTP GET instead).
    const apiTarget = import.meta.env.VITE_API_PROXY_TARGET as string | undefined;
    let wsBase: string;
    if (apiTarget) {
      wsBase = apiTarget.replace(/^http/, "ws");
    } else {
      const wsScheme = location.protocol === "https:" ? "wss:" : "ws:";
      wsBase = `${wsScheme}//${location.host}`;
    }
    ws = new WebSocket(`${wsBase}/ws/${pathPrefix}/${runId}`);

    ws.onopen = () => {
      retries = 0;
    };

    ws.onmessage = (evt) => {
      try {
        const event = JSON.parse(evt.data) as ExecutionEvent;
        onEvent(event);
      } catch (e) {
        // Malformed event frame — log & drop rather than crash the stream.
        const preview = typeof evt.data === "string" ? evt.data.slice(0, 200) : "<non-string>";
        console.warn("[ws] parse error:", e, "payload preview:", preview);
      }
    };

    ws.onclose = () => {
      if (closed) return;
      if (retries < maxRetries) {
        retries++;
        // Exponential backoff: retryDelayMs × 2^(retryCount-1)
        // Protects restarting server from hammering; matches AWS/GCP/Azure standards
        // Retries at: 1s, 2s, 4s, 8s, 16s (cumulative: 31s max)
        setTimeout(connect, retryDelayMs * Math.pow(2, retries - 1));
      }
    };

    ws.onerror = () => {
      ws?.close();
    };
  }

  connect();

  return {
    close() {
      closed = true;
      ws?.close();
    },
  };
}
