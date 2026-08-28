"""Live model discovery for Docker Model Runner.

ARP-IMPROVEMENTS F2: Docker Model Runner was previously unprobed --
``enumerate_known_models`` covered cloud, Ollama, LM Studio, and ONNX only.
Reads the native REST API directly over ``httpx``, mirroring
:mod:`agentic_v2.models.ollama_discovery`'s best-effort shape (any probe
failure contributes no models; never raises).

Source probed:

- ``GET {DOCKER_MODEL_RUNNER_BASE_URL}/engines/v1/models`` -- default
  ``http://localhost:12434``. OpenAI-compatible-shaped listing (``{"data":
  [{"id": ...}, ...]}``).

**A model listed here is not necessarily a model that loads.** Docker's
bundled llama.cpp does not recognise every architecture it lists -- e.g.
``muse-glimmer`` appears in the catalog and fails at load with
``unknown model architecture: 'muse-glimmer'``
(``agentic-workflows-v2/evals/swe_ab/docs/MODEL-PROBE-GUIDE.md`` #4a). This
module only reports the listing; callers needing "does it actually answer"
should complete a real chat call (see the ``verify`` mode on
:func:`agentic_v2.models.discovery_snapshot.discover_all_models`).

The exact response schema was not re-verified against a live instance as part
of this change (this session has no access to one); the parser tolerates a
``models`` list as a fallback to the documented ``data`` shape so a shape
drift degrades to "no models found" rather than raising.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any

import httpx

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "http://localhost:12434"
ENV_BASE_URL = "DOCKER_MODEL_RUNNER_BASE_URL"

_MODELS_PATH = "/engines/v1/models"
_TIMEOUT_SECONDS = 5.0
_MODEL_PREFIX = "docker-model-runner:"


@dataclass(frozen=True)
class DockerModelRunnerInfo:
    """A single model discovered from a live Docker Model Runner probe."""

    id: str  # provider-prefixed, e.g. "docker-model-runner:nemotron-3.5-lightning"
    name: str  # raw upstream model id

    def to_dict(self) -> dict[str, Any]:
        """JSON-serialisable view for API responses."""
        return {"id": self.id, "name": self.name}


def _get_json(url: str) -> dict[str, Any] | None:
    """GET ``url`` and return a parsed JSON object, or ``None`` on any failure."""
    try:
        response = httpx.get(url, timeout=_TIMEOUT_SECONDS)
        response.raise_for_status()
        data = response.json()
    except Exception as exc:
        logger.debug("Docker Model Runner probe failed for %s: %s", url, exc)
        return None
    return data if isinstance(data, dict) else None


def _base_url() -> str:
    return os.environ.get(ENV_BASE_URL, DEFAULT_BASE_URL).rstrip("/")


def _parse_models(data: dict[str, Any]) -> list[DockerModelRunnerInfo]:
    entries = data.get("data") or data.get("models") or []
    if not isinstance(entries, list):
        return []

    discovered: list[DockerModelRunnerInfo] = []
    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        name = entry.get("id") or entry.get("name")
        if not isinstance(name, str) or not name:
            continue
        model_id = name if name.startswith(_MODEL_PREFIX) else f"{_MODEL_PREFIX}{name}"
        if model_id in seen:
            continue
        seen.add(model_id)
        discovered.append(DockerModelRunnerInfo(id=model_id, name=name))
    return discovered


def discover_docker_model_runner_models() -> list[DockerModelRunnerInfo]:
    """Discover models Docker Model Runner currently lists (best-effort).

    Returns an empty list when the engine is unreachable, misconfigured, or
    its response does not match the shapes this parser tolerates. A listed
    model is not proven to load -- see the module docstring. Never raises.
    """
    data = _get_json(f"{_base_url()}{_MODELS_PATH}")
    if not data:
        return []
    return _parse_models(data)


__all__ = ["DockerModelRunnerInfo", "discover_docker_model_runner_models"]
