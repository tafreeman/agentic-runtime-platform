"""Backward-compatible facade for the workflow evaluation subsystem.

This module re-exports names from two dedicated submodules so that existing
callers (routes, tests) can continue to ``from .evaluation import ...``
without knowing the internal split:

* :mod:`~agentic_v2.server.datasets` -- dataset discovery, loading,
  sample-to-input adaptation, and workflow/dataset compatibility matching.
* :mod:`~agentic_v2.server.evaluation_scoring` -- hard-gate checks,
  per-criterion scoring, rubric resolution, hybrid score composition,
  and letter-grade assignment.

The only logic retained here is :func:`score_workflow_result`, a thin
delegation wrapper around :func:`evaluation_scoring.score_workflow_result_impl`
that injects the module-level ``_compute_criterion_score`` shim for
backward compatibility with monkeypatch-based tests.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..contracts import WorkflowResult
from ..workflows.loader import (
    WorkflowDefinition,
    WorkflowInput,
)
from .datasets import (
    _dataset_value_for_input,
    _extract_message_text,
    _is_empty_value,
    _load_eval_config,
    _materialize_file_input,
    _pick_first,
    adapt_sample_to_workflow_inputs,
    list_eval_sets,
    list_local_datasets,
    list_repository_datasets,
    load_local_dataset_sample,
    load_local_dataset_samples,
    load_repository_dataset_sample,
    load_repository_dataset_samples,
    match_workflow_dataset,
    validate_required_inputs_present,
)
from .evaluation_scoring import (
    CriterionFloorResult,
    HardGateResult,
    _build_judge_criteria,
    _clamp,
    _compose_hybrid_score,
)
from .evaluation_scoring import (
    _compute_criterion_score as _compute_criterion_score_impl,
)
from .evaluation_scoring import (
    _extract_expected_text,
    _grade,
    _output_text,
    _resolve_rubric,
    _step_scores,
    _text_overlap_score,
    _tokenize,
    _validate_rubric_weights,
    compute_hard_gates,
    pass_threshold,
    score_workflow_result_impl,
    validate_evaluation_payload_schema,
)
from .judge import LLMJudge


def _compute_criterion_score(
    criterion: str,
    result: WorkflowResult,
    expected_text: str,
) -> float:
    """Compatibility wrapper retained for monkeypatch-based tests."""
    return _compute_criterion_score_impl(criterion, result, expected_text)


def score_workflow_result(
    result: WorkflowResult,
    *,
    dataset_meta: dict[str, Any] | None,
    dataset_sample: dict[str, Any] | None,
    rubric: str | None = None,
    workflow_definition: WorkflowDefinition | None = None,
    enforce_hard_gates: bool = True,
    judge: LLMJudge | None = None,
    hybrid_component_weights: dict[str, float] | None = None,
) -> dict[str, Any]:
    """Produce criterion-level and aggregate scores for a workflow result."""
    return score_workflow_result_impl(
        result,
        dataset_meta=dataset_meta,
        dataset_sample=dataset_sample,
        rubric=rubric,
        workflow_definition=workflow_definition,
        enforce_hard_gates=enforce_hard_gates,
        judge=judge,
        hybrid_component_weights=hybrid_component_weights,
        compute_criterion_score_fn=_compute_criterion_score,
        match_workflow_dataset_fn=match_workflow_dataset,
    )


__all__ = [
    "CriterionFloorResult",
    "HardGateResult",
    "Path",
    "WorkflowDefinition",
    "WorkflowInput",
    "_build_judge_criteria",
    "_clamp",
    "_compose_hybrid_score",
    "_compute_criterion_score",
    "_dataset_value_for_input",
    "_extract_expected_text",
    "_extract_message_text",
    "_grade",
    "_is_empty_value",
    "_load_eval_config",
    "_materialize_file_input",
    "_output_text",
    "_pick_first",
    "_resolve_rubric",
    "_step_scores",
    "_text_overlap_score",
    "_tokenize",
    "_validate_rubric_weights",
    "adapt_sample_to_workflow_inputs",
    "compute_hard_gates",
    "list_eval_sets",
    "list_local_datasets",
    "list_repository_datasets",
    "load_local_dataset_sample",
    "load_local_dataset_samples",
    "load_repository_dataset_sample",
    "load_repository_dataset_samples",
    "match_workflow_dataset",
    "pass_threshold",
    "score_workflow_result",
    "validate_evaluation_payload_schema",
    "validate_required_inputs_present",
]
