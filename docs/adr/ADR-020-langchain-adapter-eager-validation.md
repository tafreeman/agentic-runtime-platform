# ADR-020: LangChain Adapter Eager Validation at FastAPI Startup

**Status:** Accepted
**Date:** 2026-05-14
**Implements:** Sprint 1, item S1-6
**Related:** `agentic_v2/adapters/registry.py`, `agentic_v2/server/app.py`

---

## Context

The `langchain` adapter requires the `[langchain]` optional extras (`langchain`, `langgraph`, and related packages). The package intentionally guards all adapter imports with `try/except ImportError` so that a bare `pip install -e ".[dev,server]"` succeeds without the optional deps. This is the correct design for dependency weight.

The problem is when the error surfaces. Prior to S1-6:

1. The FastAPI server starts successfully regardless of whether the LangChain extras are installed.
2. On the first call to `POST /api/run` with `adapter=langchain` (or any workflow that defaults to the langchain adapter), `AdapterRegistry.get_adapter("langchain")` triggers the deferred import, which raises `ImportError` inside the request handler.
3. The server logs a traceback and returns `501 Not Implemented` or, depending on exception handling, `500 Internal Server Error`.
4. The operator sees the failure mid-workflow — after clients have connected, after resources were allocated, potentially after a billed LLM call has started.

This is especially problematic for the `AGENTIC_DEFAULT_ADAPTER` setting (default `langchain`), where every workflow run will fail until the extras are installed. The error should be surfaced at boot time, not at request time.

---

## Decision

Add `AdapterRegistry.validate_selected(name: str) -> None` and call it during FastAPI's lifespan startup sequence.

- **`validate_selected(name)`** checks whether the named adapter is importable and fully initialised. For the `langchain` adapter, this means attempting the import that was previously deferred. If the import fails, the method raises `ConfigurationError` with a human-readable message that includes the install hint:
  ```
  ConfigurationError: Adapter 'langchain' requires optional extras.
  Install with: pip install -e ".[langchain]"
  Set AGENTIC_DEFAULT_ADAPTER=native to use the built-in engine instead.
  ```
- **`AGENTIC_DEFAULT_ADAPTER`** (default `langchain`) selects which adapter is validated. Setting it to `native` skips the LangChain extras check.
- **Lifespan integration:** The call is placed in the FastAPI `@asynccontextmanager` lifespan function in `server/app.py`. A `ConfigurationError` raised in the lifespan start block propagates as a server startup failure — `uvicorn` logs the error and exits with a non-zero code.
- **Probe exemption:** The optional `probe_and_update_tier_defaults()` function, which also attempts LangChain-related imports, retains its own `try/except` guard. It is intended to be advisory (update tier defaults if possible, but do not block startup if extras are absent). `validate_selected()` is the authoritative startup gate.

---

## Consequences

### Positive

- Misconfigured deployments fail fast at boot with a clear, actionable error message rather than mid-workflow with a traceback.
- Operators and CI pipelines catch missing extras immediately on server start rather than on first workflow execution.
- The fix is non-breaking for correctly configured deployments: if LangChain extras are installed, startup proceeds as before.
- The separation between `validate_selected()` (strict gate) and the probe function (advisory) makes the intent of each clear.

### Negative

- The `native` adapter path is unaffected — operators who use only the native engine and set `AGENTIC_DEFAULT_ADAPTER=native` are not protected against a future native-adapter initialisation bug by this mechanism. A more general `validate_all_registered()` option exists if needed.
- The `validate_selected()` call happens synchronously in the lifespan, not in an async context. If validation ever becomes async (e.g., if it needs to make a network call), the implementation must be updated.
- **CLI path:** `agentic run --adapter langchain` resolves the adapter outside the FastAPI lifespan. The startup gate does not protect CLI users — they still encounter the deferred `ImportError` at adapter resolution time. A pre-flight check in the CLI is a follow-on task.

---

## Alternatives Considered

| Alternative | Disposition |
|---|---|
| **Defer validation to first import (prior behavior)** | Retained as the fallback for the probe function, where advisory discovery is the goal. Not acceptable for the server startup path where a failed boot is preferable to a mid-workflow crash. |
| **Require all adapters to be installed** | Rejected. The optional-extras design is correct — it keeps the installation footprint minimal for users who only need the native engine. The gate should validate what is configured, not mandate all optional packages. |
| **Validate at `register()` time** | Considered. Rejected because registration happens at import time (module level), before the server has read configuration. The gate needs to know which adapter is *selected*, not which adapters are *registered*. |
| **Emit a startup warning instead of raising** | Rejected for the server path. A warning that is scrolled past in logs provides no protection. For the probe function, a warning-on-failure is the correct behavior — adopted there. |

---

## Implementation References

- New method: `agentic_v2/adapters/registry.py` (`AdapterRegistry.validate_selected`)
- Lifespan hook: `agentic_v2/server/app.py` (lifespan `@asynccontextmanager`)
- Error type: `agentic_v2/core/errors.py` (`ConfigurationError`)
- Probe function (advisory, not gated): `agentic_v2/server/app.py` (`probe_and_update_tier_defaults`)
- Configuration: `AGENTIC_DEFAULT_ADAPTER` environment variable (default `"langchain"`)
- Known limitations: [`KNOWN_LIMITATIONS.md`](../KNOWN_LIMITATIONS.md) §2.2

---

## Review Cadence

Re-evaluate when:

- The CLI gains a pre-flight adapter check that covers the `agentic run --adapter langchain` path.
- The adapter registry grows to support more than two adapters, and a `validate_all_registered()` pattern becomes warranted.
- The native adapter requires its own optional dependency (at which point `validate_selected()` would need to cover that case too).
