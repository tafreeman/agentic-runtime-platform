import { Link } from "react-router-dom";
import { ArrowLeft } from "lucide-react";

/** The catch-all route keeps a readable heading and a safe return path. */
export default function NotFoundPage() {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-4 overflow-y-auto px-5 py-16 text-center">
      <h1 className="font-display text-[40px] text-el-ink">404 not found</h1>
      <p className="text-sm text-el-muted">route not found</p>
      <p className="max-w-prose text-sm leading-relaxed text-el-secondary">This address does not match an application page. Return to the dashboard to find your workflows and runs.</p>
      <Link to="/" className="focus-ring inline-flex min-h-10 items-center gap-2 rounded-md border border-el-control-border px-4 text-sm text-el-ink transition-colors hover:bg-el-hover">
        <ArrowLeft aria-hidden="true" className="size-4" />Return to dashboard
      </Link>
    </div>
  );
}
