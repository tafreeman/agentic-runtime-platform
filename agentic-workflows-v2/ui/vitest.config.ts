import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import path from "node:path";

export default defineConfig({
  plugins: [react()],
  define: {
    __AGENTIC_ENABLE_WORKFLOW_BUILDER__: JSON.stringify(
      process.env.VITE_AGENTIC_ENABLE_WORKFLOW_BUILDER ??
        process.env.AGENTIC_ENABLE_WORKFLOW_BUILDER ??
        ""
    ),
    __AGENTIC_NO_LLM_MODE__: JSON.stringify(
      process.env.VITE_AGENTIC_NO_LLM ??
        process.env.AGENTIC_NO_LLM ??
        ""
    ),
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "src"),
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: ["./src/__tests__/setup.ts"],
    css: true,
    exclude: ["e2e/**", "node_modules/**", "dist/**"],
    coverage: {
      provider: "v8",
      reporter: ["text", "json-summary", "html"],
      include: ["src/**/*.{ts,tsx}"],
      exclude: [
        "src/**/__tests__/**",
        "src/**/*.d.ts",
        "src/main.tsx",
        "src/vite-env.d.ts",
      ],
      thresholds: {
        lines: 60,
        statements: 60,
        functions: 60,
        branches: 60,
      },
    },
  },
});
