"""Execution context for workflow state management.

Provides :class:`ExecutionContext`, the shared mutable state carrier for
a single workflow run.  Every step receives a reference to this context
(or a child scope) and uses it to read inputs, write outputs, and track
lifecycle events.

Key capabilities:
- **Hierarchical scoping** — ``child()`` creates an isolated scope that
  inherits parent variables but writes locally, preventing unintended
  cross-step pollution.
- **JMESPath queries** — ``get("results.items[0].name")`` supports
  deep nested lookups via `jmespath <https://jmespath.org>`_.
- **Event hooks** — register handlers for ``STEP_START``, ``STEP_END``,
  ``VARIABLE_SET``, ``CHECKPOINT_SAVE``, etc.  Events propagate upward
  through parent contexts.
- **Checkpoint / restore** — serialize context state to JSON for fault
  tolerance and replay.
- **Dependency injection** — :class:`ServiceContainer` provides singleton
  and factory patterns, shared across parent/child contexts.
- **Async-safe** — all variable mutations are guarded by ``asyncio.Lock``.
"""

from __future__ import annotations

import asyncio
import contextvars
import hashlib
import json
import logging
import uuid
from dataclasses import InitVar, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, TypeVar, cast

logger = logging.getLogger(__name__)

import jmespath

T = TypeVar("T")


def _fingerprint_files(paths: list[str | Path]) -> dict[str, str]:
    """Return ``{path: sha256}`` for each readable file in *paths*.

    Missing or unreadable files are recorded with a sentinel digest so a
    later diff treats "file deleted" as a change rather than silently
    skipping it.
    """
    fingerprints: dict[str, str] = {}
    for raw in paths:
        path = Path(raw)
        key = str(path)
        try:
            data = path.read_bytes()
            fingerprints[key] = hashlib.sha256(data).hexdigest()
        except (OSError, ValueError):
            fingerprints[key] = "__missing__"
    return fingerprints


PROTECTED_VARIABLE_KEYS = frozenset(
    {
        "workflow_id",
        "run_id",
        "current_step",
        "completed_steps",
        "failed_steps",
        "metadata",
        "services",
        "start_time",
        "checkpoint_dir",
    }
)
PATH_EXPRESSION_MARKERS = (".", "[", "]")


class EventType:
    """Event types for context hooks."""

    STEP_START = "step_start"
    STEP_END = "step_end"
    STEP_ERROR = "step_error"
    VARIABLE_SET = "variable_set"
    CHECKPOINT_SAVE = "checkpoint_save"
    CHECKPOINT_RESTORE = "checkpoint_restore"


EventHandler = Callable[["ExecutionContext", str, dict[str, Any]], None]


@dataclass
class ServiceContainer:
    """Dependency injection container.

    Supports singleton and factory patterns.
    """

    _singletons: dict[type, Any] = field(default_factory=dict)
    _factories: dict[type, Callable[[], Any]] = field(default_factory=dict)

    def register_singleton(self, service_type: type[T], instance: T) -> None:
        """Register a singleton service."""
        self._singletons[service_type] = instance

    def register_factory(self, service_type: type[T], factory: Callable[[], T]) -> None:
        """Register a factory for creating service instances."""
        self._factories[service_type] = factory

    def resolve(self, service_type: type[T]) -> T | None:
        """Resolve a service by type.

        Checks singletons first, then tries factory.
        """
        if service_type in self._singletons:
            # Heterogeneous DI store: value was registered as T under type[T].
            return cast("T", self._singletons[service_type])

        if service_type in self._factories:
            instance = self._factories[service_type]()
            return cast("T", instance)

        return None

    def resolve_required(self, service_type: type[T]) -> T:
        """Resolve a service, raising if not found."""
        instance = self.resolve(service_type)
        if instance is None:
            raise KeyError(f"Service not registered: {service_type.__name__}")
        return instance


