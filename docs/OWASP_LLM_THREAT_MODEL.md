# OWASP LLM threat review

This document maps the current runtime to the
[OWASP Top 10 for LLM Applications 2025](https://genai.owasp.org/resource/owasp-top-10-for-llm-applications-2025/).
Because this repository runs agents that can call tools, also use the
[OWASP Top 10 for Agentic Applications 2026](https://genai.owasp.org/resource/owasp-top-10-for-agentic-applications-for-2026/)
when preparing a deployment threat model.

This is a source review, not a penetration test, compliance claim, or
authorization to operate. Controls marked **conditional** only help when the
related setting, dependency, storage backend, or deployment control is active.

## Scope and trust boundaries

The review covers:

- HTTP and WebSocket clients sending workflow inputs;
- the FastAPI server and workflow engine;
- cloud and local model providers;
- retrieved documents and vector stores;
- agents passing content to other agents;
- built-in file, Git, shell, HTTP, and MCP tools;
- run, audit, trace, dataset, and evaluation storage; and
- the React dashboard.

The main boundaries are client-to-server, server-to-model provider,
retrieval-to-model context, model-to-tool, tenant-to-storage, and
process-to-external service.

## Current control map

| OWASP risk | Current controls | Important residual risk |
| --- | --- | --- |
| LLM01 Prompt Injection | Request and model-loop sanitizers detect common instruction overrides, prompt extraction, delimiter escapes, and unsafe Unicode. RAG context is framed and sanitized before use. | Pattern matching cannot identify every direct or indirect injection. Sanitization is a risk reduction layer, not proof that content is safe. |
| LLM02 Sensitive Information Disclosure | Input secret and PII detection, output secret redaction, secret-provider support, tenant-scoped storage paths, and opt-in sensitive tracing controls. | PII patterns are limited, redaction is best effort, and client-supplied tenant headers are not an authorization boundary. |
| LLM03 Supply Chain | Locked Python and npm dependencies, Dependabot, dependency-audit workflows, secret scanning, and SBOM generation. A local-model weight verifier exists. | Weight verification is not called by every local inference path. Third-party model, provider, MCP, action, and package provenance still needs deployment review. |
| LLM04 Data and Model Poisoning | Dataset schemas, retrieval content sanitization, content-hash deduplication, evaluation datasets, and reviewable workflow configuration. | The runtime does not establish the provenance or truth of supplied datasets, retrieved documents, remote models, or provider output. |
| LLM05 Improper Output Handling | Pydantic API contracts, validated structured outputs in selected paths, response sanitization, restricted workflow expressions, SSRF checks, and tool argument validation. | Many agent results remain free text. Each downstream consumer must treat model output as untrusted data. |
| LLM06 Excessive Agency | Per-step tool allowlists, approval gates, file sandbox roots, shell command allowlists, Git subcommand restrictions, HTTP egress checks, timeouts, and bounded agent iterations. | An allowed interpreter, Git command, or HTTP destination may still have broad effects. Approval requires a registered provider, and the dashboard does not yet provide a complete pause-and-resume approval flow. |
| LLM07 System Prompt Leakage | Direct extraction patterns are detected and repository prompts contain no intended secrets. | Prompt text cannot be assumed confidential. Never put credentials or access decisions in a system prompt. |
| LLM08 Vector and Embedding Weaknesses | Retrieved text is sanitized, framed as untrusted context, deduplicated, and limited by a context budget. Tenant identifiers are carried into storage paths and metadata. | The CLI's default hash embedder is a deterministic test-oriented implementation, not semantic retrieval. Persistent store integrity and document authorization remain deployment responsibilities. |
| LLM09 Misinformation | Rubric-based evaluation, dataset gates, multi-step review workflows, and explicit result artifacts make outputs inspectable. | There is no universal real-time factuality or citation verifier. LLM-as-judge results can also be wrong or biased. |
| LLM10 Unbounded Consumption | Per-IP HTTP rate limiting, failed-authentication throttling, model-provider limits, circuit breakers, concurrency bulkheads, retry limits, token budgets, timeouts, and bounded agent loops. | Application counters are process-local. Multi-replica deployments need gateway limits and shared budget or quota enforcement. |

## Controls that require configuration

The local-development defaults are not an internet-facing security policy.
Review these settings before deployment:

| Control | Setting or action |
| --- | --- |
| API authentication | Set `AGENTIC_API_KEY`, or configure all required `AGENTIC_OIDC_*` settings. |
| Browser origins | Set `AGENTIC_CORS_ORIGINS` to the deployed frontend origins. |
| File and Git scope | Set `AGENTIC_FILE_BASE_DIR` to a dedicated directory. |
| Shell access | Leave `AGENTIC_SHELL_ALLOWED_COMMANDS` empty unless a reviewed workflow requires specific executables. |
| Tool approval | Register an `ApprovalProvider`; review `AGENTIC_REQUIRE_TOOL_APPROVAL` and `AGENTIC_APPROVAL_REQUIRED_TOOLS`. |
| HTTP egress | Keep `AGENTIC_BLOCK_PRIVATE_IPS=1` and add network-level egress rules. |
| Request limits | Keep application rate limiting enabled and enforce authoritative limits at the ingress for multi-replica deployments. |
| Model spend | Set `AGENTIC_TOKEN_BUDGET` and add deployment-level account or project budgets. |
| Audit trail | Enable `AUDIT_LOG_ENABLED` and protect the selected file or Redis backend. |
| Sensitive telemetry | Keep `AGENTIC_TRACE_SENSITIVE=0` unless collection and retention have been approved. |

See [Security hardening](operations/security-hardening.md) and
[Configuration](configuration.md) for the exact behavior and defaults.

## Highest-priority residual risks

### Untrusted model output

Model output can become another agent's input, a tool argument, a rendered UI
value, or a persisted artifact. Schema validation exists in selected paths,
but it is not universal.

For each workflow:

1. define the smallest output contract the next step needs;
2. validate before tool execution or persistence;
3. reject unexpected fields and unsafe URLs or paths;
4. escape output for its final context; and
5. keep irreversible actions behind approval.

### Tool authority

Application allowlists are only one layer. An allowed executable or network
destination can still exceed the intended task. Run the service with a
restricted operating-system identity, a dedicated writable directory, limited
network egress, and no ambient cloud credentials.

The MCP client is not wired into normal workflow execution by default. If it is
enabled, treat every server as third-party code and every advertised tool as a
new trust boundary. Review authentication, server identity, tool schemas,
timeouts, output handling, and the permissions of the server process.

### Retrieval authorization and provenance

Sanitization does not determine whether a document is authorized, current, or
true. A production retrieval pipeline needs:

- authorization before retrieval, not only after results are returned;
- tenant isolation backed by validated identity;
- document source and ingestion-time metadata;
- deletion and re-index procedures;
- approved embedding models and consistent embedding spaces; and
- tests for poisoned documents and indirect prompt injection.

### Multi-process limits

Rate-limit, lockout, router, and some budget state is held in process memory.
Several workers or replicas can therefore grant more aggregate capacity than
one process. Put shared enforcement at the gateway or in a durable service.

### Local model integrity

`agentic_v2.models.weight_integrity` can verify configured local model files,
but the native ONNX and LangChain local-model construction paths do not both
invoke it. Until the verifier is wired into every load path, enforce model
provenance and hashes in the deployment pipeline.

## Verification before release

Exercise the deployed system, not only the source:

- protected routes reject missing and invalid credentials;
- OIDC rejects incorrect issuer, audience, signature, algorithm, and expiry;
- WebSocket handshakes reject disallowed origins and query-string tokens;
- rate limits work at the intended client identity and across replicas;
- file traversal and writes outside the sandbox fail;
- unapproved side effects fail closed;
- shell metacharacters and non-allowlisted executables are rejected;
- private, loopback, metadata, redirect, and DNS-rebinding HTTP targets fail;
- retrieved and tool-returned injection payloads cannot trigger actions;
- one tenant cannot read another tenant's runs, datasets, retrieval data, or audit events;
- model responses containing test secrets are redacted in every supported adapter path;
- token, iteration, timeout, and provider-failure limits stop work cleanly; and
- audit records and traces contain the required fields without disallowed content.

Record the deployed version, configuration, test evidence, open exceptions,
owners, and review date. Do not label a risk “mitigated” solely because a
control exists in source.

## Related documentation

- [Security hardening](operations/security-hardening.md)
- [Supply-chain security](SUPPLY_CHAIN.md)
- [AI risk management](AI_RISK_MANAGEMENT.md)
- [Known limitations](KNOWN_LIMITATIONS.md)
- [RAG](rag/index.md)
- [MCP integration](../agentic-workflows-v2/agentic_v2/integrations/mcp/README.md)
