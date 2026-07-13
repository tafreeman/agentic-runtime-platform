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
 * Global console header from the design kit: `console▊` brand, the
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

  // Env badge — honest by construction. The environment comes from the build
  // (Vite dev server vs production build), never a hardcoded "prod"; the
  // "· live" suffix is only claimed once GET /api/health has actually
  // succeeded, and it flips to "no-llm" when the server reports deterministic
  // placeholder mode.
  const envLabel = import.meta.env.DEV ? "dev" : "prod";
  let badgeDotClass = "bg-b-text-faint";
  let badgeTextClass = "text-b-text-dim";
  let badgeText = envLabel; // health still pending — claim nothing yet
  let badgeTitle = "checking backend health…";
  if (health.isError) {
    badgeDotClass = "bg-b-red";
    badgeTextClass = "text-b-red";
    badgeText = "api down";
    badgeTitle = "GET /api/health failed — backend unreachable";
  } else if (health.isSuccess) {
    badgeDotClass = "bg-b-green";
    badgeTextClass = noLlmMode ? "text-b-blue" : "text-b-green";
    badgeText = noLlmMode ? `${envLabel} · no-llm` : `${envLabel} · live`;
    badgeTitle = noLlmMode
      ? "backend healthy — deterministic placeholder mode, no provider calls"
      : "backend healthy — live providers";
  }

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
          console
          <span
            aria-hidden="true"
            className="text-b-clay motion-safe:animate-pulse"
          >
            ▊
          </span>
        </span>
        <span className="font-mono text-[11px] text-b-text-dim">
          / agentic-runtime
        </span>
      </Link>

      {/* The palette is pure navigation today — the visible copy says so.
          The accessible name keeps the "search runs, workflows, actions"
          phrase so existing queries/muscle memory still resolve it. */}
      <button
        type="button"
        onClick={openPalette}
        aria-label="Jump to page (search runs, workflows, actions)"
        className="mx-auto flex h-7 w-full max-w-md flex-none items-center gap-2 border border-b-line bg-b-bg0 px-2.5 font-mono text-[11px] text-b-text-dim transition-colors hover:border-b-clay/50 hover:text-b-text focus:outline-none focus:ring-1 focus:ring-b-clay/50"
        style={{ borderRadius: "var(--b-rad-sm)", borderWidth: "var(--b-bw)" }}
      >
        <Search size={12} aria-hidden="true" className="flex-none" />
        <span className="min-w-0 flex-1 truncate text-left">
          jump to page… (g+key)
        </span>
        <span className="flex flex-none items-center gap-1">
          <Kbd>⌘</Kbd>
          <Kbd>K</Kbd>
        </span>
      </button>

      <span
        role="status"
        data-testid="env-badge"
        aria-label={`environment: ${badgeText}`}
        title={badgeTitle}
        className={`flex flex-none items-center gap-1.5 font-mono text-[10px] tracking-[0.5px] ${badgeTextClass}`}
      >
        <span
          aria-hidden="true"
          className={`h-1.5 w-1.5 flex-none rounded-full ${badgeDotClass}`}
        />
        {badgeText}
      </span>
    </header>
  );
}
