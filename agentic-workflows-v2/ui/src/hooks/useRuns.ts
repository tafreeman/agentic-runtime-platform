import { useQuery } from "@tanstack/react-query";
import {
  listRuns,
  getRunDetail,
  getRunsSummary,
  getRunEvaluationDetail,
} from "../api/client";

export interface UseRunsOptions {
  /**
   * Auto-refresh ("live tail") — polls every 5s when true (the default,
   * preserving historical behavior). The Runs page exposes this as the
   * "Live tail" switch from the console design kit.
   */
  live?: boolean;
}

export function useRuns(workflow?: string, options?: UseRunsOptions) {
  const live = options?.live ?? true;
  return useQuery({
    queryKey: ["runs", workflow],
    queryFn: () => listRuns(workflow),
    refetchInterval: live ? 5000 : false,
    refetchIntervalInBackground: false,
  });
}

export function useRunDetail(filename: string | undefined) {
  return useQuery({
    queryKey: ["run", filename],
    queryFn: () => getRunDetail(filename!),
    enabled: !!filename,
  });
}

export function useRunsSummary(workflow?: string) {
  return useQuery({
    queryKey: ["runs-summary", workflow],
    queryFn: () => getRunsSummary(workflow),
  });
}

export function useRunEvaluationDetail(filename: string | undefined) {
  return useQuery({
    queryKey: ["run-evaluation", filename],
    queryFn: () => getRunEvaluationDetail(filename!),
    enabled: !!filename,
  });
}
