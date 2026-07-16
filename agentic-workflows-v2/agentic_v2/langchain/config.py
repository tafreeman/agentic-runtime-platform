"""YAML workflow configuration loader.

Reads workflow YAML files and produces lightweight config dataclasses.
This is intentionally *not* an executor — it just parses config.
The graph compiler (``graph.py``) turns configs into runnable graphs.
"""

from __future__ import annotations

import functools
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from ..artifact_contracts import (
    ArtifactContract,
    parse_artifact_contracts,
    validate_contract_bindings,
)
from ..utils.path_safety import ensure_within_base

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config dataclasses
# ---------------------------------------------------------------------------


@dataclass
class ModelParamsConfig:
    """Per-step sampling parameter overrides.

    ``None`` fields fall back to provider/builder defaults, so a step only
    pins the parameters it explicitly declares in YAML.
    """

    temperature: float | None = None
    top_p: float | None = None
    max_tokens: int | None = None


# Observer channels a step may enable.  ``observers: null`` (the default)
# means "all channels"; an explicit list restricts emission to those named.
KNOWN_OBSERVERS: tuple[str, ...] = ("trace", "websocket", "scoring")


@dataclass
class StepConfig:
    """A single step parsed from YAML."""

    name: str
    agent: str = ""
    description: str = ""
    depends_on: list[str] = field(default_factory=list)
    inputs: dict[str, Any] = field(default_factory=dict)
    outputs: dict[str, str] = field(default_factory=dict)
    input_contracts: dict[str, ArtifactContract] = field(default_factory=dict)
    output_contracts: dict[str, ArtifactContract] = field(default_factory=dict)
    when: str | None = None
    loop_until: str | None = None
    loop_max: int = 3
    loop_max_expr: str | None = None
    tools: list[str] | None = None
    prompt_file: str | None = None
    model_override: str | None = None
    persona: str | None = None
    observers: list[str] | None = None
    model_params: ModelParamsConfig | None = None


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


def _validate_document_name(document: dict[str, Any], expected_name: str | None) -> str:
    """Validate the document's name against the expected name and return it."""
    default_name = _validate_workflow_name(expected_name or document.get("name", ""))
    doc_name = document.get("name")
    if doc_name is not None and str(doc_name) != default_name:
        raise ValueError(
            f"Workflow document name {doc_name!r} does not match requested workflow "
            f"name {default_name!r}."
        )
    return default_name


def _validate_step_depends_on(step_name: str, raw_step: dict[str, Any]) -> None:
    """Validate a step's ``depends_on`` values are non-empty strings."""
    depends_on = raw_step.get("depends_on", [])
    if depends_on is not None and (
        not isinstance(depends_on, list)
        or any(not isinstance(item, str) or not item for item in depends_on)
    ):
        raise ValueError(
            f"Workflow step {step_name!r} has invalid 'depends_on' values."
        )


def _validate_step_mappings(step_name: str, raw_step: dict[str, Any]) -> None:
    """Validate a step's ``inputs``/``outputs`` fields are mappings when present."""
    for field_name in ("inputs", "outputs"):
        raw_mapping = raw_step.get(field_name, {})
        if raw_mapping is not None and not isinstance(raw_mapping, dict):
            raise ValueError(
                f"Workflow step {step_name!r} has invalid '{field_name}' mapping."
            )


def _validate_step_model_params(step_name: str, raw_step: dict[str, Any]) -> None:
    """Validate a step's ``model_params`` mapping when present."""
    raw_params = raw_step.get("model_params")
    if raw_params is None:
        return
    if not isinstance(raw_params, dict):
        raise ValueError(
            f"Workflow step {step_name!r} has invalid 'model_params' "
            "(must be a mapping)."
        )

    temperature = raw_params.get("temperature")
    if temperature is not None and not (
        isinstance(temperature, (int, float))
        and not isinstance(temperature, bool)
        and 0.0 <= float(temperature) <= 2.0
    ):
        raise ValueError(
            f"Workflow step {step_name!r} has invalid 'temperature' "
            "(must be a number between 0 and 2)."
        )

    top_p = raw_params.get("top_p")
    if top_p is not None and not (
        isinstance(top_p, (int, float))
        and not isinstance(top_p, bool)
        and 0.0 < float(top_p) <= 1.0
    ):
        raise ValueError(
            f"Workflow step {step_name!r} has invalid 'top_p' "
            "(must be a number greater than 0 and at most 1)."
        )

    max_tokens = raw_params.get("max_tokens")
    if max_tokens is not None and not (
        isinstance(max_tokens, int)
        and not isinstance(max_tokens, bool)
        and max_tokens >= 1
    ):
        raise ValueError(
            f"Workflow step {step_name!r} has invalid 'max_tokens' "
            "(must be a positive integer)."
        )


