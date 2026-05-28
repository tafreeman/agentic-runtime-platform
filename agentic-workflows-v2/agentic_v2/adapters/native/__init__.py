"""Native execution engine adapter.

Auto-registers the :class:`NativeEngine` adapter when this package
is imported.  The native adapter wraps the existing DAG and Pipeline
executors behind the :class:`ExecutionEngine` protocol.
"""

from ..registry import get_registry
from .engine import NativeEngine

get_registry().register("native", NativeEngine)

__all__ = ["NativeEngine"]
