import { useQuery } from "@tanstack/react-query";
import {
  listWorkflows,
  getWorkflowDAG,
  getWorkflowEditor,
  listEvaluationDatasets,
} from "../api/client";

export function useWorkflows() {
  return useQuery({
    queryKey: ["workflows"],
    queryFn: () => listWorkflows().then((r) => r.workflows),
  });
}

export function useWorkflowDAG(name: string | undefined) {
  return useQuery({
    queryKey: ["workflow-dag", name],
    queryFn: () => getWorkflowDAG(name!),
    enabled: !!name,
  });
}

export function useWorkflowEditor(name: string | undefined, enabled = true) {
  return useQuery({
    queryKey: ["workflow-editor", name],
    queryFn: () => getWorkflowEditor(name!),
    enabled: enabled && !!name,
  });
}

export function useEvaluationDatasets() {
  return useQuery({
    queryKey: ["evaluation-datasets"],
    queryFn: () => listEvaluationDatasets(),
  });
}
