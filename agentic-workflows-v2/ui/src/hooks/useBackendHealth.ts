import { useQuery } from "@tanstack/react-query";
import { healthCheck } from "../api/client";

/**
 * Shared backend-health query used by ConsoleHeader, Sidebar, and
 * ConsoleStatus. One `["backend-health"]` cache entry backs all three
 * observers; the `staleTime` keeps them on the cached response instead of each
 * independently firing its own `refetchInterval` request (React Query only
 * shares a fetch across observers while the data is fresh). Centralising the
 * key + options here also removes the previously triplicated config.
 */
export function useBackendHealth() {
  return useQuery({
    queryKey: ["backend-health"],
    queryFn: healthCheck,
    retry: false,
    staleTime: 10_000,
    refetchInterval: 15_000,
  });
}
