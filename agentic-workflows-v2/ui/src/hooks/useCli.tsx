import {
  createContext,
  useCallback,
  useContext,
  useState,
  type ReactNode,
} from "react";

/**
 * CLI parity — a tiny shared store for the "CLI twin" of the last UI action.
 * Pages/components call `setCli("agentic runs inspect …")` as the user acts;
 * the sticky {@link CliStrip} at the bottom renders it. Every meaningful UI
 * action has an equivalent command, so the console teaches the CLI.
 */
interface CliContextValue {
  cli: string;
  setCli: (command: string) => void;
}

// The twin shown before any UI action. A real command from
// agentic_v2/cli/main.py (`agentic list [workflows|agents|tools|adapters]`);
// there is no `runs list` command and no environment concept to flag.
const DEFAULT_CLI = "agentic list workflows";

const CliContext = createContext<CliContextValue>({
  cli: DEFAULT_CLI,
  setCli: () => {},
});

export function CliProvider({ children }: { children: ReactNode }) {
  const [cli, setCliState] = useState(DEFAULT_CLI);
  const setCli = useCallback((command: string) => setCliState(command), []);
  return (
    <CliContext.Provider value={{ cli, setCli }}>
      {children}
    </CliContext.Provider>
  );
}

// eslint-disable-next-line react-refresh/only-export-components
export function useCli(): CliContextValue {
  return useContext(CliContext);
}
