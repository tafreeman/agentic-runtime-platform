import { WifiOff } from "lucide-react";
import { useBackendHealth } from "../../hooks/useBackendHealth";

/**
 * The single shell-level notice for an unreachable API. Mounted once in the
 * app shell so pages don't each stack their own "could not load" banner:
 * pages keep showing whatever data they have and leave the outage message to
 * this strip. Renders nothing while the API is healthy or still being checked.
 *
 * A full-width band, so it takes a hairline bottom rule rather than a
 * rounded box (design system §7.3: radius-none for full-width bands).
 */
export default function ApiOfflineBanner() {
  const health = useBackendHealth();
  if (!health.isError) return null;

  return (
    <div
      role="alert"
      data-testid="api-offline-banner"
      className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-el-danger/40 bg-el-danger-soft px-4 py-2 text-xs text-el-danger sm:px-6"
    >
      <WifiOff aria-hidden="true" className="size-4 flex-none" />
      <span className="font-semibold">API unreachable.</span>
      <span className="text-el-ink">
        Data on this page may be stale and run actions are disabled. Start it
        with <code className="font-mono">just dev</code>, then retry.
      </span>
      <button
        type="button"
        onClick={() => void health.refetch()}
        disabled={health.isFetching}
        className="focus-ring ml-auto inline-flex min-h-9 items-center rounded-md border border-el-danger/40 px-3 font-medium text-el-danger transition-colors hover:bg-el-danger/10 disabled:opacity-60"
      >
        {health.isFetching ? "Checking…" : "Retry"}
      </button>
    </div>
  );
}
