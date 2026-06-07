#!/usr/bin/env node
// Sprint B #3 — Node half of the wire-format drift gate.
//
// Reads the committed JSON Schemas that mirror Python contracts and compiles
// them to TypeScript. CI regenerates + diffs to catch drift.
//
// Schemas produced:
//   tests/schemas/events.schema.json             → src/api/events.generated.ts
//   tests/schemas/step_result.schema.json        → src/api/step_result.generated.ts
//   tests/schemas/dag_response.schema.json       → src/api/dag_response.generated.ts
//   tests/schemas/workflow_input_schema.schema.json → src/api/workflow_input_schema.generated.ts
//   tests/schemas/workflow_editor_step.schema.json → src/api/workflow_editor_step.generated.ts
//   tests/schemas/runs_summary.schema.json       → src/api/runs_summary.generated.ts
//
// Run it manually after editing either Python contract:
//     cd agentic-workflows-v2/ui
//     npm run generate:types
import { readFileSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { compile } from 'json-schema-to-typescript';

// Resolve relative to this file so invocation from other cwds still works.
const SCRIPT_DIR = new URL('.', import.meta.url).pathname;
// On Windows, pathname looks like `/C:/...` — strip the leading slash when
// the next character is a drive letter so `resolve` treats it as absolute.
const NORMALIZED_SCRIPT_DIR =
  process.platform === 'win32' && /^\/[A-Za-z]:/.test(SCRIPT_DIR)
    ? SCRIPT_DIR.slice(1)
    : SCRIPT_DIR;

// ---------------------------------------------------------------------------
// Path helpers
// ---------------------------------------------------------------------------

function schemaPath(filename) {
  return resolve(NORMALIZED_SCRIPT_DIR, '..', '..', 'tests', 'schemas', filename);
}

function outPath(filename) {
  return resolve(NORMALIZED_SCRIPT_DIR, '..', 'src', 'api', filename);
}

// ---------------------------------------------------------------------------
// Shared title-stripping helper
//
// Pydantic stamps every property with a `title` (e.g. "Run Id"), which makes
// json-schema-to-typescript promote every primitive to its own exported alias
// (`RunId`, `RunId1`, ... `Type7`). That pollutes the module's export surface
// with dozens of meaningless names. Stripping property-level titles while
// keeping top-level $defs titles lets the compiler inline primitives and
// preserves the useful names (`WorkflowStartEvent`, `StepEndEvent`, ...).
//
// We only strip titles from leaf property schemas under `$defs.<Model>.properties`
// (for discriminated-union schemas) and from top-level properties directly on
// the root schema object (for flat models like StepResultRecord).
// ---------------------------------------------------------------------------

/**
 * Strip `title` from property-level schemas so json-schema-to-typescript
 * inlines primitives instead of promoting them to exported aliases.
 *
 * Also strip the JSON Schema `default` keyword from property schemas that
 * have no `type` constraint.  Pydantic emits e.g. `{"default": null}` for
 * `Any`-typed fields, and json-schema-to-typescript interprets a bare
 * `{"default": null}` as an object type, producing `{ [k: string]: unknown }`.
 * Removing `default` leaves `{}` which the compiler correctly maps to
 * `unknown` — matching the field's actual `Any` Pydantic annotation.
 */
function isUnconstrainedSchema(prop) {
  return (
    !('type' in prop) &&
    !('anyOf' in prop) &&
    !('$ref' in prop) &&
    !('allOf' in prop) &&
    'default' in prop
  );
}

function stripVariantTitles(prop) {
  if (!Array.isArray(prop.anyOf)) return;
  for (const variant of prop.anyOf) {
    if (variant && typeof variant === 'object' && 'title' in variant) {
      delete variant.title;
    }
  }
}

/**
 * Clean a single property-level schema: remove its generated `title`, the
 * `default` keyword on unconstrained (`Any`) fields, the `items` title for
 * array fields, and titles on `anyOf` variants (nullable fields).
 */
function cleanPropertySchema(prop) {
  if (!prop || typeof prop !== 'object') return;
  if ('title' in prop) {
    delete prop.title;
  }
  // If the property schema has no `type`, `anyOf`, `$ref`, or `allOf`,
  // it is unconstrained (i.e. `Any`). Strip the `default` keyword so
  // json-schema-to-typescript emits `unknown` rather than an object
  // index signature.
  if (isUnconstrainedSchema(prop)) {
    delete prop.default;
  }
  // `items` for array-typed properties also carries a generated title.
  if (prop.items && typeof prop.items === 'object' && 'title' in prop.items) {
    delete prop.items.title;
  }
  // `anyOf` entries (nullable fields) each get a title too.
  stripVariantTitles(prop);
}

function cleanPropertyBag(properties) {
  for (const prop of Object.values(properties)) {
    cleanPropertySchema(prop);
  }
}

function stripPropertyTitles(schema) {
  // Strip from $defs entries (discriminated-union style)
  for (const def of Object.values(schema.$defs ?? {})) {
    if (def && typeof def === 'object' && def.properties) {
      cleanPropertyBag(def.properties);
    }
  }
  // Strip from flat root-level properties (single-model schemas)
  if (schema.properties) {
    cleanPropertyBag(schema.properties);
  }
}

// ---------------------------------------------------------------------------
// events.generated.ts
// ---------------------------------------------------------------------------

const eventsSchema = JSON.parse(readFileSync(schemaPath('events.schema.json'), 'utf8'));
stripPropertyTitles(eventsSchema);

const EVENTS_HEADER = `/**
 * AUTO-GENERATED — DO NOT EDIT BY HAND
 *
 * Regenerate with: npm run generate:types (from agentic-workflows-v2/ui/)
 *
 * Source JSON Schema: agentic-workflows-v2/tests/schemas/events.schema.json
 * Origin Pydantic model: agentic_v2.contracts.events.ExecutionEvent
 *
 * CI fails the 'wire-format-drift' job if this file does not match a fresh
 * regeneration from the committed schema.
 */
`;

const eventsTs = await compile(eventsSchema, 'ExecutionEvent', {
  bannerComment: '',
  additionalProperties: false,
  style: { singleQuote: true, semi: true },
});

const eventsOutPath = outPath('events.generated.ts');
writeFileSync(eventsOutPath, EVENTS_HEADER + eventsTs, 'utf8');
console.log(`Wrote ${eventsOutPath}`);

// ---------------------------------------------------------------------------
// step_result.generated.ts
// ---------------------------------------------------------------------------

const stepResultSchema = JSON.parse(readFileSync(schemaPath('step_result.schema.json'), 'utf8'));
stripPropertyTitles(stepResultSchema);

const STEP_RESULT_HEADER = `/**
 * AUTO-GENERATED — DO NOT EDIT BY HAND
 *
 * Regenerate with: npm run generate:types (from agentic-workflows-v2/ui/)
 *
 * Source JSON Schema: agentic-workflows-v2/tests/schemas/step_result.schema.json
 * Origin Pydantic model: agentic_v2.server.models.StepResultRecord
 *
 * CI fails the 'wire-format-drift' job if this file does not match a fresh
 * regeneration from the committed schema.
 */
`;

const stepResultTs = await compile(stepResultSchema, 'StepResultRecord', {
  bannerComment: '',
  additionalProperties: false,
  style: { singleQuote: true, semi: true },
});

const stepResultOutPath = outPath('step_result.generated.ts');
writeFileSync(stepResultOutPath, STEP_RESULT_HEADER + stepResultTs, 'utf8');
console.log(`Wrote ${stepResultOutPath}`);

// ---------------------------------------------------------------------------
// dag_response.generated.ts
// ---------------------------------------------------------------------------

const dagResponseSchema = JSON.parse(readFileSync(schemaPath('dag_response.schema.json'), 'utf8'));
stripPropertyTitles(dagResponseSchema);

const DAG_RESPONSE_HEADER = `/**
 * AUTO-GENERATED — DO NOT EDIT BY HAND
 *
 * Regenerate with: npm run generate:types (from agentic-workflows-v2/ui/)
 *
 * Source JSON Schema: agentic-workflows-v2/tests/schemas/dag_response.schema.json
 * Origin Pydantic model: agentic_v2.server.models.DAGResponse
 *
 * CI fails the 'wire-format-drift' job if this file does not match a fresh
 * regeneration from the committed schema.
 */
`;

const dagResponseTs = await compile(dagResponseSchema, 'DAGResponse', {
  bannerComment: '',
  additionalProperties: false,
  style: { singleQuote: true, semi: true },
});

const dagResponseOutPath = outPath('dag_response.generated.ts');
writeFileSync(dagResponseOutPath, DAG_RESPONSE_HEADER + dagResponseTs, 'utf8');
console.log(`Wrote ${dagResponseOutPath}`);

// ---------------------------------------------------------------------------
// workflow_input_schema.generated.ts
// ---------------------------------------------------------------------------

const workflowInputSchemaSchema = JSON.parse(
  readFileSync(schemaPath('workflow_input_schema.schema.json'), 'utf8'),
);
stripPropertyTitles(workflowInputSchemaSchema);

const WORKFLOW_INPUT_SCHEMA_HEADER = `/**
 * AUTO-GENERATED — DO NOT EDIT BY HAND
 *
 * Regenerate with: npm run generate:types (from agentic-workflows-v2/ui/)
 *
 * Source JSON Schema: agentic-workflows-v2/tests/schemas/workflow_input_schema.schema.json
 * Origin Pydantic model: agentic_v2.server.models.WorkflowInputSchemaResponse
 *
 * CI fails the 'wire-format-drift' job if this file does not match a fresh
 * regeneration from the committed schema.
 */
`;

const workflowInputSchemaTs = await compile(
  workflowInputSchemaSchema,
  'WorkflowInputSchemaResponse',
  {
    bannerComment: '',
    additionalProperties: false,
    style: { singleQuote: true, semi: true },
  },
);

const workflowInputSchemaOutPath = outPath('workflow_input_schema.generated.ts');
writeFileSync(workflowInputSchemaOutPath, WORKFLOW_INPUT_SCHEMA_HEADER + workflowInputSchemaTs, 'utf8');
console.log(`Wrote ${workflowInputSchemaOutPath}`);

// ---------------------------------------------------------------------------
// workflow_editor_step.generated.ts
// ---------------------------------------------------------------------------

const workflowEditorStepSchema = JSON.parse(
  readFileSync(schemaPath('workflow_editor_step.schema.json'), 'utf8'),
);
stripPropertyTitles(workflowEditorStepSchema);

const WORKFLOW_EDITOR_STEP_HEADER = `/**
 * AUTO-GENERATED — DO NOT EDIT BY HAND
 *
 * Regenerate with: npm run generate:types (from agentic-workflows-v2/ui/)
 *
 * Source JSON Schema: agentic-workflows-v2/tests/schemas/workflow_editor_step.schema.json
 * Origin Pydantic model: agentic_v2.server.models.WorkflowEditorStep
 *
 * CI fails the 'wire-format-drift' job if this file does not match a fresh
 * regeneration from the committed schema.
 */
`;

const workflowEditorStepTs = await compile(
  workflowEditorStepSchema,
  'WorkflowEditorStep',
  {
    bannerComment: '',
    additionalProperties: false,
    style: { singleQuote: true, semi: true },
  },
);

const workflowEditorStepOutPath = outPath('workflow_editor_step.generated.ts');
writeFileSync(workflowEditorStepOutPath, WORKFLOW_EDITOR_STEP_HEADER + workflowEditorStepTs, 'utf8');
console.log(`Wrote ${workflowEditorStepOutPath}`);

// ---------------------------------------------------------------------------
// runs_summary.generated.ts
// ---------------------------------------------------------------------------

const runsSummarySchema = JSON.parse(readFileSync(schemaPath('runs_summary.schema.json'), 'utf8'));
stripPropertyTitles(runsSummarySchema);

const RUNS_SUMMARY_HEADER = `/**
 * AUTO-GENERATED — DO NOT EDIT BY HAND
 *
 * Regenerate with: npm run generate:types (from agentic-workflows-v2/ui/)
 *
 * Source JSON Schema: agentic-workflows-v2/tests/schemas/runs_summary.schema.json
 * Origin Pydantic model: agentic_v2.server.models.RunsSummaryResponse
 *
 * CI fails the 'wire-format-drift' job if this file does not match a fresh
 * regeneration from the committed schema.
 */
`;

const runsSummaryTs = await compile(runsSummarySchema, 'RunsSummaryResponse', {
  bannerComment: '',
  additionalProperties: false,
  style: { singleQuote: true, semi: true },
});

const runsSummaryOutPath = outPath('runs_summary.generated.ts');
writeFileSync(runsSummaryOutPath, RUNS_SUMMARY_HEADER + runsSummaryTs, 'utf8');
console.log(`Wrote ${runsSummaryOutPath}`);
