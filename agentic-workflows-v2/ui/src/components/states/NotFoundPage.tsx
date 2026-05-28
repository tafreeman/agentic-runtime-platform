import { Link } from "react-router-dom";

/**
 * Terminal-style 404 page.
 * Rendered when the router hits the catch-all "*" route.
 */
export default function NotFoundPage() {
  return (
    <div className="flex flex-col items-center justify-center gap-4 py-24 font-mono">
      <pre className="select-none text-center text-b-text-dim text-[12px] leading-tight">
        {[
          "  ╔════════════════════╗  ",
          "  ║  404 not found     ║  ",
          "  ╚════════════════════╝  ",
        ].join("\n")}
      </pre>
      <div className="text-[13px] text-b-text-mid">
        <span className="text-b-clay">$</span>{" "}
        <span>route not found</span>
      </div>
      {/* Breadcrumb back to root */}
      <nav aria-label="Breadcrumb" className="flex items-center gap-1.5 font-mono text-[11px] text-b-text-dim">
        <Link to="/" className="text-b-clay hover:underline">
          ~/dashboard
        </Link>
        <span>/</span>
        <span className="text-b-text-faint">404</span>
      </nav>
    </div>
  );
}
