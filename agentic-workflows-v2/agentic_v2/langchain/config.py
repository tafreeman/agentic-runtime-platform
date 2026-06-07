"""YAML workflow configuration loader.

Reads workflow YAML files and produces lightweight config dataclasses.
This is intentionally *not* an executor — it just parses config.
The graph compiler (``graph.py``) turns configs into runnable graphs.
"""

from __future__ import annotations

import functools
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from ..utils.path_safety import ensure_within_base

# ---------------------------------------------------------------------------
# Config dataclasses
# ---------------------------------------------------------------------------


@dataclass
class StepConfig:
    """A single step parsed from YAML."""

    name: str
    agent: str = ""
    description: str = ""
    depends_on: list[str] = field(default_factory=list)
    inputs: dict[str, Any] = field(default_factory=dict)
    outputs: dict[str, str] = field(default_factory=dict)
    when: str | None = None
    loop_until: str | None = None
    loop_max: int = 3
    loop_max_expr: str | None = None
    tools: list[str] | None = None
    prompt_file: str | None = None
    model_override: str | None = None


@dataclass
class InputConfig:
    """Workflow input parameter."""

    name: str
    type: str = "string"
    description: str = ""
    default: Any = None
    required: bool = True
    enum: list[str] | None = None


@dataclass
class OutputConfig:
    """Workflow output."""

    name: str
    from_expr: Any = ""
    optional: bool = False


@dataclass
class CriterionConfig:
    """Evaluation criterion."""

    name: str
    definition: str = ""
    weight: float | None = None
    critical_floor: float | None = None
    scale: dict[str, str] = field(default_factory=dict)
    evidence_required: list[str] = field(default_factory=list)
    formula_id: str = "zero_one"


@dataclass
class EvaluationConfig:
    """Workflow evaluation settings."""

    rubric_id: str | None = None
    scoring_profile: str | None = None
    weights: dict[str, float] | None = None
    criteria: list[CriterionConfig] = field(default_factory=list)


@dataclass
class WorkflowConfig:
    """Complete parsed workflow configuration.

    This is a pure-data object — no execution logic.
    """

    name: str
    description: str = ""
    version: str = "1.0"
    experimental: bool = False
    inputs: dict[str, InputConfig] = field(default_factory=dict)
    outputs: dict[str, OutputConfig] = field(default_factory=dict)
    steps: list[StepConfig] = field(default_factory=list)
    evaluation: EvaluationConfig | None = None
    capabilities: dict[str, list[str]] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Loader
# ---------------------------------------------------------------------------

_DEFAULT_DEFINITIONS_DIR = Path(__file__).parent.parent / "workflows" / "definitions"


def get_workflow_path(
    name: str,
    definitions_dir: Path | None = None,
    *,
    must_exist: bool = True,
) -> Path:
    """Resolve the filesystem path for a workflow YAML file."""
    base = _resolve_definitions_dir(definitions_dir)
    normalized_name = _validate_workflow_name(name)

    yaml_path = _resolve_workflow_path(base, normalized_name, ".yaml")
    if yaml_path.exists() or not must_exist:
        return yaml_path

    yml_path = _resolve_workflow_path(base, normalized_name, ".yml")
    if yml_path.exists():
        return yml_path

    available = list_workflows(definitions_dir)
    raise FileNotFoundError(
        f"Workflow '{normalized_name}' not found in {base}. Available: {available}"
    )


@functools.lru_cache(maxsize=128)
def load_workflow_config(
    name: str,
    definitions_dir: Path | None = None,
) -> WorkflowConfig:
    """Load a workflow YAML file by name and return a ``WorkflowConfig``.

    Parameters
    ----------
    name:
        Workflow name (without ``.yaml`` extension).
    definitions_dir:
        Directory containing YAML files.  Defaults to the package's
        built-in ``workflows/definitions/`` folder.
    """
    path = get_workflow_path(name, definitions_dir=definitions_dir)
    return _parse_file(path)


def list_workflows(definitions_dir: Path | None = None) -> list[str]:
    """List available workflow names."""
    base = _resolve_definitions_dir(definitions_dir)
    if not base.exists():
        return []
    return sorted(p.stem for p in base.iterdir() if p.suffix in (".yaml", ".yml"))


