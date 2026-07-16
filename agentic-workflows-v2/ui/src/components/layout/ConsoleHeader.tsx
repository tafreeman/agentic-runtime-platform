import { Link } from "react-router-dom";
import { Search } from "lucide-react";
import { useBackendHealth } from "../../hooks/useBackendHealth";

/** Small bordered keycap, matching the design kit's kbd treatment. */
function Kbd({ children }: Readonly<{ children: string }>) {
  return (
    <span
      className="border border-b-line bg-b-bg0 px-1 py-px font-mono text-[9px] leading-none text-b-text-dim"
      style={{ borderRadius: "var(--b-rad-sm)", borderWidth: "var(--b-bw)" }}
    >
      {children}
    </span>
  );
}

/**
 * Global Evidence Ledger header: brand, command palette affordance, and
 * search/⌘K affordance (opens the command palette), and the environment
 * badge. Sits above the sidebar + content row; the palette itself stays
 * mounted at the root and listens for the `open-command-palette` event.
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
    <header
      className="flex h-11 flex-none items-center gap-4 border-b border-b-line bg-b-bg1 px-4"
      style={{ borderBottomWidth: "var(--b-bw)" }}
    >
      <Link
        to="/"
        className="flex flex-none items-baseline gap-2 focus:outline-none focus:ring-1 focus:ring-b-clay/50"
        aria-label="console home"
      >
        <span
          className="font-mono text-[13px] font-semibold tracking-tight text-b-text"
        >
          Evidence Ledger
          <span
            aria-hidden="true"
            className="text-b-clay motion-safe:animate-pulse"
          >
            ▊
          </span>
        </span>
        <span className="hidden font-mono text-[11px] text-b-text-dim sm:inline">
          / agentic runtime
        </span>
      </Link>

      <button
        type="button"
        onClick={openPalette}
        aria-label="Jump to page on mobile"
        className="ml-auto grid h-8 w-8 place-items-center rounded-[2px] border border-b-line bg-b-bg0 text-b-text-dim focus:outline-none focus:ring-2 focus:ring-b-clay/40 sm:hidden"
      >
        <Search size={15} aria-hidden="true" />
      </button>

      {/* The palette is pure navigation today — the visible copy says so.
          The accessible name keeps the "search runs, workflows, actions"
          phrase so existing queries/muscle memory still resolve it. */}
      <button
        type="button"
        onClick={openPalette}
        aria-label="Jump to page (search runs, workflows, actions)"
        className="mx-auto hidden h-7 w-full max-w-md flex-none items-center gap-2 border border-b-line bg-b-bg0 px-2.5 font-mono text-[11px] text-b-text-dim transition-colors hover:border-b-clay/50 hover:text-b-text focus:outline-none focus:ring-1 focus:ring-b-clay/50 sm:flex"
        style={{ borderRadius: "var(--b-rad-sm)", borderWidth: "var(--b-bw)" }}
      >
        <Search size={12} aria-hidden="true" className="flex-none" />
        <span className="min-w-0 flex-1 truncate text-left">
          Search pages and actions…
        </span>
        <span className="flex flex-none items-center gap-1">
          <Kbd>⌘</Kbd>
          <Kbd>K</Kbd>
        </span>
      </button>

      <span
        className={`ml-auto hidden flex-none font-mono text-[10px] tracking-[0.5px] md:inline ${
          noLlmMode ? "text-b-teal" : "text-b-green"
        }`}
        title={
          noLlmMode
            ? "deterministic placeholder mode — no provider calls"
            : "live providers"
        }
      >
        {noLlmMode ? "no-llm · deterministic" : "prod · live"}
      </span>
    </header>
  );
}
