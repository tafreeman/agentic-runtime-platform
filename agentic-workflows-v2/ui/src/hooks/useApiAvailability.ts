import { useBackendHealth } from "./useBackendHealth";
import { API_START_HINT } from "../lib/apiErrors";

export interface ApiAvailability {
  /** True once the health check has failed — the API is unreachable. */
  readonly apiDown: boolean;
  /** True while the first health check is still in flight. */
  readonly checking: boolean;
  /**
   * Why API-backed actions are unavailable, or `undefined` when they are
   * available. Use it as the disabled-button reason (title / description).
   */
  readonly reason: string | undefined;
}

/**
 * Availability of the backend API for gating actions (start run, save, …).
 *
 * Reads the shared `["backend-health"]` cache via {@link useBackendHealth}
 * without polling — the app shell owns the single poller — so any number of
 * consumers cost no extra requests.
 */
export function useApiAvailability(): ApiAvailability {
  const health = useBackendHealth();
  const apiDown = health.isError;
  return {
    apiDown,
    checking: health.isPending,
    reason: apiDown ? `The API server is unreachable. ${API_START_HINT}` : undefined,
  };
}
