"""Accuracy metrics for evaluation.

Provides functions for calculating prediction accuracy, precision,
recall, and F1 scores.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, TypeVar

if TYPE_CHECKING:
    from collections.abc import Sequence

T = TypeVar("T")


def calculate_accuracy(
    predictions: Sequence[T],
    ground_truth: Sequence[T],
) -> float:
    """Calculate the accuracy of predictions compared to ground truth.

    Args:
        predictions: List of predicted values.
        ground_truth: List of actual/expected values.

    Returns:
        Accuracy as a float between 0.0 and 1.0.

    Raises:
        ValueError: If sequences have different lengths.

    Example:
        >>> calculate_accuracy([1, 0, 1, 1], [1, 0, 0, 1])
        0.75
    """
    if len(predictions) != len(ground_truth):
        raise ValueError(
            f"Length mismatch: predictions={len(predictions)}, "
            f"ground_truth={len(ground_truth)}"
        )

    if not ground_truth:
        return 0.0

    correct = sum(p == gt for p, gt in zip(predictions, ground_truth, strict=False))
    return correct / len(ground_truth)


def calculate_precision_recall(
    predictions: Sequence[Any],
    ground_truth: Sequence[Any],
    positive_label: Any = 1,
) -> tuple[float, float]:
    """Calculate precision and recall for binary classification.

    Args:
        predictions: List of predicted values.
        ground_truth: List of actual values.
        positive_label: The label considered "positive". Default is 1.

    Returns:
        Tuple of (precision, recall) as floats between 0.0 and 1.0.

    Raises:
        ValueError: If sequences have different lengths.

    Example:
        >>> calculate_precision_recall([1, 1, 0, 1], [1, 0, 0, 1], positive_label=1)
        (0.666..., 1.0)
    """
    if len(predictions) != len(ground_truth):
        raise ValueError(
            f"Length mismatch: predictions={len(predictions)}, "
            f"ground_truth={len(ground_truth)}"
        )

    true_positives = sum(
        1
        for p, gt in zip(predictions, ground_truth, strict=False)
        if p == positive_label and gt == positive_label
    )

    predicted_positives = sum(1 for p in predictions if p == positive_label)
    actual_positives = sum(1 for gt in ground_truth if gt == positive_label)

    precision = true_positives / predicted_positives if predicted_positives > 0 else 0.0
    recall = true_positives / actual_positives if actual_positives > 0 else 0.0

    return precision, recall


def calculate_f1_score(
    predictions: Sequence[Any],
    ground_truth: Sequence[Any],
    positive_label: Any = 1,
) -> float:
    """Calculate F1 score (harmonic mean of precision and recall).

    Args:
        predictions: List of predicted values.
        ground_truth: List of actual values.
        positive_label: The label considered "positive". Default is 1.

    Returns:
        F1 score as a float between 0.0 and 1.0.

    Example:
        >>> calculate_f1_score([1, 1, 0, 1], [1, 0, 0, 1], positive_label=1)
        0.8
    """
    precision, recall = calculate_precision_recall(
        predictions, ground_truth, positive_label
    )

    if precision + recall == 0:
        return 0.0

    return 2 * (precision * recall) / (precision + recall)


def calculate_confusion_matrix(
    predictions: Sequence[Any],
    ground_truth: Sequence[Any],
    labels: Sequence[Any] | None = None,
) -> dict[str, dict[str, int]]:
    """Calculate confusion matrix for multi-class classification.

    Args:
        predictions: List of predicted values.
        ground_truth: List of actual values.
        labels: Optional list of labels. If None, inferred from data.

    Returns:
        Nested dict representing confusion matrix.
        Access as matrix[actual][predicted] for count.

    Example:
        >>> calculate_confusion_matrix(['a', 'b', 'a'], ['a', 'a', 'a'])
        {'a': {'a': 2, 'b': 1}, 'b': {'a': 0, 'b': 0}}
    """
    if labels is None:
        labels = sorted(set(predictions) | set(ground_truth))

    matrix: dict[str, dict[str, int]] = {
        str(actual): {str(pred): 0 for pred in labels} for actual in labels
    }

    for pred, actual in zip(predictions, ground_truth, strict=False):
        matrix[str(actual)][str(pred)] += 1

    return matrix
