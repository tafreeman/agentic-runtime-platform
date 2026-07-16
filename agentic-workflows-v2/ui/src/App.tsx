import { lazy, Suspense, useEffect, useRef } from "react";
import { Navigate, Routes, Route, useLocation } from "react-router-dom";
import Sidebar from "./components/layout/Sidebar";
import ConsoleHeader from "./components/layout/ConsoleHeader";
import { isWorkflowBuilderEnabled } from "./config/featureFlags";
import NotFoundPage from "./components/states/NotFoundPage";
import CliStrip from "./components/layout/CliStrip";
import CommandPalette from "./components/common/CommandPalette";
import { CliProvider } from "./hooks/useCli";
import { useGoNav } from "./hooks/useGoNav";
import { Toaster } from "./components/ui/sonner";

const DashboardPage = lazy(() => import("./pages/DashboardPage"));
const WorkflowsPage = lazy(() => import("./pages/WorkflowsPage"));
const WorkflowDetailPage = lazy(() => import("./pages/WorkflowDetailPage"));
const WorkflowEditorPage = lazy(() => import("./pages/WorkflowEditorPage"));
const RunDetailPage = lazy(() => import("./pages/RunDetailPage"));
const RunsPage = lazy(() => import("./pages/RunsPage"));
const LivePage = lazy(() => import("./pages/LivePage"));
const DatasetsPage = lazy(() => import("./pages/DatasetsPage"));
const EvaluationsPage = lazy(() => import("./pages/EvaluationsPage"));
const ModelFinderPage = lazy(() => import("./pages/ModelFinderPage"));

function RouteFallback() {
  return (
    <div className="mx-auto max-w-7xl p-5 sm:p-8 lg:p-10" aria-live="polite">
      <div className="h-3 w-28 animate-pulse bg-el-subtle" />
      <div className="mt-5 h-10 w-72 max-w-full animate-pulse bg-el-subtle" />
      <div className="mt-10 h-64 animate-pulse border border-el-divider-soft bg-el-surface" />
      <span className="sr-only">Loading page</span>
    </div>
  );
}

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
    <div className="el-app flex h-screen flex-col overflow-hidden">
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
        className="flex-1 overflow-hidden pb-14 focus:outline-none md:pb-0"
        tabIndex={-1}
      >
        <Suspense fallback={<RouteFallback />}>
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
          <Route path="/settings" element={<Navigate to="/models?tab=providers" replace />} />
          <Route path="/runs" element={<RunsPage />} />
          <Route path="/runs/:filename" element={<RunDetailPage />} />
          <Route path="/live/:runId" element={<LivePage />} />
          <Route path="*" element={<NotFoundPage />} />
        </Routes>
        </Suspense>
      </main>
      </div>
      <CommandPalette />
      <CliStrip />
      <Toaster position="bottom-right" richColors closeButton />
    </div>
    </CliProvider>
  );
}
