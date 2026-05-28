"""Directed Acyclic Graph (DAG) workflow definition.

Provides:
- Step registration
- Dependency validation
- Cycle detection
- Topological ordering
- Ready-step discovery
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from .step import StepDefinition


class MissingDependencyError(ValueError):
    """Raised when a step depends on an unknown step."""

    def __init__(self, step: str, missing_dep: str):
        super().__init__(f"Step '{step}' depends on missing step '{missing_dep}'")
        self.step = step
        self.missing_dep = missing_dep


class CycleDetectedError(ValueError):
    """Raised when a dependency cycle is detected."""

    def __init__(self, cycle_path: list[str]):
        cycle_str = " -> ".join(cycle_path)
        super().__init__(f"Cycle detected in DAG: {cycle_str}")
        self.cycle_path = cycle_path


@dataclass
class DAG:
    """Directed Acyclic Graph for workflow execution.

    Represents a set of workflow steps with explicit dependency edges.
    Steps are executed in topological order, with maximum parallelism:
    any step whose dependencies are satisfied can run immediately,
    without waiting for unrelated steps in the same "layer".

    Key advantages over Pipeline:
        - No sync barriers between "layers"
        - Maximum parallelism derived from the dependency graph
        - Automatic topological ordering via Kahn's algorithm
        - Cycle detection at definition time (DFS three-color)

    Attributes:
        name: Human-readable identifier for this DAG.
        description: Optional prose description of the workflow.
        steps: Registry of step definitions keyed by step name.
    """

    name: str
    description: str = ""
    steps: dict[str, StepDefinition] = field(default_factory=dict)

    def add(self, step: StepDefinition) -> "DAG":
        """Add a step to the DAG.

        Args:
            step: Step definition to register.

        Returns:
            Self, for fluent chaining (``dag.add(a).add(b)``).

        Raises:
            ValueError: If a step with the same name already exists.
        """
        if step.name in self.steps:
            raise ValueError(f"Step '{step.name}' already exists in DAG")
        self.steps[step.name] = step
        return self

    def add_many(self, steps: Iterable[StepDefinition]) -> "DAG":
        """Add multiple steps to the DAG.

        Args:
            steps: Iterable of step definitions to register.

        Returns:
            Self, for fluent chaining.
        """
        for step in steps:
            self.add(step)
        return self

    def validate(self) -> None:
        """Validate DAG structure for missing dependencies and cycles.

        Performs three validation passes in order:
        1. Non-empty check — rejects DAGs with zero steps.
        2. Dependency existence — every ``depends_on`` target must be a
           registered step name.
        3. Cycle detection — DFS three-color algorithm (white/gray/black)
           over the forward adjacency list.

        Raises:
            ValueError: If the DAG contains no steps.
            MissingDependencyError: If a step references an unknown dependency.
            CycleDetectedError: If a dependency cycle exists.
        """
        if len(self.steps) == 0:
            raise ValueError(f"DAG '{self.name}' has no steps. Check the YAML schema.")
        self._check_missing_dependencies()
        adjacency = self._build_adjacency_list()
        self._detect_cycles(adjacency)

    def _check_missing_dependencies(self) -> None:
        """Verify every ``depends_on`` entry points to a registered step.

        Raises:
            MissingDependencyError: On the *first* dangling reference found.
        """
        for step_name, step in self.steps.items():
            for dep in step.depends_on:
                if dep not in self.steps:
                    raise MissingDependencyError(step_name, dep)

    def _build_adjacency_list(self) -> dict[str, list[str]]:
        """Build a forward adjacency list from ``depends_on`` fields.

        Each key maps to a list of *dependents* (steps that depend on the key).
        This is the **forward** direction: ``dep → [steps that need dep]``.

        Returns:
            Adjacency mapping of ``{step_name: [dependent_step_names]}``.
        """
        adjacency: dict[str, list[str]] = {name: [] for name in self.steps}
        for step_name, step in self.steps.items():
            for dep in step.depends_on:
                adjacency.setdefault(dep, []).append(step_name)
        return adjacency

    def build_adjacency_list(self) -> dict[str, list[str]]:
        """Public accessor for the forward adjacency list.

        Returns:
            Adjacency mapping of ``{step_name: [dependent_step_names]}``.
        """
        return self._build_adjacency_list()

    def _detect_cycles(self, adjacency: dict[str, list[str]]) -> None:
        """Detect cycles via DFS three-color algorithm.

        Uses the classic white/gray/black coloring scheme:
        - **white**: unvisited node.
        - **gray**: node is on the current DFS path (back-edge target = cycle).
        - **black**: node fully explored, no cycle through it.

        A back-edge (encountering a gray node) means the path from
        that gray node to the current node forms a cycle.

        Args:
            adjacency: Forward adjacency list ``{node: [dependents]}``.

        Raises:
            CycleDetectedError: With the cycle path from the repeated node
                back to itself (e.g. ``["A", "B", "C", "A"]``).
        """
        color: dict[str, str] = {name: "white" for name in self.steps}
        stack: list[str] = []

        def visit(node: str) -> None:
            color[node] = "gray"
            stack.append(node)

            for neighbor in adjacency.get(node, []):
                if color[neighbor] == "gray":
                    # Back-edge found — extract the cycle path
                    cycle_start = stack.index(neighbor)
                    cycle_path = stack[cycle_start:] + [neighbor]
                    raise CycleDetectedError(cycle_path)
                if color[neighbor] == "white":
                    visit(neighbor)

            stack.pop()
            color[node] = "black"

        for node in self.steps:
            if color[node] == "white":
                visit(node)

    def get_execution_order(self) -> list[str]:
        """Return a topologically sorted list of step names via Kahn's algorithm.

        Steps with no dependencies appear first.  Among steps at the same
        topological depth, ordering is insertion-order (FIFO from the ready
        queue), which provides deterministic output for identical DAG
        definitions.

        Returns:
            Ordered list of step names respecting all dependency edges.

        Raises:
            ValueError: If the DAG is empty or has missing dependencies.
            CycleDetectedError: If topological sort cannot consume all steps
                (indicates a cycle that survived the DFS check — defensive).
        """
        self.validate()
        adjacency = self._build_adjacency_list()
        # in_degree[step] = number of unsatisfied upstream dependencies
        in_degree = {name: len(step.depends_on) for name, step in self.steps.items()}

        # Seed the ready queue with root steps (no dependencies)
        ready = [name for name, deg in in_degree.items() if deg == 0]
        order: list[str] = []

        while ready:
            current = ready.pop(0)
            order.append(current)
            for dependent in adjacency.get(current, []):
                in_degree[dependent] -= 1
                if in_degree[dependent] == 0:
                    ready.append(dependent)

        if len(order) != len(self.steps):
            raise CycleDetectedError(order)

        return order

    def get_ready_steps(self, completed: set[str]) -> list[str]:
        """Identify steps that can execute immediately.

        A step is "ready" when it has not yet completed *and* every entry
        in its ``depends_on`` list is present in *completed*.  This is the
        core scheduling primitive used by :class:`DAGExecutor` to achieve
        maximum parallelism without topological layers.

        Args:
            completed: Set of step names that have already finished
                (successfully, failed, or skipped).

        Returns:
            List of step names eligible for immediate execution.
        """
        ready: list[str] = []
        for name, step in self.steps.items():
            if name in completed:
                continue
            if all(dep in completed for dep in step.depends_on):
                ready.append(name)
        return ready

    def get_dependents(self, step_name: str) -> list[str]:
        """Return names of steps that directly depend on *step_name*.

        Args:
            step_name: The upstream step whose dependents are requested.

        Returns:
            List of step names that list *step_name* in their ``depends_on``.
        """
        adjacency = self._build_adjacency_list()
        return adjacency.get(step_name, [])
