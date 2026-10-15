## 2. Runtime backend — components & data structures (agentic_v2)

Scope: `agentic-workflows-v2/agentic_v2/` at origin/main `c3b2d328` (clean worktree `C:/tmp/arp-main-inventory`). 244 Python modules, 61,892 LOC (inventory counts, `__init__` files included). Only console script: `[project.scripts] agentic = "agentic_v2.cli:main"` (`agentic-workflows-v2/pyproject.toml:130-131`). Section 3 covers the HTTP/WS API; section 5 covers the YAML workflow definitions; this section covers the Python components behind them.

### 2.0 How to read the tables

- **LOC** — physical lines from `docs/inventory/data/py_inventory.json`.
- **used by** — distinct in-package modules importing the module, recomputed by AST with relative imports resolved. The raw `imported_by` field misses `from .x import y`, which is why `contracts.schemas` and `governance.escalation` looked orphaned there. A `(pkg)` row counts importers of the package itself.
- **tests** — number of test files (`agentic-workflows-v2/tests/**`, repo-root `tests/**`) that contain the module path or one of its public class/function names. A name-match heuristic: `0` is reliable (no reference anywhere); a positive count is an upper bound on real coverage.
- **status** — `Active` = imported by another runtime module; `Test-only` = imported by no runtime module but referenced by tests; `Orphan?` = neither (only `models.llm` after verification; see 2.24). Flags `>800 LOC`, `TODO`, `no tests` are appended. `Active (pkg)` marks `__init__` re-export hubs.
- Purpose is the module docstring first line; where empty, the first public class/function docstring; a few docstring-less modules got a hand-written purpose.

### 2.0.1 Layering at a glance

| layer | subpackages | notes |
|---|---|---|
| Contracts and core | `contracts`, `core`, `artifact_contracts`, `settings`, `ui_settings` | Pydantic wire types, protocols, error hierarchy, tenant scoping, env-driven settings; imported by nearly everything. |
| Execution engine | `engine`, `adapters`, `workflows`, `langchain` | Native DAG executor (`engine/dag_executor.py`) vs LangGraph path (`langchain/`), selected through `adapters/registry.py`. |
| Model plane | `models`, `prompts`, `config/defaults` | Tier routing, backends, discovery, circuit breakers, curated registry (`config/defaults/model_registry.yaml`). |
| Agents and tools | `agents`, `tools`, `integrations` (MCP) | Agent classes, built-in tools, MCP client stack. |
| Safety | `governance`, `middleware`, `security` | Approval gate, escalation sink, prompt/response sanitization chain, SSRF URL guard. |
| Scoring | `scoring`, `evaluation` | Rubric/judge scoring, hard gates, EvalKit bridge. |
| Surfaces | `server`, `cli`, `devex` | FastAPI app (summary only here), Typer CLI, dev tooling. |

### 2.1 Top-level modules

The package `__init__` is a large re-export hub (agents, contracts, engine and model symbols; `__version__ = "0.1.0"`, `agentic-workflows-v2/agentic_v2/__init__.py`). `settings.py` is the single pydantic-settings class reading `AGENTIC_*`/OTEL env vars, including `AGENTIC_NO_LLM` (the supported keyless baseline). `ui_settings.py` is the runtime-mutable, file-persisted store behind the settings UI (providers, tier overrides, versioned model packs; path via `AGENTIC_UI_SETTINGS_PATH`). `artifact_contracts.py` / `artifact_overlay.py` implement typed inter-step artifact contracts and the code-artifact rework overlay (imported by `engine/agent_resolver.py` and `langchain/graph_wiring.py`). `logging_config.py` configures logging.

| module | LOC | purpose | key symbols | used by | tests | status |
|---|---:|---|---|---:|---:|---|
| `__init__` | 210 | Agentic Workflows V2 - Tier-based multi-model orchestration. | - | 1 | 8 | Active (pkg) |
| `settings` | 556 | Centralised application settings. | `Settings`, `is_agentic_no_llm_enabled`, `get_settings` | 26 | 36 | Active |
| `ui_settings` | 370 | Runtime-mutable UI settings store. | `ProviderConfig`, `ModelPackRef`, `ModelPack`, `UiSettings`, `is_valid_api_key_env`, `get_ui_settings_path`, `load_ui_settings` | 7 | 4 | Active |
| `artifact_contracts` | 367 | Typed content contracts for artifacts passed between workflow steps. | `ArtifactContract`, `ContractDiagnostic`, `ArtifactContractError`, `ArtifactContractConfigError`, `parse_artifact_contracts`, `validate_contract_bindings`, `validate_code_artifact` | 5 | 5 | Active |
| `artifact_overlay` | 77 | Lay reworked code artifacts over the originals, file by file. | `overlay_code_artifact`, `overlay_code_artifacts` | 2 | 1 | Active |
| `logging_config` | 82 | Logging configuration for agentic-workflows-v2. | `configure_logging` | 1 | 1 | Active |

### 2.2 `adapters`

Pluggable execution-engine backends behind a thread-safe `AdapterRegistry`. Two adapters: `native` (wraps `engine.DAGExecutor`/`PipelineExecutor`, with a SQLite `CheckpointStore`) and `langchain` (wraps `langchain.WorkflowRunner`). `"langchain"` is the default for named YAML workflows, `"native"` for runtime-generated DAGs. Both satisfy the `core.protocols.ExecutionEngine` Protocol.

| module | LOC | purpose | key symbols | used by | tests | status |
|---|---:|---|---|---:|---:|---|
| `adapters/ (pkg)` | 39 | Adapter layer - pluggable execution engine backends. | - | 4 | 8 | Active (pkg) |
| `adapters.langchain/ (pkg)` | 33 | LangChain execution engine adapter. | - | 1 | 7 | Active (pkg) |
| `adapters.langchain.engine` | 181 | LangChain execution engine - wraps the existing WorkflowRunner. | `LangChainEngine` | 1 | 7 | Active |
| `adapters.native/ (pkg)` | 9 | Native execution engine adapter. | - | 1 | 4 | Active (pkg) |
| `adapters.native._checkpoint_store` | 182 | SQLite-backed checkpoint store for workflow execution persistence. | `CheckpointStore` | 1 | 1 | Active |
| `adapters.native.engine` | 313 | Native execution engine - wraps DAGExecutor and PipelineExecutor. | `NativeEngine` | 1 | 5 | Active |
| `adapters.registry` | 112 | Adapter registry - central lookup for execution engine adapters. | `AdapterRegistry`, `get_registry` | 6 | 17 | Active |
| `adapters.workflows` | 47 | Shared loading and execution for adapter-owned workflow definitions. | `load_workflow`, `execute_workflow` | 3 | 4 | Active |

### 2.3 `agents`

Agent classes on `BaseAgent` (lifecycle state machine, tool loop, memory). Specialised agents (architect, coder, reviewer, test) sit beside a composable capability system and sliding-window `ConversationMemory`. `orchestrator*.py` decompose tasks and delegate; when a fallback chain is exhausted it emits a structured `HandoffSummary` via `governance.escalation` (lazy import, `agents/orchestrator.py:393`). `implementations/` holds SDK-backed agents (Anthropic Messages API, `claude-agent-sdk`) behind the optional `[claude]` extra; the whole directory is coverage-omitted.

| module | LOC | purpose | key symbols | used by | tests | status |
|---|---:|---|---|---:|---:|---|
| `agents/ (pkg)` | 112 | Specialized AI agents for task execution within agentic workflows. | - | 1 | 8 | Active (pkg) |
| `agents.architect` | 309 | Agent specialized for system architecture design. | `ArchitectureInput`, `TechStackChoice`, `ArchitectureOutput`, `ArchitectAgent`, `create_architect_agent` | 1 | 1 | Active |
| `agents.base` | 518 | Base agent implementation with full lifecycle management. | `BaseAgent`, `agent_to_step` | 9 | 8 | Active |
| `agents.capabilities` | 296 | Composable capability system for dynamic agent-to-task matching. | `CapabilityType`, `Capability`, `CapabilitySet`, `CapabilityMixin`, `requires_capabilities`, `get_agent_capabilities` | 6 | 4 | Active |
| `agents.coder` | 297 | Agent specialized for LLM-driven code generation. | `CoderAgent` | 2 | 3 | Active |
| `agents.config` | 108 | Agent configuration, state, and event type definitions. | `AgentState`, `AgentEvent`, `AgentConfig` | 1 | 7 | Active |
| `agents.implementations/ (pkg)` | 35 | Concrete agent implementations backed by external LLM SDKs. | - | 0 | 4 | Active (pkg) |
| `agents.implementations.agent_loader` | 118 | Loader for ``.md`` agent definition files with YAML frontmatter. | `load_agents` | 1 | 0 | Active / no tests |
| `agents.implementations.claude_agent` | 252 | Anthropic Messages API agent backed by the ``anthropic`` SDK. | `SimpleTask`, `SimpleOutput`, `ClaudeAgent` | 1 | 3 | Active |
| `agents.implementations.claude_sdk_agent` | 200 | Standalone agent wrapper around the ``claude-agent-sdk`` package. | `ClaudeSDKAgent` | 1 | 2 | Active |
| `agents.json_extraction` | 131 | Shared JSON extraction and validation for agent response parsing. | `extract_json` | 5 | 3 | Active |
| `agents.memory` | 592 | Conversation memory primitives for agent history management. | `ConversationMessage`, `CaseFacts`, `FieldReductionResult`, `ConversationMemory`, `reduce_tool_result` | 1 | 2 | Active |
| `agents.orchestrator` | 788 | Meta-agent that decomposes tasks and delegates to specialized agents. | `OrchestratorAgent` | 2 | 6 | Active |
| `agents.orchestrator_factories` | 37 | Task-input factories for :mod:`.orchestrator`. | - | 1 | 0 | Active / no tests |
| `agents.orchestrator_models` | 127 | Data structures, I/O schemas, and prompts for :mod:`.orchestrator`. | `SubTask`, `InvestigationFindings`, `AdaptiveDecomposition`, `OrchestratorInput` | 1 | 6 | Active |
| `agents.orchestrator_planning` | 147 | Deterministic planning helpers for :mod:`.orchestrator`. | - | 1 | 0 | Active / no tests |
| `agents.reviewer` | 327 | Agent specialized for structured, severity-ranked code review. | `ReviewerAgent` | 2 | 1 | Active |
| `agents.test_agent` | 455 | Agent specialized for automated test suite generation. | `TestType`, `TestGenerationInput`, `TestFile`, `TestGenerationOutput`, `create_test_agent` | 1 | 2 | Active |

### 2.4 `cli`

Typer CLI exposed as the `agentic` script. Commands in `cli/main.py`: `run`, `compare`, `orchestrate`, `resume`, `list`, `validate`, `serve`, `version`, plus the mounted `devex` sub-app (`app.add_typer(devex_app, name="devex")`, `cli/main.py:86`).

| module | LOC | purpose | key symbols | used by | tests | status |
|---|---:|---|---|---:|---:|---|
| `cli/ (pkg)` | 4 | CLI interface for agentic workflows v2. | - | 0 | 5 | Active (pkg) |
| `cli.display` | 211 | Display and formatting helpers for the agentic CLI. | - | 1 | 0 | Active / no tests |
| `cli.helpers` | 111 | CLI helper functions for adapter comparison. | - | 1 | 2 | Active |
| `cli.main` | 554 | CLI interface for agentic workflows v2. | `run`, `compare`, `orchestrate` | 1 | 4 | Active |

