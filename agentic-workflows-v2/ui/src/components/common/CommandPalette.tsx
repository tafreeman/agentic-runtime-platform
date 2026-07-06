import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
} from "react";
import { useNavigate } from "react-router-dom";
import {
  ArrowRight,
  Command,
  CornerDownLeft,
  Database,
  Gauge,
  LayoutDashboard,
  List,
  Radio,
  Search,
  Trophy,
  Workflow,
  X,
} from "lucide-react";
import { useCli } from "../../hooks/useCli";

/**
 * A single entry in the command palette. `run` performs the navigation (or
 * other action) and reports the CLI twin via {@link useCli} so the sticky
 * {@link CliStrip} stays in sync with whatever the palette just did.
 */
interface PaletteCommand {
  readonly id: string;
  readonly label: string;
  readonly hint?: string;
  readonly icon: typeof Search;
  readonly run: () => void;
}

/**
 * Global ⌘K / Ctrl+K command palette. Owns its own open state and keydown
 * listener — mount it once near the root (inside {@link CliProvider}) and it
 * takes care of the rest. Every navigation command also calls `setCli(...)`
 * with the CLI-parity twin of the action, same as clicking through the UI.
 */
export default function CommandPalette() {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [activeIndex, setActiveIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const navigate = useNavigate();
  const { setCli } = useCli();

  const close = useCallback(() => {
    setOpen(false);
    setQuery("");
    setActiveIndex(0);
  }, []);

  const goTo = useCallback(
    (path: string, cliTwin: string) => {
      setCli(cliTwin);
      navigate(path);
      close();
    },
    [navigate, setCli, close]
  );

  const commands = useMemo<PaletteCommand[]>(
    () => [
      {
        id: "dashboard",
        label: "Dashboard",
        hint: "overview",
        icon: LayoutDashboard,
        run: () => goTo("/", "agentic dashboard"),
      },
      {
        id: "live",
        label: "Live execution",
        hint: "watch a run stream",
        icon: Radio,
        run: () => goTo("/live/latest", "agentic runs watch latest --follow"),
      },
      {
        id: "runs",
        label: "Runs",
        hint: "history & inspector",
        icon: List,
        run: () => goTo("/runs", "agentic runs list"),
      },
      {
        id: "workflows",
        label: "Workflows",
        hint: "builder & definitions",
        icon: Workflow,
        run: () => goTo("/workflows", "agentic workflows list"),
      },
      {
        id: "evaluations",
        label: "Evaluations",
        hint: "suites & results",
        icon: Trophy,
        run: () => goTo("/evaluations", "agentic evals list"),
      },
      {
        id: "datasets",
        label: "Datasets",
        hint: "golden sets & fixtures",
        icon: Database,
        run: () => goTo("/datasets", "agentic datasets list"),
      },
      {
        id: "models",
        label: "Model router",
        hint: "tiers & routing rules",
        icon: Gauge,
        run: () => goTo("/models", "agentic models list"),
      },
    ],
    [goTo]
  );

  const results = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return commands;
    return commands.filter(
      (c) =>
        c.label.toLowerCase().includes(q) ||
        c.hint?.toLowerCase().includes(q) ||
        c.id.toLowerCase().includes(q)
    );
  }, [commands, query]);

  // Global ⌘K / Ctrl+K listener — opens the palette from anywhere.
  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen((prev) => !prev);
      }
    }
    globalThis.addEventListener("keydown", onKeyDown);
    return () => globalThis.removeEventListener("keydown", onKeyDown);
  }, []);

  // Autofocus the search input whenever the palette opens.
  useEffect(() => {
    if (open) {
      setQuery("");
      setActiveIndex(0);
      // Focus after paint so the input exists in the DOM.
      const id = requestAnimationFrame(() => inputRef.current?.focus());
      return () => cancelAnimationFrame(id);
    }
    return undefined;
  }, [open]);

  // Backstop Escape handler — closes the palette even if focus has moved off
  // the search input onto the close button or a result row.
  useEffect(() => {
    if (!open) return undefined;
    function onKeyDown(e: KeyboardEvent) {
      if (e.key === "Escape") {
        e.preventDefault();
        close();
      }
    }
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [open, close]);

  // Clamp the highlighted row whenever the filtered result set shrinks/grows.
  useEffect(() => {
    setActiveIndex((prev) => {
      if (results.length === 0) return 0;
      return Math.min(prev, results.length - 1);
    });
  }, [results.length]);

  const handleInputKeyDown = (e: ReactKeyboardEvent<HTMLInputElement>) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActiveIndex((prev) => (results.length === 0 ? 0 : (prev + 1) % results.length));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActiveIndex((prev) =>
        results.length === 0 ? 0 : (prev - 1 + results.length) % results.length
      );
    } else if (e.key === "Enter") {
      e.preventDefault();
      results[activeIndex]?.run();
    } else if (e.key === "Escape") {
      e.preventDefault();
      close();
    }
  };

  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center pt-[14vh]">
      {/* Backdrop */}
      <button
        type="button"
        className="absolute inset-0 cursor-default border-0 bg-black/60"
        aria-label="Close command palette"
        onClick={close}
      />

      <div
        role="dialog"
        aria-modal="true"
        aria-label="Command palette"
        className="relative w-full max-w-lg border border-b-line bg-b-bg1 font-mono shadow-2xl"
      >
        {/* Search row */}
        <div className="flex items-center gap-2.5 border-b border-b-line px-3.5">
          <Search size={14} className="flex-none text-b-text-dim" aria-hidden="true" />
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={handleInputKeyDown}
            placeholder="Search runs, workflows, actions…"
            aria-label="Search commands"
            autoComplete="off"
            spellCheck={false}
            className="h-11 min-w-0 flex-1 bg-transparent text-[13px] text-b-text placeholder:text-b-text-faint focus:outline-none"
          />
          <span className="flex flex-none items-center gap-1 text-b-text-faint">
            <Command size={12} aria-hidden="true" />
            <span className="text-[10px]">K</span>
          </span>
          <button
            type="button"
            onClick={close}
            aria-label="Close command palette"
            className="flex flex-none items-center justify-center p-1 text-b-text-dim hover:text-b-text focus:outline-none focus:ring-1 focus:ring-b-clay/50"
          >
            <X size={14} aria-hidden="true" />
          </button>
        </div>

        {/* Results */}
        <ul role="listbox" aria-label="Commands" className="max-h-80 overflow-y-auto py-1.5">
          {results.length === 0 && (
            <li className="px-3.5 py-6 text-center text-[12px] text-b-text-dim">
              No commands match &ldquo;{query}&rdquo;.
            </li>
          )}
          {results.map((command, index) => {
            const Icon = command.icon;
            const active = index === activeIndex;
            return (
              <li key={command.id} role="presentation">
                <button
                  type="button"
                  role="option"
                  aria-selected={active}
                  onClick={() => command.run()}
                  onMouseEnter={() => setActiveIndex(index)}
                  className={`flex w-full items-center gap-3 px-3.5 py-2.5 text-left text-[13px] transition-colors focus:outline-none ${
                    active
                      ? "bg-b-bg2 text-b-clay shadow-[inset_3px_0_0_theme(colors.b.clay)]"
                      : "text-b-text-mid hover:bg-b-bg2"
                  }`}
                >
                  <Icon
                    size={15}
                    className={`flex-none ${active ? "text-b-clay" : "text-b-text-dim"}`}
                    aria-hidden="true"
                  />
                  <span className="min-w-0 flex-1 truncate">{command.label}</span>
                  {command.hint && (
                    <span className="flex-none truncate text-[11px] text-b-text-faint">
                      {command.hint}
                    </span>
                  )}
                  {active && (
                    <ArrowRight size={13} className="flex-none text-b-clay" aria-hidden="true" />
                  )}
                </button>
              </li>
            );
          })}
        </ul>

        {/* Footer hints */}
        <div className="flex items-center gap-4 border-t border-b-line px-3.5 py-2 text-[10px] text-b-text-faint">
          <span className="flex items-center gap-1.5">
            <kbd className="border border-b-line bg-b-bg2 px-1.5 py-[1px] text-b-text-dim">
              ↑
            </kbd>
            <kbd className="border border-b-line bg-b-bg2 px-1.5 py-[1px] text-b-text-dim">
              ↓
            </kbd>
            move
          </span>
          <span className="flex items-center gap-1.5">
            <kbd className="flex items-center border border-b-line bg-b-bg2 px-1.5 py-[1px] text-b-text-dim">
              <CornerDownLeft size={10} aria-hidden="true" />
            </kbd>
            open
          </span>
          <span className="flex items-center gap-1.5">
            <kbd className="border border-b-line bg-b-bg2 px-1.5 py-[1px] text-b-text-dim">
              esc
            </kbd>
            close
          </span>
        </div>
      </div>
    </div>
  );
}
