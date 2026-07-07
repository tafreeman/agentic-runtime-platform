/**
 * Pure helpers for structured (visual-mode) workflow document editing.
 *
 * The raw YAML document (as JSON) is the single source of truth for edits:
 * every helper returns a NEW document object, leaving the input untouched, so
 * React state updates stay referentially honest and undo-by-refetch stays
 * trivial. Field names mirror the server-side workflow schema.
 */

export type RawDocument = Record<string, unknown>;
export type RawStep = Record<string, unknown>;

export interface EdgeInfo {
  source: string;
  target: string;
  /** Target-step input entries whose expressions reference the source step. */
  mappings: { key: string; expression: string }[];
  /** Target step's `when` conditional, if any. */
  when: string | null;
}

/** The steps array of a document (always a fresh array of step objects). */
export function getSteps(document: RawDocument): RawStep[] {
  const steps = document.steps;
  if (!Array.isArray(steps)) return [];
  return steps.filter(
    (step): step is RawStep => typeof step === "object" && step !== null
  );
}

export function getStep(document: RawDocument, name: string): RawStep | null {
  return getSteps(document).find((step) => step.name === name) ?? null;
}

function withSteps(document: RawDocument, steps: RawStep[]): RawDocument {
  return { ...document, steps };
}

/**
 * Merge `patch` into the named step. A patch value of `undefined` deletes the
 * key from the step (used to clear optional fields back to defaults).
 */
export function patchStep(
  document: RawDocument,
  name: string,
  patch: RawStep
): RawDocument {
  const steps = getSteps(document).map((step) => {
    if (step.name !== name) return step;
    const next: RawStep = { ...step };
    for (const [key, value] of Object.entries(patch)) {
      if (value === undefined) {
        delete next[key];
      } else {
        next[key] = value;
      }
    }
    return next;
  });
  return withSteps(document, steps);
}

/** A unique name for a newly added step (`step_1`, `step_2`, ...). */
export function nextStepName(document: RawDocument): string {
  const existing = new Set(getSteps(document).map((step) => String(step.name)));
  let index = existing.size + 1;
  while (existing.has(`step_${index}`)) index += 1;
  return `step_${index}`;
}

/** Append a new step; when `afterStep` is given, the new step depends on it. */
export function addStep(
  document: RawDocument,
  afterStep?: string | null
): { document: RawDocument; name: string } {
  const name = nextStepName(document);
  const step: RawStep = {
    name,
    agent: "tier2_assistant",
    description: "",
    depends_on: afterStep ? [afterStep] : [],
    inputs: {},
    outputs: {},
  };
  return { document: withSteps(document, [...getSteps(document), step]), name };
}

/**
 * Drop input entries on `step` whose expressions reference `sourceName`.
 * Returns the original object when nothing referenced it.
 */
function scrubInputRefs(step: RawStep, sourceName: string): RawStep {
  const inputs = step.inputs;
  if (typeof inputs !== "object" || inputs === null) return step;
  const marker = `steps.${sourceName}.`;
  const entries = Object.entries(inputs as Record<string, unknown>);
  const kept = entries.filter(
    ([, value]) => !(typeof value === "string" && value.includes(marker))
  );
  if (kept.length === entries.length) return step;
  return { ...step, inputs: Object.fromEntries(kept) };
}

/**
 * Remove a step, scrub it from every other step's depends_on, and drop
 * input mappings that referenced its outputs (they would dangle otherwise).
 */
export function removeStep(document: RawDocument, name: string): RawDocument {
  const steps = getSteps(document)
    .filter((step) => step.name !== name)
    .map((step) => {
      const scrubbed = scrubInputRefs(step, name);
      const deps = Array.isArray(scrubbed.depends_on) ? scrubbed.depends_on : [];
      if (!deps.includes(name)) return scrubbed;
      return { ...scrubbed, depends_on: deps.filter((dep) => dep !== name) };
    });
  return withSteps(document, steps);
}