### 2.5 `config`

The Python package is an empty marker (`__all__ = []`, coverage-omitted); the content is data under `config/defaults/`: `agents.yaml`, `evaluation.yaml`, `model_registry.yaml`, `personas.yaml`, `trusted_model_hashes.yaml`. Confirmed consumers: `server/routes/agents.py` (agents.yaml) and `models/model_registry.py` (model_registry.yaml, ADR-040); the rest are inferred from names (unverified).

| module | LOC | purpose | key symbols | used by | tests | status |
|---|---:|---|---|---:|---:|---|
| `config/ (pkg)` | 3 | Configuration management. | - | 0 | 0 | Active (pkg) |

### 2.6 `contracts`

Pydantic v2 wire/message definitions. `chat`, `events` and `messages` feed the committed JSON-schema/TypeScript contract pipeline together with `server/models.py` (see 2.23). `schemas.py` holds structured agent I/O (TaskInput/TaskOutput, code generation, code review, test generation) and is re-exported by the package `__init__`; `verification` and `sanitization` hold policy/result models.

| module | LOC | purpose | key symbols | used by | tests | status |
|---|---:|---|---|---:|---:|---|
| `contracts/ (pkg)` | 144 | Contracts module - Pydantic v2 message and schema definitions. | - | 34 | 8 | Active (pkg) |
| `contracts.chat` | 205 | Typed wire format for the ``POST /api/chat`` model playground endpoint. | `ChatTextPart`, `ChatImagePart`, `ChatMessage`, `ModelChatRequest`, `validate_chat_stream_event` | 2 | 4 | Active |
| `contracts.events` | 153 | Typed wire format for WebSocket/SSE execution events. | `WorkflowStartEvent`, `StepStartEvent`, `StepEndEvent`, `TokenDeltaEvent`, `validate_event` | 2 | 3 | Active |
| `contracts.messages` | 533 | Message contracts for agent communication and step/workflow results. | `MessageType`, `StepStatus`, `ReviewStatus`, `TestGateStatus` | 3 | 48 | Active |
| `contracts.result_conversion` | 165 | Convert external step evidence into the shared result contract. | `as_dict`, `coerce_step_status`, `workflow_status` | 2 | 5 | Active |
| `contracts.sanitization` | 64 | Pydantic result types for the sanitization pipeline (Classification, Severity, Finding, SanitizationResult). | `Classification`, `Severity`, `FindingCategory`, `Finding` | 10 | 13 | Active |
| `contracts.schemas` | 385 | Task schemas for structured agent inputs/outputs. | `Severity`, `IssueCategory`, `TestType`, `TaskInput` | 1 | 11 | Active |
| `contracts.verification` | 66 | Policy governing how verification loops behave for a step. | `VerificationStatus`, `CorrectionOutcome`, `VerificationPolicy`, `CorrectionAttempt` | 3 | 2 | Active |

### 2.7 `core`

Engine-agnostic foundations: Protocols (`ExecutionEngine`, `SupportsStreaming`, `AgentProtocol`, `ToolProtocol`, `DetectorProtocol`, `MiddlewareProtocol`, `VerifierProtocol`), the `AgenticError` hierarchy with `classify_error`/`ErrorCode`, an in-memory store, and `TenantContext` filesystem scoping.

| module | LOC | purpose | key symbols | used by | tests | status |
|---|---:|---|---|---:|---:|---|
| `core/ (pkg)` | 101 | Core module - engine-agnostic protocols, contracts, and context. | - | 0 | 8 | Active (pkg) |
| `core.errors` | 86 | Core error hierarchy for the agentic workflow system. | `AgenticError`, `WorkflowError`, `StepError`, `SchemaValidationError`, `classify_error` | 14 | 16 | Active |
| `core.memory` | 192 | Core memory abstractions -- protocol and in-memory implementation. | `MemoryStoreProtocol`, `InMemoryStore` | 2 | 3 | Active |
| `core.protocols` | 196 | Core protocols - engine-agnostic interfaces for the workflow system. | `ExecutionEngine`, `SupportsStreaming`, `SupportsCheckpointing`, `AgentProtocol` | 2 | 7 | Active |
| `core.tenant` | 190 | Tenant context and filesystem scoping helpers. | `TenantContext`, `sanitize_tenant_id`, `get_tenant_context`, `tenant_dataset_dir` | 8 | 9 | Active |

### 2.8 `devex`

Developer-experience utilities mounted under `agentic devex`: port guard, workspace-wide test runner, structural workflow YAML linter.

| module | LOC | purpose | key symbols | used by | tests | status |
|---|---:|---|---|---:|---:|---|
| `devex/ (pkg)` | 1 | Developer experience (devex) utilities for agentic-workflows-v2. | - | 0 | 3 | Active (pkg) |
| `devex.cli` | 106 | Typer sub-application for developer-experience commands. | `port_guard_cmd`, `workspace_test_runner_cmd`, `workflow_linter_cmd` | 1 | 0 | Active / no tests |
| `devex.port_guard` | 63 | Port availability checker for local development services. | `check_port`, `guard_ports` | 1 | 1 | Active |
| `devex.workflow_linter` | 115 | Structural YAML linter for workflow definition files. | `LintViolation`, `lint_workflow_dict`, `lint_workflow_file`, `lint_workflow_by_name` | 2 | 1 | Active |
| `devex.workspace_test_runner` | 95 | Workspace-wide test runner for all monorepo packages. | `run_package_tests`, `run_all` | 1 | 1 | Active |

### 2.9 `engine`

The native execution core. `StepDefinition`/`StepExecutor` run one step (retry, timeout, `when`/`unless`, loops, verification gate); `DAG` + `DAGExecutor` schedule steps with dynamic parallel scheduling; `Pipeline*` composes ordered/parallel/conditional elements; `WorkflowExecutor` is the facade; `ExecutionContext` carries run state, masking and event hooks; `tool_execution`, `prompt_assembly`, `llm_output_parsing` implement the LLM/tool inner loop; `ek_step_delegation` optionally hands the inner loop to ExecutionKit (guarded import, opt-in).

| module | LOC | purpose | key symbols | used by | tests | status |
|---|---:|---|---|---:|---:|---|
| `engine/ (pkg)` | 122 | Engine module - Workflow execution infrastructure. | - | 4 | 8 | Active (pkg) |
| `engine.agent_resolver` | 609 | Maps YAML agent names to executable step functions (LLM, tool, native agent paths). | `resolve_agent` | 1 | 6 | Active |
| `engine.consensus` | 232 | Consensus / voting primitives -- ensemble and self-consistency patterns. | `ConsensusResult`, `canonical_key`, `coerce_min_agreement`, `majority_vote` | 3 | 1 | Active |
| `engine.context` | 672 | Execution context for workflow state management. | `EventType`, `ServiceContainer`, `ExecutionContext`, `get_context`, `set_context`, `reset_context` | 13 | 30 | Active |
| `engine.dag` | 211 | Directed Acyclic Graph (DAG) workflow definition. | `MissingDependencyError`, `CycleDetectedError`, `DAG` | 6 | 14 | Active |
| `engine.dag_executor` | 627 | DAG executor with dynamic parallel scheduling. | `DAGExecutor` | 4 | 14 | Active |
| `engine.ek_step_delegation` | 441 | ADR-023 Phase 6a/6c: delegate the INNER LLM mechanics of a step to EK patterns. | `BudgetEnforcingProvider`, `complete_turn_via_ek`, `structured_via_ek`, `wrap_runtime_tool` | 2 | 3 | Active |
| `engine.executor` | 506 | Top-level workflow executor with unified orchestration. | `ExecutorEvent`, `ExecutionConfig`, `ExecutionHistory`, `WorkflowExecutor`, `get_executor`, `reset_executor`, `execute` | 2 | 6 | Active |
| `engine.expressions` | 680 | Expression evaluation helpers for conditional execution. | `ExpressionError`, `StepResultView`, `ExpressionEvaluator`, `evaluate_safe_expression` | 6 | 3 | Active |
| `engine.llm_output_parsing` | 826 | LLM output parsing - JSON extraction, normalization, and sentinel artifact parsing. | `extract_json_candidates`, `normalize_expected_structure`, `select_json_dict` | 4 | 3 | Active / >800 LOC |
| `engine.patterns/ (pkg)` | 3 | Execution patterns (sequential, parallel, iterative, etc.). | - | 0 | 0 | Active (pkg) |
| `engine.pipeline` | 393 | Pipeline orchestration for multi-step workflows. | `PipelineStatus`, `ParallelGroup`, `ConditionalBranch`, `Pipeline`, `run_pipeline` | 3 | 5 | Active |
| `engine.prompt_assembly` | 200 | Prompt assembly - system prompt loading, context formatting, and tool descriptions. | `load_agent_system_prompt`, `parameter_spec_to_json_schema`, `build_context_block` | 1 | 3 | Active |
| `engine.protocol` | 14 | Execution engine protocol - backward-compatibility shim. | - | 2 | 2 | Active |
| `engine.runtime` | 317 | Runtime abstractions for isolated task execution. | `RuntimeExecutionResult`, `RuntimeExecutionError`, `IsolatedTaskRuntime`, `SubprocessRuntime`, `create_runtime` | 2 | 1 | Active |
| `engine.step` | 699 | Step definition and execution. | `RetryStrategy`, `RetryConfig`, `StepDefinition`, `StepExecutor`, `step`, `run_step` | 10 | 28 | Active |
| `engine.step_state` | 70 | Step lifecycle state machine. | `StepState`, `StepStateManager` | 2 | 4 | Active |
| `engine.tool_execution` | 553 | Tool execution - tool contract resolution, call normalization, and the tool loop. | `parameter_spec_to_json_schema`, `normalize_tool_choice`, `build_tool_contracts` | 6 | 8 | Active |
| `engine.verification` | 347 | Verification loop engine for bounded self-correction. | `VerificationGate`, `VerificationLoop` | 1 | 0 | Active / no tests |

### 2.10 `evaluation`

Small shared helper: the normalization formula registry used by workflow scoring (`server/normalization.py` is a back-compat re-export of it, test-only).

| module | LOC | purpose | key symbols | used by | tests | status |
|---|---:|---|---|---:|---:|---|
| `evaluation/ (pkg)` | 19 | Evaluation-domain utilities shared across workflow/server layers. | - | 0 | 0 | Active (pkg) |
| `evaluation.normalization` | 99 | Normalization formula registry for workflow scoring. | `NormalizationFormula`, `clamp01`, `list_formula_ids`, `is_registered_formula` | 6 | 1 | Active |

### 2.11 `governance`

Fail-closed human-approval gate on the tool-dispatch hot path (`approval.py`; with no `ApprovalProvider` registered the call is DENIED) and a structured escalation sink for exhausted agent fallback chains (`escalation.py`, default behaviour: log at WARNING and return the handoff).

