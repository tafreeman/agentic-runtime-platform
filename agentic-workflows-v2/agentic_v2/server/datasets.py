"""Dataset loading, listing, and discovery utilities.

Handles three dataset sources:

* **Repository datasets** -- loaded via ``tools.agents.benchmarks`` from
  HuggingFace or GitHub, with fallback to ``evaluation.yaml`` config.
* **Local datasets** -- JSON files discovered under ``tests/fixtures/datasets/``,
  ``evaluation/datasets/``, or ``tools/agents/benchmarks/gold_standards/``.
* **Eval sets** -- predefined groupings of datasets from ``evaluation.yaml``.

Key responsibilities:

* **Discovery** (:func:`list_repository_datasets`, :func:`list_local_datasets`,
  :func:`list_eval_sets`) -- enumerate available datasets for UI selection.
* **Loading** (:func:`load_repository_dataset_sample`,
  :func:`load_local_dataset_sample`) -- fetch a single indexed sample and
  return ``(sample_dict, metadata_dict)``.

Dataset-to-workflow matching and sample adaptation logic lives in
:mod:`~agentic_v2.server.dataset_matching` and is re-exported here for
backward compatibility.

All public names are re-exported by :mod:`~agentic_v2.server.evaluation`
for backward compatibility.
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict
from pathlib import Path
from typing import Any

import yaml

from ..core.tenant import DEFAULT_TENANT_ID, sanitize_tenant_id, tenant_dataset_dir

# Re-export matching/adaptation functions for backward compatibility
from .dataset_matching import (
    _dataset_value_for_input,
    _extract_message_text,
    _is_empty_value,
    _materialize_file_input,
    _pick_first,
    adapt_sample_to_workflow_inputs,
    match_workflow_dataset,
    validate_required_inputs_present,
)

__all__ = [
    "_dataset_value_for_input",
    "_extract_message_text",
    "_is_empty_value",
    "_materialize_file_input",
    "_pick_first",
    "adapt_sample_to_workflow_inputs",
    "match_workflow_dataset",
    "validate_required_inputs_present",
]

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Project root helpers
# ---------------------------------------------------------------------------


def _resolve_project_root() -> Path:
    """Locate the project root by searching parent directories for ``pyproject.toml``.

    Returns:
        Path to the project root directory.
    """
    this_file = Path(__file__).resolve()
    candidates = [this_file.parents[2], this_file.parents[3]]
    for root in candidates:
        if (root / "agentic_v2").exists() and (root / "pyproject.toml").exists():
            return root
        if (root / "src" / "agentic_v2").exists() and (
            root / "pyproject.toml"
        ).exists():
            return root
    return this_file.parents[2]


def _resolve_eval_config_path(project_root: Path) -> Path:
    """Resolve the path to ``evaluation.yaml`` under the project root.

    Args:
        project_root: Resolved project root directory.

    Returns:
        Path to the evaluation config file (may not exist on disk).
    """
    candidates = [
        project_root / "agentic_v2" / "config" / "defaults" / "evaluation.yaml",
        project_root / "src" / "agentic_v2" / "config" / "defaults" / "evaluation.yaml",
    ]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


_PROJECT_ROOT = _resolve_project_root()
_WORKSPACE_ROOT = _PROJECT_ROOT.parent
_EVAL_CONFIG_PATH = _resolve_eval_config_path(_PROJECT_ROOT)


def _load_eval_config() -> dict[str, Any]:
    """Load and parse the evaluation YAML configuration file.

    Returns:
        Parsed config dict, or empty dict if the file is missing or invalid.
    """
    if not _EVAL_CONFIG_PATH.exists():
        return {}
    try:
        with _EVAL_CONFIG_PATH.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
            return data if isinstance(data, dict) else {}
    except (OSError, yaml.YAMLError, ValueError) as exc:
        logger.warning("Failed to load evaluation config: %s", exc)
        return {}


# ---------------------------------------------------------------------------
# Dataset discovery & listing
# ---------------------------------------------------------------------------


def list_repository_datasets() -> list[dict[str, Any]]:
    """Return repository-backed dataset options from benchmark registries.

    Attempts to load from ``tools.agents.benchmarks.datasets.BENCHMARK_DEFINITIONS``.
    Falls back to the ``evaluation.datasets`` section of the eval config.

    Returns:
        Sorted list of dataset option dicts with ``id``, ``name``,
        ``source``, ``description``, and ``sample_count`` keys.
    """
    options: list[dict[str, Any]] = []
    try:
        from tools.agents.benchmarks.datasets import BENCHMARK_DEFINITIONS

        for dataset_id, definition in BENCHMARK_DEFINITIONS.items():
            source = getattr(getattr(definition, "source", None), "value", "")
            if source not in {"huggingface", "github"}:
                continue
            options.append(
                {
                    "id": dataset_id,
                    "name": definition.name,
                    "source": "repository",
                    "description": definition.description,
                    "sample_count": definition.size,
                }
            )
        return sorted(options, key=lambda x: x["id"])
    except (ImportError, AttributeError, TypeError) as exc:
        logger.info("Repository benchmark definitions unavailable: %s", exc)

    fallback = _load_eval_config().get("evaluation", {}).get("datasets", {})
    for dataset_id, cfg in fallback.items():
        if not isinstance(cfg, dict):
            continue
        if cfg.get("type") and cfg.get("url"):
            options.append(
                {
                    "id": str(dataset_id),
                    "name": str(dataset_id).replace("_", " ").title(),
                    "source": "repository",
                    "description": cfg.get("description", ""),
                    "sample_count": None,
                }
            )
    return sorted(options, key=lambda x: x["id"])


def _local_dataset_roots(tenant_id: str | None = None) -> list[Path]:
    """Return existing directories that may contain local JSON datasets.

    Returns:
        List of existing directory paths under fixtures, evaluation, and tools.
    """
    legacy_candidates = [
        _PROJECT_ROOT / "tests" / "fixtures" / "datasets",
        _PROJECT_ROOT / "evaluation" / "datasets",
        _WORKSPACE_ROOT / "tools" / "agents" / "benchmarks" / "gold_standards",
    ]
    if tenant_id is None:
        candidates = legacy_candidates
    else:
        safe_tenant = sanitize_tenant_id(tenant_id)
        candidates = [
            tenant_dataset_dir(safe_tenant, create=False),
        ]
        if safe_tenant == DEFAULT_TENANT_ID:
            candidates.extend(legacy_candidates)
    return [p for p in candidates if p.exists() and p.is_dir()]


def _safe_relative_id(path: Path) -> str:
    """Convert an absolute path to a workspace-relative POSIX identifier.

    Args:
        path: Absolute file path.

    Returns:
        POSIX-style relative path string, or absolute fallback.
    """
    try:
        return path.relative_to(_WORKSPACE_ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def _estimate_sample_count(path: Path) -> int | None:
    """Estimate the number of samples in a local JSON dataset file.

    Args:
        path: Path to the JSON file.

    Returns:
        Sample count, or None if the file cannot be parsed.
    """
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return len(data)
        if isinstance(data, dict):
            for key in ("tasks", "samples", "items"):
                value = data.get(key)
                if isinstance(value, list):
                    return len(value)
            return 1
    except (OSError, ValueError):
        return None
    return None


def list_local_datasets(tenant_id: str | None = None) -> list[dict[str, Any]]:
    """Discover and return local JSON dataset files from known directories.

    Scans ``_local_dataset_roots()`` recursively for ``*.json`` files,
    deduplicates by workspace-relative ID, and estimates sample counts.

    Returns:
        Sorted list of dataset option dicts.
    """
    options: list[dict[str, Any]] = []
    for root in _local_dataset_roots(tenant_id):
        for json_path in sorted(root.rglob("*.json")):
            options.append(
                {
                    "id": _safe_relative_id(json_path),
                    "name": json_path.stem.replace("_", " "),
                    "source": "local",
                    "description": f"Local JSON dataset ({json_path.parent.name})",
                    "sample_count": _estimate_sample_count(json_path),
                }
            )
    dedup: dict[str, dict[str, Any]] = {}
    for option in options:
        dedup[option["id"]] = option
    return sorted(dedup.values(), key=lambda x: x["id"])


def list_eval_sets() -> list[dict[str, Any]]:
    """Return predefined evaluation sets from the ``evaluation.eval_sets`` config
    section.

    Returns:
        Sorted list of eval set dicts with ``id``, ``name``,
        ``description``, and ``datasets`` keys.
    """
    config = _load_eval_config()
    eval_sets_config = config.get("evaluation", {}).get("eval_sets", {})

    if not isinstance(eval_sets_config, dict):
        return []

    eval_sets: list[dict[str, Any]] = []
    for set_id, set_config in eval_sets_config.items():
        if not isinstance(set_config, dict):
            continue

        eval_sets.append(
            {
                "id": str(set_id),
                "name": set_config.get("name", str(set_id).replace("_", " ").title()),
                "description": set_config.get("description", ""),
                "datasets": set_config.get("datasets", []),
            }
        )

    return sorted(eval_sets, key=lambda x: x["id"])


# ---------------------------------------------------------------------------
# Dataset loading
# ---------------------------------------------------------------------------


def _is_under_allowed_root(path: Path, tenant_id: str | None = None) -> bool:
    """Check whether a resolved path falls under an allowed dataset root.

    Args:
        path: File path to check.

    Returns:
        True if the path is within a known dataset directory.
    """
    resolved = path.resolve()
    for root in _local_dataset_roots(tenant_id):
        try:
            resolved.relative_to(root.resolve())
            return True
        except ValueError:
            continue
    return False


def _resolve_local_dataset(dataset_ref: str, tenant_id: str | None = None) -> Path:
    """Resolve a local dataset reference to a JSON file path under an allowed root.

    Args:
        dataset_ref: Dataset ID string matching a known local dataset.

    Returns:
        Resolved filesystem path to the JSON file.

    Raises:
        ValueError: If the dataset is not found or is outside allowed roots.
    """
    for option in list_local_datasets(tenant_id):
        if option["id"] == dataset_ref:
            option_path = (_WORKSPACE_ROOT / option["id"]).resolve()
            if (
                option_path.exists()
                and option_path.is_file()
                and _is_under_allowed_root(option_path, tenant_id)
            ):
                return option_path

    raise ValueError(f"Local dataset not found or not allowed: {dataset_ref}")


def _extract_sample(data: Any, sample_index: int) -> tuple[dict[str, Any], str | None]:
    """Extract a single sample from parsed JSON dataset data.

    Supports top-level lists, or dicts with ``tasks``/``samples``/``items``
    keys containing lists.

    Args:
        data: Parsed JSON data (list or dict).
        sample_index: Zero-based index of the desired sample.

    Returns:
        A 2-tuple of ``(sample_dict, task_id_string)``.

    Raises:
        ValueError: If the data format is unsupported or empty.
    """
    if isinstance(data, list):
        if not data:
            raise ValueError("Dataset has no samples")
        idx = min(max(sample_index, 0), len(data) - 1)
        sample = data[idx]
        if isinstance(sample, dict):
            return sample, str(sample.get("task_id") or sample.get("id") or idx)
        return {"value": sample}, str(idx)

    if isinstance(data, dict):
        for key in ("tasks", "samples", "items"):
            entries = data.get(key)
            if isinstance(entries, list) and entries:
                idx = min(max(sample_index, 0), len(entries) - 1)
                sample = entries[idx]
                if isinstance(sample, dict):
                    return sample, str(sample.get("task_id") or sample.get("id") or idx)
                return {"value": sample}, str(idx)
        return data, str(data.get("task_id") or data.get("id") or "0")

    raise ValueError("Unsupported dataset format; expected JSON object or array")


def _extract_all_samples(data: Any) -> list[dict[str, Any]]:
    """Return the full list of samples from parsed local dataset JSON.

    Supports top-level lists, or dicts with ``tasks``/``samples``/``items``
    keys containing lists. Falls back to a single-item list when the
    payload is a standalone dict.

    Args:
        data: Parsed JSON payload (list or dict).

    Returns:
        List of sample-shaped dicts; non-dict items are wrapped as
        ``{"value": item}`` for schema consistency.

    Raises:
        ValueError: If the data format is unsupported.
    """
    if isinstance(data, list):
        return [
            item if isinstance(item, dict) else {"value": item} for item in data
        ]

    if isinstance(data, dict):
        for key in ("tasks", "samples", "items"):
            entries = data.get(key)
            if isinstance(entries, list):
                return [
                    entry if isinstance(entry, dict) else {"value": entry}
                    for entry in entries
                ]
        return [data]

    raise ValueError("Unsupported dataset format; expected JSON object or array")


def load_local_dataset_sample(
    dataset_ref: str, sample_index: int = 0, tenant_id: str | None = None
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Load a single sample from a local JSON dataset file.

    Args:
        dataset_ref: Dataset ID matching a known local dataset.
        sample_index: Zero-based sample index within the dataset.

    Returns:
        A 2-tuple of ``(sample_dict, metadata_dict)``.

    Raises:
        ValueError: If the dataset is not found or the format is unsupported.
    """
    path = _resolve_local_dataset(dataset_ref, tenant_id)
    payload = json.loads(path.read_text(encoding="utf-8"))
    sample, task_id = _extract_sample(payload, sample_index)
    sample_count = _estimate_sample_count(path)
    meta = {
        "source": "local",
        "dataset_id": dataset_ref,
        "dataset_path": _safe_relative_id(path),
        "sample_index": sample_index,
        "task_id": task_id,
        "sample_count": sample_count,
    }
    return sample, meta


