"""Workflow loader — YAML definitions to executable DAG objects.

Reads YAML files from ``workflows/definitions/`` and produces
:class:`WorkflowDefinition` objects containing a validated :class:`DAG`,
typed input/output declarations, capability metadata, and optional
evaluation configuration.

The loader also resolves each step's ``agent`` field into an executable
function via :func:`resolve_agent`, which maps ``tier{N}_{role}`` names
to either deterministic Tier-0 implementations or LLM-backed step
functions.

Supports caching, ``experimental`` flag for draft workflows, and
``capabilities`` metadata for dataset-workflow compatibility matching.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from ..engine.agent_resolver import resolve_agent
from ..engine.dag import DAG
from ..engine.step import StepDefinition


@dataclass
class WorkflowInput:
    """Input parameter definition for a workflow."""

    name: str
    type: str = "string"
    description: str = ""
    default: Any = None
    required: bool = True
    enum: list[str] | None = None


@dataclass
class WorkflowOutput:
    """Output definition for a workflow."""

    name: str
    from_expr: Any
    optional: bool = False


@dataclass
class WorkflowDefinition:
    """Parsed workflow definition from YAML."""

    name: str
    description: str = ""
    version: str = "1.0"
    inputs: dict[str, WorkflowInput] = field(default_factory=dict)
    outputs: dict[str, WorkflowOutput] = field(default_factory=dict)
    capabilities: "WorkflowCapabilities" = field(
        default_factory=lambda: WorkflowCapabilities()
    )
    evaluation: "WorkflowEvaluation | None" = None
    experimental: bool = False
    dag: DAG = field(default_factory=lambda: DAG(name="unnamed"))


@dataclass
class WorkflowCapabilities:
    """Workflow capabilities used for dataset/workflow compatibility checks."""

    inputs: list[str] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)


@dataclass
class WorkflowEvaluation:
    """Workflow-local scoring configuration."""

    rubric_id: str | None = None
    weights: dict[str, float] | None = None
    scoring_profile: str | None = None
    criteria: list["WorkflowCriterion"] = field(default_factory=list)


@dataclass
class WorkflowCriterion:
    """Workflow-local criterion definition."""

    name: str
    definition: str = ""
    evidence_required: list[str] = field(default_factory=list)
    scale: dict[str, str] = field(default_factory=dict)
    weight: float | None = None
    critical_floor: float | None = None
    formula_id: str = "zero_one"


class WorkflowLoadError(Exception):
    """Raised when workflow loading fails."""

    pass


class WorkflowLoader:
    """Load workflow definitions from YAML files.

    Usage:
        loader = WorkflowLoader()
        workflow = loader.load("code_review")
        dag = workflow.dag
    """

    def __init__(self, definitions_dir: Path | None = None):
        """Initialize the loader.

        Args:
            definitions_dir: Directory containing workflow YAML files.
                           Defaults to workflows/definitions/ in package.
        """
        if definitions_dir is None:
            # Default to package definitions directory
            definitions_dir = Path(__file__).parent / "definitions"
        self.definitions_dir = Path(definitions_dir)
        self._cache: dict[str, WorkflowDefinition] = {}

    def load(self, name: str, use_cache: bool = True) -> WorkflowDefinition:
        """Load a workflow by name.

        Args:
            name: Workflow name (without .yaml extension)
            use_cache: Whether to use cached definition

        Returns:
            Parsed WorkflowDefinition

        Raises:
            WorkflowLoadError: If workflow cannot be loaded
        """
        if use_cache and name in self._cache:
            return self._cache[name]

        # Find the YAML file
        yaml_path = self.definitions_dir / f"{name}.yaml"
        if not yaml_path.exists():
            yaml_path = self.definitions_dir / f"{name}.yml"

        if not yaml_path.exists():
            available = self.list_workflows()
            raise WorkflowLoadError(
                f"Workflow '{name}' not found in {self.definitions_dir}. "
                f"Available: {available}"
            )

        workflow = self._parse_file(yaml_path)

        if use_cache:
            self._cache[name] = workflow

        return workflow

    def load_file(self, path: Path) -> WorkflowDefinition:
        """Load a workflow from a specific file path."""
        if not path.exists():
            raise WorkflowLoadError(f"Workflow file not found: {path}")
        return self._parse_file(path)

    def list_workflows(self, include_experimental: bool = False) -> list[str]:
        """List all available workflow names."""
        if not self.definitions_dir.exists():
            return []

        workflows = []
        for path in self.definitions_dir.iterdir():
            if path.suffix in (".yaml", ".yml"):
                if not include_experimental and self._is_experimental_definition(path):
                    continue
                workflows.append(path.stem)
        return sorted(workflows)

    def clear_cache(self) -> None:
        """Clear the workflow cache."""
        self._cache.clear()

    def _parse_file(self, path: Path) -> WorkflowDefinition:
        """Parse a YAML workflow file."""
        try:
            with open(path, encoding="utf-8") as f:
                data = yaml.safe_load(f)
        except yaml.YAMLError as e:
            raise WorkflowLoadError(f"Invalid YAML in {path}: {e}")

        if not isinstance(data, dict):
            raise WorkflowLoadError(f"Workflow must be a YAML mapping: {path}")

        return self._parse_definition(data, path.stem)

    def _parse_definition(
        self, data: dict[str, Any], default_name: str
    ) -> WorkflowDefinition:
        """Parse workflow definition from dict."""
        name = data.get("name", default_name)
        description = data.get("description", "")
        version = data.get("version", "1.0")
        experimental = bool(data.get("experimental", False))

        # Parse inputs
        inputs = {}
        for input_name, input_def in data.get("inputs", {}).items():
            if isinstance(input_def, dict):
                inputs[input_name] = WorkflowInput(
                    name=input_name,
                    type=input_def.get("type", "string"),
                    description=input_def.get("description", ""),
                    default=input_def.get("default"),
                    required=input_def.get("required", True),
                    enum=input_def.get("enum"),
                )
            else:
                # Simple value is the default
                inputs[input_name] = WorkflowInput(
                    name=input_name,
                    default=input_def,
                    required=False,
                )

        # Parse outputs
        outputs = {}
        for output_name, output_def in data.get("outputs", {}).items():
            if isinstance(output_def, dict):
                outputs[output_name] = WorkflowOutput(
                    name=output_name,
                    from_expr=output_def.get("from", ""),
                    optional=output_def.get("optional", False),
                )
            else:
                outputs[output_name] = WorkflowOutput(
                    name=output_name,
                    from_expr=output_def,
                )

        # Parse capabilities for workflow/dataset compatibility checks
        capabilities = WorkflowCapabilities()
        raw_capabilities = data.get("capabilities")
        if isinstance(raw_capabilities, dict):
            raw_inputs = raw_capabilities.get("inputs", [])
            raw_outputs = raw_capabilities.get("outputs", [])

            if isinstance(raw_inputs, list):
                capabilities.inputs = [
                    str(item) for item in raw_inputs if str(item).strip()
                ]
            if isinstance(raw_outputs, list):
                capabilities.outputs = [
                    str(item) for item in raw_outputs if str(item).strip()
                ]

        # Parse optional workflow-level evaluation config
        workflow_evaluation: WorkflowEvaluation | None = None
        raw_evaluation = data.get("evaluation")
        if raw_evaluation is not None:
            if not isinstance(raw_evaluation, dict):
                raise WorkflowLoadError(
                    f"Workflow '{name}' has invalid 'evaluation' block (expected mapping)."
                )

            rubric_id = raw_evaluation.get("rubric_id")
            scoring_profile = raw_evaluation.get("scoring_profile")
            weights_raw = raw_evaluation.get("weights")
            weights: dict[str, float] | None = None
            criteria_raw = raw_evaluation.get("criteria")
            criteria: list[WorkflowCriterion] = []

            if criteria_raw is not None:
                if not isinstance(criteria_raw, list):
                    raise WorkflowLoadError(
                        f"Workflow '{name}' has invalid evaluation.criteria (expected list)."
                    )
                for index, criterion_raw in enumerate(criteria_raw):
                    if not isinstance(criterion_raw, dict):
                        raise WorkflowLoadError(
                            f"Workflow '{name}' criterion #{index} is not a mapping."
                        )
                    criterion_name = criterion_raw.get("name")
                    if not criterion_name:
                        raise WorkflowLoadError(
                            f"Workflow '{name}' criterion #{index} missing required 'name'."
                        )

                    evidence_required = criterion_raw.get("evidence_required", [])
                    if evidence_required is None:
                        evidence_required = []
                    if not isinstance(evidence_required, list):
                        raise WorkflowLoadError(
                            f"Workflow '{name}' criterion '{criterion_name}' has invalid evidence_required."
                        )
                    evidence_required = [str(item) for item in evidence_required]

                    scale = criterion_raw.get("scale", {})
                    if scale is None:
                        scale = {}
                    if not isinstance(scale, dict) or not scale:
                        raise WorkflowLoadError(
                            f"Workflow '{name}' criterion '{criterion_name}' must define anchored scale mapping."
                        )
                    scale_map = {str(k): str(v) for k, v in scale.items()}

                    formula_id = str(criterion_raw.get("formula_id", "zero_one"))
                    from ..evaluation.normalization import is_registered_formula

                    if not is_registered_formula(formula_id):
                        raise WorkflowLoadError(
                            f"Workflow '{name}' criterion '{criterion_name}' uses unknown formula_id '{formula_id}'."
                        )

                    weight_value = criterion_raw.get("weight")
                    parsed_weight: float | None = None
                    if weight_value is not None:
                        try:
                            parsed_weight = float(weight_value)
                        except (TypeError, ValueError) as exc:
                            raise WorkflowLoadError(
                                f"Workflow '{name}' criterion '{criterion_name}' has non-numeric weight."
                            ) from exc
                        if parsed_weight <= 0:
                            raise WorkflowLoadError(
                                f"Workflow '{name}' criterion '{criterion_name}' must have positive weight."
                            )

                    critical_floor = criterion_raw.get("critical_floor")
                    parsed_floor: float | None = None
                    if critical_floor is not None:
                        try:
                            parsed_floor = float(critical_floor)
                        except (TypeError, ValueError) as exc:
                            raise WorkflowLoadError(
                                f"Workflow '{name}' criterion '{criterion_name}' has non-numeric critical_floor."
                            ) from exc
                        if not (0.0 <= parsed_floor <= 1.0):
                            raise WorkflowLoadError(
                                f"Workflow '{name}' criterion '{criterion_name}' critical_floor must be in [0,1]."
                            )

                    criteria.append(
                        WorkflowCriterion(
                            name=str(criterion_name),
                            definition=str(criterion_raw.get("definition", "")),
                            evidence_required=evidence_required,
                            scale=scale_map,
                            weight=parsed_weight,
                            critical_floor=parsed_floor,
                            formula_id=formula_id,
                        )
                    )

            if weights_raw is not None:
                if not isinstance(weights_raw, dict):
                    raise WorkflowLoadError(
                        f"Workflow '{name}' has invalid evaluation.weights (expected mapping)."
                    )
                weights = {}
                for key, value in weights_raw.items():
                    try:
                        weight = float(value)
                    except (TypeError, ValueError) as exc:
                        raise WorkflowLoadError(
                            f"Workflow '{name}' has non-numeric weight for '{key}'."
                        ) from exc
                    if weight <= 0:
                        raise WorkflowLoadError(
                            f"Workflow '{name}' has non-positive weight for '{key}'."
                        )
                    weights[str(key)] = weight

                total = sum(weights.values())
                if abs(total - 1.0) > 0.01:
                    raise WorkflowLoadError(
                        f"Workflow '{name}' evaluation.weights must sum to 1.0 (+/-0.01), got {total:.4f}."
                    )

            if weights is None and criteria:
                derived_weights = {
                    criterion.name: criterion.weight
                    for criterion in criteria
                    if criterion.weight is not None
                }
                if derived_weights:
                    total = sum(derived_weights.values())
                    if abs(total - 1.0) > 0.01:
                        raise WorkflowLoadError(
                            f"Workflow '{name}' criterion weights must sum to 1.0 (+/-0.01), got {total:.4f}."
                        )
                    weights = {k: float(v) for k, v in derived_weights.items()}

            workflow_evaluation = WorkflowEvaluation(
                rubric_id=str(rubric_id) if rubric_id is not None else None,
                weights=weights,
                scoring_profile=(
                    str(scoring_profile) if scoring_profile is not None else None
                ),
                criteria=criteria,
            )

        # Parse steps into DAG
        dag = DAG(name=name, description=description)

        for step_data in data.get("steps", []):
            step = self._parse_step(step_data)
            resolve_agent(step)  # Bind executable func from agent metadata
            dag.add(step)

        if len(dag.steps) == 0:
            # Check if steps exist under a nested key (e.g., workflow.steps)
            nested_steps = data.get("workflow", {})
            if isinstance(nested_steps, dict) and nested_steps.get("steps"):
                if experimental:
                    # Experimental definitions may use non-runtime schemas.
                    # Best-effort load only runtime-compatible steps.
                    for step_data in nested_steps.get("steps", []):
                        if not isinstance(step_data, dict):
                            continue
                        if "name" not in step_data or "agent" not in step_data:
                            continue
                        try:
                            step = self._parse_step(step_data)
                            resolve_agent(step)
                            dag.add(step)
                        except Exception:
                            continue
                else:
                    raise WorkflowLoadError(
                        f"Workflow '{name}' has steps nested under 'workflow.steps' "
                        f"instead of top-level 'steps'. Restructure the YAML."
                    )
            if experimental:
                # Keep experimental definitions loadable for inspection/testing
                # even when they are not yet runnable in the stable DAG format.
                if len(dag.steps) == 0:
                    placeholder = StepDefinition(
                        name="experimental_placeholder",
                        description="Placeholder step for experimental workflow",
                        metadata={"agent": "tier0_parser"},
                    )
                    resolve_agent(placeholder)
                    dag.add(placeholder)
            else:
                raise WorkflowLoadError(f"Workflow '{name}' has no executable steps.")

        return WorkflowDefinition(
            name=name,
            description=description,
            version=version,
            inputs=inputs,
            outputs=outputs,
            capabilities=capabilities,
            evaluation=workflow_evaluation,
            experimental=experimental,
            dag=dag,
        )

    @staticmethod
    def _is_experimental_definition(path: Path) -> bool:
        """Return True when a workflow definition is marked experimental."""
        try:
            with open(path, encoding="utf-8") as f:
                data = yaml.safe_load(f)
            return isinstance(data, dict) and bool(data.get("experimental", False))
        except Exception:
            # If we cannot parse, keep it visible rather than hiding by accident.
            return False

    def _parse_step(self, data: dict[str, Any]) -> StepDefinition:
        """Parse a step definition from dict."""
        name = data.get("name")
        if not name:
            raise WorkflowLoadError("Step must have a 'name' field")

        # Build input/output mappings
        input_mapping = {}
        raw_inputs = data.get("inputs", {})
        if isinstance(raw_inputs, dict):
            for key, value in raw_inputs.items():
                input_mapping[key] = value

        output_mapping = {}
        raw_outputs = data.get("outputs", {})
        if isinstance(raw_outputs, dict):
            for key, value in raw_outputs.items():
                if isinstance(value, str):
                    output_mapping[key] = value

        # Parse 'when' condition as string expression
        when_expr = data.get("when")
        when_func = None
        if when_expr:
            # Create a callable condition from the expression string.
            # The ExpressionEvaluator is instantiated at runtime with the live
            # ExecutionContext so that ${...} references are resolved.
            raw_expr = when_expr

            def _make_condition(expr: str):
                def _condition(ctx) -> bool:
                    from ..engine.expressions import ExpressionEvaluator

                    evaluator = ExpressionEvaluator(ctx, {})
                    return evaluator.evaluate(expr)

                return _condition

            when_func = _make_condition(raw_expr)

        # Parse loop_max — must resolve to a positive integer.
        # Values may be a literal int/str OR a ${...} expression that will be
        # evaluated at run-time.  Expressions are stored as-is and resolved by
        # the executor; literals are coerced immediately.
        loop_max_raw = data.get("loop_max", 3)
        loop_max_expr: str | None = None
        if isinstance(loop_max_raw, str) and loop_max_raw.strip().startswith("${"):
            # Runtime expression — defer resolution; store sentinel 0 as a
            # signal for the executor to evaluate and clamp to >= 1.
            loop_max = 0
            loop_max_expr = loop_max_raw.strip()
        else:
            try:
                loop_max = max(1, int(loop_max_raw))
            except (TypeError, ValueError):
                loop_max = 3

        return StepDefinition(
            name=name,
            description=data.get("description", ""),
            depends_on=data.get("depends_on", []),
            when=when_func,
            input_mapping=input_mapping,
            output_mapping=output_mapping,
            loop_until=data.get("loop_until") or None,
            loop_max=loop_max,
            metadata={
                "agent": data.get("agent"),
                "when_expr": when_expr,
                # When loop_max was a ${...} expression, store it so the
                # executor can resolve it at runtime (loop_max==0 is the signal).
                "loop_max_expr": loop_max_expr,
                # Optional: override the agent persona prompt file, e.g.
                #   prompt_file: coder.md
                # Must be a filename relative to prompts/ directory.
                "prompt_file": data.get("prompt_file") or None,
                # Optional tool filter for this step:
                # - omitted/None => all tools allowed for the step's tier
                # - [] => no tools
                # - ["file_read", "search"] => only those tool names
                "tools": (
                    data.get("tools") if isinstance(data.get("tools"), list) else None
                ),
                "model_override": (
                    data.get("model_override")
                    if isinstance(data.get("model_override"), str)
                    else data.get("model")
                ),
            },
        )


def load_workflow(name: str, definitions_dir: Path | None = None) -> WorkflowDefinition:
    """Convenience function to load a workflow.

    Args:
        name: Workflow name
        definitions_dir: Optional custom definitions directory

    Returns:
        Parsed WorkflowDefinition
    """
    loader = WorkflowLoader(definitions_dir=definitions_dir)
    return loader.load(name)


def get_dag(name: str, definitions_dir: Path | None = None) -> DAG:
    """Convenience function to get just the DAG from a workflow.

    Args:
        name: Workflow name
        definitions_dir: Optional custom definitions directory

    Returns:
        The workflow's DAG
    """
    return load_workflow(name, definitions_dir).dag
