# AI implementation evidence standard

Use this standard when describing the repository in a README, release note,
architecture document, audit, résumé, demo, or review. A claim must be narrow
enough that another engineer can verify it.

This file does not grade the repository. Point-in-time scorecards belong in a
dated report, not in the maintained product documentation.

## Evidence labels

Use one of these labels when the level of proof matters:

| Label | Meaning |
| --- | --- |
| **SOURCE-VERIFIED** | The cited implementation path exists and was inspected. No execution claim is made. |
| **TEST-VERIFIED** | A named automated test exercised the behavior and passed in the stated environment. |
| **RUNTIME-VERIFIED** | A named command or request exercised the real local path and produced the recorded result. |
| **LIVE-VERIFIED** | A real external provider or service was called successfully. Record the provider, model or service, date, and safe result summary. |
| **INFERRED** | The conclusion follows from cited evidence but was not directly exercised. State the inference. |
| **UNVERIFIED** | Evidence was unavailable, blocked, or not run. Do not restate the claim as fact. |

Passing a mock or no-LLM test is not live-provider evidence. Finding a class is
not proof that the class is constructed in the active path.

## Rules for claims

1. Cite the active call path, not only a configuration default or unused
   module.
2. Distinguish an implemented component from a component enabled by default.
3. Name optional dependencies and settings required for the claimed behavior.
4. State the environment and command for runtime evidence.
5. Record failures and warnings as part of the result.
6. Do not convert missing evidence into a defect. Use **UNVERIFIED** until the
   relevant path is checked.
7. Do not claim production readiness, security, compliance, scale, or model
   quality from unit tests alone.
8. Prefer stable behavior and thresholds over test counts or line counts.
9. Link to the test, workflow, or generated artifact that makes the claim
   reproducible.
10. Add a date to live-provider, performance, dependency, and platform-support
    claims because they can change without a source edit.

## Claim format

Use this compact structure:

```text
Claim:
Evidence level:
Scope:
Evidence:
Command or test:
Observed result:
Limits:
Verified:
```

Example:

```text
Claim: Workflow inputs are validated against the selected workflow schema.
Evidence level: TEST-VERIFIED
Scope: FastAPI POST /api/run
Evidence: agentic_v2/server/routes/workflows.py
Command or test: python -m pytest tests/test_server_workflows.py -q
Observed result: Invalid inputs returned HTTP 400 in the tested cases.
Limits: Does not cover every workflow or external reverse-proxy behavior.
Verified: 2026-07-28
```

## Minimum evidence by subject

### Workflow execution

Required:

- workflow definition;
- loader or validator path;
- active adapter path;
- engine behavior test; and
- one deterministic runtime command when practical.

For model-backed behavior, add a separate live-provider result. Do not use
`AGENTIC_NO_LLM=1` as evidence of output quality.

### Model routing and fallback

Required:

- the registry or discovery source;
- the constructed backend path;
- selection and failure-classification tests; and
- a runtime result for each provider named in a public claim.

A model listed in a catalog may still be unavailable, unsupported by the
selected adapter, missing credentials, or rejected by provider policy.

### Retrieval

Required:

- loader and chunking path;
- embedding implementation actually constructed;
- vector-store implementation actually constructed;
- retrieval and context-assembly tests; and
- persistence behavior across process boundaries.

The current `agentic rag` CLI uses a process-local hash embedder and in-memory
store. It is useful for exercising the command path, but it is not evidence of
semantic retrieval or persistent indexing. Provider-backed embeddings and
LanceDB require a separately verified construction path.

### Evaluation

Required:

- dataset or sample source;
- rubric version;
- runner and scorer path;
- number of runs;
- threshold and failure behavior; and
- whether the judge was deterministic, mocked, local, or remote.

The committed golden gate scores saved structural results. It does not rerun
the workflow unless `--live` is used.

### Security

Required:

- threat and trust boundary;
- control implementation;
- configuration that activates the control;
- negative test or abuse case;
- deployment dependency; and
- residual risk.

A source control is not a deployment guarantee. Authentication, tenant
identity, rate limits, audit durability, model provenance, egress controls,
and operating-system permissions must be tested in the deployed environment.

Use [Security hardening](docs/operations/security-hardening.md),
[OWASP threat review](docs/OWASP_LLM_THREAT_MODEL.md), and
[Supply-chain security](docs/SUPPLY_CHAIN.md).

### Performance and reliability

Required:

- exact commit;
- hardware and operating system;
- process, worker, and concurrency configuration;
- workload and data size;
- warm-up policy;
- sample count;
- percentile calculation;
- failure count; and
- raw or generated result artifact.

Do not generalize a component benchmark to end-to-end service capacity. The
current load report includes direct worker-level concurrency evidence and must
not be presented as successful HTTP-path load evidence where requests failed
before measurement.

### UI behavior

Required:

- route or component;
- API or WebSocket contract;
- unit or browser test; and
- screenshot for a visual claim.

A component file that is not rendered by a route is not a shipped UI feature.
The node configuration overlay is currently an unfinished prototype.

## Repository verification commands

Use the narrowest relevant command while editing. Before a release or broad
evidence refresh, run the repository gates:

```powershell
just test
just docs
pre-commit run --all-files
npm --prefix agentic-workflows-v2/ui run build
```

Key documentation and contract checks:

```powershell
python agentic-workflows-v2/scripts/check_docs_refs.py
python scripts/generate_doc_stats.py --check
python scripts/check-doc-drift.py
python -m pytest agentic-workflows-v2/tests/test_schema_drift.py -q
```

Deterministic evaluation gate:

```powershell
$env:AGENTIC_NO_LLM = "1"
python scripts/eval_gate.py `
  --cases datasets/default/golden_cases.json `
  --threshold 0.80
```

From `agentic-workflows-v2`, regenerate wire contracts after an intentional
contract change:

```powershell
python -m scripts.generate_ts_types
npm --prefix ui run generate:types
python scripts/generate_schemas.py
```

`just` recipes in this repository invoke PowerShell. On Linux or macOS, run
the underlying Python and npm commands directly.

## Current evidence boundaries

These limits must remain visible in public summaries:

- The RAG CLI index is process-local and uses deterministic hash embeddings.
- `tools.llm.model_inventory` currently fails to import its legacy
  `llm_client` dependency.
- ONNX discovery and exact-model LangChain chat do not use the same model-ID
  prefix contract.
- Local-model weight verification is not wired into every model load path.
- MCP support is optional and not registered in normal workflow execution by
  default.
- The dashboard does not provide a complete human approval pause-and-resume
  flow.
- The node configuration overlay is not connected to workflow execution.
- Application rate limits and several resilience counters are process-local.
- `simple_agent.py` is not currently runnable because its example agent omits
  required abstract methods.
- Live provider quality, cost, latency, quota, and availability require fresh
  evidence.

See [Known limitations](docs/KNOWN_LIMITATIONS.md) for details and owners.

## Updating evidence

When behavior changes:

1. update or add the test;
2. run the narrow test and record the result;
3. update the active documentation;
4. update generated artifacts through their generator;
5. keep ADRs and changelog entries as historical records;
6. remove obsolete scores and counts from maintained pages; and
7. run the documentation and link checks.

Do not edit a report to make a failed check appear successful. Fix the
implementation, narrow the claim, or mark it **UNVERIFIED**.
