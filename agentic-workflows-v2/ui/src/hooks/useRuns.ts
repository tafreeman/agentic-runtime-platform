import { useQuery } from "@tanstack/react-query";
import {
  listRuns,
  getRunDetail,
  getRunsSummary,
  getRunEvaluationDetail,
} from "../api/client";

export function useRuns(workflow?: string) {
  return useQuery({
    queryKey: ["runs", workflow],
    queryFn: () => listRuns(workflow),
    refetchInterval: 5000,
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
