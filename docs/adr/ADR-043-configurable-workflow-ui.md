# ADR-043: Configurable Workflow UI — Per-Step Node Config, UI Settings Store, and Run Comparison

**Status:** Accepted
**Date:** 2026-07-07
**Related:** `agentic_v2/langchain/config.py` (StepConfig),
`agentic_v2/langchain/personas.py` (new), `agentic_v2/ui_settings.py` (new),
`agentic_v2/server/routes/{catalog,settings_routes}.py` (new),
`agentic_v2/server/models_settings.py` (new), `POST /api/eval/compare`
(`server/routes/runs.py`), ADR-014 (wire-format drift), ADR-040 (curated
model registry)

## Context

The web UI could visualize workflows but not configure them: the editor was a
raw-YAML textarea with a read-only inspector, DAG edges were anonymous
arrows, model routing was env-var-only, and evaluation offered no way to
compare two runs of the same task. Making the platform usable from the front
end (ComfyUI-style: click a node or edge, edit everything that matters)
requires new wire contracts, per-step engine plumbing, and a place to persist
UI-managed settings.

## Decision

1. **Per-step node config lives in the workflow YAML schema.** `StepConfig`
   gains `model_params` (`temperature`/`top_p`/`max_tokens`, validated
   ranges), `persona` (registry id), and `observers` (channel allowlist:
   `trace`/`websocket`/`scoring`; `null` = all). Temperature threads through
   `create_agent → get_model_for_tier → get_chat_model`; `top_p`/`max_tokens`
   are applied generically via Pydantic `model_copy` with per-provider field
   aliasing (`num_predict` for Ollama, etc.), so unsupported params degrade
   silently instead of breaking a provider.

2. **Personas are a first-class registry**
   (`config/defaults/personas.yaml`), combining pre-canned BMAD-style
   personas (Winston the architect, Mary, James, Quinn) with the existing
   `prompts/*.md` role prompts. Resolution order: `step.persona` >
   `step.prompt_file` > role-from-agent-name > generic fallback.

3. **UI-managed settings persist in a JSON store**
   (`agentic_v2/ui_settings.py`, default `<repo>/.agentic_ui_settings.json`,
   env override `AGENTIC_UI_SETTINGS_PATH`) — NOT in `model_registry.yaml`
   or env vars, which stay deployment-owned. It holds provider endpoint
   entries (base URL + **the name of** the credential env var, never the
   secret), tier rerank overrides, and model capability tags. Routing
   consumes tier overrides between the env-var pin and the probed default:
   `model_override > AGENTIC_MODEL_TIER_{n} > UI override > probed default >
   registry chain`. Rationale: a UI edit should never silently beat an
   explicit deployment pin.

4. **DAG edges are self-describing.** The DAG endpoint enriches each edge
   with `id`, `label` (target input keys fed by the source), `mappings`
   (full `key = ${...}` expressions), and the target's `when` — the editor
   renders labels and an edge inspector instead of anonymous arrows, and the
   same derivation runs client-side against unsaved drafts.

5. **Run comparison is replay-based.** `POST /api/eval/compare` re-scores two
   captured run logs under one rubric (same path as re-evaluate) and returns
   per-criterion deltas plus a winner. Nothing persists and no workflow
   re-executes; comparing prompt/workflow variants means running each once,
   then comparing the logs.

6. **Media inputs are data URLs, summarized in prompts.** `image`/`audio`
   typed workflow inputs arrive as `data:` URLs from the run form;
   `build_task_description` replaces payloads with `<media mime ~N KB>`
   placeholders so base64 never burns prompt context. True multimodal
   message construction is future work.

## Consequences

- Wire-format change: `WorkflowEditorStep` (+`model`/`persona`/`observers`/
  `model_params`), `DAGNodeModel` (+`persona`/`model`), `DAGEdgeModel`
  (+`id`/`label`/`mappings`/`when`). Schemas and generated TS committed per
  ADR-014.
- `.agentic_ui_settings.json` is per-instance mutable state (gitignored);
  multi-worker deployments share it via the filesystem only — Redis-backed
  parity is future work if needed.
- Observer filtering is coarse (per-channel gating of existing emitters),
  not a pluggable observer framework.
