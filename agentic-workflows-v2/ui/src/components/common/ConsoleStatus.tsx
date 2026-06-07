import { useQuery } from "@tanstack/react-query";
import { healthCheck } from "../../api/client";
import BPill from "./BPill";

interface ConsoleStatusProps {
  noLlmMode?: boolean;
}

export default function ConsoleStatus({ noLlmMode = false }: Readonly<ConsoleStatusProps>) {
  const health = useQuery({
    queryKey: ["backend-health"],
    queryFn: healthCheck,
    retry: false,
    refetchInterval: 15_000,
  });

  const connected = health.isSuccess;
  const loading = health.isLoading || health.isFetching;

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
    <div className="flex items-center gap-1.5" data-testid="console-status">
      <BPill tone={pillTone}>
        {pillLabel}
      </BPill>
      {connected && (
        <span className="font-mono text-[10px] text-b-text-faint">
          v{health.data.version}
        </span>
      )}
      {noLlmMode && <BPill tone="clay">no-llm</BPill>}
    </div>
  );
}
