import { useBackendHealth } from "../../hooks/useBackendHealth";
import BPill from "./BPill";

export default function ConsoleStatus() {
  const health = useBackendHealth();

  const connected = health.isSuccess;
  const loading = health.isLoading || health.isFetching;
  // Server-reported mode (not a client build-time flag) so the badge can
  // never drift from how the server process was actually started.
  const noLlmMode = health.data?.no_llm_mode ?? false;

  let pillTone: "ok" | "dim" | "err";
  if (connected) {
    pillTone = "ok";
  } else if (loading) {
    pillTone = "dim";
  } else {
    pillTone = "err";
  }

  let pillLabel: string;
  if (connected) {
    pillLabel = "api connected";
  } else if (loading) {
    pillLabel = "api checking";
  } else {
    pillLabel = "api disconnected";
  }

  return (
    <div className="flex flex-none items-center gap-1.5 whitespace-nowrap" data-testid="console-status">
      <BPill tone={pillTone}>
        {pillLabel}
      </BPill>
      {connected && (
        <span className="font-mono text-micro text-el-muted">
          v{health.data.version}
        </span>
      )}
      {noLlmMode && <BPill tone="clay">no-llm</BPill>}
    </div>
  );
}
