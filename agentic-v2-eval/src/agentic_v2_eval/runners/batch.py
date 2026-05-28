"""Synchronous batch evaluation runner with progress tracking.

Iterates over a list of test cases, applies a user-supplied evaluator
function to each, collects results and errors, and reports progress via
optional callbacks.  Supports fail-fast or continue-on-error modes.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Generic, TypeVar

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)

T = TypeVar("T")  # Test case type
R = TypeVar("R")  # Result type


@dataclass
class BatchResult(Generic[R]):
    """Aggregate result of a batch evaluation run.

    Attributes:
        results: Successfully computed evaluation results.
        errors: List of ``(index, exception)`` tuples for failed cases.
        total: Total number of test cases submitted.
        successful: Count of successfully evaluated cases.
        failed: Count of cases that raised an exception.
    """

    results: list[R] = field(default_factory=list)
    errors: list[tuple[int, Exception]] = field(default_factory=list)
    total: int = 0
    successful: int = 0
    failed: int = 0

    @property
    def success_rate(self) -> float:
        """Calculate success rate."""
        return self.successful / self.total if self.total > 0 else 0.0


class BatchRunner(Generic[T, R]):
    """Configurable batch evaluation runner.

    Example:
        >>> runner = BatchRunner(evaluator=my_eval_func)
        >>> result = runner.run(test_cases)
        >>> print(f"Success rate: {result.success_rate:.1%}")
    """

    def __init__(
        self,
        evaluator: Callable[[T], R],
        on_progress: Callable[[int, int], None] | None = None,
        on_error: Callable[[int, T, Exception], None] | None = None,
        continue_on_error: bool = True,
    ):
        """Initialize batch runner.

        Args:
            evaluator: Function to evaluate a single test case.
            on_progress: Optional callback(current, total) for progress updates.
            on_error: Optional callback(index, test_case, error) for error handling.
            continue_on_error: Whether to continue after errors (default: True).
        """
        self.evaluator = evaluator
        self.on_progress = on_progress
        self.on_error = on_error
        self.continue_on_error = continue_on_error

    def run(self, test_cases: list[T]) -> BatchResult[R]:
        """Run batch evaluation on test cases.

        Args:
            test_cases: List of test cases to evaluate.

        Returns:
            BatchResult containing results and statistics.
        """
        result = BatchResult[R]()
        result.total = len(test_cases)

        for idx, test_case in enumerate(test_cases):
            try:
                eval_result = self.evaluator(test_case)
                result.results.append(eval_result)
                result.successful += 1

            except Exception as e:
                result.errors.append((idx, e))
                result.failed += 1
                logger.warning(f"Error evaluating test case {idx}: {e}")

                if self.on_error:
                    self.on_error(idx, test_case, e)

                if not self.continue_on_error:
                    raise

            if self.on_progress:
                self.on_progress(idx + 1, result.total)

        return result


def run_batch_evaluation(
    test_cases: list[T],
    evaluator: Callable[[T], R],
    continue_on_error: bool = True,
) -> list[R]:
    """Run batch evaluation on a set of test cases.

    Simple function interface for batch evaluation.

    Args:
        test_cases: List of test cases to evaluate.
        evaluator: Function to evaluate a single test case.
        continue_on_error: Whether to continue after errors.

    Returns:
        List of results for successful evaluations.

    Example:
        >>> results = run_batch_evaluation(
        ...     test_cases=[{"input": "hello"}],
        ...     evaluator=lambda tc: {"output": tc["input"].upper()}
        ... )
    """
    runner = BatchRunner(
        evaluator=evaluator,
        continue_on_error=continue_on_error,
    )
    batch_result = runner.run(test_cases)
    return batch_result.results
