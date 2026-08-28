"""Live model discovery for Lemonade, the Ryzen AI hybrid NPU serving path.

ARP-IMPROVEMENTS F2: Lemonade was previously unprobed -- ``enumerate_known_models``
covered cloud, Ollama, LM Studio, and ONNX only. Reads the native REST API
directly over ``httpx``, mirroring :mod:`agentic_v2.models.ollama_discovery`'s
best-effort shape (any probe failure contributes no models; never raises).

Source probed:

- ``GET {LEMONADE_BASE_URL}/api/v1/models`` -- default
  ``http://localhost:13305``. **Not** ``:8000`` -- that port belongs to an
  unrelated ``Manager`` process on the machine this was probed against; see
  ``agentic-workflows-v2/evals/swe_ab/docs/MODEL-PROBE-GUIDE.md`` #2.

The exact response schema was not re-verified against a live Lemonade instance
as part of this change (this session has no access to one); the parser below
accepts both an OpenAI-style ``data`` list and a ``models`` list, and reads
``id``/``checkpoint``/``name`` for the identifier so a shape drift degrades to
"no models found" rather than raising. Confirm and tighten against a live
instance before relying on ``recipe``/``labels``.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "http://localhost:13305"
ENV_BASE_URL = "LEMONADE_BASE_URL"

_MODELS_PATH = "/api/v1/models"
_TIMEOUT_SECONDS = 5.0
_MODEL_PREFIX = "lemonade:"


@dataclass(frozen=True)
class LemonadeModelInfo:
    """A single Lemonade model discovered from a live ``/api/v1/models`` probe."""

    id: str  # provider-prefixed, e.g. "lemonade:CodeLlama-7b-Instruct-hf-Hybrid"
    name: str  # raw upstream checkpoint/model name
    recipe: str | None = None  # e.g. "ryzenai-llm" (NPU+iGPU hybrid) or "llamacpp"
    labels: tuple[str, ...] = ()  # e.g. ("coding", "tool-calling", "vision")

    def to_dict(self) -> dict[str, Any]:
        """JSON-serialisable view for API responses."""
        return {
            "id": self.id,
            "name": self.name,
            "recipe": self.recipe,
            "labels": list(self.labels),
        }


def _get_json(url: str) -> dict[str, Any] | None:
    """GET ``url`` and return a parsed JSON object, or ``None`` on any failure."""
    try:
        response = httpx.get(url, timeout=_TIMEOUT_SECONDS)
        response.raise_for_status()
        data = response.json()
    except Exception as exc:
        logger.debug("Lemonade probe failed for %s: %s", url, exc)
        return None
    return data if isinstance(data, dict) else None


def _base_url() -> str:
    return os.environ.get(ENV_BASE_URL, DEFAULT_BASE_URL).rstrip("/")


def _parse_models(data: dict[str, Any]) -> list[LemonadeModelInfo]:
    """Map a models-listing payload to :class:`LemonadeModelInfo` records.

    Tolerant of either an OpenAI-style ``data`` list or a ``models`` list, and
    of the identifier living under ``id``, ``checkpoint``, or ``name`` --
    the live schema was not re-confirmed for this change (see module
    docstring).
    """
    entries = data.get("data") or data.get("models") or []
    if not isinstance(entries, list):
        return []

    discovered: list[LemonadeModelInfo] = []
    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        name = entry.get("id") or entry.get("checkpoint") or entry.get("name")
        if not isinstance(name, str) or not name:
            continue
        model_id = name if name.startswith(_MODEL_PREFIX) else f"{_MODEL_PREFIX}{name}"
        if model_id in seen:
            continue
        seen.add(model_id)

        recipe = entry.get("recipe")
        raw_labels = entry.get("labels")
        labels = (
            tuple(label for label in raw_labels if isinstance(label, str) and label)
            if isinstance(raw_labels, list)
            else ()
        )
        discovered.append(
            LemonadeModelInfo(
                id=model_id,
                name=name,
                recipe=recipe if isinstance(recipe, str) else None,
                labels=labels,
            )
        )
    return discovered


def discover_lemonade_models() -> list[LemonadeModelInfo]:
    """Discover models the local Lemonade server currently reports (best-effort).

    Returns an empty list when Lemonade is unreachable, misconfigured, or its
    response does not match the shapes this parser tolerates. Never raises.
    """
    data = _get_json(f"{_base_url()}{_MODELS_PATH}")
    if not data:
        return []
    return _parse_models(data)


__all__ = ["LemonadeModelInfo", "discover_lemonade_models"]