def _validate_step_observers(step_name: str, raw_step: dict[str, Any]) -> None:
    """Validate a step's ``observers`` list references known channels."""
    raw_observers = raw_step.get("observers")
    if raw_observers is None:
        return
    if not isinstance(raw_observers, list) or any(
        not isinstance(item, str) or not item for item in raw_observers
    ):
        raise ValueError(
            f"Workflow step {step_name!r} has invalid 'observers' "
            "(must be a list of channel names)."
        )
    unknown = sorted(set(raw_observers) - set(KNOWN_OBSERVERS))
    if unknown:
        raise ValueError(
            f"Workflow step {step_name!r} references unknown observers "
            f"{unknown}. Known observers: {list(KNOWN_OBSERVERS)}."
        )


def _validate_step(index: int, raw_step: Any, seen_step_names: set[str]) -> None:
    """Validate a single raw step mapping, tracking seen names for dup detection."""
    if not isinstance(raw_step, dict):
        raise ValueError(f"Workflow step #{index} must be a mapping.")
    step_name = raw_step.get("name")
    if not isinstance(step_name, str) or not step_name.strip():
        raise ValueError(f"Workflow step #{index} is missing required 'name'.")
    if step_name in seen_step_names:
        raise ValueError(f"Workflow step name {step_name!r} is duplicated.")
    seen_step_names.add(step_name)

    _validate_step_depends_on(step_name, raw_step)
    _validate_step_mappings(step_name, raw_step)
    _validate_step_model_params(step_name, raw_step)
    _validate_step_observers(step_name, raw_step)


def _validate_steps(document: dict[str, Any]) -> None:
    """Validate the document's ``steps`` list and each step within it."""
    raw_steps = document.get("steps")
    if not isinstance(raw_steps, list) or not raw_steps:
        raise ValueError("Workflow document must define a non-empty 'steps' list.")

    seen_step_names: set[str] = set()
    for index, raw_step in enumerate(raw_steps):
        _validate_step(index, raw_step, seen_step_names)


def validate_workflow_document(
    document: dict[str, Any],
    *,
    expected_name: str | None = None,
) -> WorkflowConfig:
    """Validate a raw workflow document and return the parsed config."""
    if not isinstance(document, dict):
        raise ValueError("Workflow document must be a mapping.")

    default_name = _validate_document_name(document, expected_name)
    _validate_steps(document)

    config = _parse(document, default_name)
    return config


def validate_workflow_inputs(
    config: WorkflowConfig,
    supplied: dict[str, Any],
) -> dict[str, Any]:
    """Validate supplied workflow inputs and apply declared defaults.

    Returns a new dict of validated inputs; raises ``ValueError`` listing every
    violation (missing/empty required inputs, enum mismatches) so callers can
    reject a run before it starts.
    """
    result: dict[str, Any] = {}
    errors: list[str] = []

    for name, input_cfg in config.inputs.items():
        if name in supplied:
            value = supplied[name]
            # Treat None or a blank string as missing for required inputs
            if input_cfg.required and (
                value is None or (isinstance(value, str) and not value.strip())
            ):
                errors.append(f"Required input '{name}' must not be empty")
                continue
            if input_cfg.enum and value not in input_cfg.enum:
                errors.append(
                    f"Input '{name}' must be one of {input_cfg.enum}, got '{value}'"
                )
            result[name] = value
        elif input_cfg.default is not None:
            result[name] = input_cfg.default
        elif input_cfg.required:
            errors.append(f"Missing required input: '{name}'")

    if errors:
        raise ValueError(
            f"Input validation failed for '{config.name}': " + "; ".join(errors)
        )

    return result


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
        or not re.fullmatch(r"[\w.-]+", name, flags=re.ASCII)
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
        input_ref = re.fullmatch(r"\$\{\s*inputs\.([A-Za-z_][\w]*)\s*\}", stripped)
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


def _parse_inputs(data: dict[str, Any]) -> dict[str, InputConfig]:
    """Parse the workflow ``inputs`` mapping into ``InputConfig`` objects."""
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
    return inputs


def _coerce_optional_float(value: Any, *, field_name: str) -> float | None:
    """Coerce an optional YAML scalar to float, dropping invalid values.

    The editor/save path rejects invalid params up front
    (:func:`_validate_step_model_params`); this parse path tolerates
    hand-edited files by logging and falling back to the provider default
    instead of failing the whole workflow load.
    """
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        logger.warning("Ignoring invalid model_params.%s=%r", field_name, value)
        return None


def _coerce_optional_int(value: Any, *, field_name: str) -> int | None:
    """Coerce an optional YAML scalar to int, dropping invalid values."""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        logger.warning("Ignoring invalid model_params.%s=%r", field_name, value)
        return None


def _parse_model_params(raw: Any) -> ModelParamsConfig | None:
    """Parse a raw ``model_params`` mapping into a ``ModelParamsConfig``."""
    if not isinstance(raw, dict):
        return None
    temperature = _coerce_optional_float(
        raw.get("temperature"), field_name="temperature"
    )
    top_p = _coerce_optional_float(raw.get("top_p"), field_name="top_p")
    max_tokens = _coerce_optional_int(raw.get("max_tokens"), field_name="max_tokens")
    if temperature is None and top_p is None and max_tokens is None:
        return None
    return ModelParamsConfig(
        temperature=temperature,
        top_p=top_p,
        max_tokens=max_tokens,
    )


