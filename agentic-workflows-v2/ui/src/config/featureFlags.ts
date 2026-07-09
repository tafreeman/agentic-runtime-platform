export function parseBooleanFlag(value: unknown): boolean {
  if (typeof value === "boolean") return value;
  if (typeof value !== "string") return false;

  const normalized = value.trim().toLowerCase();
  return normalized === "1" || normalized === "true" || normalized === "yes" || normalized === "on";
}

export function isWorkflowBuilderEnabled(): boolean {
  return parseBooleanFlag(__AGENTIC_ENABLE_WORKFLOW_BUILDER__);
}
