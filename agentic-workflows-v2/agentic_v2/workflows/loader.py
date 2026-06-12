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

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

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
            raise WorkflowLoadError(f"Invalid YAML in {path}: {e}") from e

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

        inputs = self._parse_inputs(data.get("inputs", {}))
        outputs = self._parse_outputs(data.get("outputs", {}))
        capabilities = self._parse_capabilities(data.get("capabilities"))
        workflow_evaluation = self._parse_evaluation(data.get("evaluation"), name)
        dag = self._build_dag(data, name, description, experimental)

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
    def _parse_inputs(raw_inputs: dict[str, Any]) -> dict[str, WorkflowInput]:
        """Parse the ``inputs`` block into WorkflowInput objects."""
        inputs: dict[str, WorkflowInput] = {}
        for input_name, input_def in raw_inputs.items():
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
        return inputs

    @staticmethod
    def _parse_outputs(raw_outputs: dict[str, Any]) -> dict[str, WorkflowOutput]:
        """Parse the ``outputs`` block into WorkflowOutput objects."""
        outputs: dict[str, WorkflowOutput] = {}
        for output_name, output_def in raw_outputs.items():
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
        return outputs

    @staticmethod
    def _parse_capabilities(raw_capabilities: Any) -> WorkflowCapabilities:
        """Parse the ``capabilities`` block for compatibility checks."""
        capabilities = WorkflowCapabilities()
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
        return capabilities

    def _parse_evaluation(
        self, raw_evaluation: Any, name: str
    ) -> WorkflowEvaluation | None:
        """Parse the optional workflow-level ``evaluation`` block."""
        if raw_evaluation is None:
            return None
        if not isinstance(raw_evaluation, dict):
            raise WorkflowLoadError(
                f"Workflow '{name}' has invalid 'evaluation' block (expected mapping)."
            )

        rubric_id = raw_evaluation.get("rubric_id")
        scoring_profile = raw_evaluation.get("scoring_profile")
        weights_raw = raw_evaluation.get("weights")
        criteria_raw = raw_evaluation.get("criteria")

        criteria = self._parse_criteria(criteria_raw, name)
        weights = self._parse_weights(weights_raw, name)
        if weights is None and criteria:
            weights = self._derive_weights_from_criteria(criteria, name)

        return WorkflowEvaluation(
            rubric_id=str(rubric_id) if rubric_id is not None else None,
            weights=weights,
            scoring_profile=(
                str(scoring_profile) if scoring_profile is not None else None
            ),
            criteria=criteria,
        )

    def _parse_criteria(
        self, criteria_raw: Any, name: str
    ) -> list[WorkflowCriterion]:
        """Parse the ``evaluation.criteria`` list into WorkflowCriterion objects."""
        criteria: list[WorkflowCriterion] = []
        if criteria_raw is None:
            return criteria
        if not isinstance(criteria_raw, list):
            raise WorkflowLoadError(
                f"Workflow '{name}' has invalid evaluation.criteria (expected list)."
            )
        for index, criterion_raw in enumerate(criteria_raw):
            criteria.append(self._parse_criterion(criterion_raw, index, name))
        return criteria

    def _parse_criterion(
        self, criterion_raw: Any, index: int, name: str
    ) -> WorkflowCriterion:
        """Parse and validate a single evaluation criterion."""
        if not isinstance(criterion_raw, dict):
            raise WorkflowLoadError(
                f"Workflow '{name}' criterion #{index} is not a mapping."
            )
        criterion_name = criterion_raw.get("name")
        if not criterion_name:
            raise WorkflowLoadError(
                f"Workflow '{name}' criterion #{index} missing required 'name'."
            )

        evidence_required = self._parse_evidence_required(
            criterion_raw.get("evidence_required", []), criterion_name, name
        )
        scale_map = self._parse_scale(
            criterion_raw.get("scale", {}), criterion_name, name
        )
        formula_id = self._parse_formula_id(
            criterion_raw.get("formula_id", "zero_one"), criterion_name, name
        )
        parsed_weight = self._parse_criterion_weight(
            criterion_raw.get("weight"), criterion_name, name
        )
        parsed_floor = self._parse_critical_floor(
            criterion_raw.get("critical_floor"), criterion_name, name
        )

        return WorkflowCriterion(
            name=str(criterion_name),
            definition=str(criterion_raw.get("definition", "")),
            evidence_required=evidence_required,
            scale=scale_map,
            weight=parsed_weight,
            critical_floor=parsed_floor,
            formula_id=formula_id,
        )

    @staticmethod
    def _parse_evidence_required(
        evidence_required: Any, criterion_name: Any, name: str
    ) -> list[str]:
        """Validate and normalize a criterion's ``evidence_required`` list."""
        if evidence_required is None:
            evidence_required = []
        if not isinstance(evidence_required, list):
            raise WorkflowLoadError(
                f"Workflow '{name}' criterion '{criterion_name}' has invalid evidence_required."
            )
        return [str(item) for item in evidence_required]

    @staticmethod
    def _parse_scale(scale: Any, criterion_name: Any, name: str) -> dict[str, str]:
        """Validate and normalize a criterion's anchored ``scale`` mapping."""
        if scale is None:
            scale = {}
        if not isinstance(scale, dict) or not scale:
            raise WorkflowLoadError(
                f"Workflow '{name}' criterion '{criterion_name}' must define anchored scale mapping."
            )
        return {str(k): str(v) for k, v in scale.items()}

    @staticmethod
    def _parse_formula_id(formula_raw: Any, criterion_name: Any, name: str) -> str:
        """Validate a criterion's ``formula_id`` against the registry."""
        formula_id = str(formula_raw)
        from ..evaluation.normalization import is_registered_formula

        if not is_registered_formula(formula_id):
            raise WorkflowLoadError(
                f"Workflow '{name}' criterion '{criterion_name}' uses unknown formula_id '{formula_id}'."
            )
        return formula_id

    @staticmethod
    def _parse_criterion_weight(
        weight_value: Any, criterion_name: Any, name: str
    ) -> float | None:
        """Validate and coerce a criterion's optional ``weight``."""
        if weight_value is None:
            return None
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
        return parsed_weight

    @staticmethod
    def _parse_critical_floor(
        critical_floor: Any, criterion_name: Any, name: str
    ) -> float | None:
        """Validate and coerce a criterion's optional ``critical_floor``."""
        if critical_floor is None:
            return None
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
        return parsed_floor

    @staticmethod
    def _parse_weights(weights_raw: Any, name: str) -> dict[str, float] | None:
        """Validate and normalize the ``evaluation.weights`` mapping."""
        if weights_raw is None:
            return None
        if not isinstance(weights_raw, dict):
            raise WorkflowLoadError(
                f"Workflow '{name}' has invalid evaluation.weights (expected mapping)."
            )
        weights: dict[str, float] = {}
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
        return weights

    @staticmethod
    def _derive_weights_from_criteria(
        criteria: list[WorkflowCriterion], name: str
    ) -> dict[str, float] | None:
        """Derive evaluation weights from per-criterion weights when present."""
        derived_weights = {
            criterion.name: criterion.weight
            for criterion in criteria
            if criterion.weight is not None
        }
        if not derived_weights:
            return None
        total = sum(derived_weights.values())
        if abs(total - 1.0) > 0.01:
            raise WorkflowLoadError(
                f"Workflow '{name}' criterion weights must sum to 1.0 (+/-0.01), got {total:.4f}."
            )
        return {k: float(v) for k, v in derived_weights.items()}

    def _build_dag(
        self,
        data: dict[str, Any],
        name: str,
        description: str,
        experimental: bool,
    ) -> DAG:
        """Parse steps into a DAG, handling nested/experimental fallbacks."""
        dag = DAG(name=name, description=description)

        for step_data in data.get("steps", []):
            step = self._parse_step(step_data)
            resolve_agent(step)  # Bind executable func from agent metadata
            dag.add(step)

        if len(dag.steps) == 0:
            self._handle_empty_dag(dag, data, name, experimental)

        return dag

    def _handle_empty_dag(
        self,
        dag: DAG,
        data: dict[str, Any],
        name: str,
        experimental: bool,
    ) -> None:
        """Resolve an empty DAG via nested steps or experimental placeholders."""
        # Check if steps exist under a nested key (e.g., workflow.steps)
        nested_steps = data.get("workflow", {})
        if isinstance(nested_steps, dict) and nested_steps.get("steps"):
            if experimental:
                # Experimental definitions may use non-runtime schemas.
                # Best-effort load only runtime-compatible steps.
                self._load_experimental_nested_steps(dag, nested_steps)
            else:
                raise WorkflowLoadError(
                    f"Workflow '{name}' has steps nested under 'workflow.steps' "
                    f"instead of top-level 'steps'. Restructure the YAML."
                )
        if experimental:
            # Keep experimental definitions loadable for inspection/testing
            # even when they are not yet runnable in the stable DAG format.
            if len(dag.steps) == 0:
                self._add_experimental_placeholder(dag)
        else:
            raise WorkflowLoadError(f"Workflow '{name}' has no executable steps.")

    def _load_experimental_nested_steps(
        self, dag: DAG, nested_steps: dict[str, Any]
    ) -> None:
        """Best-effort load of runtime-compatible steps from a nested block."""
        for step_data in nested_steps.get("steps", []):
            if not isinstance(step_data, dict):
                continue
            if "name" not in step_data or "agent" not in step_data:
                continue
            try:
                step = self._parse_step(step_data)
                resolve_agent(step)
                dag.add(step)
            except Exception as exc:
                logger.debug("Skipping invalid DAG step %r: %s", step_data.get("name"), exc)
                continue

    @staticmethod
    def _add_experimental_placeholder(dag: DAG) -> None:
        """Add a placeholder step so an experimental workflow stays loadable."""
        placeholder = StepDefinition(
            name="experimental_placeholder",
            description="Placeholder step for experimental workflow",
            metadata={"agent": "tier0_parser"},
        )
        resolve_agent(placeholder)
        dag.add(placeholder)

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

        input_mapping = self._parse_step_input_mapping(data.get("inputs", {}))
        output_mapping = self._parse_step_output_mapping(data.get("outputs", {}))
        when_func = self._build_when_condition(data.get("when"))
        loop_max, loop_max_expr = self._parse_loop_max(data.get("loop_max", 3))

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
                "when_expr": data.get("when"),
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

    @staticmethod
    def _parse_step_input_mapping(raw_inputs: Any) -> dict[str, Any]:
        """Build a step's input mapping from its ``inputs`` block."""
        input_mapping: dict[str, Any] = {}
        if isinstance(raw_inputs, dict):
            for key, value in raw_inputs.items():
                input_mapping[key] = value
        return input_mapping

    @staticmethod
    def _parse_step_output_mapping(raw_outputs: Any) -> dict[str, str]:
        """Build a step's output mapping from its ``outputs`` block."""
        output_mapping: dict[str, str] = {}
        if isinstance(raw_outputs, dict):
            for key, value in raw_outputs.items():
                if isinstance(value, str):
                    output_mapping[key] = value
        return output_mapping

    @staticmethod
    def _build_when_condition(when_expr: Any):
        """Compile a ``when`` expression string into a runtime predicate."""
        if not when_expr:
            return None

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

        return _make_condition(raw_expr)

    @staticmethod
    def _parse_loop_max(loop_max_raw: Any) -> tuple[int, str | None]:
        """Resolve ``loop_max`` to a positive int or a deferred expression.

        Values may be a literal int/str OR a ``${...}`` expression that will be
        evaluated at run-time.  Expressions are stored as-is and resolved by the
        executor; literals are coerced immediately.

        Returns:
            Tuple of (loop_max, loop_max_expr). When a runtime expression is
            given, loop_max is the sentinel 0 and loop_max_expr holds the
            expression string.
        """
        if isinstance(loop_max_raw, str) and loop_max_raw.strip().startswith("${"):
            # Runtime expression — defer resolution; store sentinel 0 as a
            # signal for the executor to evaluate and clamp to >= 1.
            return 0, loop_max_raw.strip()
        try:
            return max(1, int(loop_max_raw)), None
        except (TypeError, ValueError):
            return 3, None


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
