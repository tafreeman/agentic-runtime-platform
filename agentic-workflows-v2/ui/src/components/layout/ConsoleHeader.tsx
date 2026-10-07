import { Link } from "react-router-dom";
import { Search } from "lucide-react";
import { useBackendHealth } from "../../hooks/useBackendHealth";
import PaletteShortcut from "./PaletteShortcut";

/**
 * Global Evidence Ledger header: brand (the shell's only brand mark), the
 * search / ⌘K (Ctrl K) affordance that opens the command palette, and the
 * server-reported provider-mode badge. Sits above the sidebar + content row;
 * the palette itself stays mounted at the root and listens for the
 * `open-command-palette` event.
 */
export default function ConsoleHeader() {
  // Shared ["backend-health"] query (see useBackendHealth). ConsoleHeader is
  // the single polling owner (always mounted in the shell); Sidebar and
  // ConsoleStatus read the same cache without their own interval. The badge
  // reflects the server's own reported mode, not a client build-time flag.
  const health = useBackendHealth({ poll: true });
  const noLlmMode = health.data?.no_llm_mode ?? false;

  const openPalette = () => {
    globalThis.dispatchEvent(new CustomEvent("open-command-palette"));
  };

  return (
    <header className="flex h-11 flex-none items-center gap-4 border-b border-el-divider bg-el-surface px-4">
      <Link
        to="/"
        className="flex flex-none items-baseline gap-2 rounded-sm py-2.5 focus-ring"
        aria-label="console home"
      >
        <span className="font-mono text-[13px] font-semibold tracking-tight text-el-ink">
          Evidence Ledger
          {/* The shell's one vermilion key mark; static (no decorative loop). */}
          <span aria-hidden="true" className="text-el-accent">
            ▊
          </span>
        </span>
        <span className="hidden font-mono text-micro text-el-muted sm:inline">
          / agentic runtime
        </span>
      </Link>

      {/* Mobile: labelled search control. The visual box is 36px; the ::after
          hit area extends it to a 44px touch target. */}
      <button
        type="button"
        onClick={openPalette}
        aria-label="Search pages"
        className="relative ml-auto inline-flex h-9 flex-none items-center gap-1.5 rounded-md border border-el-divider bg-el-canvas px-3 text-xs text-el-secondary transition-colors after:absolute after:-inset-1 hover:text-el-ink focus-ring sm:hidden"
      >
        <Search size={15} aria-hidden="true" className="flex-none" />
        <span>Search</span>
      </button>

      {/* The palette is pure navigation today — the visible copy says so.
          The accessible name keeps the "search runs, workflows, actions"
          phrase so existing queries/muscle memory still resolve it. */}
      <button
        type="button"
        onClick={openPalette}
        aria-label="Jump to page (search runs, workflows, actions)"
        // min-w-0 + flex-1 (not flex-none): at narrow widths / 200% zoom the
        // box shrinks to fit beside the brand instead of being clipped.
        className="mx-auto hidden h-9 w-full max-w-md min-w-0 flex-1 items-center gap-2 rounded-md border border-el-divider bg-el-canvas px-2.5 text-xs text-el-muted transition-colors hover:border-el-muted hover:text-el-ink focus-ring sm:flex"
      >
        <Search size={12} aria-hidden="true" className="flex-none" />
        <span className="min-w-0 flex-1 truncate text-left">
          Search pages and actions…
        </span>
        <PaletteShortcut />
      </button>

      {/* Only once the server has reported its mode: while the health check
          is pending or failing the mode is unknown, and the shell's offline
          banner carries the outage, so no (green) guess is shown. */}
      {health.data ? (
        <span
          className={`ml-auto hidden flex-none font-mono text-micro md:inline ${
            noLlmMode ? "text-el-warning" : "text-el-success"
          }`}
          title={
            noLlmMode
              ? "deterministic placeholder mode — no provider calls"
              : "live providers"
          }
        >
          {noLlmMode ? "no-llm · deterministic" : "live providers"}
        </span>
      ) : null}
    </header>
  );
}
