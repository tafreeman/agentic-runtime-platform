# AI risk management

**Updated:** 2026-07-28

**Scope:** this repository as a software platform

**Reference:** [NIST AI Risk Management Framework
1.0](https://doi.org/10.6028/NIST.AI.100-1)

This is an engineering risk review. It is not a compliance assessment,
security authorization, or claim that a deployment is safe for a specific
use.

The NIST AI RMF groups work into four functions: **Govern**, **Map**,
**Measure**, and **Manage**. The framework is not a checklist. This page uses
those functions to show what the repository provides, what it does not
provide, and what a deployment owner must decide.

## System boundary

The platform:

- loads YAML workflow definitions;
- runs deterministic and model-backed steps;
- calls local or external model providers;
- can expose the runtime through a FastAPI server and React dashboard;
- records run data and optional audit, metric, and trace data;
- provides an evaluation package for datasets, rubrics, and reports; and
- includes optional retrieval and indexing components.

The platform does not train foundation models. It also does not determine
whether a use case, dataset, prompt, provider, or model is appropriate for a
particular organization.

Do not treat the repository as sufficient approval for medical, legal,
employment, public-benefit, criminal-justice, safety-critical, or other
high-impact decisions. Those uses require controls, evidence, and accountable
human review outside this codebase.

## Current alignment

| Function | Repository evidence | Current limit |
| --- | --- | --- |
| Govern | Contribution rules, coding standards, security reporting, architecture decisions, dependency checks, secret scanning, and CI gates | The repository does not define an organization's owners, risk appetite, training records, legal review, or approval authority |
| Map | Architecture, configuration, known limitations, security hardening guidance, and workflow-specific inputs and outputs | The deploying organization must document affected people, intended decisions, prohibited uses, data classes, and provider boundaries |
| Measure | Unit, integration, browser, and workflow tests; backend and UI coverage gates; rubrics; evaluation runners; optional metrics and tracing | There is no universal quality score, continuous model-drift gate, fairness test suite, or production monitoring service |
| Manage | Tool restrictions, input detectors, authentication options, tenant context, audit logging, model fallback, circuit breaking, security reporting, and a public limitations register | Incident response, retention, rollback, escalation, and provider-disable procedures remain deployment responsibilities |

## Main risks and controls

### Incorrect or inconsistent model output

**Repository controls**

- Workflow rubrics and the `agentic-v2-eval` package can score recorded output.
- `code_artifact` contracts can reject empty, unsafe, or placeholder code
  artifacts.
- Bounded review loops and consensus workflows provide examples of additional
  checks.
- Provider failures can move to a configured fallback model.

**Limits**

- Artifact contracts are opt-in and currently cover code artifacts only.
- A successful model call does not prove that its answer is correct.
- Switching to a fallback model can change output behavior.
- The repository does not continuously test provider model changes against a
  fixed production dataset.

**Deployment action**

Pin or approve provider/model combinations, maintain representative evaluation
datasets, set acceptance thresholds, and require human review where an error
could cause material harm.

### Prompt injection and unsafe tool use

**Repository controls**

- Middleware includes prompt-injection, secret, and PII detectors.
- Tool access is filtered by agent tier and an optional per-step allowlist.
- Approval policies can guard tools with side effects.
- HTTP and file tools include configurable restrictions.

**Limits**

- Pattern-based input detection is not a proof that content is safe.
- A broadly permitted tool can still perform a harmful valid operation.
- Model instructions and retrieved content can conflict.

**Deployment action**

Give workflows the smallest useful tool set, isolate file and network access,
require approval for material changes, and test hostile inputs before release.

### Sensitive data disclosure

**Repository controls**

- Secret and PII detectors can flag known patterns.
- API-key and OIDC authentication modes are available.
- Tenant context and audit logging are available for server deployments.
- Configuration keeps provider credentials in environment variables or secret
  sources rather than workflow YAML.

**Limits**

- The repository does not supply an organizational data-classification policy,
  data-loss-prevention service, CUI handling plan, privacy impact assessment, or
  provider contract review.
- Logs, traces, prompts, retrieval indexes, and provider requests can contain
  sensitive content if a deployment allows it.

**Deployment action**

Define permitted data classes before enabling a provider. Configure log and
trace redaction, access control, retention, and deletion. Do not send regulated
or confidential data to a provider without explicit organizational approval.

### Provider outage, rate limit, or behavior change

**Repository controls**

- Model routing supports ordered fallbacks.
- Smart routing includes health statistics, cooldowns, circuit breaking, and
  per-provider concurrency limits.
- Local runtimes can be configured for some workflows.

**Limits**

- Provider availability and model identifiers change outside this repository.
- Fallbacks protect availability, not output equivalence.
- Router state and some other runtime state are process-local.

**Deployment action**

Test every configured fallback, define which failures may cross provider
boundaries, monitor provider-specific results, and document a manual disable
procedure.

### Retrieval quality and index integrity

**Repository controls**

- RAG components use explicit loader, chunker, embedding, vector-store,
  retriever, reranker, and context-assembly interfaces.
- Persistent LanceDB storage and provider-backed embeddings are available
  through optional components.
- Retrieved context can be framed and limited by a token budget.

**Limits**

- The current `agentic rag` CLI uses a process-local hash embedder and
  in-memory store. It is suitable for smoke tests, not semantic production
  retrieval.
- Embeddings from different providers are not interchangeable.
- Reranker and metadata-filter behavior has documented restrictions.

**Deployment action**

Choose one approved embedding space per index, use durable storage, record the
embedding model and dimensions with the index, evaluate retrieval quality, and
  review the [known limitations](KNOWN_LIMITATIONS.md) before enabling RAG in a
  deployment.

### Malformed workflow output

**Repository controls**

- The loader validates graph structure, dependencies, cycles, expressions,
  evaluation configuration, and artifact-contract bindings.
- Required workflow outputs that cannot be resolved are recorded.
- Code-artifact contracts validate supported generated-code boundaries.

**Limits**

- Most model output is still text or loosely structured mappings.
- A workflow can omit artifact contracts.
- Schema-valid output can still be wrong.

**Deployment action**

Use contracts at important boundaries, reject unresolved required outputs, and
add domain validation before downstream systems act on a result.

### Supply-chain compromise

**Repository controls**

- CI includes CodeQL, dependency review, Python and npm dependency audits, and
  CycloneDX SBOM generation.
- Pre-commit checks include secret detection.
- Optional model-weight integrity helpers are present.

**Limits**

- CI results apply to the tested revision, not every downstream image or
  deployment environment.
- An SBOM lists components; it does not establish that they are safe.

**Deployment action**

Rebuild and scan release artifacts in the target environment, verify pinned
dependencies and model weights, review provenance, and keep a patch process.

### Logging, metrics, and audit data

**Repository controls**

- OpenTelemetry tracing and Prometheus metrics are optional.
- The server can write append-only audit records.
- Run records support inspection and offline evaluation.

**Limits**

- The repository does not deploy a monitoring service or incident-management
  system.
- Observability data may expose prompts, filenames, model output, or tenant
  identifiers if configured without care.

**Deployment action**

Set collection, redaction, access, retention, and alerting rules. Test that
incident responders can find a failed run without exposing more data than they
need.

## Priority gaps

These gaps should be resolved by a deployment or by future platform work:

1. Define owners, approvers, escalation paths, and a risk-acceptance process.
2. Document allowed data classes and provider boundaries.
3. Maintain representative quality, safety, and fairness datasets for the
   intended use.
4. Add scheduled drift checks for approved provider/model versions.
5. Define production incident response, rollback, retention, and deletion.
6. Expand structured output contracts beyond generated code where downstream
   automation depends on model output.
7. Test multi-process state, storage, and tenant isolation in the intended
   deployment topology.

## Evidence index

| Topic | Source |
| --- | --- |
| Architecture and boundaries | [Architecture](ARCHITECTURE.md) |
| Runtime configuration | [Configuration](configuration.md) |
| Known implementation limits | [Known limitations](KNOWN_LIMITATIONS.md) |
| Server hardening | [Security hardening](operations/security-hardening.md) |
| Security reporting | [Repository security policy](https://github.com/tafreeman/agentic-runtime-platform/blob/main/agentic-workflows-v2/SECURITY.md) |
| Workflow syntax | [Workflow authoring](WORKFLOW_AUTHORING.md) |
| Evaluation | [Evaluation architecture](architecture-eval.md) |
| Engineering rules | [Contributing](CONTRIBUTING.md) and [coding standards](CODING_STANDARDS.md) |
| Architecture decisions | [ADR index](adr/ADR-INDEX.md) |

Review this page when provider policy, security boundaries, persistent storage,
evaluation gates, or production topology changes.
