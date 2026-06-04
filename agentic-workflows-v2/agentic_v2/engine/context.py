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
import json
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, TypeVar, cast

logger = logging.getLogger(__name__)

import jmespath

T = TypeVar("T")


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

    # Parent context (for scoping)
    _parent: "ExecutionContext" | None = None

    # Event handlers
    _event_handlers: dict[str, list[EventHandler]] = field(default_factory=dict)

    # Services (DI container)
    services: ServiceContainer = field(default_factory=ServiceContainer)

    # Execution metadata
    start_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: dict[str, Any] = field(default_factory=dict)

    # Step tracking
    current_step: str | None = None
    completed_steps: list[str] = field(default_factory=list)
    failed_steps: list[str] = field(default_factory=list)

    # Checkpointing
    checkpoint_dir: Path | None = None

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

    # -------------------------------------------------------------------------
    # Variable Management
    # -------------------------------------------------------------------------

    async def get(self, key: str, default: Any = None) -> Any:
        """Get a variable, checking parent if not found locally.

        Supports JMESPath queries: ctx.get("results.items[0].name")
        """
        async with self._lock:
            # Try local first
            if "." in key or "[" in key:
                # JMESPath query
                try:
                    result = jmespath.search(key, self._variables)
                    if result is not None:
                        return result
                except jmespath.exceptions.JMESPathError:
                    pass
            elif key in self._variables:
                return self._variables[key]

            # Try parent
            if self._parent is not None:
                return await self._parent.get(key, default)

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

        if self._parent is not None:
            return self._parent.get_sync(key, default)

        return default

    async def set(self, key: str, value: Any) -> None:
        """Set a variable (local to this context)."""
        self._validate_variable_key(key)
        async with self._lock:
            old_value = self._variables.get(key)
            self._variables[key] = value

        await self._emit(
            EventType.VARIABLE_SET,
            {"key": key, "old_value": old_value, "new_value": value},
        )

    def set_sync(self, key: str, value: Any) -> None:
        """Synchronous set."""
        self._validate_variable_key(key)
        self._variables[key] = value

    async def set_internal(self, key: str, value: Any) -> None:
        """Set an engine-owned variable, including protected lifecycle keys.

        This is the explicit opt-in escape hatch for runtime code that must
        seed a protected context key in the variable namespace.  It still
        enforces plain, top-level variable names.
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
        for key in kwargs:
            self._validate_variable_key(key)

        async with self._lock:
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

    def has(self, key: str) -> bool:
        """Check if variable exists (locally or in parent)."""
        if key in self._variables:
            return True
        if self._parent is not None:
            return self._parent.has(key)
        return False

    def all_variables(self) -> dict[str, Any]:
        """Get all variables (merged with parent)."""
        if self._parent is not None:
            merged = self._parent.all_variables()
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

    async def save_checkpoint(self, name: str | None = None) -> Path:
        """Save current state to a checkpoint file.

        Returns path to checkpoint file.
        """
        if self.checkpoint_dir is None:
            raise ValueError("No checkpoint directory configured")

        self.checkpoint_dir.mkdir(parents=True, exist_ok=True)

        checkpoint_name = (
            name or f"checkpoint_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
        )
        checkpoint_path = self.checkpoint_dir / f"{checkpoint_name}.json"

        checkpoint_data = {
            "workflow_id": self.workflow_id,
            "run_id": self.run_id,
            "variables": self._serialize_variables(),
            "completed_steps": self.completed_steps,
            "failed_steps": self.failed_steps,
            "metadata": self.metadata,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        checkpoint_path.write_text(json.dumps(checkpoint_data, indent=2, default=str))

        await self._emit(EventType.CHECKPOINT_SAVE, {"path": str(checkpoint_path)})

        return checkpoint_path

    async def restore_checkpoint(self, checkpoint_path: Path) -> None:
        """Restore state from a checkpoint file."""
        if not checkpoint_path.exists():
            raise FileNotFoundError(f"Checkpoint not found: {checkpoint_path}")

        data = json.loads(checkpoint_path.read_text())
        variables = self._validate_checkpoint_variables(data.get("variables", {}))

        async with self._lock:
            self._variables = variables.copy()

        self.completed_steps = data.get("completed_steps", [])
        self.failed_steps = data.get("failed_steps", [])
        self.metadata.update(data.get("metadata", {}))

        await self._emit(EventType.CHECKPOINT_RESTORE, {"path": str(checkpoint_path)})

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
        return (datetime.now(timezone.utc) - self.start_time).total_seconds()

    def __repr__(self) -> str:
        return (
            f"ExecutionContext(workflow={self.workflow_id[:8]}, "
            f"run={self.run_id[:8]}, "
            f"vars={len(self._variables)}, "
            f"completed={len(self.completed_steps)})"
        )


# Global context for simple use cases
_current_context: ExecutionContext | None = None


def get_context() -> ExecutionContext:
    """Get or create the global execution context."""
    global _current_context
    if _current_context is None:
        _current_context = ExecutionContext()
    return _current_context


def set_context(ctx: ExecutionContext) -> None:
    """Set the global execution context."""
    global _current_context
    _current_context = ctx


def reset_context() -> None:
    """Reset the global context (for testing)."""
    global _current_context
    _current_context = None
