import { useBackendHealth } from "../../hooks/useBackendHealth";

/**
 * The single shell-level notice for an unreachable API. Mounted once in the
 * app shell so pages don't each stack their own "could not load" banner:
 * pages keep showing whatever data they have and leave the outage message to
 * this strip. Renders nothing while the API is healthy or still being checked.
 */
export default function ApiOfflineBanner() {
  const health = useBackendHealth();
  if (!health.isError) return null;

  return (
    <div
      role="alert"
      data-testid="api-offline-banner"
      className="flex flex-wrap items-center gap-x-3 gap-y-1 border-b border-el-divider bg-el-danger/10 px-4 py-2 text-xs text-el-danger sm:px-6"
    >
      <span className="font-semibold">API unreachable.</span>
      <span className="text-el-ink">
        Data on this page may be stale and run actions are disabled. Start it
        with <code className="font-mono">just dev</code>, then retry.
      </span>
      <button
        type="button"
        onClick={() => void health.refetch()}
        disabled={health.isFetching}
        className="focus-ring ml-auto min-h-9 rounded-md border border-el-danger/40 px-3 text-el-danger transition-colors hover:bg-el-danger/10 disabled:opacity-60"
      >
        {health.isFetching ? "Checking…" : "Retry"}
      </button>
    </div>
  );
}
