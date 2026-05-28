"""Concrete trace adapter implementations."""

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .base import CanonicalEvent, TraceAdapter

logger = logging.getLogger(__name__)


class ConsoleTraceAdapter(TraceAdapter):
    """Trace adapter that emits events to console/logging.

    Useful for development and debugging. Events are logged at INFO
    level.
    """

    def __init__(self, pretty_print: bool = True):
        """Initialize console trace adapter.

        Args:
            pretty_print: If True, format JSON output with indentation
        """
        self.pretty_print = pretty_print

    def emit(self, event: CanonicalEvent) -> None:
        """Emit event to console via logging."""
        if self.pretty_print:
            event_str = json.dumps(event.to_dict(), indent=2, default=str)
        else:
            event_str = event.to_json()

        logger.info(f"[TRACE] {event.type} | {event_str}")


class FileTraceAdapter(TraceAdapter):
    """Trace adapter that appends events to a JSON lines file.

    Each event is written as a single-line JSON object, making it easy
    to process with tools like jq or stream into analysis pipelines.
    """

    def __init__(self, file_path: Path, buffer_size: int = 1):
        """Initialize file trace adapter.

        Args:
            file_path: Path to the output file (will be created if doesn't exist)
            buffer_size: Number of events to buffer before flushing (default: 1 = no buffering)
        """
        self.file_path = Path(file_path)
        self.buffer_size = buffer_size
        self._buffer = []

        # Ensure parent directory exists
        self.file_path.parent.mkdir(parents=True, exist_ok=True)

    def emit(self, event: CanonicalEvent) -> None:
        """Emit event to file."""
        self._buffer.append(event.to_json())

        if len(self._buffer) >= self.buffer_size:
            self._flush()

    def _flush(self) -> None:
        """Flush buffered events to file."""
        if not self._buffer:
            return

        with open(self.file_path, "a", encoding="utf-8") as f:
            for line in self._buffer:
                f.write(line + "\n")

        self._buffer.clear()

    def __del__(self):
        """Ensure buffer is flushed on cleanup."""
        try:
            self._flush()
        except Exception:
            pass  # Suppress errors during cleanup


class CompositeTraceAdapter(TraceAdapter):
    """Trace adapter that forwards events to multiple adapters.

    Useful for emitting to console and file simultaneously, or to
    multiple backends.
    """

    def __init__(self, *adapters: TraceAdapter):
        """Initialize composite adapter.

        Args:
            *adapters: One or more trace adapters to forward events to
        """
        self.adapters = list(adapters)

    def emit(self, event: CanonicalEvent) -> None:
        """Emit event to all registered adapters."""
        for adapter in self.adapters:
            try:
                adapter.emit(event)
            except Exception as e:
                logger.error(f"Error emitting event to {type(adapter).__name__}: {e}")


class NullTraceAdapter(TraceAdapter):
    """No-op trace adapter that discards events.

    Useful as a default when tracing is disabled.
    """

    def emit(self, event: CanonicalEvent) -> None:
        """Discard event."""
        pass


class OtelTraceAdapter(TraceAdapter):
    """Trace adapter that emits workflow events as OpenTelemetry spans.

    Tracks workflow and step lifecycles via explicit span management,
    mapping run_id to workflow spans and run_id:step_name to step spans.
    """

    _SENSITIVE_KEYS = frozenset({"inputs", "outputs", "prompt", "response", "content"})

    def __init__(self, tracer: Any, capture_sensitive: bool = False):
        self._tracer = tracer
        self._capture_sensitive = capture_sensitive
        self._workflow_spans: dict[str, Any] = {}

    def _sanitize_data(self, data: dict[str, Any]) -> dict[str, Any]:
        """Filter sensitive fields from event data when capture is disabled."""
        if self._capture_sensitive:
            return dict(data)
        return {k: v for k, v in data.items() if k not in self._SENSITIVE_KEYS}

    def emit(self, event: CanonicalEvent) -> None:
        try:
            self._emit_impl(event)
        except Exception as exc:
            logger.warning("OtelTraceAdapter emit failed for %s: %s", event.type, exc)

    def _emit_impl(self, event: CanonicalEvent) -> None:
        run_id = event.data.get("run_id")
        sanitized = self._sanitize_data(event.data)

        if event.type == "workflow_start":
            span = self._tracer.start_span(event.type, attributes=sanitized)
            if run_id:
                self._workflow_spans[run_id] = span
            return

        if event.type == "workflow_end":
            if run_id and run_id in self._workflow_spans:
                span = self._workflow_spans.pop(run_id)
                span.end()
            return

        if event.type == "step_start":
            span = self._tracer.start_span(event.type, attributes=sanitized)
            step_name = event.step_name or event.data.get("step_name")
            if run_id and step_name:
                self._workflow_spans[f"{run_id}:{step_name}"] = span
            return

        if event.type == "step_complete":
            step_name = event.step_name or event.data.get("step_name")
            key = f"{run_id}:{step_name}" if run_id and step_name else None
            if key and key in self._workflow_spans:
                span = self._workflow_spans.pop(key)
                span.end()
            return

        # Generic event — fire-and-forget span
        span = self._tracer.start_span(event.type, attributes=sanitized)
        span.end()