| module | LOC | purpose | key symbols | used by | tests | status |
|---|---:|---|---|---:|---:|---|
| `governance/ (pkg)` | 54 | Governance primitives for the agentic runtime. | - | 1 | 6 | Active (pkg) |
| `governance.approval` | 268 | Human-approval gates for the tool-execution hot path (P1 #12). | `ApprovalDecision`, `ApprovalRequest`, `ApprovalProvider`, `AutoApproveProvider`, `set_approval_provider`, `get_approval_provider`, `resolve_required_tool_names` | 7 | 5 | Active |
| `governance.escalation` | 137 | Structured human-escalation handoff for exhausted fallback chains. | `FailureType`, `HandoffSummary`, `EscalationSink`, `set_escalation_sink`, `get_escalation_sink`, `route_handoff` | 1 | 1 | Active |

### 2.12 `integrations`

External-framework glue. The bulk is the MCP client stack (`integrations/mcp/`: types, JSON-RPC protocol client, stdio/WebSocket transports, connection manager with backoff, tool/resource/prompt adapters and LRU-cached discovery, context-budget guard, disk-backed oversize storage, error envelope); the whole `mcp/*` tree is coverage-omitted. Also OpenTelemetry tracing/metrics (`otel`, `metrics`, `tracing`), a LangChain bridge (`langchain.py`) and framework-neutral adapter ABCs (`base`).

| module | LOC | purpose | key symbols | used by | tests | status |
|---|---:|---|---|---:|---:|---|
| `integrations/ (pkg)` | 31 | Integrations with external frameworks. | - | 0 | 8 | Active (pkg) |
| `integrations.base` | 151 | Base adapter interfaces for framework-neutral integration. | `CanonicalEvent`, `AgentAdapter`, `ToolAdapter`, `WorkflowAdapter` | 7 | 5 | Active |
| `integrations.langchain` | 219 | LangChain integration for agentic-workflows-v2. | - | 0 | 2 | Test-only |
| `integrations.mcp/ (pkg)` | 40 | Model Context Protocol (MCP) Integration Package. | - | 0 | 7 | Active (pkg) |
| `integrations.mcp.adapters/ (pkg)` | 5 | Adapter layer exports. | - | 0 | 1 | Active (pkg) |
| `integrations.mcp.adapters.prompt_adapter` | 122 | MCP Prompt Adapter - proxies MCP prompts as local context sources. | `McpPromptAdapter` | 1 | 0 | Active / no tests |
| `integrations.mcp.adapters.resource_adapter` | 220 | MCP Resource Adapter - exposes meta-tools for resource discovery and reading. | `McpResourceAdapter` | 1 | 0 | Active / no tests |
| `integrations.mcp.adapters.tool_adapter` | 229 | MCP Tool Adapter - wraps remote MCP tools as local tool instances. | `McpToolAdapter` | 1 | 1 | Active |
| `integrations.mcp.config` | 343 | MCP Configuration Loader. | `McpConfigLoader`, `expand_variables`, `expand_dict_variables`, `parse_server_config` | 1 | 1 | Active |
| `integrations.mcp.discovery/ (pkg)` | 5 | Discovery services exports. | - | 0 | 0 | Active (pkg) |
| `integrations.mcp.discovery.prompts` | 135 | Prompt discovery service with LRU caching. | `PromptDiscovery` | 2 | 0 | Active / no tests |
| `integrations.mcp.discovery.resources` | 131 | Resource discovery service with LRU caching. | `ResourceDiscovery` | 2 | 0 | Active / no tests |
| `integrations.mcp.discovery.tools` | 100 | Tool discovery service with LRU caching. | `ToolDiscovery` | 2 | 0 | Active / no tests |
| `integrations.mcp.error_envelope` | 223 | MCP-standard tool-result error envelope. | `ErrorCategory`, `ToolResultEnvelope`, `classify_tool_error`, `format_model_error_text` | 2 | 2 | Active |
| `integrations.mcp.protocol/ (pkg)` | 4 | Protocol layer exports. | - | 0 | 4 | Active (pkg) |
| `integrations.mcp.protocol.client` | 308 | MCP Protocol Client - JSON-RPC correlation and timeout management. | `McpTimeoutError`, `McpProtocolError`, `McpProtocolClient` | 7 | 4 | Active |
| `integrations.mcp.protocol.messages` | 132 | JSON-RPC message builders and validators. | `MessageBuilder`, `ErrorCode` | 2 | 2 | Active |
| `integrations.mcp.results/ (pkg)` | 4 | Result processing exports. | - | 0 | 1 | Active (pkg) |
| `integrations.mcp.results.budget` | 227 | Context Budget Guard - protects LLM context from oversized MCP outputs. | `ContextBudgetGuard`, `get_max_mcp_output_tokens`, `estimate_token_count`, `estimate_content_blocks_tokens` | 1 | 1 | Active |
| `integrations.mcp.results.storage` | 239 | MCP Output Storage - disk-backed storage for oversized/binary outputs. | `McpOutputStorage` | 1 | 1 | Active |
| `integrations.mcp.runtime/ (pkg)` | 4 | Runtime layer exports. | - | 0 | 1 | Active (pkg) |
| `integrations.mcp.runtime.backoff` | 64 | Exponential backoff with jitter for reconnection attempts. | `ExponentialBackoff` | 2 | 1 | Active |
| `integrations.mcp.runtime.manager` | 342 | MCP Connection Manager - orchestrates server connections and lifecycle. | `ConnectionMetadata`, `McpConnectionManager` | 2 | 1 | Active |
| `integrations.mcp.transports/ (pkg)` | 3 | Transport layer base interfaces and exports. | - | 0 | 1 | Active (pkg) |
| `integrations.mcp.transports.base` | 89 | Abstract base class for MCP transports. | `McpTransport` | 4 | 1 | Active |
| `integrations.mcp.transports.stdio` | 194 | Stdio transport for MCP servers running as subprocesses. | `StdioTransport` | 1 | 1 | Active |
| `integrations.mcp.transports.websocket` | 151 | WebSocket transport for MCP servers. | `WebSocketTransport` | 1 | 0 | Active / no tests |
| `integrations.mcp.types` | 144 | Core type definitions for MCP integration. | `TransportType`, `McpConnectionState`, `McpStdioConfig`, `McpWebSocketConfig` | 13 | 4 | Active |
| `integrations.metrics` | 283 | OpenTelemetry Metrics API with Prometheus scrape endpoint. | `is_metrics_enabled`, `get_service_name`, `normalize_path` | 4 | 2 | Active |
| `integrations.otel` | 173 | OpenTelemetry setup for AI Toolkit tracing. | `is_tracing_enabled`, `is_sensitive_capture_enabled`, `get_otlp_endpoint` | 9 | 6 | Active |
| `integrations.tracing` | 324 | Concrete trace adapter implementations. | `ConsoleTraceAdapter`, `FileTraceAdapter`, `CompositeTraceAdapter`, `NullTraceAdapter` | 5 | 5 | Active |

### 2.13 `langchain`

LangGraph-based engine: YAML `WorkflowConfig` loader (`config.py`), graph compiler (`graph.py`, `graph_wiring.py`), `WorkflowRunner`, provider model registry/builders (`models.py`, `model_builders.py`), personas, standard file tools, `WorkflowState` TypedDict. Optional heavy deps are probed through `dependencies.py` (`MissingLangChainDependencyError`). `agents.py`, `model_builders.py`, `tools.py` are coverage-omitted.

| module | LOC | purpose | key symbols | used by | tests | status |
|---|---:|---|---|---:|---:|---|
| `langchain/ (pkg)` | 38 | LangChain-native agentic workflow engine. | - | 6 | 8 | Active (pkg) |
| `langchain.agents` | 123 | Agent factory - creates LangGraph ReAct agents from config. | `parse_agent_tier`, `create_agent` | 2 | 6 | Active |
| `langchain.config` | 569 | YAML workflow configuration loader. | `ModelParamsConfig`, `StepConfig`, `InputConfig`, `OutputConfig`, `get_workflow_path`, `load_workflow_config`, `list_workflows` | 10 | 28 | Active |
| `langchain.dependencies` | 31 | Helpers for classifying optional LangChain/LangGraph import failures. | `MissingLangChainDependencyError`, `is_missing_langchain_dependency_error`, `to_missing_langchain_dependency_error` | 5 | 2 | Active |
| `langchain.expressions` | 133 | Expression evaluator for YAML conditions. | `ConditionEvaluationError`, `evaluate_condition`, `resolve_expression` | 2 | 3 | Active |
| `langchain.graph` | 184 | Graph compiler - turns YAML WorkflowConfig into a LangGraph StateGraph. | `compile_workflow` | 4 | 14 | Active |
| `langchain.graph_wiring` | 1274 | Graph topology/wiring - node factories and edge assembly for LangGraph. | `resolve_inputs_into_context`, `next_iteration`, `resolve_loop_max` | 2 | 9 | Active / >800 LOC |
| `langchain.model_builders` | 890 | Factory functions that construct LangChain ``BaseChatModel`` instances. | `build_github_model`, `build_openai_model`, `build_nvidia_model` | 1 | 9 | Active / >800 LOC |
| `langchain.model_utils` | 226 | Provider detection utilities and shared helpers for the LangChain model registry. | `provider_prefix`, `is_provider_available`, `probe_available_providers` | 4 | 5 | Active |
| `langchain.models` | 743 | Model provider registry for the LangChain workflow engine. | `DriftReport`, `probe_available_providers`, `probe_and_update_tier_defaults`, `detect_registry_drift` | 7 | 28 | Active |
| `langchain.personas` | 97 | Persona registry - pre-canned agent personas selectable per step. | `Persona`, `list_personas`, `get_persona`, `resolve_persona_prompt` | 2 | 1 | Active |
| `langchain.response_sanitization` | 37 | Response sanitization for the LangGraph engine. | `sanitize_agent_response_text` | 1 | 1 | Active |
| `langchain.result_builder` | 87 | Result construction helpers for the LangChain workflow runner. | `steps_dict_to_list`, `build_workflow_result` | 1 | 1 | Active |
| `langchain.runner` | 971 | Top-level workflow runner. | `WorkflowRunner` | 2 | 17 | Active / >800 LOC |
| `langchain.state` | 55 | Workflow state definition for LangGraph. | `WorkflowState`, `initial_state` | 3 | 9 | Active |
| `langchain.tools` | 593 | Standard LangChain tool definitions. | `file_read`, `file_write`, `file_list` | 3 | 13 | Active |

### 2.14 `middleware`

Prompt/response sanitization pipeline: `MiddlewareChain` runs pluggable detectors (secrets via regex + entropy, PII, prompt-injection markers, Unicode normalization); `ClassificationPolicy` maps findings to a classification; `SanitizationMiddleware` and `ResponseSanitizer` are the entry points used by `models/sanitization_dispatch.py` and the server ASGI wrapper.

| module | LOC | purpose | key symbols | used by | tests | status |
|---|---:|---|---|---:|---:|---|
| `middleware/ (pkg)` | 16 | Prompt sanitization and security middleware pipeline. | - | 0 | 8 | Active (pkg) |
| `middleware.base` | 95 | Base middleware chain that processes content through an ordered detector pipeline. | `SanitizationDetectorError`, `MiddlewareChain` | 2 | 1 | Active |
| `middleware.detectors/ (pkg)` | 11 | Pluggable threat detectors for the sanitization pipeline. | - | 0 | 4 | Active (pkg) |
| `middleware.detectors.base` | 45 | Compiled-pattern dataclasses (SecretPattern, InjectionPattern) shared by detectors. | `SecretPattern`, `InjectionPattern` | 2 | 0 | Active / no tests |
| `middleware.detectors.injection` | 71 | Detects known prompt injection markers and instruction override attempts. | `PromptInjectionDetector` | 2 | 2 | Active |
| `middleware.detectors.pii` | 46 | Detects personally identifiable information (PII) patterns. | `PIIDetector` | 2 | 1 | Active |
| `middleware.detectors.secrets` | 220 | Detects secrets and API keys via regex patterns and entropy analysis. | `SecretDetector` | 3 | 2 | Active |
| `middleware.detectors.unicode` | 93 | Normalizes Unicode and removes dangerous invisible characters. | `UnicodeSanitizer` | 3 | 4 | Active |
| `middleware.policy` | 44 | Classification policy that maps detector findings to sanitization outcomes. | `PolicyConfig`, `ClassificationPolicy` | 3 | 1 | Active |
| `middleware.response_sanitizer` | 114 | Response-path sanitizer for LLM outputs. | `ResponseSanitizationConfig`, `ResponseSanitizer` | 4 | 4 | Active |
| `middleware.sanitization` | 85 | High-level sanitization middleware combining detectors, policy, and chain. | `SanitizationMiddleware` | 5 | 4 | Active |

### 2.15 `models`

The model plane. `ModelTier` + `ModelRouter` (fallback chains) are extended by `SmartModelRouter` (stats, circuit breakers, cooldowns, bulkheads, optional Redis-shared state); `LLMClientWrapper` (`client.py`) is the high-level client with caching, token budget, retries and sanitization; `backends*.py` implement providers (GitHub Models, OpenAI-compatible/NVIDIA, OpenRouter, Ollama, ONNX, Claude subscription); `*_discovery.py` probe live model catalogs; `model_registry.py` loads the curated registry YAML (ADR-040); `ek_provider.py`/`ek_adapters.py` bridge to ExecutionKit (ADR-023).

| module | LOC | purpose | key symbols | used by | tests | status |
|---|---:|---|---|---:|---:|---|
| `models/ (pkg)` | 112 | Models module - Model routing and statistics. | - | 15 | 8 | Active (pkg) |
| `models.backends` | 458 | LLM backend implementations. | `MultiBackend`, `MockBackend`, `get_backend`, `auto_configure_backend` | 3 | 30 | Active |
| `models.backends_base` | 47 | Abstract base class and shared types for LLM backends. | `LLMBackend` | 6 | 12 | Active |
| `models.backends_claude` | 331 | Claude backend authenticated by a Claude subscription sign-in. | `ClaudeSubscriptionError`, `ClaudeSubscriptionBackend`, `subscription_env`, `claude_sdk_available` | 2 | 1 | Active |
| `models.backends_cloud` | 802 | Cloud provider LLM backend implementations. | `GitHubModelsBackend`, `OpenAIBackend`, `NvidiaBackend`, `OpenRouterBackend`, `nvidia_thinking_disabled`, `nim_chat_template_kwargs`, `nim_reasoning_payload` | 2 | 10 | Active / >800 LOC |
| `models.backends_local` | 302 | Local model LLM backend implementations. | `OllamaBackend`, `OnnxBackend` | 1 | 5 | Active |
| `models.cache_budget` | 81 | Token budget and response cache data structures. | `TokenBudget`, `ProcessWideTokenBudget`, `CachedResponse` | 2 | 6 | Active |
| `models.client` | 896 | LLM client wrapper with smart routing integration. | `LLMClientWrapper`, `get_client`, `effective_no_llm_mode`, `reset_client` | 7 | 20 | Active / >800 LOC |
| `models.cloud_discovery` | 659 | Live model discovery for keyed cloud providers (ADR-039). | `CloudModelInfo`, `resolve_openai_base_url`, `discover_openai_models`, `discover_anthropic_models` | 6 | 10 | Active |
| `models.discovery_logging` | 75 | Defense-in-depth redaction of credential-bearing URL query params in logs. | `SecretQueryParamFilter`, `redact_url_secrets`, `install_redaction_filter` | 1 | 1 | Active |
| `models.discovery_snapshot` | 305 | Unified model discovery snapshot across every serving path (ARP-IMPROVEMENTS F2). | `DiscoveredModel`, `discover_all_models` | 0 | 1 | Test-only |
| `models.docker_model_runner_discovery` | 85 | Live model discovery for Docker Model Runner. | `DockerModelRunnerInfo`, `discover_docker_model_runner_models` | 1 | 2 | Active |
| `models.ek_adapters` | 177 | ADR-023 Phase 4: pure adapter between runtime backend dicts and EK contracts. | `dict_to_llm_response`, `llm_response_to_dict`, `map_http_error` | 2 | 2 | Active |
| `models.ek_provider` | 586 | ADR-023 Phase 5a: ExecutionKit ``LLMProvider`` over the runtime router. | `ProviderAttempt`, `SmartRouterProvider`, `get_provider`, `reset_provider_cache` | 2 | 9 | Active |
| `models.fallback_selector` | 98 | Model fallback-selection loop for LLM client calls. | `run_with_fallback` | 1 | 1 | Active |
| `models.foundry_local_discovery` | 96 | Live model discovery for Foundry Local, the on-device ONNX runtime. | `FoundryLocalModelInfo`, `discover_foundry_local_models` | 1 | 2 | Active |
| `models.lemonade_discovery` | 105 | Live model discovery for Lemonade, the Ryzen AI hybrid NPU serving path. | `LemonadeModelInfo`, `discover_lemonade_models` | 1 | 2 | Active |
| `models.llm` | 31 | LLM Client Adapter for Agentic V2. | `LLMClient` | 0 | 0 | Orphan? / no tests |
| `models.local_discovery` | 441 | Discovery for local LM Studio and ONNX model providers (ADR-038). | `LocalModelInfo`, `LmStudioCatalog`, `LmStudioLoadError`, `LmStudioUnavailableError`, `resolve_lmstudio_host`, `discover_lmstudio_catalog`, `discover_lmstudio_models` | 6 | 6 | Active |
| `models.model_registry` | 422 | Curated single source-of-truth model registry (ADR-040). | `RegisteredModel`, `SpecialModels`, `Registry`, `RegistryDriftError`, `load_registry`, `clear_cache`, `tier_chain` | 12 | 13 | Active |
| `models.model_stats` | 322 | Model statistics tracking with advanced metrics. | `CircuitState`, `LatencyPercentiles`, `ModelStats` | 4 | 9 | Active |
| `models.ollama_discovery` | 232 | Live Ollama model discovery via the raw REST API (ADR-037). | `OllamaModelInfo`, `local_model_names`, `name_is_listed`, `is_served_locally` | 5 | 7 | Active |
| `models.price_annotation` | 145 | Annotate model-probe rows with ``price_label`` / ``price_reason``. | `annotate_price_labels` | 1 | 3 | Active |
| `models.price_label` | 173 | Free / paid / local / unknown price labels for model-probe rows. | `Prices`, `PriceFacts`, `rate_prices`, `label_price` | 1 | 2 | Active |
| `models.rate_limit_tracker` | 544 | Rate-limit tracking with provider-aware header parsing (ADR-002E). | `TokenBucket`, `ProviderRateLimits`, `RateLimitTracker` | 3 | 1 | Active |
| `models.redis_state` | 480 | Redis-backed circuit breaker state store for multi-worker deployments. | `RedisCircuitBreakerStore` | 3 | 4 | Active |
| `models.retry_utils` | 126 | Retry-with-jitter utilities for LLM client calls. | `retry_with_jitter`, `compute_retry_delay`, `resolve_rate_limit_delay` | 1 | 3 | Active |
| `models.router` | 331 | Model router with configurable fallback chains. | `ModelTier`, `FallbackChain`, `ChainBuilder`, `ModelRouter`, `get_router`, `reset_router` | 11 | 28 | Active |
| `models.sanitization_dispatch` | 169 | Sanitization dispatch helpers for LLM prompt and response filtering. | `sanitize_prompt`, `sanitize_content_blocks`, `sanitize_messages` | 1 | 1 | Active |
| `models.secrets` | 121 | Secret provider abstractions with environment fallback. | `SecretProvider`, `MappingSecretProvider`, `EnvSecretProvider`, `ChainedSecretProvider`, `get_default_secret_provider`, `set_default_secret_provider`, `reset_default_secret_provider` | 7 | 3 | Active |
| `models.smart_router` | 906 | Production router: per-model stats, 3-state circuit breakers, adaptive cooldowns, bulkheads, rate-limit awareness, Redis-shared state. | `CircuitResolvedError`, `ModelSelection`, `CooldownConfig`, `SmartModelRouter`, `get_smart_router`, `set_smart_router`, `reset_smart_router` | 6 | 24 | Active / >800 LOC |
| `models.weight_integrity` | 330 | Integrity checks for locally loaded model weight files. | `TrustedHashConfigError`, `ModelWeightVerificationError`, `TrustedModelHash`, `VerificationResult`, `verify_model_weights`, `compute_model_sha256`, `load_trusted_hashes` | 0 | 2 | Test-only |

### 2.16 `prompts`

Markdown agent prompts (`architect.md`, `coder.md`, `orchestrator.md`, `planner.md`, `reviewer.md`, `tester.md`, `validator.md`, `judges/plan_judge_*.md`) with `load_prompt`/`list_prompts` and a content-addressed `PromptRegistry` (WP3-A). The entire package is coverage-omitted.

| module | LOC | purpose | key symbols | used by | tests | status |
|---|---:|---|---|---:|---:|---|
| `prompts/ (pkg)` | 87 | Prompt templates for agentic_v2 agents. | `load_prompt`, `list_prompts`, `get_prompt_path` | 0 | 4 | Active (pkg) |
| `prompts.registry` | 189 | Prompt versioning registry (WP3-A). | `PromptRecord`, `PromptRegistry`, `normalize_prompt_text`, `compute_content_hash`, `default_registry` | 3 | 4 | Active |

### 2.17 `scoring`

Workflow-result scoring: hard gates, criterion floors, hybrid objective + LLM-judge + advisory layers (`evaluation_scoring.py`), bias-aware `LLMJudge`, scoring profiles A-E, dataset-to-workflow matching, ADR-042 EvalKit bridge (`evalkit_bridge.py`, runtime-owned `rubrics/`), advisory per-step scoring, and the ADR-007 multidimensional research scorer.

| module | LOC | purpose | key symbols | used by | tests | status |
|---|---:|---|---|---:|---:|---|
| `scoring/ (pkg)` | 7 | Scoring and judge domain logic for workflow evaluation. | - | 1 | 8 | Active (pkg) |
| `scoring.dataset_matching` | 499 | Dataset-to-workflow matching and sample adaptation utilities. | `match_workflow_dataset`, `validate_required_inputs_present`, `adapt_sample_to_workflow_inputs` | 2 | 3 | Active |
| `scoring.eval_config` | 64 | Loader for the evaluation YAML configuration. | - | 3 | 0 | Active / no tests |
| `scoring.evalkit_bridge` | 264 | ARP adapter for the published optional EvalKit dependency (ADR-042). | `rubric_from_yaml_dict`, `score_criteria`, `workflow_callable_target` | 1 | 2 | Active |
| `scoring.evaluation_scoring` | 1029 | Scoring engine for workflow evaluation results. | `JudgeRequiredError`, `HardGateResult`, `CriterionFloorResult`, `pass_threshold`, `judge_required`, `validate_evaluation_payload_schema` | 2 | 5 | Active / >800 LOC |
| `scoring.judge` | 609 | LLM-as-Judge evaluation engine for hybrid workflow scoring. | `JudgeCriterionDefinition`, `JudgeCriterionScore`, `JudgeEvaluationResult`, `JudgeResponseProvider`, `validate_judge_structured_output`, `check_swapped_order_consistency`, `evaluate_calibration_set` | 5 | 7 | Active |
| `scoring.multidimensional_scoring` | 462 | ADR-007: Multidimensional research quality scoring engine. | `ResearchTier`, `DimensionResult`, `MultidimensionalGateResult`, `classify_dimension`, `compute_ci_tiebreaker`, `evaluate_research_round` | 0 | 2 | Test-only |
| `scoring.rubrics/ (pkg)` | 18 | Runtime-owned rubric resources (ADR-042 Slice C). | `load_rubric` | 1 | 1 | Active (pkg) |
| `scoring.scoring_criteria` | 573 | Criterion-level scoring, grading, and hybrid score composition. | `has_content_leaves`, `has_scoring_tokens`, `serialize_output_text` | 2 | 1 | Active |
| `scoring.scoring_profiles` | 121 | Predefined scoring profiles (A--E) for workflow-family evaluation. | `ScoringProfile`, `get_profile` | 1 | 1 | Active |
| `scoring.step_scoring` | 246 | Advisory step scoring: output presence never implies quality or a pass. | `ScoreStatus`, `CriterionEvidence`, `StepScore`, `StepScoringListener`, `exact_match_evidence`, `score_step`, `build_step_scoring_listener` | 1 | 1 | Active |

### 2.18 `security`

Single module: the shared SSRF URL guard (`url_guard.py`: `validate_url`, `validate_url_pinned`, `check_resolved_address`) used by outbound-HTTP paths such as `tools/builtin/http_ops.py`.

| module | LOC | purpose | key symbols | used by | tests | status |
|---|---:|---|---|---:|---:|---|
| `security/ (pkg)` | 4 | Security utilities for the agentic_v2 runtime. | - | 0 | 1 | Active (pkg) |
| `security.url_guard` | 362 | Shared SSRF URL guard for all outbound-HTTP paths. | `check_resolved_address`, `validate_url`, `validate_url_pinned` | 4 | 1 | Active |

### 2.19 `tools`

Tool system: `BaseTool`/`ToolSchema`/`ToolResult`, an auto-discovering `ToolRegistry`, and `tools/builtin/` (tiered: Tier 0 no-LLM file/git/http/shell/memory/transform/build ops, Tier 1 code analysis, Tier 2 search). The repo-root `tools/` package is a separate, out-of-scope package.

| module | LOC | purpose | key symbols | used by | tests | status |
|---|---:|---|---|---:|---:|---|
| `tools/ (pkg)` | 12 | Tool system for agentic workflows v2. | - | 4 | 8 | Active (pkg) |
| `tools.base` | 193 | Base classes for the tool system. | `ToolSchema`, `ToolResult`, `BaseTool` | 19 | 11 | Active |
| `tools.builtin/ (pkg)` | 87 | Built-in tools for Tier 0-2 operations. | - | 1 | 8 | Active (pkg) |
| `tools.builtin.build_ops` | 445 | Tier 0 build verification tools. | `BuildAppTool` | 1 | 2 | Active |
| `tools.builtin.code_analysis` | 240 | Tier 1 code analysis tools - Small model required. | `CodeAnalysisTool`, `AstDumpTool` | 1 | 1 | Active |
| `tools.builtin.code_execution` | 311 | Tier 0 Code execution tool with sandboxing. | `CodeExecutionTool` | 1 | 3 | Active |
| `tools.builtin.context_ops` | 146 | Tier 0 context utilities. | `TokenEstimateTool`, `ContextTrimTool` | 1 | 2 | Active |
| `tools.builtin.file_ops` | 396 | Tier 0 file operation tools - No LLM required. | `FileCopyTool`, `FileMoveTool`, `FileDeleteTool`, `DirectoryCreateTool` | 1 | 4 | Active |
| `tools.builtin.git_ops` | 249 | Tier 0 Git operation tools - No LLM required. | `GitTool`, `GitStatusTool`, `GitDiffTool` | 1 | 4 | Active |
| `tools.builtin.http_ops` | 386 | Tier 0 HTTP request tools - No LLM required. | `GuardedResolver`, `HttpTool`, `HttpGetTool`, `HttpPostTool` | 1 | 4 | Active |
| `tools.builtin.memory_ops` | 391 | Tier 0 persistent memory tools. | `MemoryUpsertTool`, `MemoryGetTool`, `MemoryListTool`, `MemorySearchTool` | 1 | 2 | Active |
| `tools.builtin.search_ops` | 356 | Tier 2 semantic search tools - Medium model required. | `SearchTool`, `GrepTool` | 1 | 3 | Active |
| `tools.builtin.shell_ops` | 344 | Tier 0 Shell execution tools - No LLM required. | `ShellTool`, `ShellExecTool` | 1 | 4 | Active |
| `tools.builtin.transform` | 303 | Tier 0 transformation tools - No LLM required. | `JsonTransformTool`, `TemplateRenderTool`, `ConfigMergeTool`, `YamlLoadTool` | 1 | 1 | Active |
| `tools.builtin.verify_fact` | 190 | Cross-role fact-verification tool (the exam's shared-tool pattern). | `VerifyFactTool` | 1 | 1 | Active |
| `tools.registry` | 126 | Tool registry with auto-discovery. | `ToolRegistry`, `get_registry`, `reset_registry` | 2 | 17 | Active |
| `tools.subprocess_utils` | 30 | Shared subprocess environment utilities for tool modules. | `minimal_subprocess_env` | 3 | 1 | Active |

### 2.20 `utils`

Path-containment helpers (`is_within_base`, `ensure_within_base`) used across tools and server.

| module | LOC | purpose | key symbols | used by | tests | status |
|---|---:|---|---|---:|---:|---|
| `utils/ (pkg)` | 3 | Utility helpers shared across runtime modules. | - | 0 | 2 | Active (pkg) |
| `utils.path_safety` | 49 | Path safety helpers for validating repository-local file paths. | `is_within_base`, `ensure_within_base` | 9 | 2 | Active |

### 2.21 `server (summary; API detail in section 3)`

FastAPI application: factory (`app.py`), lifespan, API-key and OIDC auth, audit log, ASGI middleware (sanitization, metrics, W3C traceparent, rate limit), WebSocket/SSE streaming with durable replay stores, route modules under `routes/`, and the Pydantic request/response models (`models.py`, `models_settings.py`). Route-by-route detail is in section 3; only module facts here.

| module | LOC | purpose |
|---|---:|---|
| `server/ (pkg)` | 4 | Server module for agentic workflows v2. |
| `server._step_events` | 281 | Step event builders and broadcast logic for LangGraph streaming. |
| `server._stream_merge` | 56 | Stream state merging helpers for LangGraph node updates. |
| `server.app` | 157 | FastAPI application factory for the Agentic Workflows V2 server. |
| `server.audit_log` | 437 | Tamper-evident audit logging for server security and workflow events. |
| `server.auth` | 420 | API key authentication middleware for the Agentic server. |
| `server.auth_oidc` | 319 | OIDC JWT authentication middleware for the Agentic server. |
| `server.datasets` | 667 | Dataset loading, listing, and discovery utilities. |
| `server.evaluation` | 137 | Backward-compatible facade for the workflow evaluation subsystem. |
| `server.execution` | 646 | Workflow execution orchestration. |
| `server.lifespan` | 267 | FastAPI lifespan context manager and its startup helper functions. |
| `server.middleware/ (pkg)` | 130 | ASGI middleware wrappers for the Agentic Workflows V2 server. |
| `server.middleware.metrics` | 52 | HTTP metrics middleware for the Agentic Workflows V2 server. |
| `server.middleware.rate_limit` | 80 | Global rate-limiting setup using slowapi. |
| `server.middleware.tracing` | 110 | W3C traceparent propagation middleware for the Agentic Workflows V2 server. |
| `server.models` | 747 | Pydantic request and response models for the Agentic server REST API. |
| `server.models_settings` | 306 | Wire models for catalog, settings and eval-comparison APIs. |
| `server.normalization` | 30 | Backward-compatible re-exports for score normalization helpers. |
| `server.pack_validation` | 165 | Model-pack validation shared by the settings routes and run submission. |
| `server.replay_store` | 682 | Durable replay-buffer backends for per-run WebSocket event history. |
| `server.result_normalization` | 302 | Pure helper functions for normalizing workflow results. |
| `server.routes/ (pkg)` | 16 | API route modules for the Agentic server. |
| `server.routes.agents` | 57 | Agent discovery endpoint for the Agentic server. |
| `server.routes.catalog` | 73 | Catalog routes: personas, tools, and observer channels. |
| `server.routes.chat` | 276 | Direct model chat playground route. |
| `server.routes.evaluation_routes` | 582 | Evaluation dataset listing and preview routes. |
| `server.routes.health` | 126 | Health and readiness endpoints for the Agentic server. |
| `server.routes.model_finder` | 764 | Local model finder routes backed by host hardware profiling. |
| `server.routes.models` | 146 | Model provider discovery and probe endpoint. |
| `server.routes.runs` | 573 | Run history routes for the Agentic Workflows V2 server. |
| `server.routes.settings_routes` | 668 | Runtime settings routes: provider endpoints and model tier configuration. |
| `server.routes.workflows` | 474 | Workflow execution, DAG visualization, and evaluation routes. |
| `server.spa` | 46 | Single-page application (SPA) static file serving helpers. |
| `server.websocket` | 566 | WebSocket and SSE streaming for real-time workflow execution updates. |

### 2.22 `workflows (summary; YAML detail in section 5)`

Python side of YAML workflows: `loader.py` parses `definitions/*.yaml` into `WorkflowDefinition` + DAG; `runner.py` is the unified entry point; `run_logger.py` writes JSON run records; `artifact_extractor.py` writes FILE blocks to disk; `lib/ci_calculator.py` supports multidimensional scoring. Definitions shipped (`workflows/definitions/`): `bug_resolution`, `code_review`, `conditional_branching`, `consensus_review`, `fullstack_generation`, `iterative_review`, `plan_tribunal`, `test_deterministic`, `test_workflow`.

| module | LOC | purpose |
|---|---:|---|
| `workflows/ (pkg)` | 30 | Workflow definitions and orchestration. |
| `workflows.artifact_extractor` | 183 | Artifact extractor - writes FILE blocks from step outputs to disk. |
| `workflows.lib/ (pkg)` | 28 | Shared workflow helper functions. |
| `workflows.lib.ci_calculator` | 178 | Confidence-index helpers for multidimensional research scoring. |
| `workflows.loader` | 639 | Workflow loader - YAML definitions to executable DAG objects. |
| `workflows.run_logger` | 471 | Structured JSON run logger for workflow evaluations. |
| `workflows.runner` | 423 | Workflow runner - unified entry point for YAML workflows. |

### 2.23 Data structures

Counts across `agentic_v2/` (inventory `classes[].kinds`): 132 Pydantic models, 31 Enums, 15 Protocols, 10 ABCs, 6 exception classes, 1 TypedDict (`langchain/state.py`), 1 pydantic-settings class (`settings.py`); a further 119 `@dataclass` classes were found by AST scan (the inventory's `kinds` field does not tag dataclasses). The table below lists the ones that matter; `WIRE` marks the eight wire-format contract models.

#### 2.23.1 The 8 wire-format contract models (Python to JSON Schema to TypeScript)

Pipeline: Pydantic model, then `agentic-workflows-v2/scripts/generate_ts_types.py` writes the aggregate JSON Schema into `agentic-workflows-v2/tests/schemas/`, then `npm run generate:types` (from `ui/`) emits the `*.generated.ts` mirror. CI job `wire-format-drift` fails on any mismatch (`.claude/rules/ci.md`, ADR-014). The generated headers say "AUTO-GENERATED — DO NOT EDIT BY HAND".

| # | Pydantic model | defined in | JSON Schema (`agentic-workflows-v2/tests/schemas/`) | TS mirror (`agentic-workflows-v2/ui/src/api/`) | TS LOC |
|---|---|---|---|---|---:|
| 1 | `ExecutionEvent` (discriminated union) | `agentic_v2/contracts/events.py` | `events.schema.json` | `events.generated.ts` | 182 |
| 2 | `StepResultRecord` | `agentic_v2/contracts/messages.py` | `step_result.schema.json` | `step_result.generated.ts` | 70 |
| 3 | `DAGResponse` | `agentic_v2/server/models.py` | `dag_response.schema.json` | `dag_response.generated.ts` | 93 |
| 4 | `WorkflowInputSchemaResponse` | `agentic_v2/server/models.py` | `workflow_input_schema.schema.json` | `workflow_input_schema.generated.ts` | 96 |
| 5 | `WorkflowEditorStep` | `agentic_v2/server/models.py` | `workflow_editor_step.schema.json` | `workflow_editor_step.generated.ts` | 66 |
| 6 | `RunsSummaryResponse` | `agentic_v2/server/models.py` | `runs_summary.schema.json` | `runs_summary.generated.ts` | 30 |
| 7 | `ChatRequest` (RootModel union) | `agentic_v2/contracts/chat.py` | `chat_request.schema.json` | `chat_request.generated.ts` | 186 |
| 8 | `ChatStreamEvent` (discriminated union) | `agentic_v2/contracts/chat.py` | `chat_stream_event.schema.json` | `chat_stream_event.generated.ts` | 57 |

Source of the mapping: module docstring and constants at `agentic-workflows-v2/scripts/generate_ts_types.py:9-53`. `agentic-workflows-v2/ui/src/api/` also holds hand-written `client.ts`, `types.ts`, `websocket.ts`, `hardware.ts` (not generated).

Separate from the eight: `agentic-workflows-v2/tests/schemas/` holds 24 further per-model snapshots (`AgentMessage.json`, `ChatDoneEvent.json`, `CodeReviewOutput.json`, `ReviewReport.json`, `StepResult.json`, `TaskInput.json`, `WorkflowResult.json`, ...; 32 files total including the 8 aggregates), written by `agentic-workflows-v2/scripts/generate_schemas.py` and checked by `agentic-workflows-v2/tests/test_schema_drift.py`. These have no TS mirror (inferred from absence of matching `*.generated.ts`).

#### 2.23.2 Key structures

| name | kind | file | key fields / members | role |
|---|---|---|---|---|
| `ExecutionEvent` | Annotated union (discriminator `type`) | `agentic-workflows-v2/agentic_v2/contracts/events.py` | - | WIRE: discriminated union (on `type`) of 12 event models: WorkflowStart/End, StepStart/End/Complete/Error, TokenDelta, Error, EvaluationStart/Complete, ApprovalRequired/Decision. Emitted over WS/SSE. |
| `StepResultRecord` | Pydantic | `agentic-workflows-v2/agentic_v2/contracts/messages.py` | step_name, status, agent_role, tier, model_used, duration_ms | WIRE: persisted per-step record (step_name, status, agent_role, tier, model_used, duration_ms, retry_count, tokens_used, ...). |
| `StepResult` | Pydantic | `agentic-workflows-v2/agentic_v2/contracts/messages.py` | step_name, status, agent_role, tier, model_used, input_data | Step outcome contract (input_data/output_data/error) used between agents and engine. |
| `WorkflowResult` | Pydantic | `agentic-workflows-v2/agentic_v2/contracts/messages.py` | workflow_id, workflow_name, steps, overall_status, start_time, end_time | Workflow outcome (steps, overall_status, final_output, metadata). |
| `AgentMessage` | Pydantic | `agentic-workflows-v2/agentic_v2/contracts/messages.py` | message_type, role, content, metadata, timestamp, correlation_id | Inter-agent message envelope (message_type, role, content, correlation_id). |
| `ReviewReport / Finding` | mixed (first: Pydantic) | `agentic-workflows-v2/agentic_v2/contracts/messages.py` | overall_status, quality_score, findings, summary, positive_observations | Structured code-review result (overall_status, quality_score, findings). |
| `StepStatus / MessageType / ReviewStatus / TestGateStatus / FindingSeverity` | mixed (first: Enum) | `agentic-workflows-v2/agentic_v2/contracts/messages.py` | - | Status enums (`str, Enum`). |
| `ChatRequest` | Pydantic RootModel | `agentic-workflows-v2/agentic_v2/contracts/chat.py` | - | WIRE: `RootModel` union of `ModelChatRequest` (model) and `TierChatRequest` (tier) over `messages` + `temperature`; body of `POST /api/chat`. |
| `ChatStreamEvent` | Annotated union (discriminator `type`) | `agentic-workflows-v2/agentic_v2/contracts/chat.py` | - | WIRE: union of ChatTokenEvent / ChatRouteEvent / ChatMediaEvent / ChatDoneEvent / ChatErrorEvent for the chat SSE stream. |
| `VerificationPolicy / CorrectionAttempt / VerificationResult` | mixed (first: Pydantic) | `agentic-workflows-v2/agentic_v2/contracts/verification.py` | enabled, max_retries, token_budget_pct, verification_commands, stop_on_first_failure, escalation_strategy | Self-correction loop policy (max_retries, token_budget_pct, verification_commands, escalation_strategy) and results. |
| `SanitizationResult / Finding` | mixed (first: Pydantic) | `agentic-workflows-v2/agentic_v2/contracts/sanitization.py` | classification, findings, sanitized_text, original_hash, timestamp, detector_versions | Immutable sanitization pipeline output (classification, findings, sanitized_text, original_hash). |
| `TaskInput / TaskOutput (+ CodeGeneration*, CodeReview*, TestGeneration*)` | mixed (first: Pydantic) | `agentic-workflows-v2/agentic_v2/contracts/schemas.py` | task_id, context, constraints | Structured agent I/O base classes and per-task schemas; backing `tests/schemas/TaskInput.json` etc. |
| `DAGResponse` | Pydantic | `agentic-workflows-v2/agentic_v2/server/models.py` | name, description, nodes, edges, inputs | WIRE: workflow DAG for the UI (name, description, nodes: DAGNodeModel, edges: DAGEdgeModel, inputs). |
| `WorkflowInputSchemaResponse` | Pydantic | `agentic-workflows-v2/agentic_v2/server/models.py` | name, description, nodes, edges, inputs | WIRE: workflow input schema (items: name/type/default/required/enum) plus nodes/edges. |
| `WorkflowEditorStep` | Pydantic | `agentic-workflows-v2/agentic_v2/server/models.py` | name, agent, description, tier, depends_on, when | WIRE: editable step (agent, tier, depends_on, when, loop_until, loop_max, model params). |
| `RunsSummaryResponse` | Pydantic | `agentic-workflows-v2/agentic_v2/server/models.py` | total_runs, success, failed, avg_duration_ms, workflows, tokens_30d | WIRE: run-history aggregates (total_runs, success, failed, avg_duration_ms, workflows, tokens_30d). |
| `WorkflowRunRequest` | Pydantic | `agentic-workflows-v2/agentic_v2/server/models.py` | workflow, input_data, run_id, adapter, model_override, model_pack | Run submission (workflow, input_data, adapter, model_override, model_pack, evaluation, execution_profile). |
| `RunEvaluationDetail / ScoreLayersModel / HardGatesModel` | mixed (first: Pydantic) | `agentic-workflows-v2/agentic_v2/server/models.py` | enabled, rubric, rubric_id, rubric_version, criteria, overall_score | Evaluation result payloads exposed to the UI. |
| `ExecutionContext` | dataclass | `agentic-workflows-v2/agentic_v2/engine/context.py` | workflow_id, run_id, _variables, _lock, _masked, _parent | Per-run mutable state: variables (locked, maskable), parent/child scopes, event handlers, service container, start_time. |
| `ServiceContainer` | dataclass | `agentic-workflows-v2/agentic_v2/engine/context.py` | _singletons, _factories | DI container (singletons + factories). |
| `StepDefinition` | dataclass | `agentic-workflows-v2/agentic_v2/engine/step.py` | name, description, func, tier, timeout_seconds, retry | Declarative step: name, func, tier, timeout, retry, when/unless, loop_until, verify policy; fluent builder. |
| `RetryConfig / RetryStrategy` | mixed (first: dataclass) | `agentic-workflows-v2/agentic_v2/engine/step.py` | max_retries, strategy, base_delay_seconds, max_delay_seconds, jitter, retry_on | Retry policy (max_retries, strategy, delays, jitter, retry_on/no_retry_on). |
| `StepState / StepStateManager` | mixed (first: Enum) | `agentic-workflows-v2/agentic_v2/engine/step_state.py` | - | Step lifecycle state machine with validated transitions. |
| `DAG` | dataclass | `agentic-workflows-v2/agentic_v2/engine/dag.py` | name, description, steps | Steps dict + dependency validation; raises MissingDependencyError / CycleDetectedError. |
| `ExecutionConfig / ExecutionHistory` | mixed (first: dataclass) | `agentic-workflows-v2/agentic_v2/engine/executor.py` | global_timeout_seconds, step_default_timeout_seconds, max_global_retries, enable_checkpoints, checkpoint_interval, max_memory_mb | Executor knobs (global timeout, checkpoints, memory cap) and audit trail. |
| `Pipeline / ParallelGroup / ConditionalBranch` | mixed (first: dataclass) | `agentic-workflows-v2/agentic_v2/engine/pipeline.py` | name, description, elements, checkpoint_interval, fail_fast, tags | Composable pipeline elements. |
| `IsolatedTaskRuntime (ABC)` | ABC | `agentic-workflows-v2/agentic_v2/engine/runtime.py` | - | SubprocessRuntime (default) and DockerRuntime (optional, resource-limited). |
| `ConsensusResult` | dataclass | `agentic-workflows-v2/agentic_v2/engine/consensus.py` | winner, votes, total_samples, agreement, tied, meets_threshold | Immutable vote outcome (winner, votes, agreement, meets_threshold). |
| `WorkflowState` | TypedDict | `agentic-workflows-v2/agentic_v2/langchain/state.py` | messages, context, inputs, outputs, steps, current_step | LangGraph state TypedDict (messages, context, inputs, outputs, steps, current_step, errors). |
| `WorkflowConfig / StepConfig / EvaluationConfig` | mixed (first: dataclass) | `agentic-workflows-v2/agentic_v2/langchain/config.py` | name, description, version, experimental, inputs, outputs | YAML-parsed workflow (LangChain path); parallel to `workflows.loader.WorkflowDefinition` (duplicate-model smell, see 2.25). |
| `WorkflowDefinition / WorkflowInput / WorkflowOutput` | mixed (first: dataclass) | `agentic-workflows-v2/agentic_v2/workflows/loader.py` | name, description, version, inputs, outputs, capabilities | YAML-parsed workflow for the native path (plus evaluation + capabilities). |
| `ModelTier (IntEnum) / FallbackChain / ModelRouter` | mixed (first: Enum) | `agentic-workflows-v2/agentic_v2/models/router.py` | - | Tier enum, ordered model chain, availability-aware router. |
| `SmartModelRouter / ModelSelection / CooldownConfig` | mixed (first: dataclass) | `agentic-workflows-v2/agentic_v2/models/smart_router.py` | model_stats, cooldown_config, stats_file, _auto_save, model_costs, rate_limit_tracker | Router state: per-model stats, cooldown config, provider semaphores/probe locks, optional Redis store; `ModelSelection` carries requested vs actual tier and `is_degraded`. |
| `ModelStats / CircuitState / LatencyPercentiles` | mixed (first: dataclass) | `agentic-workflows-v2/agentic_v2/models/model_stats.py` | model_id, success_count, failure_count, rate_limit_count, timeout_count, _ema_latency_ms | Counters, EMA latency, percentile window, 3-state circuit (CLOSED/OPEN/HALF_OPEN). |
| `TokenBucket / ProviderRateLimits / RateLimitTracker` | mixed (first: dataclass) | `agentic-workflows-v2/agentic_v2/models/rate_limit_tracker.py` | capacity, refill_rate, _tokens, _last_refill | Dual RPM/TPM buckets per provider (ADR-002E). |
| `TokenBudget / ProcessWideTokenBudget / CachedResponse` | mixed (first: dataclass) | `agentic-workflows-v2/agentic_v2/models/cache_budget.py` | max_tokens, used_tokens | Per-run and process-wide token caps; response cache entry. |
| `Registry / RegisteredModel / SpecialModels` | mixed (first: Pydantic) | `agentic-workflows-v2/agentic_v2/models/model_registry.py` | version, models, tiers, special | Pydantic model of `config/defaults/model_registry.yaml` (id, provider, tiers, capability, status, cost_lane, price_in/out, context_window). |
| `LLMBackend (ABC)` | ABC | `agentic-workflows-v2/agentic_v2/models/backends_base.py` | - | Provider backend interface. |
| `SecretProvider (Protocol) + Mapping/Env/Chained` | mixed (first: Protocol) | `agentic-workflows-v2/agentic_v2/models/secrets.py` | - | Secret lookup chain with env fallback. |
| `SmartRouterProvider / ProviderAttempt` | mixed (first: class) | `agentic-workflows-v2/agentic_v2/models/ek_provider.py` | - | ExecutionKit LLMProvider over the runtime router (ADR-023). |
| `ExecutionEngine / SupportsStreaming / SupportsCheckpointing / AgentProtocol / ToolProtocol / DetectorProtocol / MiddlewareProtocol / VerifierProtocol` | mixed (first: Protocol) | `agentic-workflows-v2/agentic_v2/core/protocols.py` | - | 8 runtime-checkable Protocol seams. |
| `AgenticError tree + ErrorCode` | mixed (first: Exception) | `agentic-workflows-v2/agentic_v2/core/errors.py` | - | Exception hierarchy (Workflow/Step/SchemaValidation/Adapter/Tool/MemoryStore/Configuration/NoProviderConfigured) and LLM error codes for retry logic. |
| `TenantContext` | dataclass | `agentic-workflows-v2/agentic_v2/core/tenant.py` | tenant_id, source, actor_subject | Resolved tenant scope (tenant_id, source, actor_subject). |
| `ApprovalProvider (Protocol) / ApprovalRequest / ApprovalDecision / ApprovalOutcome` | mixed (first: Protocol) | `agentic-workflows-v2/agentic_v2/governance/approval.py` | - | HITL gate types; providers: AutoApprove, AutoDeny, Callback, Policy (allowlist). |
| `HandoffSummary / FailureType / EscalationSink` | mixed (first: dataclass) | `agentic-workflows-v2/agentic_v2/governance/escalation.py` | subtask_id, failure_type, attempted_agents, partial_results, suggested_next_action | Escalation payload (subtask_id, failure_type, attempted_agents, partial_results, suggested_next_action). |
| `AgentConfig / AgentState / AgentEvent` | mixed (first: dataclass) | `agentic-workflows-v2/agentic_v2/agents/config.py` | name, description, system_prompt, default_tier, max_tier, max_iterations | Agent configuration and lifecycle enums. |
| `ConversationMemory / CaseFacts / ConversationMessage` | mixed (first: dataclass) | `agentic-workflows-v2/agentic_v2/agents/memory.py` | messages, max_messages, max_tokens, summaries, max_summaries, token_counter | Sliding-window history with summaries and durable run facts. |
| `Capability / CapabilitySet / CapabilityType` | mixed (first: dataclass) | `agentic-workflows-v2/agentic_v2/agents/capabilities.py` | type, proficiency, requirements, metadata | Capability declaration and matching. |
| `SubTask / OrchestratorInput / OrchestratorOutput` | mixed (first: dataclass) | `agentic-workflows-v2/agentic_v2/agents/orchestrator_models.py` | id, description, required_capabilities, dependencies, assigned_agent, result | Orchestrator decomposition schemas. |
| `BaseTool (ABC) / ToolSchema / ToolResult` | mixed (first: ABC) | `agentic-workflows-v2/agentic_v2/tools/base.py` | - | Tool contract and standardized result. |
| `McpServerConfig (+ Stdio/WebSocket/SSE configs), McpCapabilities, JsonRpc*` | mixed (first: Pydantic) | `agentic-workflows-v2/agentic_v2/integrations/mcp/types.py` | name, enabled, transport_type, stdio, websocket, sse | MCP configuration and JSON-RPC wire types (14 pydantic models). |
| `CanonicalEvent / AgentAdapter / ToolAdapter / WorkflowAdapter / TraceAdapter` | mixed (first: dataclass) | `agentic-workflows-v2/agentic_v2/integrations/base.py` | type, timestamp, step_name, data | Framework-neutral integration ABCs. |
| `JudgeEvaluationResult / JudgeCriterionScore / JudgeResponseProvider` | mixed (first: dataclass) | `agentic-workflows-v2/agentic_v2/scoring/judge.py` | criteria, normalized_score, model, model_version, prompt_version, temperature | Frozen judge outputs; pluggable judge backend Protocol. |
| `StepScore / ScoreStatus / StepScoringListener` | mixed (first: dataclass) | `agentic-workflows-v2/agentic_v2/scoring/step_scoring.py` | step_name, agent_type, rubric_name, weighted_score, criterion_scores, passed | Advisory step score; unavailable evidence carries null score. |
| `HardGateResult / CriterionFloorResult` | mixed (first: dataclass) | `agentic-workflows-v2/agentic_v2/scoring/evaluation_scoring.py` | required_outputs_present, overall_status_success, no_critical_step_failures, release_build_verified, schema_contract_valid, dataset_workflow_compatible | Binary gate and per-criterion floor results. |
| `ArtifactContract / ContractDiagnostic` | mixed (first: dataclass) | `agentic-workflows-v2/agentic_v2/artifact_contracts.py` | kind, required, aliases | Immutable per-artifact declaration and machine-readable violation. |
| `Settings (pydantic-settings)` | pydantic-settings | `agentic-workflows-v2/agentic_v2/settings.py` | agentic_tracing, agentic_metrics, agentic_trace_sensitive, otel_exporter_otlp_endpoint, otel_exporter_otlp_protocol, otel_service_name | All AGENTIC_*/OTEL env config. |
| `UiSettings / ProviderConfig / ModelPack / ModelPackRef` | mixed (first: Pydantic) | `agentic-workflows-v2/agentic_v2/ui_settings.py` | version, providers, tier_overrides, model_capabilities, model_packs, active_model_pack | Persisted UI settings document with immutable versioned model packs. |
| `PromptRegistry / PromptRecord` | mixed (first: class) | `agentic-workflows-v2/agentic_v2/prompts/registry.py` | - | Content-addressed (SHA-256) prompt versions. |
| `ReplayStore (Protocol)` | Protocol | `agentic-workflows-v2/agentic_v2/server/replay_store.py` | - | In-memory / Redis / SQLite event replay buffers. |
| `PolicyConfig / ClassificationPolicy` | mixed (first: Pydantic) | `agentic-workflows-v2/agentic_v2/middleware/policy.py` | critical_action, high_action, medium_action, low_action, high_entropy_action | Severity-to-classification mapping. |

### 2.24 Orphan / unused candidates

`py_inventory.json` flagged five non-test modules as `orphan_candidate`. Its import graph ignores relative imports and lazy (in-function) imports, so each was re-verified by grep over `agentic-workflows-v2/`, `scripts/`, `tools/`, `.github/`, pyproject files and YAML (searched for dotted paths, `from .x import`, `importlib`/string references, entry points, `__init__` re-exports). Verdicts:

| module | LOC | verdict | evidence |
|---|---:|---|---|
| `agentic_v2.contracts.schemas` | 385 | **Used (false positive)** | Imported relatively by `agentic_v2/contracts/__init__.py:73` (`from .schemas import (...)`), then re-exported to `agentic_v2/__init__.py`, `core/__init__.py` and consumed by `agents/architect.py`, `agents/base.py`, `agents/orchestrator*.py`, `agents/reviewer.py`, `agents/test_agent.py`, `agents/implementations/claude_agent.py` through `agentic_v2.contracts`. Exercised by `agentic-workflows-v2/tests/test_contracts.py` (code-generation/code-review schema classes) and the `tests/schemas/TaskInput.json` family. |
| `agentic_v2.governance.escalation` | 137 | **Used (false positive, lazy import)** | Re-exported by `agentic_v2/governance/__init__.py`; consumed by a function-local import in `agentic_v2/agents/orchestrator.py:393` (`from ..governance import HandoffSummary, route_handoff`) in `_emit_escalation_handoff`; tested by `agentic-workflows-v2/tests/test_escalation_handoff.py` (7 tests) and referenced from `tests/test_orchestrator_behavior.py`. |
| `agentic_v2.agents.implementations.agent_loader` | 118 | **Used dynamically (public API only; untested)** | Imported in `agents/implementations/__init__.py:31-32` inside a `try/except ImportError` guard (optional `[claude]` extra) and re-exported as `AGENTS`/`load_agents`. Runs `load_agents()` at import (`agent_loader.py:155`), reading `.md` agent files from a shipped dir plus `AGENTIC_EXTERNAL_AGENTS_DIR`. No in-repo consumer of `AGENTS`/`load_agents` was found outside that `__init__`, no test exercises it (only `tests/test_env_template_contract.py` mentions the env var), and `pyproject.toml` coverage-omits `agents/implementations/*`. Effectively an external-facing convenience with no internal caller. |
| `agentic_v2.engine.patterns` (package) | 3 | **Truly unused (empty stub)** | `engine/patterns/__init__.py` is a docstring plus `__all__ = []`; no importer, no test, no YAML/string reference. Only mention is the coverage-omit line `agentic-workflows-v2/pyproject.toml:180`. Git history: initial public release `d30379cb`, later touched only by the hygiene commit `7aeaf2d4`. Safe to delete together with the omit entry. |
| `agentic_v2.models.llm` | 31 | **Truly unused (legacy adapter, deletion planned)** | `LLMClient` adapter over the legacy `tools.llm.llm_client.LLMClient` implementing `agentic_v2_eval.interfaces.LLMClientProtocol`. No importer in runtime, scripts, tools or tests. Referenced only by ADR-042 (Slice D1 plans to delete or inline it, `docs/adr/ADR-042-agentic-evalkit-adoption.md:93`), the coverage-omit list (`pyproject.toml:205`), and `docs/integration-architecture.md:121`. It imports the repo-root `tools.llm.llm_client` and `agentic_v2_eval.interfaces`, so deleting it also removes those couplings from the runtime package. |

Additional modules with zero runtime importers but referenced by tests or other repos (not in the flagged five; **Test-only** in the tables above):

| module | LOC | verdict | evidence |
|---|---:|---|---|
| `agentic_v2.models.weight_integrity` | 330 | Used out-of-package | Imported lazily by repo-root `tools/llm/provider_adapters.py:260`; data file `config/defaults/trusted_model_hashes.yaml`; tests `tests/test_weight_integrity.py`. |
| `agentic_v2.models.discovery_snapshot` | 305 | Test-only in package | Referenced by docs in `models/docker_model_runner_discovery.py` and `model_registry.py:307`; `tools/llm/model_bakeoff.py:359` only uses the key name, not the module. Tests: `tests/models/test_discovery_snapshot.py`. No runtime caller found. |
| `agentic_v2.scoring.multidimensional_scoring` | 462 | Test-only (ADR-007 engine) | Referenced in comments (`config/defaults/evaluation.yaml:211`, `workflows/lib/ci_calculator.py:4`); tests `tests/test_multidimensional_scoring.py`, `tests/test_multidimensional_scoring_wiring.py`. No runtime importer. |
| `agentic_v2.server.normalization` | 30 | Test-only back-compat shim | Re-exports `evaluation.normalization`; docstring reference in `scoring/evaluation_scoring.py:14`; tests `tests/test_normalization.py`. |
| `agentic_v2.integrations.langchain` | 219 | Optional public bridge, test-only | `AgenticChatModel` / tool / runnable adapters; guarded `langchain_core` import; listed in mypy overrides (`pyproject.toml:404`); tests `tests/test_integrations_langchain.py`, `tests/test_approval_gates.py`. |

#### 2.24.1 Stale bytecode-only directories in the local checkout

| path (local checkout only) | contents | verdict |
|---|---|---|
| `agentic-workflows-v2/agentic_v2/memoryctl/` | `__pycache__/` only: 14 `.pyc` files (`cli`, `archive`, `budget`, `dedupe`, `index_cmd`, `links`, `report`, `staleness`, `stats`, `validate`, `verify_cmd`, `_shared`, `__init__`, `__main__`) | Stale bytecode; sources are gone from origin/main (0 tracked files under the path; `git status --ignored` shows `!!`). memoryctl lives as a standalone repo (`repos/memoryctl`, no remote, per workspace notes). **`agentic-workflows-v2/docs/REPO_MAP.md:40` still lists `memoryctl/` as a runtime package: stale doc.** |
| `agentic-workflows-v2/agentic_v2/rag/` | `__pycache__/` only: 17 `.pyc` files (`chunking`, `config`, `context_assembly`, `contracts`, ...) | Stale bytecode; package removed by ADR-057 (`docs/adr/ADR-057-remove-rag-package.md`, accepted 2026-08-10, superseded by external `groundkit`). Not present in the clean main worktree. Both directories are git-ignored, harmless, and safe to delete locally; a stray `.pyc` could in principle satisfy `import agentic_v2.rag` from a stale environment (inference, unverified). |

Because the audited tree is origin/main (`c3b2d328`), neither directory appears in any table above.

### 2.25 Needs work

#### 2.25.1 TODO / FIXME / XXX / HACK markers

Only one marker exists in the whole runtime package (inventory `markers` field, all 244 modules):

| file | line | tag | text |
|---|---:|---|---|
| `agentic-workflows-v2/agentic_v2/workflows/runner.py` | 416 | TODO | `(ADR-001): When a custom step_executor is provided we must ...` (comment is truncated in the inventory) |

`workflows/runner.py` is also in the coverage-omit list (below), so the TODO sits in code the 80% gate does not measure.

#### 2.25.2 Modules over 800 LOC (split candidates; standard is ~800)

| module | LOC | notes |
|---|---:|---|
| `agentic_v2/langchain/graph_wiring.py` | 1274 | Largest file; node factories + edge assembly + loop/join logic in one module. Split node factories from edge assembly. |
| `agentic_v2/scoring/evaluation_scoring.py` | 1029 | Hard gates, floors, layered scoring, schema validation. |
| `agentic_v2/langchain/runner.py` | 971 | `WorkflowRunner`. Overlaps in purpose with `workflows/runner.py` (423 LOC) and `adapters/langchain/engine.py`. |
| `agentic_v2/models/smart_router.py` | 906 | Router + stats persistence + Redis sync + probe locks. |
| `agentic_v2/models/client.py` | 896 | Already partly decomposed (`cache_budget`, `fallback_selector`, `retry_utils`, `sanitization_dispatch`); coverage-omitted. |
| `agentic_v2/langchain/model_builders.py` | 890 | Provider factory functions; coverage-omitted. |
| `agentic_v2/engine/llm_output_parsing.py` | 826 | JSON extraction + normalization + sentinel parsing; a parallel simpler parser in `agents/json_extraction.py` (131 LOC) still exists. |
| `agentic_v2/models/backends_cloud.py` | 802 | Four cloud backends plus NIM helpers; coverage-omitted. Just over the line. |

Near the line (700-800): `agents/orchestrator.py` 788, `server/models.py` 747, `langchain/models.py` 743, `server/routes/model_finder.py` 764 (summary scope).

#### 2.25.3 Modules with no test reference at all

Name/path search found zero references in `agentic-workflows-v2/tests/**` or repo-root `tests/**` for these 21 modules (a module may still be exercised indirectly through a caller):

| module | LOC | note |
|---|---:|---|
| `engine/verification.py` | 347 | `VerificationGate`/`VerificationLoop`, called from `engine/step.py:652` (`_run_verification_gate`); also coverage-omitted. Highest-risk gap: bounded self-correction logic with neither direct tests nor measurement. Only incidental mentions in `tests/conftest.py` and `tests/engine/test_consensus_step.py`. |
| `agents/implementations/agent_loader.py` | 118 | see 2.24; omitted. |
| `agents/orchestrator_planning.py` | 147 | Deterministic planning helpers for the orchestrator (indirect coverage via orchestrator tests, unverified). |
| `agents/orchestrator_factories.py` | 37 | |
| `cli/display.py` | 211 | Rich display helpers. |
| `devex/cli.py` | 106 | Typer sub-app; omitted. |
| `integrations/mcp/adapters/prompt_adapter.py` | 122 | MCP tree is omitted wholesale. |
| `integrations/mcp/adapters/resource_adapter.py` | 220 | |
| `integrations/mcp/discovery/{prompts,resources,tools}.py` | 135 / 131 / 100 | |
| `integrations/mcp/transports/websocket.py` | 151 | |
| `middleware/detectors/base.py` | 45 | Pattern dataclasses; exercised through detectors. |
| `scoring/eval_config.py` | 64 | YAML loader. |
| `server/_step_events.py` | 281 | LangGraph streaming event builders. |
| `server/_stream_merge.py` | 56 | |
| `server/middleware/rate_limit.py` | 80 | slowapi setup. |
| `server/models_settings.py` | 306 | Wire models for settings/catalog APIs. |
| `server/pack_validation.py` | 165 | Model-pack validation shared by settings routes and run submission. |
| `server/routes/catalog.py` | 73 | |
| `server/spa.py` | 46 | |

Also zero directly-named tests but exercised through package re-exports: `contracts/schemas.py` and `governance/escalation.py` read as untested in the raw inventory but are covered (see 2.24).

#### 2.25.4 `[tool.coverage.run] omit` (agentic-workflows-v2/pyproject.toml)

The 80% gate (`fail_under = 80`) is measured on `agentic_v2/` minus 21 omit patterns that expand to 49 modules and 10,551 LOC, i.e. 17.0% of the 61,892 runtime LOC. Not "dead": most have dedicated tests but need live providers or optional extras.

| omit pattern | modules / LOC | reason given in pyproject | note |
|---|---|---|---|
| `agents/implementations/*` | 4 / 605 | optional SDK-backed agents | agent_loader untested |
| `cli/helpers.py`, `devex/cli.py`, `config/__init__.py` | 3 / 220 | CLI glue / empty marker | |
| `engine/verification.py` | 347 | no comment | no direct tests; on the step execution path |
| `engine/patterns/__init__.py` | 3 | empty stub | delete with the stub |
| `engine/ek_step_delegation.py`, `models/ek_adapters.py`, `models/ek_provider.py` | 3 / 1,204 | ADR-023 ExecutionKit bridge, optional `executionkit` dep; covered only by the `ek-delegation-tests` job | |
| `models/backends_claude.py` | 331 | optional `claude` extra; `claude-subscription-tests` job | |
| `integrations/mcp/*` | 25 modules / 3,458 | MCP stack | largest omitted block; 6 non-init modules with zero test refs |
| `langchain/agents.py`, `model_builders.py`, `tools.py` | 3 / 1,606 | live-provider/optional deps | |
| `models/backends_base.py`, `backends_cloud.py`, `backends_local.py`, `client.py` | 4 / 2,047 | backend wiring needs live providers | `client.py` is the core LLM client at 896 LOC |
| `models/llm.py` | 31 | legacy adapter | truly unused, see 2.24 |
| `prompts/*` | 2 / 276 | prompt loading | |
| `workflows/runner.py` | 423 | unified YAML entry point | holds the only TODO |

Other observations from this pass:

- **Stale mypy override:** `pyproject.toml` (~line 402) lists `agentic_v2.langchain.nodes`, a module that does not exist in `agentic_v2/langchain/` (no `nodes.py`). Dead config entry (the `[[tool.mypy.overrides]]` block is the per-module type-debt list).
- **Duplicate workflow models:** `langchain/config.py` (`WorkflowConfig`, `StepConfig`, `EvaluationConfig`, 569 LOC) and `workflows/loader.py` (`WorkflowDefinition`, `WorkflowInput`, `WorkflowEvaluation`, 639 LOC) both parse the same YAML into parallel dataclass trees.
- **Two JSON-extraction modules:** `agents/json_extraction.py` (131 LOC) and `engine/llm_output_parsing.py` (826 LOC); whether they overlap functionally was not traced (unverified).
- **Two runners:** `workflows/runner.py` (`WorkflowRunner`, 423 LOC) and `langchain/runner.py` (`WorkflowRunner`, 971 LOC) share a class name across packages.
- **Stale doc:** `agentic-workflows-v2/docs/REPO_MAP.md:40` lists a nonexistent `memoryctl/` package.