/** Add `source` to `target`'s depends_on (no-op for self/duplicate/cycle-free checks beyond identity). */
export function addDependency(
  document: RawDocument,
  source: string,
  target: string
): RawDocument {
  if (source === target) return document;
  const steps = getSteps(document).map((step) => {
    if (step.name !== target) return step;
    const deps = Array.isArray(step.depends_on)
      ? step.depends_on.map(String)
      : [];
    if (deps.includes(source)) return step;
    return { ...step, depends_on: [...deps, source] };
  });
  return withSteps(document, steps);
}

/**
 * Remove `source` from `target`'s depends_on, and drop the target's input
 * mappings that read from `source` — a severed edge must not leave stale
 * data references behind.
 */
export function removeDependency(
  document: RawDocument,
  source: string,
  target: string
): RawDocument {
  const steps = getSteps(document).map((step) => {
    if (step.name !== target) return step;
    const scrubbed = scrubInputRefs(step, source);
    const deps = Array.isArray(scrubbed.depends_on)
      ? scrubbed.depends_on.map(String)
      : [];
    return { ...scrubbed, depends_on: deps.filter((dep) => dep !== source) };
  });
  return withSteps(document, steps);
}

/** Details for the edge `source -> target`: data mappings + condition. */
export function edgeInfo(
  document: RawDocument,
  source: string,
  target: string
): EdgeInfo {
  const targetStep = getStep(document, target);
  const marker = `steps.${source}.`;
  const mappings: EdgeInfo["mappings"] = [];
  const inputs = targetStep?.inputs;
  if (typeof inputs === "object" && inputs !== null) {
    for (const [key, value] of Object.entries(inputs)) {
      if (typeof value === "string" && value.includes(marker)) {
        mappings.push({ key, expression: value });
      }
    }
  }
  return {
    source,
    target,
    mappings,
    when: typeof targetStep?.when === "string" ? targetStep.when : null,
  };
}

/** Update one input-mapping expression on a step. */
export function patchStepInput(
  document: RawDocument,
  stepName: string,
  inputKey: string,
  expression: string
): RawDocument {
  const step = getStep(document, stepName);
  const inputs =
    typeof step?.inputs === "object" && step.inputs !== null
      ? { ...(step.inputs as Record<string, unknown>) }
      : {};
  inputs[inputKey] = expression;
  return patchStep(document, stepName, { inputs });
}

/**
 * Derive the DAG view (nodes + labeled edges) from a draft document so the
 * canvas live-updates with unsaved edits. Mirrors the server's DAG endpoint
 * enrichment: edge labels list the target inputs fed by the source step.
 */
export function deriveGraph(document: RawDocument): {
  nodes: {
    id: string;
    agent: string | null;
    description: string;
    depends_on: string[];
    tier: string | null;
    persona: string | null;
    model: string | null;
  }[];
  edges: {
    id: string;
    source: string;
    target: string;
    label: string | null;
    mappings: string[];
    when: string | null;
  }[];
} {
  const steps = getSteps(document);
  const nodes = steps.map((step) => ({
    id: String(step.name ?? ""),
    agent: typeof step.agent === "string" ? step.agent : null,
    description: typeof step.description === "string" ? step.description : "",
    depends_on: Array.isArray(step.depends_on)
      ? step.depends_on.map(String)
      : [],
    tier: typeof step.tier === "string" ? step.tier : null,
    persona: typeof step.persona === "string" ? step.persona : null,
    model:
      typeof step.model === "string"
        ? step.model
        : typeof step.model_override === "string"
          ? step.model_override
          : null,
  }));

  const edges = nodes.flatMap((node) =>
    node.depends_on.map((source) => {
      const info = edgeInfo(document, source, node.id);
      return {
        id: `${source}->${node.id}`,
        source,
        target: node.id,
        label:
          info.mappings.length > 0
            ? info.mappings.map((m) => m.key).join(", ")
            : null,
        mappings: info.mappings.map((m) => `${m.key} = ${m.expression}`),
        when: info.when,
      };
    })
  );

  return { nodes, edges };
}

/** Structural equality for dirty-state tracking. */
export function documentsEqual(a: RawDocument | null, b: RawDocument | null): boolean {
  return JSON.stringify(a) === JSON.stringify(b);
}

/** Deep-clone a document (edits never share references with the query cache). */
export function cloneDocument(document: RawDocument): RawDocument {
  return JSON.parse(JSON.stringify(document)) as RawDocument;
}
