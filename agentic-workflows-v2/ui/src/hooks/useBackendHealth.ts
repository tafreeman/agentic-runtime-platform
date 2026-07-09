import { useQuery } from "@tanstack/react-query";
import { healthCheck } from "../api/client";

/**
 * Shared backend-health query. All consumers read one `["backend-health"]`
 * cache entry, but only the designated poller (ConsoleHeader, always mounted in
 * the app shell) passes `poll: true` to own the single 15s refetch interval;
 * secondary consumers (Sidebar, ConsoleStatus) omit it and just subscribe to
 * the cache. The whole UI therefore issues one `/api/health` request per
 * interval instead of one per mounted observer.
 *
 * Note: `refetchInterval` is per-observer and is NOT suppressed by `staleTime`
 * (that only gates stale-triggered refetches like mount/focus/reconnect), so a
 * single polling owner — not `staleTime` alone — is what actually dedupes the
 * interval traffic.
 */
export function useBackendHealth({ poll = false }: { poll?: boolean } = {}) {
  return useQuery({
    queryKey: ["backend-health"],
    queryFn: healthCheck,
    retry: false,
    staleTime: 10_000,
    refetchInterval: poll ? 15_000 : false,
  });
}
