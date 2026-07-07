import { useEffect, useRef } from "react";
import { Routes, Route, useLocation } from "react-router-dom";
import Sidebar from "./components/layout/Sidebar";
import ConsoleHeader from "./components/layout/ConsoleHeader";
import DashboardPage from "./pages/DashboardPage";
import WorkflowsPage from "./pages/WorkflowsPage";
import WorkflowDetailPage from "./pages/WorkflowDetailPage";
import WorkflowEditorPage from "./pages/WorkflowEditorPage";
import RunDetailPage from "./pages/RunDetailPage";
import RunsPage from "./pages/RunsPage";
import LivePage from "./pages/LivePage";
import { isWorkflowBuilderEnabled } from "./config/featureFlags";
import DatasetsPage from "./pages/DatasetsPage";
import EvaluationsPage from "./pages/EvaluationsPage";
import ModelFinderPage from "./pages/ModelFinderPage";
import SettingsPage from "./pages/SettingsPage";
import NotFoundPage from "./components/states/NotFoundPage";
import CliStrip from "./components/layout/CliStrip";
import CommandPalette from "./components/common/CommandPalette";
import { CliProvider } from "./hooks/useCli";
import { useGoNav } from "./hooks/useGoNav";

/**
 * Mounts the global `g`+key navigation sequence. Rendered as a child of
 * {@link CliProvider} because the hook reports each jump's CLI twin.
 */
function GoNav() {
  useGoNav();
  return null;
}

export default function App() {
  const workflowBuilderEnabled = isWorkflowBuilderEnabled();
  const location = useLocation();
  const mainRef = useRef<HTMLElement>(null);
  const isFirstRender = useRef(true);

  // Move focus to the main region on client-side navigation so keyboard and
  // screen-reader users are told the content changed. Skip the initial load —
  // focus belongs wherever the browser placed it then.
  useEffect(() => {
    if (isFirstRender.current) {
      isFirstRender.current = false;
      return;
    }
    mainRef.current?.focus();
  }, [location.pathname]);

  return (
    <CliProvider>
    <GoNav />
    <div className="flex h-screen flex-col overflow-hidden">
      {/* Skip-to-main-content: visually hidden until focused via keyboard Tab */}
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded-none focus:bg-b-bg1 focus:px-3 focus:py-1.5 focus:font-mono focus:text-[11px] focus:text-b-clay focus:ring-1 focus:ring-b-clay/50 focus:outline-none"
      >
        skip to main content
      </a>
      <ConsoleHeader />
      <div className="flex min-h-0 flex-1 overflow-hidden">
      <Sidebar />
      <main
        ref={mainRef}
        id="main-content"
        className="flex-1 overflow-hidden focus:outline-none"
        tabIndex={-1}
      >
        <Routes>
          <Route path="/" element={<DashboardPage />} />
          <Route path="/workflows" element={<WorkflowsPage />} />
          {workflowBuilderEnabled && (
            <Route path="/workflows/:name/edit" element={<WorkflowEditorPage />} />
          )}
          <Route path="/workflows/:name" element={<WorkflowDetailPage />} />
          <Route path="/datasets" element={<DatasetsPage />} />
          <Route path="/evaluations" element={<EvaluationsPage />} />
          <Route path="/models" element={<ModelFinderPage />} />
          <Route path="/settings" element={<SettingsPage />} />
          <Route path="/runs" element={<RunsPage />} />
          <Route path="/runs/:filename" element={<RunDetailPage />} />
          <Route path="/live/:runId" element={<LivePage />} />
          <Route path="*" element={<NotFoundPage />} />
        </Routes>
      </main>
      </div>
      <CommandPalette />
      <CliStrip />
    </div>
    </CliProvider>
  );
}
