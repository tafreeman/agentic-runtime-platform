"""Workflow data extraction and reporting pipeline for the benchmark runner.

Provides helpers for pulling structured data out of multi-agent
``OrchestratorResult`` objects and for evaluating / persisting that data.
Extracted from runner.py.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Optional dependency: LLM-based evaluator
# ---------------------------------------------------------------------------
try:
    from tools.agents.benchmarks.llm_evaluator import evaluate_with_llm

    HAS_LLM_EVALUATOR = True
except ImportError:
    HAS_LLM_EVALUATOR = False


# ---------------------------------------------------------------------------
# Agent expectations catalogue
# ---------------------------------------------------------------------------

_AGENT_EXPECTATIONS: dict[str, dict[str, str]] = {
    "analyst": {
        "key_qualities": "Deep analysis, pattern recognition, evidence-based findings",
        "expected_sections": "KEY FINDINGS, PATTERNS IDENTIFIED, RECOMMENDATIONS",
        "success_criteria": "Provides actionable insights with supporting evidence",
    },
    "researcher": {
        "key_qualities": "Thorough research, fact verification, source reliability",
        "expected_sections": "RESEARCH FINDINGS, INFORMATION GAPS, KEY TAKEAWAYS",
        "success_criteria": "Comprehensive information gathering with reliability assessment",
    },
    "strategist": {
        "key_qualities": "Strategic planning, risk assessment, clear recommendations",
        "expected_sections": "STRATEGIC APPROACH, OPTIONS CONSIDERED, RISK MITIGATION",
        "success_criteria": "Clear strategy with trade-offs and success metrics",
    },
    "implementer": {
        "key_qualities": "Practical solutions, working code, technical specifications",
        "expected_sections": "IMPLEMENTATION APPROACH, CODE/ARTIFACTS, NEXT STEPS",
        "success_criteria": "Concrete implementation with runnable code or clear specs",
    },
    "validator": {
        "key_qualities": "Quality assurance, edge case identification, test coverage",
        "expected_sections": "VALIDATION RESULTS, ISSUES FOUND, RECOMMENDATIONS",
        "success_criteria": "Thorough validation with clear pass/fail criteria",
    },
}

_DEFAULT_EXPECTATIONS: dict[str, str] = {
    "key_qualities": "Clear, relevant, actionable output",
    "expected_sections": "Structured response addressing the task",
    "success_criteria": "Addresses the task requirements effectively",
}


def get_agent_expectations(agent_type: str) -> dict[str, str]:
    """Return the expected-quality descriptor dict for *agent_type*.

    Falls back to generic expectations for unknown agent types.
    """
    return _AGENT_EXPECTATIONS.get(agent_type, _DEFAULT_EXPECTATIONS)


def evaluate_agent_output(
    agent_task_id: str,
    agent_type: str,
    task_description: str,
    agent_output: str,
    original_prompt: str,
    model: str,
    benchmark_id: str,
    evaluator_model: str | None = None,
    verbose: bool = False,
) -> dict[str, Any] | None:
    """Evaluate a single agent's output using LLM-based evaluation.

    Returns a compact result dict, or ``None`` when the LLM evaluator is
    unavailable.
    """
    if not HAS_LLM_EVALUATOR:
        return None

    if not agent_output or len(agent_output.strip()) < 50:
        return {
            "score": 0.0,
            "grade": "F",
            "reason": "Output too short or empty",
        }

    agent_gold_standard = {
        "task_type": agent_type,
        "task_description": task_description,
        "original_prompt": original_prompt,
        "expected_qualities": get_agent_expectations(agent_type),
    }

    try:
        eval_result = evaluate_with_llm(
            task_id=agent_task_id,
            task_prompt=(
                f"[{agent_type.upper()} AGENT TASK]\n{task_description}\n\n"
                f"[CONTEXT]\nOriginal request: {original_prompt[:500]}"
            ),
            generated_output=agent_output,
            gold_standard=agent_gold_standard,
            model=model,
            benchmark_id=benchmark_id,
            evaluator_model=evaluator_model,
            verbose=False,
        )

        return {
            "score": eval_result.overall_score,
            "grade": eval_result.grade,
            "dimension_scores": {
                k: v.score for k, v in eval_result.dimension_scores.items()
            },
            "strengths": eval_result.strengths[:2] if eval_result.strengths else [],
            "weaknesses": eval_result.weaknesses[:2] if eval_result.weaknesses else [],
        }
    except Exception as exc:
        if verbose:
            print(f"    [!] Agent eval error: {exc}")
        return {
            "score": 0.0,
            "grade": "F",
            "reason": f"Evaluation failed: {exc}",
        }


def extract_workflow_data(
    result: Any,
    evaluate_phases: bool = False,
    model: str | None = None,
    benchmark_id: str | None = None,
    original_prompt: str | None = None,
    verbose: bool = False,
) -> dict[str, Any]:
    """Extract full workflow data from an ``OrchestratorResult``.

    Captures all phases, agent outputs, and metadata for comprehensive
    logging. When *evaluate_phases* is ``True``, each agent output is scored
    via :func:`evaluate_agent_output`.
    """
    workflow_data: dict[str, Any] = {
        "task_description": result.task_description,
        "total_duration_seconds": result.total_duration_seconds,
        "metadata": result.metadata,
        "phases": [],
        "agent_results": {},
        "phase_evaluations": {},
    }

    # Extract plan phases
    if result.plan and result.plan.phases:
        for phase_idx, phase_tasks in enumerate(result.plan.phases):
            phase_data: dict[str, Any] = {"phase_number": phase_idx + 1, "tasks": []}
            for task in phase_tasks:
                phase_data["tasks"].append(
                    {
                        "task_id": task.id,
                        "description": task.description,
                        "agent_type": (
                            task.agent_type.value
                            if hasattr(task.agent_type, "value")
                            else str(task.agent_type)
                        ),
                        "status": (
                            task.status.value
                            if hasattr(task.status, "value")
                            else str(task.status)
                        ),
                        "priority": (
                            task.priority.value
                            if hasattr(task.priority, "value")
                            else str(task.priority)
                        ),
                        "dependencies": task.dependencies,
                        "expected_output": task.expected_output,
                        "inputs": task.inputs,
                    }
                )
            workflow_data["phases"].append(phase_data)

        workflow_data["integration_strategy"] = result.plan.integration_strategy

    # Extract individual agent results
    if result.agent_results:
        for task_id, task in result.agent_results.items():
            agent_type = (
                task.agent_type.value
                if hasattr(task.agent_type, "value")
                else str(task.agent_type)
            )
            agent_output = task.result or ""

            agent_data: dict[str, Any] = {
                "task_id": task.id,
                "description": task.description,
                "agent_type": agent_type,
                "status": (
                    task.status.value
                    if hasattr(task.status, "value")
                    else str(task.status)
                ),
                "output": agent_output,
                "confidence": task.confidence,
                "error": task.error,
                "duration_seconds": task.duration_seconds,
                "started_at": task.started_at.isoformat() if task.started_at else None,
                "completed_at": (
                    task.completed_at.isoformat() if task.completed_at else None
                ),
            }
            workflow_data["agent_results"][task_id] = agent_data

            # Optionally evaluate this agent's output
            if evaluate_phases and agent_output and model:
                if verbose:
                    print(f"    [Eval] Scoring {task_id} ({agent_type})...")

                eval_result = evaluate_agent_output(
                    agent_task_id=task_id,
                    agent_type=agent_type,
                    task_description=task.description,
                    agent_output=agent_output,
                    original_prompt=original_prompt or result.task_description,
                    model=model,
                    benchmark_id=benchmark_id,
                    evaluator_model=model,
                    verbose=verbose,
                )

                if eval_result:
                    workflow_data["phase_evaluations"][task_id] = eval_result
                    agent_data["evaluation"] = eval_result

                    if verbose:
                        score = eval_result.get("score", 0)
                        grade = eval_result.get("grade", "?")
                        print(f"           Score: {score:.1f}/10 (Grade: {grade})")

    # Phase summary scores
    if workflow_data["phase_evaluations"]:
        scores: list[float] = [
            e.get("score", 0) for e in workflow_data["phase_evaluations"].values()
        ]
        workflow_data["phase_summary"] = {
            "total_agents": len(scores),
            "average_score": sum(scores) / len(scores) if scores else 0,
            "min_score": min(scores) if scores else 0,
            "max_score": max(scores) if scores else 0,
            "scores_by_agent": {
                k: v.get("score", 0)
                for k, v in workflow_data["phase_evaluations"].items()
            },
        }

    return workflow_data


def save_workflow_phases_md(
    workflow_data: dict[str, Any],
    task_id: str,
    output_dir: Path,
) -> None:
    """Persist workflow phases as a human-readable Markdown file."""
    lines = [
        f"# Workflow Phases: Task {task_id}",
        "",
        f"**Total Duration:** {workflow_data.get('total_duration_seconds', 0):.1f}s",
        f"**Integration Strategy:** {workflow_data.get('integration_strategy', 'N/A')}",
        "",
        "---",
        "",
    ]

    for phase in workflow_data.get("phases", []):
        phase_num = phase.get("phase_number", "?")
        lines.append(f"## Phase {phase_num}")
        lines.append("")

        for task_info in phase.get("tasks", []):
            task_id_str = task_info.get("task_id", "unknown")
            agent = task_info.get("agent_type", "unknown")
            status = task_info.get("status", "unknown")
            desc = task_info.get("description", "No description")

            lines.append(f"### {task_id_str} ({agent}) - {status}")
            lines.append("")
            lines.append(f"**Task:** {desc}")
            lines.append("")

            agent_result = workflow_data.get("agent_results", {}).get(task_id_str, {})
            output = agent_result.get("output", "")
            duration = agent_result.get("duration_seconds")

            if duration:
                lines.append(f"**Duration:** {duration:.1f}s")
                lines.append("")

            agent_eval = workflow_data.get("phase_evaluations", {}).get(task_id_str, {})
            if agent_eval:
                score = agent_eval.get("score", 0)
                grade = agent_eval.get("grade", "?")
                lines.append(f"**Evaluation:** {score:.1f}/10 (Grade: {grade})")

                dim_scores = agent_eval.get("dimension_scores", {})
                if dim_scores:
                    dims_str = ", ".join(f"{k}: {v:.1f}" for k, v in dim_scores.items())
                    lines.append(f"  - Dimensions: {dims_str}")

                strengths = agent_eval.get("strengths", [])
                if strengths:
                    lines.append(f"  - Strengths: {'; '.join(strengths)}")
                weaknesses = agent_eval.get("weaknesses", [])
                if weaknesses:
                    lines.append(f"  - Weaknesses: {'; '.join(weaknesses)}")
                lines.append("")

            if output:
                lines.append("**Output:**")
                lines.append("")
                lines.append("```")
                lines.append(output[:3000] if len(output) > 3000 else output)
                if len(output) > 3000:
                    lines.append(f"... [truncated, {len(output)} chars total]")
                lines.append("```")
                lines.append("")
            else:
                lines.append("**Output:** (none)")
                lines.append("")

        lines.append("---")
        lines.append("")

    # Phase evaluation summary
    phase_summary = workflow_data.get("phase_summary", {})
    if phase_summary:
        lines.append("## Phase Evaluation Summary")
        lines.append("")
        lines.append(
            f"**Total Agents Evaluated:** {phase_summary.get('total_agents', 0)}"
        )
        lines.append(
            f"**Average Score:** {phase_summary.get('average_score', 0):.1f}/10"
        )
        lines.append(
            f"**Score Range:** "
            f"{phase_summary.get('min_score', 0):.1f} - "
            f"{phase_summary.get('max_score', 0):.1f}"
        )
        lines.append("")

        scores_by_agent = phase_summary.get("scores_by_agent", {})
        if scores_by_agent:
            lines.append("| Agent | Score | Grade |")
            lines.append("|-------|-------|-------|")
            for agent_id, score in scores_by_agent.items():
                if score >= 9:
                    grade = "A"
                elif score >= 8:
                    grade = "B"
                elif score >= 7:
                    grade = "C"
                elif score >= 6:
                    grade = "D"
                else:
                    grade = "F"
                lines.append(f"| {agent_id} | {score:.1f} | {grade} |")
            lines.append("")
        lines.append("---")
        lines.append("")

    metadata = workflow_data.get("metadata", {})
    if metadata:
        lines.append("## Workflow Metadata")
        lines.append("")
        lines.append("```json")
        lines.append(json.dumps(metadata, indent=2, default=str))
        lines.append("```")

    phases_file = output_dir / f"task_{task_id}_phases.md"
    phases_file.write_text("\n".join(lines), encoding="utf-8")