def load_workflow_document(
    name: str,
    definitions_dir: Path | None = None,
) -> tuple[Path, dict[str, Any], str]:
    """Load the raw workflow YAML document and its source text."""
    path = get_workflow_path(name, definitions_dir=definitions_dir)
    source = path.read_text(encoding="utf-8")
    data = yaml.safe_load(source)
    if not isinstance(data, dict):
        raise ValueError(f"Workflow YAML must be a mapping: {path}")
    return path, data, source


def render_workflow_document(document: dict[str, Any]) -> str:
    """Render a workflow document to YAML while preserving key order."""
    return yaml.safe_dump(document, sort_keys=False, allow_unicode=True)


def validate_workflow_document(
    document: dict[str, Any],
    *,
    expected_name: str | None = None,
) -> WorkflowConfig:
    """Validate a raw workflow document and return the parsed config."""
    if not isinstance(document, dict):
        raise ValueError("Workflow document must be a mapping.")

    default_name = _validate_workflow_name(expected_name or document.get("name", ""))
    doc_name = document.get("name")
    if doc_name is not None and str(doc_name) != default_name:
        raise ValueError(
            f"Workflow document name {doc_name!r} does not match requested workflow "
            f"name {default_name!r}."
        )

    raw_steps = document.get("steps")
    if not isinstance(raw_steps, list) or not raw_steps:
        raise ValueError("Workflow document must define a non-empty 'steps' list.")

    seen_step_names: set[str] = set()
    for index, raw_step in enumerate(raw_steps):
        if not isinstance(raw_step, dict):
            raise ValueError(f"Workflow step #{index} must be a mapping.")
        step_name = raw_step.get("name")
        if not isinstance(step_name, str) or not step_name.strip():
            raise ValueError(f"Workflow step #{index} is missing required 'name'.")
        if step_name in seen_step_names:
            raise ValueError(f"Workflow step name {step_name!r} is duplicated.")
        seen_step_names.add(step_name)

        depends_on = raw_step.get("depends_on", [])
        if depends_on is not None and (
            not isinstance(depends_on, list)
            or any(not isinstance(item, str) or not item for item in depends_on)
        ):
            raise ValueError(
                f"Workflow step {step_name!r} has invalid 'depends_on' values."
            )

        for field_name in ("inputs", "outputs"):
            raw_mapping = raw_step.get(field_name, {})
            if raw_mapping is not None and not isinstance(raw_mapping, dict):
                raise ValueError(
                    f"Workflow step {step_name!r} has invalid '{field_name}' mapping."
                )

    config = _parse(document, default_name)
    return config


def save_workflow_document(
    name: str,
    document: dict[str, Any],
    definitions_dir: Path | None = None,
) -> tuple[Path, dict[str, Any], WorkflowConfig, str]:
    """Validate and persist a workflow document to disk."""
    config = validate_workflow_document(document, expected_name=name)
    path = get_workflow_path(name, definitions_dir=definitions_dir, must_exist=False)
    persisted_document = dict(document)
    persisted_document.setdefault("name", name)
    yaml_text = render_workflow_document(persisted_document)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml_text, encoding="utf-8")
    return path, persisted_document, config, yaml_text


# ---------------------------------------------------------------------------
# Internal parsing
# ---------------------------------------------------------------------------


