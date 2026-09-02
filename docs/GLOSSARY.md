# Glossary

This page defines terms used in the repository. Source paths are relative to
`agentic-workflows-v2/` unless stated otherwise.

## Workflow runtime

**Adapter**

An implementation of the runtime execution interface. The CLI supports:

- `langchain`, which compiles a workflow to LangGraph and is the default for
  named YAML workflows
- `native`, which runs the repository's dependency-light DAG executor

See `agentic_v2/adapters/`.

**Agent**

The function or model-backed worker that executes one workflow step. A step
names its agent with the `agent:` field.

See `agentic_v2/engine/agent_resolver.py`.

**Agent tier**

A number from 0 through 5 used to select model capacity, output limits, and
available tools. Tier 0 is intended for deterministic or lowest-capability
work, but the current resolver can still pass a tier-0 agent through the model
client. A tier number alone does not prove that no provider path is involved.

**Checkpoint**

Saved workflow state that a compatible execution engine can use to resume work.
Checkpoint support is an optional engine capability, not a guarantee for every
adapter.

See `agentic_v2/core/protocols.py`.

**Condition**

A `when:` expression on a workflow step. The step runs only when the expression
resolves to true. A skipped step has no usable output, so downstream mappings
should use `coalesce()` when they also accept another source.

**DAG**

A directed acyclic graph. Workflow steps are graph nodes and `depends_on`
values are edges. The runtime rejects missing dependencies and cycles.

See `agentic_v2/engine/dag.py`.

**Execution context**

The state for one workflow run. It holds workflow inputs, step results,
services, and lifecycle events.

See `agentic_v2/engine/context.py`.

**Expression**

A value inside `${...}`. Expressions can read inputs, step outputs, and context
values. They support a restricted set of comparisons, boolean operations,
arithmetic, collection literals, and `coalesce()`. Imports and arbitrary
function calls are rejected.

See `agentic_v2/engine/expressions.py`.

**Fan-out / fan-in**

A dependency shape where several independent steps run after the same parent,
then a later step waits for all of them.

**Loop**

Bounded repetition of one step. `loop_until:` defines the stop condition and
`loop_max:` limits how many times the step can run.

**Step**

One unit of work in a workflow. A YAML step has a name and agent, and may
declare dependencies, inputs, outputs, conditions, artifact contracts, tools,
and a bounded loop.

**Workflow**

A YAML file that declares inputs, steps, dependencies, and outputs. Built-in
definitions live in `agentic_v2/workflows/definitions/`.

See [Workflow authoring](WORKFLOW_AUTHORING.md).

## Contracts and artifacts

**Artifact contract**

Optional validation attached to a step input or output. The current
`code_artifact` contract accepts source code as a non-empty relative-path map
or as complete `FILE`/`ENDFILE` blocks. It rejects unsafe paths, empty content,
and placeholder-only output.

See `agentic_v2/artifact_contracts.py`.

**Contract**

A typed boundary model shared by runtime components. Most public contracts use
Pydantic models under `agentic_v2/contracts/`.

**Protocol**

A Python structural interface. A class satisfies a protocol by providing the
required methods and properties; it does not need to inherit from the protocol.

See `agentic_v2/core/protocols.py`.

**Run record**

The JSON representation of a completed workflow run. Run records support the
dashboard, comparison, and offline evaluation routes.

See `agentic_v2/workflows/run_logger.py`.

## Models and tools

**Fallback chain**

An ordered list of model identifiers. When a model is unavailable or a call
fails in a retryable way, the router can try the next configured model.

**Model provider**

A service or local runtime that accepts model requests. The repository has
backends for cloud providers and local runtimes. Availability depends on
installed extras, credentials, and reachable endpoints.

See [Configuration](configuration.md).

**Model tier**

See **Agent tier**.

**Tool**

A named operation an agent can call, such as reading a file or making an HTTP
request. The runtime filters tools by tier and by a step's `tools:` allowlist.
An empty allowlist disables tools for that step.

See `agentic_v2/tools/` and `agentic_v2/engine/tool_execution.py`.

**Tool approval**

A policy decision applied before a tool with side effects runs. Approval
behavior depends on the configured policy and provider.

## Retrieval-augmented generation

**RAG**

Retrieval-augmented generation. The application searches indexed content and
adds selected passages to a model request.

**Chunk**

A section of a loaded document. Chunks include text, an identifier, position,
and metadata.

**Embedding**

A numeric vector produced from text for similarity search. Provider embeddings
can support semantic search.

**BM25**

A keyword-ranking algorithm used for sparse lexical search.

**Hybrid retrieval**

Combining vector search and BM25 results, typically merged with reciprocal
rank fusion.

**Reciprocal rank fusion (RRF)**

A method for merging ranked result lists using each result's position rather
than trying to compare provider-specific scores directly.

**Vector store**

A component that stores vectors and finds nearby vectors.

## Evaluation

**Criterion**

One named part of a rubric, with a weight and scoring guidance.

**Dataset**

Input cases and expected values used by an evaluation runner.

**Evaluator**

Code that scores a result. The evaluation package includes structural,
pattern-based, standard, quality, and model-backed evaluators.

**LLM judge**

A model-backed evaluator that scores output against explicit criteria. Its
score is evidence from that judge configuration, not a human verdict.

**Rubric**

A set of weighted criteria used to score output. Criterion weights must sum to
1.0 within the loader's tolerance.

**Runner**

Code that applies an evaluator to one or more dataset cases and collects the
results.

See [Evaluation framework](architecture-eval.md).

## Operations

**No-LLM mode**

Development mode enabled with `AGENTIC_NO_LLM=1`. Supported model-client paths
return deterministic placeholder text, which is useful for interface tests. It
does not make every subsystem deterministic.

See [No-LLM development mode](NO_LLM_MODE.md).

**OpenTelemetry (OTEL)**

The tracing standard used by optional runtime instrumentation. Tracing is
disabled unless configured.

**Readiness check**

An endpoint that reports whether the server is ready to accept work. In this
repository it is `GET /api/health/ready`.

**Smoke test**

A small check that confirms a basic path works. `test_deterministic` is the
recommended provider-free workflow smoke test.
