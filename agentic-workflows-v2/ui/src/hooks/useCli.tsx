import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { useLocation } from "react-router-dom";

/**
 * CLI equivalents — a tiny shared store for the real `agentic` command that
 * matches what the user is looking at or just did. The sticky
 * {@link CliStrip} renders it.
 *
 * Only real commands from agentic_v2/cli/main.py appear here (`run`,
 * `compare`, `orchestrate`, `resume`, `list <workflows|agents|tools|adapters>`,
 * `validate`, `serve`, `version`). Most views — runs, live execution,
 * evaluations, datasets, the model router — have no CLI counterpart, and for
 * those the store holds `null` so the strip says so instead of inventing one.
 */
export type CliCommand = string | null;

interface CliContextValue {
  cli: CliCommand;
  setCli: (command: CliCommand) => void;
  /** Re-derive the command for a newly visited route (see {@link cliForPath}). */
  syncRoute: (pathname: string) => void;
}

/**
 * The real CLI equivalent of a route, given the command shown before the
 * navigation. Live execution keeps an `agentic run …` command that started
 * the run being watched (the CLI streams the same run in the terminal);
 * every other route without a counterpart clears the strip.
 */
// eslint-disable-next-line react-refresh/only-export-components
export function cliForPath(pathname: string, previous: CliCommand = null): CliCommand {
  if (pathname === "/workflows") return "agentic list workflows";
  const edit = /^\/workflows\/([^/]+)\/edit\/?$/.exec(pathname);
  if (edit?.[1]) return `agentic validate ${decodeURIComponent(edit[1])}`;
  const detail = /^\/workflows\/([^/]+)\/?$/.exec(pathname);
  // The detail page previews the DAG/inputs: the CLI's validate-and-plan run.
  if (detail?.[1]) return `agentic run ${decodeURIComponent(detail[1])} --dry-run`;
  if (pathname.startsWith("/live/")) {
    const startedRun =
      previous?.startsWith("agentic run ") && !previous.includes("--dry-run");
    return startedRun ? previous : null;
  }
  return null;
}

const CliContext = createContext<CliContextValue>({
  cli: null,
  setCli: () => {},
  syncRoute: () => {},
});

export function CliProvider({ children }: { children: ReactNode }) {
  const [cli, setCliState] = useState<CliCommand>(null);
  const setCli = useCallback((command: CliCommand) => setCliState(command), []);
  const syncRoute = useCallback(
    (pathname: string) => setCliState((prev) => cliForPath(pathname, prev)),
    [],
  );
  const value = useMemo(() => ({ cli, setCli, syncRoute }), [cli, setCli, syncRoute]);
  return <CliContext.Provider value={value}>{children}</CliContext.Provider>;
}

// eslint-disable-next-line react-refresh/only-export-components
export function useCli(): CliContextValue {
  return useContext(CliContext);
}

/**
 * Keeps the strip in step with the current route: on every navigation the
 * command is re-derived with {@link cliForPath}. Mount once inside both the
 * router and {@link CliProvider} (App does this next to the `g` shortcuts).
 */
// eslint-disable-next-line react-refresh/only-export-components
export function useCliRouteSync(): void {
  const { pathname } = useLocation();
  const { syncRoute } = useCli();
  useEffect(() => {
    syncRoute(pathname);
  }, [pathname, syncRoute]);
}
