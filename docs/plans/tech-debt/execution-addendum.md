# Architecture: shared workflow execution

Status: proposed architecture. The changes below are not yet implemented.

Related decision: `docs/adr/ADR-001-002-003-architecture-decisions.md`.
Delivery steps: [G3 and G4](../2026-09-10-tech-debt-workflow.md).

## Problem

Agentic Runtime Platform supports a native workflow engine and a LangGraph
engine. The command line and server still manage parts of execution separately.
The server also owns a separate LangChain runner. This makes tracing, progress
updates, caching and error handling harder to keep consistent.

One server error path starts a new run after streaming fails. If the first run
already performed an action, that retry can perform it twice.

## Decision

Keep both engines. Add one service that loads workflows, selects an engine and
executes a run. Both the command line and server use this service.

The server creates its service at application startup and closes it at shutdown.
A command-line invocation creates and closes its own service. Neither service
changes engine instances held in the global registry cache.

A streaming failure must not start another run. Resuming a saved run requires
an explicit request.

## Components and interfaces

Add this method to `AdapterRegistry`:

```python
def create_adapter(
    self, name: str, **constructor_overrides: Any
) -> ExecutionEngine: ...
```

It creates a new engine from the registered defaults and supplied overrides.
Read the registration under the registry lock; construct the engine after
releasing the lock. Keep the existing cached `get_adapter` method unchanged.
Unknown names and engine-construction failures remain different errors.

Add `agentic_v2/workflows/execution_service.py`:

```python
ProgressObserver = Callable[[dict[str, Any]], Awaitable[None]]

@dataclass(frozen=True)
class ExecutionOptions:
    run_id: str
    tenant_id: str
    model_override: str | None = None
    use_cache: bool = True

class WorkflowExecutionService:
    def __init__(
        self, *, adapter_factory: Callable[[str], ExecutionEngine]
    ) -> None: ...
    async def __aenter__(self) -> WorkflowExecutionService: ...
    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None: ...
    def load_workflow(
        self, adapter_name: str, workflow_name: str,
        *, definitions_dir: Path | None = None
    ) -> Any: ...
    async def execute(
        self, adapter_name: str, definition: Any,
        inputs: Mapping[str, Any], *, options: ExecutionOptions,
        on_update: ProgressObserver | None = None
    ) -> WorkflowResult: ...
    def invalidate_compiled_workflow(self, workflow_name: str) -> int: ...
```

Definitions remain engine-specific. Reuse the existing result type and step
conversion code. Do not change public result fields or engine method signatures.

The factory supplies the existing tracing and saved-run collaborators.
Application startup owns shared resources; the service closes only resources
it creates. Close saved-run storage before shutting down tracing. Do not store
user inputs, tenant identity or model overrides on a shared engine instance.

## Request flow

1. The HTTP route validates the request and identifies the tenant.
2. Request preparation loads the definition through the service and resolves
   model and evaluation settings.
3. A coordinator calls the service and processes progress updates.
4. The coordinator evaluates the result and writes one terminal run record.
5. The route continues to return the existing pending response.

Add `server/run_preparation.py` with:

- `PreparedRun`: an internal frozen record containing the adapter, definition,
  copied inputs, execution options, resolved model pack and evaluation settings.
  Reuse existing types for model and evaluation settings.
- `prepare_run(request, *, tenant_id, service) -> PreparedRun`: accepts the
  existing HTTP request type and returns the resolved values.
- `RunPreparationError(code, message)`: carries preparation failures to the
  route, which selects the HTTP response.
- `resolve_model_pack(...)`: applies the policy below using existing pack types.

Add `server/run_coordinator.py` with `RunCoordinator.run(prepared) -> None`.
Its `evaluate_result`, `build_run_metadata` and `persist_terminal_result`
methods separate evaluation, record construction and storage. Supply execution,
evaluation and storage dependencies through the constructor so tests can use
fakes. Keep existing stored fields and operation order.

| Request setting | Behavior |
| --- | --- |
| Explicit invalid or incompatible model pack | Reject the request |
| Default or inherited invalid/incompatible pack | Drop the pack and keep the existing warning and default source |
| Model override on an unsupported engine | Reject the request |

A failure to evaluate a successful run must not change the workflow's own
success status. Record the evaluation failure separately.

## Progress and failure handling

Keep dictionary callbacks for compatibility. Filter progress fields before
sending them to clients. Run and tenant IDs come from the request context,
not callback data. Preserve attempt identity when a step runs more than once.
Never send the engine's entire internal state to a client.

Handle a disconnected client in the delivery layer. Surface other callback
failures without rerunning the workflow. Propagate cancellation and write the
terminal record once. Keep existing tracing and saved-run/resume behavior;
this change adds no new HTTP resume endpoints.

## Migration and verification

First add tests for tracing, progress order, saved runs and cache invalidation.
Replace the server runner singleton with the startup-owned service. Route
workflow edits through that same service to invalidate cached definitions.

Keep `adapters/workflows.py` as a compatibility wrapper. Add an optional
keyword-only `service` argument. A supplied service is borrowed, not closed.
Async execution without one creates a temporary service. Synchronous loading
must not open asynchronous resources.

Test both engines through command line and server. Cover supplied definitions,
input isolation, model settings, concurrent tenants, cancellation and shutdown.
After a fake step performs an action, inject a streaming or callback failure
and assert that the action occurred only once. Verify filtered progress,
tracing, saved-run continuity and identical result fields. Test every row in
the model-pack table and successful execution followed by failed evaluation.