def load_local_dataset_samples(
    dataset_ref: str,
    offset: int = 0,
    limit: int = 20,
    tenant_id: str | None = None,
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """Load a paginated batch of samples from a local JSON dataset in one call.

    Reads the JSON file once and slices the in-memory list, avoiding the
    O(n^2) re-read pattern that per-index callers would otherwise incur.

    Args:
        dataset_ref: Dataset ID matching a known local dataset.
        offset: Zero-based start index of the page.
        limit: Maximum number of samples to return.

    Returns:
        List of ``(sample_dict, metadata_dict)`` tuples whose
        ``sample_index`` values are absolute (not page-local).

    Raises:
        ValueError: If the dataset is not found or the format is unsupported.
    """
    path = _resolve_local_dataset(dataset_ref, tenant_id)
    payload = json.loads(path.read_text(encoding="utf-8"))
    all_samples = _extract_all_samples(payload)
    sample_count = len(all_samples)

    start = max(offset, 0)
    end = min(start + max(limit, 0), sample_count)
    page = all_samples[start:end]

    results: list[tuple[dict[str, Any], dict[str, Any]]] = []
    relative_path = _safe_relative_id(path)
    for local_idx, sample in enumerate(page):
        absolute_index = start + local_idx
        task_id = str(
            sample.get("task_id") or sample.get("id") or absolute_index
        )
        meta = {
            "source": "local",
            "dataset_id": dataset_ref,
            "dataset_path": relative_path,
            "sample_index": absolute_index,
            "task_id": task_id,
            "sample_count": sample_count,
        }
        results.append((sample, meta))
    return results


def load_repository_dataset_sample(
    dataset_id: str, sample_index: int = 0
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Load a single sample from a repository-backed benchmark dataset.

    Uses ``tools.agents.benchmarks.loader.load_benchmark`` to fetch data
    from HuggingFace or GitHub.

    Args:
        dataset_id: Benchmark registry dataset identifier.
        sample_index: Zero-based sample index.

    Returns:
        A 2-tuple of ``(sample_dict, metadata_dict)``.

    Raises:
        ValueError: If the dataset cannot be loaded or has no samples.
    """
    try:
        from tools.agents.benchmarks.loader import load_benchmark

        tasks = load_benchmark(
            benchmark_id=dataset_id, limit=max(sample_index + 1, 1)
        )
        if not tasks:
            raise ValueError(
                f"No samples returned for repository dataset '{dataset_id}'"
            )
        index = min(max(sample_index, 0), len(tasks) - 1)
        task = tasks[index]
        sample = task.to_dict() if hasattr(task, "to_dict") else asdict(task)
        meta = {
            "source": "repository",
            "dataset_id": dataset_id,
            "sample_index": index,
            "task_id": sample.get("task_id"),
            "benchmark_id": sample.get("benchmark_id", dataset_id),
            "sample_count": _repository_sample_count(dataset_id, fallback=len(tasks)),
        }
        return sample, meta
    except (ImportError, ValueError, KeyError, OSError, TypeError) as exc:
        raise ValueError(
            f"Unable to load repository dataset '{dataset_id}'. "
            "Choose a local JSON dataset or ensure benchmark dependencies are available."
        ) from exc


def _repository_sample_count(dataset_id: str, fallback: int) -> int:
    """Return the canonical size of a repository dataset.

    Looks up ``BENCHMARK_DEFINITIONS[dataset_id].size`` as the authoritative
    count. Falls back to the caller-supplied value when the registry is
    unavailable (e.g. optional benchmark extras not installed) or the
    dataset id is unknown.

    Args:
        dataset_id: Benchmark registry identifier.
        fallback: Size to use when the registry lookup fails.

    Returns:
        Integer sample count. Never raises.
    """
    try:
        from tools.agents.benchmarks.datasets import BENCHMARK_DEFINITIONS

        definition = BENCHMARK_DEFINITIONS.get(dataset_id)
        if definition is not None:
            size = getattr(definition, "size", None)
            if isinstance(size, int) and size > 0:
                return size
    except (ImportError, AttributeError, TypeError) as exc:
        logger.debug(
            "Benchmark registry unavailable for %s: %s", dataset_id, exc
        )
    return fallback


def load_repository_dataset_samples(
    dataset_id: str, offset: int = 0, limit: int = 20
) -> list[tuple[dict[str, Any], dict[str, Any]]]:
    """Load a paginated batch of samples from a repository dataset in one call.

    Replaces the O(n^2) loop pattern where the route called
    :func:`load_repository_dataset_sample` per ``sample_index``. The
    underlying ``load_benchmark`` helper supports ``offset`` and ``limit``
    natively, so the batch fetches exactly ``limit`` rows.

    Args:
        dataset_id: Benchmark registry identifier.
        offset: Zero-based start index of the page.
        limit: Maximum number of samples to return.

    Returns:
        List of ``(sample_dict, metadata_dict)`` tuples whose
        ``sample_index`` values are absolute (not page-local).

    Raises:
        ValueError: If the benchmark cannot be loaded or the dataset is
            unknown to the registry.
    """
    try:
        from tools.agents.benchmarks.loader import load_benchmark

        tasks = load_benchmark(
            benchmark_id=dataset_id, offset=max(offset, 0), limit=max(limit, 0)
        )
        sample_count = _repository_sample_count(dataset_id, fallback=len(tasks))

        results: list[tuple[dict[str, Any], dict[str, Any]]] = []
        for local_idx, task in enumerate(tasks):
            sample = task.to_dict() if hasattr(task, "to_dict") else asdict(task)
            absolute_index = max(offset, 0) + local_idx
            meta = {
                "source": "repository",
                "dataset_id": dataset_id,
                "sample_index": absolute_index,
                "task_id": sample.get("task_id"),
                "benchmark_id": sample.get("benchmark_id", dataset_id),
                "sample_count": sample_count,
            }
            results.append((sample, meta))
        return results
    except (ImportError, ValueError, KeyError, OSError, TypeError) as exc:
        raise ValueError(
            f"Unable to load repository dataset '{dataset_id}'. "
            "Choose a local JSON dataset or ensure benchmark dependencies are available."
        ) from exc
