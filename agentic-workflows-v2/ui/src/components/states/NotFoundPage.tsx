import { Link } from "react-router-dom";

/**
 * Terminal-style 404 page.
 * Rendered when the router hits the catch-all "*" route.
 */
export default function NotFoundPage() {
  return (
    <div className="flex flex-col items-center justify-center gap-4 py-24 font-mono">
      <pre
        aria-hidden="true"
        className="select-none text-center text-xs leading-tight text-el-muted"
      >
        {[
          "  ╔════════════════════╗  ",
          "  ║  404 not found     ║  ",
          "  ╚════════════════════╝  ",
        ].join("\n")}
      </pre>
      <div className="text-[13px] text-el-secondary">
        <span className="text-el-muted">$</span>{" "}
        <span>route not found</span>
      </div>
      {/* Breadcrumb back to root */}
      <nav aria-label="Breadcrumb" className="flex items-center gap-1.5 font-mono text-micro text-el-muted">
        <Link
          to="/"
          className="focus-ring inline-flex min-h-9 items-center rounded-md px-1 text-el-accent-strong underline-offset-2 hover:underline"
        >
          ~/dashboard
        </Link>
        <span aria-hidden="true">/</span>
        <span aria-current="page">404</span>
      </nav>
    </div>
  );
}
