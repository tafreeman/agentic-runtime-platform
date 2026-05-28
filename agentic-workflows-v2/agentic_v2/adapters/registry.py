"""Adapter registry — central lookup for execution engine adapters.

The :class:`AdapterRegistry` is a singleton that maps string adapter
names (e.g. ``"native"``, ``"langchain"``) to concrete engine classes.

Adapter packages register themselves on import via
``get_registry().register("name", EngineClass)``.  The registry
intentionally does **not** import adapter packages eagerly — callers
trigger registration by importing the adapter package they need, or
the ``adapters/__init__.py`` imports known built-in packages.

Thread-safety: :meth:`register` and :meth:`get_adapter` acquire a
lock to prevent races during lazy registration.
"""

from __future__ import annotations

import logging
import threading
from typing import Any

from ..core.errors import AdapterError, AdapterNotFoundError, ConfigurationError

logger = logging.getLogger(__name__)


class AdapterRegistry:
    """Singleton registry for execution engine adapters.

    Usage::

        from agentic_v2.adapters import get_registry

        reg = get_registry()
        engine = reg.get_adapter("native")
        result = await engine.execute(dag, ctx)
    """

    _instance: AdapterRegistry | None = None
    _lock = threading.Lock()

    @classmethod
    def reset_for_tests(cls) -> None:
        """Reset the singleton for test isolation.

        This method is intentionally limited to tests; production code
        should continue using :func:`get_registry`.
        """
        with cls._lock:
            cls._instance = None

    def __new__(cls) -> AdapterRegistry:
        with cls._lock:
            if cls._instance is None:
                instance = super().__new__(cls)
                instance._adapters = {}
                instance._instance_lock = threading.Lock()
                cls._instance = instance
        return cls._instance

    def register(self, name: str, engine_class: type, **kwargs: Any) -> None:
        """Register an engine adapter class under the given name.

        Args:
            name: Unique adapter name (e.g. ``"native"``).
            engine_class: Class satisfying :class:`ExecutionEngine` protocol.
            **kwargs: Passed to the engine constructor on first ``get_adapter``.

        Raises:
            AdapterError: If *name* is already registered.
        """
        with self._instance_lock:
            if name in self._adapters:
                raise AdapterError(f"Adapter {name!r} already registered")
            self._adapters[name] = (engine_class, kwargs, None)
            logger.debug("Registered adapter %r -> %s", name, engine_class.__name__)

    def get_adapter(self, name: str) -> Any:
        """Retrieve (and lazily instantiate) an adapter by name.

        Instances are cached — the same adapter object is returned on
        subsequent calls for the same *name*.

        Args:
            name: Registered adapter name.

        Returns:
            An instance of the registered engine class.

        Raises:
            AdapterNotFoundError: If *name* is not registered.
        """
        with self._instance_lock:
            entry = self._adapters.get(name)
            if entry is None:
                available = ", ".join(sorted(self._adapters)) or "(none)"
                raise AdapterNotFoundError(
                    f"Adapter {name!r} not found. Available: {available}"
                )
            engine_class, kwargs, instance = entry
            if instance is None:
                instance = engine_class(**kwargs)
                self._adapters[name] = (engine_class, kwargs, instance)
            return instance

    def list_adapters(self) -> list[str]:
        """Return the names of all registered adapters."""
        with self._instance_lock:
            return list(self._adapters.keys())

    def validate_selected(self, name: str) -> None:
        """Eagerly validate that the selected adapter is fully functional.

        For ``"langchain"``: attempts to import the LangChain module surface and
        raises :class:`~agentic_v2.core.errors.ConfigurationError` with an
        actionable install hint if the optional extras are missing.

        For ``"native"`` (and any other adapter): this method is a no-op —
        the native engine has no optional dependencies.

        Args:
            name: Registered adapter name to validate (e.g. ``"langchain"``).

        Raises:
            ConfigurationError: When *name* is ``"langchain"`` and the
                ``langchain``/``langgraph`` extras are not installed.
        """
        if name != "langchain":
            return

        try:
            import langchain  # noqa: F401
            import langgraph  # noqa: F401
        except ImportError as exc:
            raise ConfigurationError(
                "LangChain engine selected but extras not installed. "
                "Install with: pip install -e '.[langchain]'"
            ) from exc

        logger.debug("LangChain adapter validation passed")


def get_registry() -> AdapterRegistry:
    """Return the global :class:`AdapterRegistry` singleton."""
    return AdapterRegistry()
