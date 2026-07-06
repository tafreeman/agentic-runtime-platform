import { useParams, useNavigate } from "react-router-dom";
import { ArrowLeft } from "lucide-react";
import RunDetailPanel from "../components/runs/RunDetailPanel";
import BTopBar from "../components/layout/BTopBar";

/**
 * Deep-link route (`/runs/:filename`) — thin wrapper that supplies the page
 * chrome (breadcrumb + back button) around the shared `RunDetailPanel`. The
 * master–detail inspector on RunsPage renders the same panel directly,
 * without this chrome, inside its aside.
 */
export default function RunDetailPage() {
  const { filename } = useParams<{ filename: string }>();
  const navigate = useNavigate();

  if (!filename) {
    return (
      <div className="flex h-full items-center justify-center font-mono text-[11px] text-b-red">
        $ run not found
      </div>
    );
  }

  return (
    <div className="flex h-full flex-col">
      <BTopBar path={`runs/${filename}`}>
        <button
          type="button"
          onClick={() => navigate(-1)}
          className="btn-ghost"
          aria-label="Go back"
        >
          <ArrowLeft className="h-3 w-3" aria-hidden="true" />
          <span>[esc] back</span>
        </button>
      </BTopBar>

      <div className="min-h-0 flex-1">
        <RunDetailPanel filename={filename} layout="page" />
      </div>
    </div>
  );
}