def _parse_file(path: Path) -> WorkflowConfig:
    with open(path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        raise ValueError(f"Workflow YAML must be a mapping: {path}")
    return _parse(data, path.stem)


def _resolve_definitions_dir(definitions_dir: Path | None) -> Path:
    base = definitions_dir or _DEFAULT_DEFINITIONS_DIR
    return base.resolve()


def _validate_workflow_name(name: str) -> str:
    if (
        not isinstance(name, str)
        or not name
        or not re.fullmatch(r"[A-Za-z0-9_.-]+", name)
    ):
        raise ValueError(f"Invalid workflow name: {name}")
    return name


def _resolve_workflow_path(base: Path, name: str, suffix: str) -> Path:
    try:
        return ensure_within_base(base / f"{name}{suffix}", base)
    except ValueError as exc:
        raise ValueError(f"Invalid workflow name: {name}") from exc


def _coerce_positive_int(value: Any, *, field_name: str) -> int:
    try:
        return max(1, int(value))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be a positive integer.") from exc


def _parse_loop_max(
    raw_value: Any,
    inputs: dict[str, InputConfig],
) -> tuple[int, str | None]:
    """Parse a step loop bound and preserve runtime input expressions."""
    if isinstance(raw_value, str):
        stripped = raw_value.strip()
        input_ref = re.fullmatch(
            r"\$\{\s*inputs\.([A-Za-z_][\w]*)\s*\}", stripped
        )
        if input_ref:
            input_name = input_ref.group(1)
            input_cfg = inputs.get(input_name)
            fallback = (
                input_cfg.default
                if input_cfg is not None and input_cfg.default is not None
                else 3
            )
            return (
                _coerce_positive_int(fallback, field_name="loop_max"),
                stripped,
            )
        if stripped.startswith("${") and stripped.endswith("}"):
            return 3, stripped

    return _coerce_positive_int(raw_value, field_name="loop_max"), None


def _parse(data: dict[str, Any], default_name: str) -> WorkflowConfig:
    # --- Inputs ---
    inputs: dict[str, InputConfig] = {}
    for k, v in data.get("inputs", {}).items():
        if isinstance(v, dict):
            inputs[k] = InputConfig(
                name=k,
                type=v.get("type", "string"),
                description=v.get("description", ""),
                default=v.get("default"),
                required=v.get("required", True),
                enum=v.get("enum"),
            )
        else:
            inputs[k] = InputConfig(name=k, default=v, required=False)

    # --- Steps ---
    steps: list[StepConfig] = []
    for raw in data.get("steps", []):
        if not isinstance(raw, dict) or "name" not in raw:
            continue
        loop_max, loop_max_expr = _parse_loop_max(raw.get("loop_max", 3), inputs)
        steps.append(
            StepConfig(
                name=raw["name"],
                agent=raw.get("agent", ""),
                description=raw.get("description", ""),
                depends_on=raw.get("depends_on", []),
                inputs=dict(raw.get("inputs", {})),
                outputs=dict(raw.get("outputs", {})),
                when=raw.get("when"),
                loop_until=raw.get("loop_until"),
                loop_max=loop_max,
                loop_max_expr=loop_max_expr,
                tools=(
                    raw.get("tools") if isinstance(raw.get("tools"), list) else None
                ),
                prompt_file=raw.get("prompt_file"),
                model_override=(
                    raw.get("model_override")
                    if isinstance(raw.get("model_override"), str)
                    else raw.get("model")
                ),
            )
        )

    # --- Outputs ---
    outputs: dict[str, OutputConfig] = {}
    for k, v in data.get("outputs", {}).items():
        if isinstance(v, dict):
            outputs[k] = OutputConfig(
                name=k,
                from_expr=v.get("from", ""),
                optional=v.get("optional", False),
            )
        else:
            outputs[k] = OutputConfig(name=k, from_expr=v)

    # --- Evaluation ---
    evaluation = None
    raw_eval = data.get("evaluation")
    if isinstance(raw_eval, dict):
        criteria = []
        for c in raw_eval.get("criteria", []):
            if isinstance(c, dict) and c.get("name"):
                criteria.append(
                    CriterionConfig(
                        name=c["name"],
                        definition=c.get("definition", ""),
                        weight=float(c["weight"]) if c.get("weight") else None,
                        critical_floor=(
                            float(c["critical_floor"])
                            if c.get("critical_floor") is not None
                            else None
                        ),
                        scale={
                            str(sk): str(sv)
                            for sk, sv in (c.get("scale") or {}).items()
                        },
                        evidence_required=c.get("evidence_required", []),
                        formula_id=c.get("formula_id", "zero_one"),
                    )
                )
        evaluation = EvaluationConfig(
            rubric_id=raw_eval.get("rubric_id"),
            scoring_profile=raw_eval.get("scoring_profile"),
            weights=raw_eval.get("weights"),
            criteria=criteria,
        )

    # --- Capabilities ---
    capabilities: dict[str, list[str]] = {}
    raw_cap = data.get("capabilities")
    if isinstance(raw_cap, dict):
        for ck, cv in raw_cap.items():
            if isinstance(cv, list):
                capabilities[ck] = [str(i) for i in cv]

    return WorkflowConfig(
        name=data.get("name", default_name),
        description=data.get("description", ""),
        version=str(data.get("version", "1.0")),
        experimental=bool(data.get("experimental", False)),
        inputs=inputs,
        outputs=outputs,
        steps=steps,
        evaluation=evaluation,
        capabilities=capabilities,
    )