class LangSmithTraceAdapter(TraceAdapter):
    """Trace adapter that emits workflow events to LangSmith.

    This adapter is intentionally tolerant: if LangSmith is unavailable or a
    particular call fails, it logs and continues without interrupting workflow
    execution.
    """

    def __init__(
        self,
        *,
        project_name: str = "agentic-workflows-v2",
        client: object | None = None,
    ):
        self.project_name = project_name
        self._root_run_by_workflow_run_id: dict[str, str] = {}
        self._client = client or self._build_client()

    @staticmethod
    def _build_client() -> object:
        try:
            from langsmith import Client
        except ImportError as exc:
            raise ImportError(
                "LangSmith adapter requires 'langsmith'. "
                "Install with: pip install langsmith"
            ) from exc
        return Client()

    @staticmethod
    def _utc_now() -> datetime:
        return datetime.now(timezone.utc)

    def _extract_workflow_run_id(self, event: CanonicalEvent) -> str | None:
        run_id = event.data.get("run_id")
        if isinstance(run_id, str):
            return run_id
        return None

    def _create_run(self, **kwargs) -> None:
        create_run = getattr(self._client, "create_run", None)
        if not callable(create_run):
            logger.debug("LangSmith client has no create_run(); skipping trace")
            return
        create_run(**kwargs)

    def _patch_run(self, run_id: str, **kwargs) -> None:
        update_run = getattr(self._client, "update_run", None)
        if not callable(update_run):
            logger.debug("LangSmith client has no update_run(); skipping trace update")
            return
        update_run(run_id=run_id, **kwargs)

    def emit(self, event: CanonicalEvent) -> None:
        try:
            self._emit_impl(event)
        except Exception as exc:
            logger.warning("LangSmith trace emit failed for %s: %s", event.type, exc)

    def _emit_impl(self, event: CanonicalEvent) -> None:
        workflow_run_id = self._extract_workflow_run_id(event)

        if event.type == "workflow_start":
            external_id = str(uuid.uuid4())
            self._create_run(
                id=external_id,
                name=f"workflow:{event.data.get('workflow_name', 'unknown')}",
                run_type="chain",
                inputs=event.data.get("inputs", {}),
                extra={"canonical_event": event.to_dict()},
                project_name=self.project_name,
                start_time=self._utc_now(),
            )
            if workflow_run_id:
                self._root_run_by_workflow_run_id[workflow_run_id] = external_id
            return

        if event.type == "workflow_end":
            if workflow_run_id and workflow_run_id in self._root_run_by_workflow_run_id:
                root_id = self._root_run_by_workflow_run_id[workflow_run_id]
                self._patch_run(
                    root_id,
                    outputs=event.data.get("outputs", {}),
                    end_time=self._utc_now(),
                    extra={
                        "canonical_event": event.to_dict(),
                        "status": event.data.get("status"),
                    },
                )
            else:
                self._create_run(
                    id=str(uuid.uuid4()),
                    name=f"workflow_end:{event.data.get('workflow_name', 'unknown')}",
                    run_type="chain",
                    inputs={},
                    outputs=event.data.get("outputs", {}),
                    extra={"canonical_event": event.to_dict()},
                    project_name=self.project_name,
                    start_time=self._utc_now(),
                    end_time=self._utc_now(),
                )
            return

        # step_start / step_complete or any other canonical event
        payload = {
            "step_name": event.step_name,
            **event.data,
        }
        kwargs = {
            "id": str(uuid.uuid4()),
            "name": event.type,
            "run_type": "tool",
            "inputs": payload,
            "extra": {"canonical_event": event.to_dict()},
            "project_name": self.project_name,
            "start_time": self._utc_now(),
            "end_time": self._utc_now(),
        }
        if workflow_run_id and workflow_run_id in self._root_run_by_workflow_run_id:
            kwargs["parent_run_id"] = self._root_run_by_workflow_run_id[workflow_run_id]
        self._create_run(**kwargs)