@dataclass
class ExecutionContext:
    """Shared mutable state for a single workflow run.

    Carries variables, step tracking, event hooks, and a DI container
    through the entire execution lifecycle.  Child contexts (created via
    :meth:`child`) inherit the parent's variables on read but write
    locally, enabling step-level isolation.

    Attributes:
        workflow_id: UUID identifying the workflow definition.
        run_id: UUID identifying this particular execution run.
        services: Shared :class:`ServiceContainer` for dependency injection.
        start_time: UTC timestamp when the context was created.
        metadata: Arbitrary key-value pairs for run-level annotations.
        current_step: Name of the step currently executing (or ``None``).
        completed_steps: Ordered list of successfully completed step names.
        failed_steps: Ordered list of failed step names.
        checkpoint_dir: Directory for checkpoint JSON files (``None`` = disabled).
    """

    # Identity
    workflow_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    run_id: str = field(default_factory=lambda: str(uuid.uuid4()))

    # Variable store
    _variables: dict[str, Any] = field(default_factory=dict)
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    # Inherited keys hidden from this scope (see mask_inherited)
    _masked: set[str] = field(default_factory=set)

    # Parent context (for scoping)
    _parent: "ExecutionContext" | None = None

    # Event handlers
    _event_handlers: dict[str, list[EventHandler]] = field(default_factory=dict)

    # Services (DI container)
    services: ServiceContainer = field(default_factory=ServiceContainer)

    # Execution metadata
    start_time: datetime = field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = field(default_factory=dict)

    # Step tracking
    current_step: str | None = None
    completed_steps: list[str] = field(default_factory=list)
    failed_steps: list[str] = field(default_factory=list)

    # Checkpointing
    checkpoint_dir: Path | None = None

    # Init-only convenience: callers may seed the variable store directly via
    # ``ExecutionContext(variables={...})`` (used by the native DAG adapter in
    # server/execution.py and the CLI helpers). ``__post_init__`` copies it into
    # the private ``_variables`` field; the langchain adapter seeds ``_variables``
    # by other means, which is why only the native/CLI paths exercised this.
    variables: InitVar[dict[str, Any] | None] = None

    def __post_init__(self, variables: dict[str, Any] | None) -> None:
        """Seed ``_variables`` from the init-only ``variables`` arg, when provided."""
        if variables:
            self._variables = dict(variables)

    def child(self, step_name: str | None = None) -> "ExecutionContext":
        """Create a child context with inherited variables.

        Child can read parent variables but writes are local.
        """
        child_ctx = ExecutionContext(
            workflow_id=self.workflow_id,
            run_id=self.run_id,
            _parent=self,
            services=self.services,
            start_time=self.start_time,
            metadata=self.metadata.copy(),
            checkpoint_dir=self.checkpoint_dir,
        )
        if step_name:
            child_ctx.current_step = step_name
        return child_ctx

    def fork_session(self, name: str) -> "ExecutionContext":
        """Branch a divergent run off this shared baseline.

        Returns a child scope (see :meth:`child`) that reads this context's
        variables but writes locally, so a forked experiment never mutates the
        baseline. The fork is tagged with a fresh ``run_id`` and a
        ``metadata["fork_name"]`` / ``metadata["forked_from_run"]`` lineage so
        divergent branches stay distinguishable in traces and checkpoints.

        This is the in-house counterpart to the Claude Agent SDK's
        ``fork_session`` (see ``docs/adr/ADR-026-resume-vs-summary-session.md``):
        both let you explore an alternative trajectory from a common point
        without disturbing the original.

        Args:
            name: Human-readable label for the fork (also used as the default
                checkpoint name when the fork is later saved).

        Returns:
            A child :class:`ExecutionContext` seeded from this baseline.
        """
        if not isinstance(name, str) or not name.strip():
            raise ValueError("fork_session requires a non-empty name")

        fork = self.child(step_name=self.current_step)
        # A fork is a distinct run; give it its own identity for trace isolation.
        fork.run_id = str(uuid.uuid4())
        fork.metadata = {
            **self.metadata,
            "fork_name": name,
            "forked_from_run": self.run_id,
        }
        return fork

    # -------------------------------------------------------------------------
    # Variable Management
    # -------------------------------------------------------------------------

    async def get(self, key: str, default: Any = None) -> Any:
        """Get a variable, checking parent if not found locally.

        Supports JMESPath queries: ctx.get("results.items[0].name")
        """
        async with self._lock:
            # Resolve locally while holding only this context's lock. Read the
            # parent reference inside the lock, but do NOT call into the parent
            # here: acquiring the parent lock while holding ours is a
            # lock-inversion deadlock (two tasks descending opposite ends of the
            # parent/child chain can each hold one lock and wait on the other).
            local_hit = False
            local_value: Any = None
            if "." in key or "[" in key:
                # JMESPath query
                try:
                    result = jmespath.search(key, self._variables)
                    if result is not None:
                        local_hit = True
                        local_value = result
                except jmespath.exceptions.JMESPathError:
                    pass
            elif key in self._variables:
                local_hit = True
                local_value = self._variables[key]

            masked = self._mask_root(key) in self._masked
            parent = self._parent

        if local_hit:
            return local_value

        # A masked key reads as unset in this scope: do not fall back to
        # the parent (see mask_inherited).
        if masked:
            return default

        # Delegate to the parent WITHOUT holding self._lock, breaking the
        # inversion: the parent acquires its own lock independently.
        if parent is not None:
            return await parent.get(key, default)

        return default

    def get_sync(self, key: str, default: Any = None) -> Any:
        """Synchronous get (use when not in async context)."""
        if "." in key or "[" in key:
            try:
                result = jmespath.search(key, self._variables)
                if result is not None:
                    return result
            except jmespath.exceptions.JMESPathError:
                pass
        elif key in self._variables:
            return self._variables[key]

        if self._mask_root(key) in self._masked:
            return default

        if self._parent is not None:
            return self._parent.get_sync(key, default)

        return default

    async def set(self, key: str, value: Any) -> None:
        """Set a variable (local to this context)."""
        self._validate_variable_key(key)
        async with self._lock:
            old_value = self._variables.get(key)
            self._variables[key] = value
            self._masked.discard(key)

        await self._emit(
            EventType.VARIABLE_SET,
            {"key": key, "old_value": old_value, "new_value": value},
        )

    def set_sync(self, key: str, value: Any) -> None:
        """Synchronous set."""
        self._validate_variable_key(key)
        self._variables[key] = value
        self._masked.discard(key)

    async def merge_step_view(self, step_name: str, step_view: dict[str, Any]) -> None:
        """Atomically record a step's view under the shared ``steps`` namespace.

        Read-modify-write of the nested ``steps`` dict is held under a single
        lock so concurrent steps (``max_concurrency`` > 1) cannot lose each
        other's entries: a locked get followed by a locked set would still race
        in the gap between them. The dict is replaced copy-on-write rather than
        mutated in place, per the immutability convention.

        On a fork/child context the baseline ``steps`` live in the parent, so
        seed from the inherited view when this context has not written its own
        ``steps`` yet -- otherwise the first forked step would replace the
        inherited dict with a single-entry one and shadow it (``all_variables()``
        shallow-merges, so ``${steps.<earlier>.outputs...}`` would then fail to
        resolve on the fork). ``get_sync`` resolves ``steps`` with the documented
        read-through-parent semantics and takes no async lock, so reading it
        before acquiring ``self._lock`` avoids the parent/child lock-inversion
        that ``get()`` documents.
        """
        inherited = self.get_sync("steps")
        async with self._lock:
            existing = self._variables.get("steps")
            base = existing if isinstance(existing, dict) else inherited
            steps_state = dict(base) if isinstance(base, dict) else {}
            steps_state[step_name] = step_view
            self._variables["steps"] = steps_state

    async def set_internal(self, key: str, value: Any) -> None:
        """Set an engine-owned variable, including protected lifecycle keys.

        This is the explicit opt-in escape hatch for runtime code that
        must seed a protected context key in the variable namespace.  It
        still enforces plain, top-level variable names.
        """
        self._validate_variable_key(key, allow_protected=True)
        async with self._lock:
            old_value = self._variables.get(key)
            self._variables[key] = value

        await self._emit(
            EventType.VARIABLE_SET,
            {"key": key, "old_value": old_value, "new_value": value},
        )

    def set_internal_sync(self, key: str, value: Any) -> None:
        """Synchronous internal set for engine-owned variables."""
        self._validate_variable_key(key, allow_protected=True)
        self._variables[key] = value

    async def update(self, **kwargs: Any) -> None:
        """Update multiple variables at once."""
        async with self._lock:
            # Validate inside the lock so validate-then-write is atomic: a
            # concurrent writer cannot slip a mutation in between the check and
            # the commit (TOCTOU). A rejected key aborts before any write.
            for key in kwargs:
                self._validate_variable_key(key)
            self._variables.update(kwargs)

    async def delete(self, key: str) -> bool:
        """Delete a variable.

        Returns True if existed.
        """
        async with self._lock:
            if key in self._variables:
                del self._variables[key]
                return True
            return False

    async def mask_inherited(self, key: str) -> None:
        """Hide an inherited variable from this scope.

        The parent's value is untouched; within this context the key reads
        as unset (``get``/``has``/``all_variables``) until a local ``set``
        overrides the mask. The step executor uses this to keep aliases
        normalized away by an artifact contract out of the step's variable
        view.
        """
        async with self._lock:
            self._variables.pop(key, None)
            self._masked.add(key)

    @staticmethod
    def _mask_root(key: str) -> str:
        """Root variable name of a plain key or JMESPath query."""
        return key.split(".", 1)[0].split("[", 1)[0]

    def has(self, key: str) -> bool:
        """Check if variable exists (locally or in parent)."""
        if key in self._variables:
            return True
        if key in self._masked:
            return False
        if self._parent is not None:
            return self._parent.has(key)
        return False

    def all_variables(self) -> dict[str, Any]:
        """Get all variables (merged with parent, minus masked keys)."""
        if self._parent is not None:
            merged = self._parent.all_variables()
            for masked_key in self._masked:
                merged.pop(masked_key, None)
            merged.update(self._variables)
            return merged
        return self._variables.copy()

    def interpolate(self, template: str) -> str:
        """Interpolate variables into a template string.

        Supports ${var} and ${path.to.value} syntax.
        """
        import re

        def replace_var(match: re.Match) -> str:
            var_path = match.group(1)
            value = self.get_sync(var_path, f"${{{var_path}}}")
            return str(value)

        return re.sub(r"\$\{([^}]+)\}", replace_var, template)

    # -------------------------------------------------------------------------
    # Event Handling
    # -------------------------------------------------------------------------

    def on(self, event_type: str, handler: EventHandler) -> None:
        """Register an event handler."""
        if event_type not in self._event_handlers:
            self._event_handlers[event_type] = []
        self._event_handlers[event_type].append(handler)

    def off(self, event_type: str, handler: EventHandler) -> bool:
        """Unregister an event handler."""
        if event_type in self._event_handlers:
            try:
                self._event_handlers[event_type].remove(handler)
                return True
            except ValueError:
                pass
        return False

    async def _emit(self, event_type: str, data: dict[str, Any]) -> None:
        """Emit an event to all handlers."""
        handlers = self._event_handlers.get(event_type, [])
        for handler in handlers:
            try:
                result = handler(self, event_type, data)
                if asyncio.iscoroutine(result):
                    await result
            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.warning(
                    "Event handler %s failed for event %s: %s",
                    getattr(handler, "__name__", repr(handler)),
                    event_type,
                    e,
                    exc_info=True,
                )

        # Propagate to parent
        if self._parent is not None:
            await self._parent._emit(event_type, data)

    @staticmethod
    def _validate_variable_key(
        key: str,
        *,
        allow_protected: bool = False,
    ) -> None:
        """Validate public variable writes use safe top-level names."""
        if not isinstance(key, str):
            raise TypeError("Context variable names must be strings")

        if key.strip() == "":
            raise ValueError("Context variable names cannot be empty")

        if any(marker in key for marker in PATH_EXPRESSION_MARKERS):
            raise ValueError(
                "Context variable writes do not accept JMESPath/path expressions; "
                "write the top-level object instead"
            )

        if not allow_protected and key in PROTECTED_VARIABLE_KEYS:
            raise ValueError(
                f"Context variable '{key}' is protected; use an internal write helper"
            )

    # -------------------------------------------------------------------------
    # Step Tracking
    # -------------------------------------------------------------------------

    async def mark_step_start(self, step_name: str) -> None:
        """Mark a step as started."""
        self.current_step = step_name
        await self._emit(EventType.STEP_START, {"step": step_name})

    async def mark_step_complete(self, step_name: str) -> None:
        """Mark a step as completed."""
        if step_name not in self.completed_steps:
            self.completed_steps.append(step_name)
        self.current_step = None
        await self._emit(EventType.STEP_END, {"step": step_name, "success": True})

    async def mark_step_failed(self, step_name: str, error: str) -> None:
        """Mark a step as failed."""
        if step_name not in self.failed_steps:
            self.failed_steps.append(step_name)
        self.current_step = None
        await self._emit(EventType.STEP_ERROR, {"step": step_name, "error": error})

    def is_step_complete(self, step_name: str) -> bool:
        """Check if a step has completed."""
        return step_name in self.completed_steps

    def is_step_failed(self, step_name: str) -> bool:
        """Check if a step has failed."""
        return step_name in self.failed_steps

    # -------------------------------------------------------------------------
    # Checkpointing
    # -------------------------------------------------------------------------

    async def save_checkpoint(
        self,
        name: str | None = None,
        *,
        tracked_files: list[str | Path] | None = None,
    ) -> Path:
        """Save current state to a checkpoint file.

        Args:
            name: Optional checkpoint name (defaults to a timestamped name).
            tracked_files: Optional paths whose content fingerprints (sha256)
                are recorded so a later resume can detect which files changed
                since this checkpoint (see :meth:`detect_changed_files`).

        Returns path to checkpoint file.
        """
        if self.checkpoint_dir is None:
            raise ValueError("No checkpoint directory configured")

        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)

        checkpoint_name = (
            name or f"checkpoint_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}"
        )
        checkpoint_path = self.checkpoint_dir / f"{checkpoint_name}.json"

        checkpoint_data = {
            "workflow_id": self.workflow_id,
            "run_id": self.run_id,
            "variables": self._serialize_variables(),
            "completed_steps": self.completed_steps,
            "failed_steps": self.failed_steps,
            "metadata": self.metadata,
            "file_fingerprints": _fingerprint_files(tracked_files or []),
            "timestamp": datetime.now(UTC).isoformat(),
        }

        checkpoint_path.write_text(json.dumps(checkpoint_data, indent=2, default=str))

        await self._emit(EventType.CHECKPOINT_SAVE, {"path": str(checkpoint_path)})

        return checkpoint_path

    async def restore_checkpoint(self, checkpoint_path: Path) -> None:
        """Restore state from a checkpoint file."""
        if not checkpoint_path.exists():
            raise FileNotFoundError(f"Checkpoint not found: {checkpoint_path}")

        data = json.loads(checkpoint_path.read_text())
        # Validate every untrusted field BEFORE mutating any state so a rejected
        # (e.g. attacker-tampered) checkpoint leaves the context unchanged.
        variables = self._validate_checkpoint_variables(data.get("variables", {}))
        workflow_id = self._validate_checkpoint_identity(
            "workflow_id", data.get("workflow_id"), self.workflow_id
        )
        run_id = self._validate_checkpoint_identity(
            "run_id", data.get("run_id"), self.run_id
        )
        completed_steps = self._validate_checkpoint_completed_steps(
            data.get("completed_steps", [])
        )

        async with self._lock:
            self._variables = variables.copy()

        # Restore identity so a resumed run keeps the saved workflow/run lineage
        # (save_checkpoint persists both). Without this a resume kept a freshly
        # generated run_id and any later fork recorded the wrong forked_from_run.
        self.workflow_id = workflow_id
        self.run_id = run_id

        self.completed_steps = completed_steps
        self.failed_steps = data.get("failed_steps", [])
        self.metadata.update(data.get("metadata", {}))

        await self._emit(EventType.CHECKPOINT_RESTORE, {"path": str(checkpoint_path)})

    @staticmethod
    def detect_changed_files(checkpoint_path: Path) -> list[str]:
        """Return the tracked files that changed since *checkpoint_path*.

        Compares each file's current sha256 against the fingerprint
        recorded at save time. A file is "changed" if its content
        differs **or** it no longer exists. Files added since the
        checkpoint are not reported (only the originally-tracked set is
        compared).

        Returns the changed file paths, sorted for deterministic output.
        Returns an empty list when the checkpoint recorded no
        fingerprints.
        """
        if not checkpoint_path.exists():
            raise FileNotFoundError(f"Checkpoint not found: {checkpoint_path}")

        data = json.loads(checkpoint_path.read_text())
        recorded: dict[str, str] = data.get("file_fingerprints", {}) or {}
        current = _fingerprint_files(list(recorded.keys()))

        changed = [
            path
            for path, old_digest in recorded.items()
            if current.get(path) != old_digest
        ]
        return sorted(changed)

    @staticmethod
    def build_changed_files_notice(changed_files: list[str]) -> str:
        """Render a "these files changed" notice for the caller/operator.

        Surfaces the notice as a string for the caller to prepend to a
        resumed prompt; this method does not assemble or inject any
        prompt itself. Returns an empty string when nothing changed so
        callers can prepend the result unconditionally.
        """
        if not changed_files:
            return ""
        lines = "\n".join(f"  - {path}" for path in changed_files)
        return (
            "[Resume notice] The following files changed on disk since this "
            "session was checkpointed; re-read them before relying on prior "
            f"tool results:\n{lines}\n"
        )

    def _is_running_context(self) -> bool:
        """Return True if this context is already bound to an active run.

        A freshly constructed context used purely to *resume* a
        checkpoint has no step history and no in-flight step, so its
        auto-generated identity is a placeholder the checkpoint is
        allowed to overwrite. Once any step has run (or is running) the
        identity is load-bearing and an incoming checkpoint must not be
        allowed to silently reassign it.
        """
        return bool(self.completed_steps or self.failed_steps or self.current_step)

    def _validate_checkpoint_identity(
        self, field_name: str, candidate: Any, current: str
    ) -> str:
        """Validate an identity field (``workflow_id`` / ``run_id``).

        Rejects type confusion and identity hijacking from an untrusted
        checkpoint. A missing value falls back to the current identity; a
        present value must be a ``str`` and, when this context is already bound
        to a running execution, must match the running identity exactly.
        """
        if candidate is None:
            return current
        if not isinstance(candidate, str):
            raise ValueError(
                f"Invalid checkpoint {field_name}: expected str, got "
                f"{type(candidate).__name__}"
            )
        if self._is_running_context() and candidate != current:
            raise ValueError(
                f"Checkpoint {field_name} {candidate!r} does not match the "
                f"running context {current!r}; refusing to reassign identity"
            )
        return candidate

    def _validate_checkpoint_completed_steps(self, steps: Any) -> list[str]:
        """Validate ``completed_steps`` from an untrusted checkpoint.

        Rejects a non-list payload or any non-string element so a
        tampered checkpoint cannot inject structured data into the
        execution guards.
        """
        if not isinstance(steps, list):
            raise ValueError(
                "Invalid checkpoint completed_steps: expected a list, got "
                f"{type(steps).__name__}"
            )
        for step_name in steps:
            if not isinstance(step_name, str):
                raise ValueError(
                    "Invalid checkpoint completed_steps: expected str entries, "
                    f"got {type(step_name).__name__}"
                )
        return list(steps)

    def _validate_checkpoint_variables(self, variables: Any) -> dict[str, Any]:
        """Validate checkpoint variables before restoring them."""
        if not isinstance(variables, dict):
            raise ValueError("Invalid checkpoint variables: expected a mapping")

        for key in variables:
            try:
                self._validate_variable_key(key)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"Invalid checkpoint variable key {key!r}: {exc}"
                ) from exc

        return variables

    def _serialize_variables(self) -> dict[str, Any]:
        """Serialize variables for checkpointing (handle non-JSON types)."""

        def serialize(obj: Any) -> Any:
            if isinstance(obj, (str, int, float, bool, type(None))):
                return obj
            if isinstance(obj, (list, tuple)):
                return [serialize(item) for item in obj]
            if isinstance(obj, dict):
                return {k: serialize(v) for k, v in obj.items()}
            if isinstance(obj, datetime):
                return {"__type__": "datetime", "value": obj.isoformat()}
            if isinstance(obj, Path):
                return {"__type__": "path", "value": str(obj)}
            return str(obj)

        return {key: serialize(value) for key, value in self._variables.items()}

    # -------------------------------------------------------------------------
    # Utilities
    # -------------------------------------------------------------------------

    @property
    def elapsed_seconds(self) -> float:
        """Get elapsed time since context creation."""
        return (datetime.now(UTC) - self.start_time).total_seconds()

    def __repr__(self) -> str:
        return (
            f"ExecutionContext(workflow={self.workflow_id[:8]}, "
            f"run={self.run_id[:8]}, "
            f"vars={len(self._variables)}, "
            f"completed={len(self.completed_steps)})"
        )


# Per-task ambient context for simple use cases.
#
# A plain module global is shared by every concurrent asyncio Task, so two
# workflow runs racing in the same event loop would clobber each other's
# context (and history). A ContextVar is copied into each Task at creation, so
# every run reads and writes its own isolated slot. ``default=None`` keeps the
# lazy "get or create" semantics callers already rely on.
_current_context: contextvars.ContextVar[ExecutionContext | None] = (
    contextvars.ContextVar("_current_context", default=None)
)


def get_context() -> ExecutionContext:
    """Get or create the per-task execution context."""
    ctx = _current_context.get()
    if ctx is None:
        ctx = ExecutionContext()
        _current_context.set(ctx)
    return ctx


def set_context(ctx: ExecutionContext) -> None:
    """Set the per-task execution context."""
    _current_context.set(ctx)


def reset_context() -> None:
    """Reset the per-task context (for testing)."""
    _current_context.set(None)