def _parse_step(raw: dict[str, Any], inputs: dict[str, InputConfig]) -> StepConfig:
    """Parse a single raw step mapping into a ``StepConfig``."""
    loop_max, loop_max_expr = _parse_loop_max(raw.get("loop_max", 3), inputs)
    step_inputs = dict(raw.get("inputs", {}))
    step_outputs = dict(raw.get("outputs", {}))
    input_contracts = parse_artifact_contracts(
        raw.get("input_contracts"),
        location=f"steps.{raw['name']}.input_contracts",
    )
    output_contracts = parse_artifact_contracts(
        raw.get("output_contracts"),
        location=f"steps.{raw['name']}.output_contracts",
    )
    validate_contract_bindings(
        input_contracts,
        step_inputs,
        location=f"steps.{raw['name']}.input_contracts",
    )
    validate_contract_bindings(
        output_contracts,
        step_outputs,
        location=f"steps.{raw['name']}.output_contracts",
    )
    return StepConfig(
        name=raw["name"],
        agent=raw.get("agent", ""),
        description=raw.get("description", ""),
        depends_on=raw.get("depends_on", []),
        inputs=step_inputs,
        outputs=step_outputs,
        input_contracts=input_contracts,
        output_contracts=output_contracts,
        when=raw.get("when"),
        loop_until=raw.get("loop_until"),
        loop_max=loop_max,
        loop_max_expr=loop_max_expr,
        tools=(raw.get("tools") if isinstance(raw.get("tools"), list) else None),
        prompt_file=raw.get("prompt_file"),
        model_override=(
            raw.get("model_override")
            if isinstance(raw.get("model_override"), str)
            else raw.get("model")
        ),
        persona=(raw.get("persona") if isinstance(raw.get("persona"), str) else None),
        observers=(
            [str(o) for o in raw.get("observers")]
            if isinstance(raw.get("observers"), list)
            else None
        ),
        model_params=_parse_model_params(raw.get("model_params")),
    )


def _parse_steps(
    data: dict[str, Any], inputs: dict[str, InputConfig]
) -> list[StepConfig]:
    """Parse the workflow ``steps`` list into ``StepConfig`` objects."""
    steps: list[StepConfig] = []
    for raw in data.get("steps", []):
        if not isinstance(raw, dict) or "name" not in raw:
            continue
        steps.append(_parse_step(raw, inputs))
    return steps


def _parse_outputs(data: dict[str, Any]) -> dict[str, OutputConfig]:
    """Parse the workflow ``outputs`` mapping into ``OutputConfig`` objects."""
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
    return outputs


def _parse_criterion(c: dict[str, Any]) -> CriterionConfig:
    """Parse a single evaluation criterion mapping into a ``CriterionConfig``."""
    return CriterionConfig(
        name=c["name"],
        definition=c.get("definition", ""),
        weight=float(c["weight"]) if c.get("weight") else None,
        critical_floor=(
            float(c["critical_floor"]) if c.get("critical_floor") is not None else None
        ),
        scale={str(sk): str(sv) for sk, sv in (c.get("scale") or {}).items()},
        evidence_required=c.get("evidence_required", []),
        formula_id=c.get("formula_id", "zero_one"),
    )


def _parse_evaluation(data: dict[str, Any]) -> EvaluationConfig | None:
    """Parse the workflow ``evaluation`` mapping into an ``EvaluationConfig``."""
    raw_eval = data.get("evaluation")
    if not isinstance(raw_eval, dict):
        return None
    criteria = [
        _parse_criterion(c)
        for c in raw_eval.get("criteria", [])
        if isinstance(c, dict) and c.get("name")
    ]
    return EvaluationConfig(
        rubric_id=raw_eval.get("rubric_id"),
        scoring_profile=raw_eval.get("scoring_profile"),
        weights=raw_eval.get("weights"),
        criteria=criteria,
    )


def _parse_capabilities(data: dict[str, Any]) -> dict[str, list[str]]:
    """Parse the workflow ``capabilities`` mapping into lists of strings."""
    capabilities: dict[str, list[str]] = {}
    raw_cap = data.get("capabilities")
    if isinstance(raw_cap, dict):
        for ck, cv in raw_cap.items():
            if isinstance(cv, list):
                capabilities[ck] = [str(i) for i in cv]
    return capabilities


def _parse(data: dict[str, Any], default_name: str) -> WorkflowConfig:
    inputs = _parse_inputs(data)
    steps = _parse_steps(data, inputs)
    outputs = _parse_outputs(data)
    evaluation = _parse_evaluation(data)
    capabilities = _parse_capabilities(data)

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
