"""Unit tests for agentic_v2.devex.workflow_linter."""

from __future__ import annotations

import pathlib
import textwrap


from agentic_v2.devex.workflow_linter import (
    LintViolation,
    lint_workflow_dict,
    lint_workflow_file,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

_MINIMAL_STEP: dict = {
    "name": "step_one",
    "agent": "tier1_researcher",
    "description": "Does a thing",
    "inputs": {"query": "{{input.query}}"},
    "outputs": ["result"],
}

_VALID_DOC: dict = {
    "name": "test_workflow",
    "steps": [_MINIMAL_STEP],
}


# ---------------------------------------------------------------------------
# lint_workflow_dict — top-level checks
# ---------------------------------------------------------------------------


def test_valid_minimal_doc_returns_no_violations() -> None:
    assert lint_workflow_dict(_VALID_DOC) == []


def test_missing_top_level_name_returns_violation() -> None:
    doc = {"steps": [_MINIMAL_STEP]}
    violations = lint_workflow_dict(doc)
    fields = [v.field for v in violations]
    assert "name" in fields


def test_missing_steps_returns_violation() -> None:
    doc = {"name": "test_workflow"}
    violations = lint_workflow_dict(doc)
    assert any(v.field == "steps" for v in violations)


def test_empty_steps_list_returns_violation() -> None:
    doc = {"name": "test_workflow", "steps": []}
    violations = lint_workflow_dict(doc)
    assert any(v.field == "steps" for v in violations)


# ---------------------------------------------------------------------------
# lint_workflow_dict — step-level checks
# ---------------------------------------------------------------------------


def test_step_missing_agent_returns_violation_with_step_name() -> None:
    step = {k: v for k, v in _MINIMAL_STEP.items() if k != "agent"}
    doc = {"name": "test_workflow", "steps": [step]}
    violations = lint_workflow_dict(doc)
    agent_violations = [v for v in violations if v.field == "agent"]
    assert len(agent_violations) == 1
    assert agent_violations[0].step == "step_one"


def test_depends_on_referencing_nonexistent_step_returns_violation() -> None:
    step = {**_MINIMAL_STEP, "depends_on": ["ghost_step"]}
    doc = {"name": "test_workflow", "steps": [step]}
    violations = lint_workflow_dict(doc)
    dep_violations = [v for v in violations if v.field == "depends_on"]
    assert len(dep_violations) == 1
    assert "ghost_step" in dep_violations[0].message


def test_depends_on_not_a_list_returns_violation() -> None:
    step = {**_MINIMAL_STEP, "depends_on": "step_one"}
    doc = {"name": "test_workflow", "steps": [step]}
    violations = lint_workflow_dict(doc)
    dep_violations = [v for v in violations if v.field == "depends_on"]
    assert len(dep_violations) == 1
    assert "list" in dep_violations[0].message


def test_valid_depends_on_referencing_existing_step_is_clean() -> None:
    step_a = {**_MINIMAL_STEP, "name": "step_a", "depends_on": []}
    step_b = {**_MINIMAL_STEP, "name": "step_b", "depends_on": ["step_a"]}
    doc = {"name": "test_workflow", "steps": [step_a, step_b]}
    assert lint_workflow_dict(doc) == []


# ---------------------------------------------------------------------------
# lint_workflow_file
# ---------------------------------------------------------------------------


def test_lint_workflow_file_valid_yaml(tmp_path: pathlib.Path) -> None:
    wf_file = tmp_path / "my_workflow.yaml"
    wf_file.write_text(
        textwrap.dedent("""\
            name: my_workflow
            steps:
              - name: step_one
                agent: tier1_researcher
                description: Does a thing
                inputs:
                  query: "{{input.query}}"
                outputs:
                  - result
        """),
        encoding="utf-8",
    )
    violations = lint_workflow_file(wf_file)
    assert violations == []


def test_lint_workflow_file_malformed_yaml(tmp_path: pathlib.Path) -> None:
    wf_file = tmp_path / "bad.yaml"
    wf_file.write_text("name: test\nsteps: [unclosed", encoding="utf-8")
    violations = lint_workflow_file(wf_file)
    assert len(violations) == 1
    assert violations[0].field == "yaml"
    assert "YAML parse error" in violations[0].message


# ---------------------------------------------------------------------------
# LintViolation __str__
# ---------------------------------------------------------------------------


def test_lint_violation_str_with_step() -> None:
    v = LintViolation(field="agent", step="step_one", message="required step field missing")
    assert str(v) == "ERROR [step_one] field 'agent': required step field missing"


def test_lint_violation_str_without_step() -> None:
    v = LintViolation(field="name", message="required field missing")
    assert str(v) == "ERROR field 'name': required field missing"
