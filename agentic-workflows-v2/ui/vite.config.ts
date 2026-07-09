import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, __dirname, "");
  const explicitApiTarget =
    env.VITE_API_PROXY_TARGET || process.env.VITE_API_PROXY_TARGET || "";
  const apiProxyTarget = explicitApiTarget || "http://localhost:8010";
  const wsProxyTarget = apiProxyTarget.replace(/^http/i, "ws");
  const workflowBuilderFlag =
    env.VITE_AGENTIC_ENABLE_WORKFLOW_BUILDER ??
    env.AGENTIC_ENABLE_WORKFLOW_BUILDER ??
    process.env.VITE_AGENTIC_ENABLE_WORKFLOW_BUILDER ??
    process.env.AGENTIC_ENABLE_WORKFLOW_BUILDER ??
    "";

  // In dev, always inject the backend URL so websocket.ts can connect directly
  // (Vite's proxy silently drops WebSocket upgrades). In production, omit it
  // so the client defaults to same-origin WebSocket (backend serves the UI).
  const clientDefines: Record<string, string> = {
    __AGENTIC_ENABLE_WORKFLOW_BUILDER__: JSON.stringify(workflowBuilderFlag),
  };
  if (mode === "development") {
    clientDefines["import.meta.env.VITE_API_PROXY_TARGET"] = JSON.stringify(apiProxyTarget);
  }

  return {
    plugins: [react()],
    define: clientDefines,
    resolve: {
      alias: {
        "@": path.resolve(__dirname, "src"),
      },
    },
    server: {
      port: 5173,
      hmr: {
        // Use a dedicated port so the main HTTP server's upgrade events are
        // not consumed by Vite's HMR WebSocket, allowing the /ws proxy to work.
        port: 5183,
      },
      proxy: {
        "/api": apiProxyTarget,
        "/ws": {
          target: wsProxyTarget,
          ws: true,
          changeOrigin: true,
        },
      },
    },
  };
});
