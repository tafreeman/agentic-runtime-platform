"""Structural YAML linter for workflow definition files.

Provides a fast, dependency-free pre-check for workflow YAML files.
Runs before any LangGraph compilation so contributors get actionable errors
without needing the ``langchain`` extra installed.

Does NOT duplicate the full semantic validation in ``langchain/config.py`` —
this is a structural pre-check only.
"""

from __future__ import annotations

import pathlib
from dataclasses import dataclass
from typing import Any

import yaml

REQUIRED_TOP_LEVEL: list[str] = ["name", "steps"]
REQUIRED_STEP_FIELDS: list[str] = ["name", "agent", "description"]


@dataclass
class LintViolation:
    field: str
    message: str
    step: str | None = None
    severity: str = "error"

    def __str__(self) -> str:
        location = f"[{self.step}] " if self.step else ""
        return f"{self.severity.upper()} {location}field '{self.field}': {self.message}"


def _lint_depends_on(
    step: dict[str, Any], step_name: str, step_names: set[str]
) -> list[LintViolation]:
    """Validate a step's ``depends_on`` field."""
    depends = step.get("depends_on")
    if depends is None:
        return []
    if not isinstance(depends, list):
        return [
            LintViolation(
                field="depends_on",
                step=step_name,
                message="must be a list of step name strings",
            )
        ]
    return [
        LintViolation(
            field="depends_on",
            step=step_name,
            message=f"references unknown step '{dep}'",
        )
        for dep in depends
        if dep not in step_names
    ]


def _lint_step(step: Any, step_names: set[str]) -> list[LintViolation]:
    """Validate a single step mapping and return its violations."""
    if not isinstance(step, dict):
        return [
            LintViolation(field="steps[]", message="each step must be a mapping")
        ]

    step_name: str = step.get("name", "<unnamed>")
    violations: list[LintViolation] = [
        LintViolation(
            field=field_name,
            step=step_name,
            message="required step field missing",
        )
        for field_name in REQUIRED_STEP_FIELDS
        if field_name not in step
    ]
    violations.extend(_lint_depends_on(step, step_name, step_names))
    return violations


def lint_workflow_dict(doc: dict[str, Any]) -> list[LintViolation]:
    """Validate *doc* (pre-parsed YAML) and return all violations."""
    violations: list[LintViolation] = []

    for field_name in REQUIRED_TOP_LEVEL:
        if field_name not in doc:
            violations.append(
                LintViolation(field=field_name, message="required field missing")
            )

    steps = doc.get("steps")
    if not isinstance(steps, list) or len(steps) == 0:
        violations.append(
            LintViolation(field="steps", message="must be a non-empty list")
        )
        return violations

    step_names: set[str] = {
        s.get("name")
        for s in steps
        if isinstance(s, dict) and "name" in s
    }

    for step in steps:
        violations.extend(_lint_step(step, step_names))

    return violations


def lint_workflow_file(path: pathlib.Path) -> list[LintViolation]:
    """Load YAML from *path* and return lint violations."""
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError as exc:
        return [LintViolation(field="file", message=str(exc))]

    try:
        doc = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        return [LintViolation(field="yaml", message=f"YAML parse error: {exc}")]

    if not isinstance(doc, dict):
        return [LintViolation(field="document", message="workflow YAML must be a mapping")]

    return lint_workflow_dict(doc)


def lint_workflow_by_name(name: str) -> list[LintViolation]:
    """Resolve workflow by *name* and lint its YAML file."""
    from ..workflows.loader import WorkflowLoader

    loader = WorkflowLoader()
    yaml_path = loader.definitions_dir / f"{name}.yaml"
    if not yaml_path.exists():
        yml_path = loader.definitions_dir / f"{name}.yml"
        if yml_path.exists():
            yaml_path = yml_path
        else:
            return [
                LintViolation(
                    field="name",
                    message=f"workflow '{name}' not found in {loader.definitions_dir}",
                )
            ]
    return lint_workflow_file(yaml_path)
