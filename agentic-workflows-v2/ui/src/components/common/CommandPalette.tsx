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
import PaletteShortcut from "../layout/PaletteShortcut";

/**
 * A single entry in the command palette. `run` performs the navigation; the
 * sticky {@link CliStrip} follows the route, so it shows the destination's
 * real CLI equivalent (or none) without the palette inventing one.
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
 * listener — mount it once near the root and it takes care of the rest.
 */
export default function CommandPalette() {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [activeIndex, setActiveIndex] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const navigate = useNavigate();

  const close = useCallback(() => {
    setOpen(false);
    setQuery("");
    setActiveIndex(0);
  }, []);

  const goTo = useCallback(
    (path: string) => {
      navigate(path);
      close();
    },
    [navigate, close]
  );

  const commands = useMemo<PaletteCommand[]>(
    () => [
      {
        id: "dashboard",
        label: "Dashboard",
        hint: "overview",
        icon: LayoutDashboard,
        run: () => goTo("/"),
      },
      {
        id: "live",
        label: "Live execution",
        hint: "watch a run stream",
        icon: Radio,
        run: () => goTo("/live/latest"),
      },
      {
        id: "runs",
        label: "Runs",
        hint: "history & inspector",
        icon: List,
        run: () => goTo("/runs"),
      },
      {
        id: "workflows",
        label: "Workflows",
        hint: "builder & definitions",
        icon: Workflow,
        run: () => goTo("/workflows"),
      },
      {
        id: "evaluations",
        label: "Evaluations",
        hint: "suites & results",
        icon: Trophy,
        run: () => goTo("/evaluations"),
      },
      {
        id: "datasets",
        label: "Datasets",
        hint: "golden sets & fixtures",
        icon: Database,
        run: () => goTo("/datasets"),
      },
      {
        id: "models",
        label: "Model router",
        hint: "tiers & routing rules",
        icon: Gauge,
        run: () => goTo("/models"),
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

  // Programmatic open — the header's search affordance dispatches this event
  // so it behaves exactly like pressing ⌘K.
  useEffect(() => {
    function onOpenEvent() {
      setOpen(true);
    }
    globalThis.addEventListener("open-command-palette", onOpenEvent);
    return () =>
      globalThis.removeEventListener("open-command-palette", onOpenEvent);
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
      {/* Backdrop — same scrim as the shared Dialog overlay in both themes. */}
      <button
        type="button"
        tabIndex={-1}
        className="absolute inset-0 cursor-default border-0 bg-el-ink/25 dark:bg-el-canvas/75"
        aria-label="Close command palette"
        onClick={close}
      />

      <div
        role="dialog"
        aria-modal="true"
        aria-label="Command palette"
        className="relative w-full max-w-lg rounded-lg border border-el-divider bg-el-raised font-mono shadow-(--el-shadow-raised)"
      >
        {/* Search row. The input draws no outline of its own: the row shows a
            full-strength 2px inset ring while the input has focus. */}
        <div className="flex items-center gap-2.5 rounded-t-lg border-b border-el-divider px-3.5 focus-within:ring-2 focus-within:ring-inset focus-within:ring-ring">
          <Search size={14} className="flex-none text-el-muted" aria-hidden="true" />
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={handleInputKeyDown}
            placeholder="jump to page… (g+key)"
            aria-label="Search commands"
            autoComplete="off"
            spellCheck={false}
            className="h-11 min-w-0 flex-1 bg-transparent text-[13px] text-el-ink placeholder:text-el-faint outline-hidden"
          />
          {/* Platform-aware hint (⌘K on Apple, Ctrl K elsewhere), the same
              markup as the header search affordance. */}
          <PaletteShortcut variant="inline" className="text-el-muted" />
          <button
            type="button"
            onClick={close}
            aria-label="Close command palette"
            className="-mr-2 flex size-9 flex-none items-center justify-center rounded-md text-el-muted transition-colors hover:bg-el-hover hover:text-el-ink focus-ring"
          >
            <X size={14} aria-hidden="true" />
          </button>
        </div>

        {/* Results */}
        <ul role="listbox" aria-label="Commands" className="max-h-80 overflow-y-auto py-1.5">
          {results.length === 0 && (
            <li className="px-3.5 py-6 text-center text-xs text-el-muted">
              No commands match &ldquo;{query}&rdquo;.
            </li>
          )}
          {results.map((command, index) => {
            const Icon = command.icon;
            const active = index === activeIndex;
            return (
              <li key={command.id} role="presentation">
                {/* Active row = selected-row rule (§7.4): subtle tint + 2px
                    accent-strong rail; text stays ink. */}
                <button
                  type="button"
                  role="option"
                  aria-selected={active}
                  onClick={() => command.run()}
                  onMouseEnter={() => setActiveIndex(index)}
                  className={`flex w-full items-center gap-3 px-3.5 py-2.5 text-left text-[13px] transition-colors focus-ring-inset ${
                    active
                      ? "bg-el-subtle text-el-ink shadow-[inset_2px_0_0_rgb(var(--el-accent-strong))]"
                      : "text-el-secondary hover:bg-el-subtle"
                  }`}
                >
                  <Icon
                    size={15}
                    className={`flex-none ${active ? "text-el-ink" : "text-el-muted"}`}
                    aria-hidden="true"
                  />
                  <span className="min-w-0 flex-1 truncate">{command.label}</span>
                  {command.hint && (
                    <span className="flex-none truncate text-micro text-el-muted">
                      {command.hint}
                    </span>
                  )}
                  {active && (
                    <ArrowRight
                      size={13}
                      className="flex-none text-el-accent-strong"
                      aria-hidden="true"
                    />
                  )}
                </button>
              </li>
            );
          })}
        </ul>

        {/* Footer hints */}
        <div className="flex items-center gap-4 rounded-b-lg border-t border-el-divider px-3.5 py-2 text-micro text-el-muted">
          <span className="flex items-center gap-1.5">
            <kbd className="rounded-sm border border-el-divider bg-el-subtle px-1.5 py-px text-el-secondary">
              ↑
            </kbd>
            <kbd className="rounded-sm border border-el-divider bg-el-subtle px-1.5 py-px text-el-secondary">
              ↓
            </kbd>
            move
          </span>
          <span className="flex items-center gap-1.5">
            <kbd className="flex items-center rounded-sm border border-el-divider bg-el-subtle px-1.5 py-px text-el-secondary">
              <CornerDownLeft size={10} aria-hidden="true" />
            </kbd>
            open
          </span>
          <span className="flex items-center gap-1.5">
            <kbd className="rounded-sm border border-el-divider bg-el-subtle px-1.5 py-px text-el-secondary">
              esc
            </kbd>
            close
          </span>
        </div>
      </div>
    </div>
  );
}
