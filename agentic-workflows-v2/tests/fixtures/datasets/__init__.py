"""Dataset fixtures for workflow testing.

Provides adapters that map Hugging Face dataset samples to the input
schemas expected by each built-in workflow (code_review,
fullstack_generation).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_DATASETS_DIR = Path(__file__).parent


def _load(name: str) -> list[dict[str, Any]]:
    path = _DATASETS_DIR / f"{name}.json"
    if not path.exists():
        raise FileNotFoundError(f"Dataset fixture not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Raw loaders
# ---------------------------------------------------------------------------


def load_code_review_instruct() -> list[dict[str, Any]]:
    """Dahoas/code-review-instruct-critique-revision-python."""
    return _load("code_review_instruct")


def load_python_code_instructions() -> list[dict[str, Any]]:
    """iamtarun/python_code_instructions_18k_alpaca."""
    return _load("python_code_instructions_18k")


def load_react_code_instructions() -> list[dict[str, Any]]:
    """cfahlgren1/react-code-instructions."""
    return _load("react_code_instructions")


def load_code_instructions_120k() -> list[dict[str, Any]]:
    """iamtarun/code_instructions_120k_alpaca."""
    return _load("code_instructions_120k")


def load_swe_bench_lite() -> list[dict[str, Any]]:
    """princeton-nlp/SWE-bench_Lite."""
    return _load("swe_bench_lite")


def load_swe_bench_verified() -> list[dict[str, Any]]:
    """princeton-nlp/SWE-bench_Verified."""
    return _load("swe_bench_verified")


def load_mbpp() -> list[dict[str, Any]]:
    """google-research-datasets/mbpp."""
    return _load("mbpp")


def load_humaneval() -> list[dict[str, Any]]:
    """openai/openai_humaneval."""
    return _load("humaneval")


def load_codeparrot_apps() -> list[dict[str, Any]]:
    """codeparrot/apps."""
    return _load("codeparrot_apps")


# ---------------------------------------------------------------------------
# Workflow-specific adapters
# ---------------------------------------------------------------------------


def code_review_inputs(limit: int = 5) -> list[dict[str, Any]]:
    """Adapt code review dataset → code_review.yaml inputs.

    Returns dicts with keys: code_file, review_depth, _meta
    where _meta carries the original data for assertion.
    """
    results = []

    # From code review instruct (has real code + critique)
    for rec in load_code_review_instruct()[:limit]:
        code = rec.get("response") or rec.get("body", "")
        results.append(
            {
                "code_file": "__inline__",
                "code_content": code[:2000],
                "review_depth": "standard",
                "_meta": {
                    "source": "Dahoas/code-review-instruct-critique-revision-python",
                    "question_id": rec.get("question_id"),
                    "has_answer": bool(rec.get("answer")),
                },
            }
        )

    # From python code instructions (has instruction + output code)
    for rec in load_python_code_instructions()[:limit]:
        results.append(
            {
                "code_file": "__inline__",
                "code_content": rec.get("output", "")[:2000],
                "review_depth": "quick",
                "_meta": {
                    "source": "iamtarun/python_code_instructions_18k_alpaca",
                    "instruction": rec.get("instruction", ""),
                },
            }
        )

    return results


def fullstack_generation_inputs(limit: int = 5) -> list[dict[str, Any]]:
    """Adapt code instruction datasets → fullstack_generation.yaml inputs.

    Returns dicts with keys: feature_spec, tech_stack, _meta
    """
    results = []

    # From react code instructions (real React app specs)
    for rec in load_react_code_instructions()[:limit]:
        messages = rec.get("messages", [])
        user_msg = next((m["content"] for m in messages if m.get("role") == "user"), "")
        results.append(
            {
                "feature_spec": user_msg[:3000],
                "tech_stack": {
                    "frontend": "react",
                    "backend": "fastapi",
                    "database": "postgresql",
                },
                "_meta": {
                    "source": "cfahlgren1/react-code-instructions",
                    "model": rec.get("model"),
                    "has_response": len(messages) > 1,
                },
            }
        )

    # From code instructions 120k (multi-language)
    for rec in load_code_instructions_120k()[:limit]:
        results.append(
            {
                "feature_spec": rec.get("instruction", ""),
                "tech_stack": {
                    "frontend": "react",
                    "backend": "fastapi",
                    "database": "postgresql",
                },
                "_meta": {
                    "source": "iamtarun/code_instructions_120k_alpaca",
                    "has_input": bool(rec.get("input")),
                    "has_output": bool(rec.get("output")),
                },
            }
        )

    return results


def python_code_review_inputs(limit: int = 5) -> list[dict[str, Any]]:
    """Adapt mbpp + humaneval → code_review.yaml inputs (Python only).

    Returns dicts with keys: code_file, review_depth, _meta
    """
    results = []

    # MBPP — real Python solutions with test assertions
    for rec in load_mbpp()[:limit]:
        results.append(
            {
                "code_file": "__inline__",
                "code_content": rec.get("code", "")[:2000],
                "review_depth": "standard",
                "_meta": {
                    "source": "google-research-datasets/mbpp",
                    "task_id": rec.get("task_id"),
                    "description": rec.get("text", ""),
                    "test_list": rec.get("test_list", []),
                },
            }
        )

    # HumanEval — function prompts + canonical solutions
    for rec in load_humaneval()[:limit]:
        code = rec.get("prompt", "") + rec.get("canonical_solution", "")
        results.append(
            {
                "code_file": "__inline__",
                "code_content": code[:2000],
                "review_depth": "deep",
                "_meta": {
                    "source": "openai/openai_humaneval",
                    "task_id": rec.get("task_id"),
                    "entry_point": rec.get("entry_point"),
                    "has_test": bool(rec.get("test")),
                },
            }
        )

    return results


def python_fullstack_inputs(limit: int = 5) -> list[dict[str, Any]]:
    """Adapt codeparrot/apps → fullstack_generation.yaml inputs (Python only).

    Returns dicts with keys: feature_spec, tech_stack, _meta
    """
    results = []

    for rec in load_codeparrot_apps()[:limit]:
        question = rec.get("question", "")
        starter = rec.get("starter_code", "") or ""
        spec = question
        if starter:
            spec += f"\n\nStarter code:\n{starter}"

        results.append(
            {
                "feature_spec": spec[:3000],
                "tech_stack": {
                    "frontend": "none",
                    "backend": "python",
                    "database": "none",
                },
                "_meta": {
                    "source": "codeparrot/apps",
                    "problem_id": rec.get("problem_id"),
                    "difficulty": rec.get("difficulty"),
                    "has_solutions": bool(rec.get("solutions")),
                    "has_io": bool(rec.get("input_output")),
                },
            }
        )

    # Also use MBPP problems as generation specs
    for rec in load_mbpp()[:limit]:
        results.append(
            {
                "feature_spec": rec.get("text", ""),
                "tech_stack": {
                    "frontend": "none",
                    "backend": "python",
                    "database": "none",
                },
                "_meta": {
                    "source": "google-research-datasets/mbpp",
                    "task_id": rec.get("task_id"),
                    "has_tests": bool(rec.get("test_list")),
                },
            }
        )

    return results


# ---------------------------------------------------------------------------
# Summary / inventory
# ---------------------------------------------------------------------------


def dataset_summary() -> dict[str, dict[str, Any]]:
    """Return a summary of all available dataset fixtures."""
    datasets = {
        "code_review_instruct": {
            "hf_id": "Dahoas/code-review-instruct-critique-revision-python",
            "workflow": "code_review",
            "loader": "load_code_review_instruct",
        },
        "python_code_instructions_18k": {
            "hf_id": "iamtarun/python_code_instructions_18k_alpaca",
            "workflow": "code_review",
            "loader": "load_python_code_instructions",
        },
        "react_code_instructions": {
            "hf_id": "cfahlgren1/react-code-instructions",
            "workflow": "fullstack_generation",
            "loader": "load_react_code_instructions",
        },
        "code_instructions_120k": {
            "hf_id": "iamtarun/code_instructions_120k_alpaca",
            "workflow": "fullstack_generation",
            "loader": "load_code_instructions_120k",
        },
        "swe_bench_lite": {
            "hf_id": "princeton-nlp/SWE-bench_Lite",
            "workflow": "bug_resolution",
            "loader": "load_swe_bench_lite",
        },
        "swe_bench_verified": {
            "hf_id": "princeton-nlp/SWE-bench_Verified",
            "workflow": "bug_resolution",
            "loader": "load_swe_bench_verified",
        },
        "mbpp": {
            "hf_id": "google-research-datasets/mbpp",
            "workflow": "code_review",
            "loader": "load_mbpp",
        },
        "humaneval": {
            "hf_id": "openai/openai_humaneval",
            "workflow": "code_review",
            "loader": "load_humaneval",
        },
        "codeparrot_apps": {
            "hf_id": "codeparrot/apps",
            "workflow": "fullstack_generation",
            "loader": "load_codeparrot_apps",
        },
    }
    for name, info in datasets.items():
        path = _DATASETS_DIR / f"{name}.json"
        info["sample_count"] = len(json.loads(path.read_text())) if path.exists() else 0
        info["file_exists"] = path.exists()
    return datasets
