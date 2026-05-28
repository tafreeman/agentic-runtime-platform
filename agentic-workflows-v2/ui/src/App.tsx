import { Routes, Route } from "react-router-dom";
import Sidebar from "./components/layout/Sidebar";
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
import NotFoundPage from "./components/states/NotFoundPage";

export default function App() {
  const workflowBuilderEnabled = isWorkflowBuilderEnabled();

  return (
    <div className="flex h-screen overflow-hidden">
      {/* Skip-to-main-content: visually hidden until focused via keyboard Tab */}
      <a
        href="#main-content"
        className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded-sm focus:bg-b-bg1 focus:px-3 focus:py-1.5 focus:font-mono focus:text-[11px] focus:text-b-clay focus:ring-1 focus:ring-b-clay/50 focus:outline-none"
      >
        skip to main content
      </a>
      <Sidebar />
      <main id="main-content" className="flex-1 overflow-hidden" tabIndex={-1}>
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
          <Route path="/runs" element={<RunsPage />} />
          <Route path="/runs/:filename" element={<RunDetailPage />} />
          <Route path="/live/:runId" element={<LivePage />} />
          <Route path="*" element={<NotFoundPage />} />
        </Routes>
      </main>
    </div>
  );
}
