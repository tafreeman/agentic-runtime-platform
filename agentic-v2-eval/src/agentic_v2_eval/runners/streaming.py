"""Streaming and async-streaming evaluation runners.

Provides two runners for incremental result delivery:

    StreamingRunner: Synchronous iterator-based runner with per-result
        callbacks and error hooks.
    AsyncStreamingRunner: ``asyncio``-based concurrent runner with
        configurable parallelism via a semaphore.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Generic, Literal, TypeVar

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Awaitable, Callable, Iterator

logger = logging.getLogger(__name__)

T = TypeVar("T")  # Test case type
R = TypeVar("R")  # Result type


@dataclass
class StreamingStats:
    """Running statistics collected during a streaming evaluation.

    Attributes:
        processed: Total test cases seen so far.
        successful: Count of successfully evaluated cases.
        failed: Count of cases that raised an exception.
    """

    processed: int = 0
    successful: int = 0
    failed: int = 0

    @property
    def success_rate(self) -> float:
        """Calculate success rate."""
        return self.successful / self.processed if self.processed > 0 else 0.0


class StreamingRunner(Generic[T, R]):
    """Streaming evaluation runner with callbacks.

    Example:
        >>> runner = StreamingRunner(
        ...     evaluator=my_eval_func,
        ...     on_result=lambda r: print(f"Got result: {r}")
        ... )
        >>> stats = runner.run(test_cases)
    """

    def __init__(
        self,
        evaluator: Callable[[T], R],
        on_result: Callable[[R], None] | None = None,
        on_error: Callable[[T, Exception], None] | None = None,
        continue_on_error: bool = True,
    ):
        """Initialize streaming runner.

        Args:
            evaluator: Function to evaluate a single test case.
            on_result: Callback invoked for each successful result.
            on_error: Callback invoked for each error.
            continue_on_error: Whether to continue after errors.
        """
        self.evaluator = evaluator
        self.on_result = on_result
        self.on_error = on_error
        self.continue_on_error = continue_on_error

    def run(self, test_cases: Iterator[T] | list[T]) -> StreamingStats:
        """Run streaming evaluation.

        Args:
            test_cases: Iterable of test cases.

        Returns:
            StreamingStats with evaluation statistics.
        """
        stats = StreamingStats()

        for test_case in test_cases:
            stats.processed += 1

            try:
                result = self.evaluator(test_case)
                stats.successful += 1

                if self.on_result:
                    self.on_result(result)

            except Exception as e:
                stats.failed += 1
                logger.warning(f"Streaming evaluation error: {e}")

                if self.on_error:
                    self.on_error(test_case, e)

                if not self.continue_on_error:
                    raise

        return stats

    def iter_results(self, test_cases: Iterator[T] | list[T]) -> Iterator[R]:
        """Iterate over results, yielding each as it's computed.

        Args:
            test_cases: Iterable of test cases.

        Yields:
            Results for successful evaluations.
        """
        for test_case in test_cases:
            try:
                result = self.evaluator(test_case)
                yield result
            except Exception as e:
                logger.warning(f"Streaming evaluation error: {e}")
                if not self.continue_on_error:
                    raise


class AsyncStreamingRunner(Generic[T, R]):
    """Async streaming evaluation runner with bounded concurrency.

    Evaluates test cases concurrently (up to ``max_concurrency``)
    using ``asyncio`` tasks, yielding results as they complete.
    Accepts both sync and async evaluator functions.

    Example::

        runner = AsyncStreamingRunner(evaluator=async_eval_func)
        async for result in runner.iter_results(test_cases):
            print(result)
    """

    def __init__(
        self,
        evaluator: Callable[[T], R | Awaitable[R]],
        on_result: Callable[[R], None] | None = None,
        continue_on_error: bool = True,
        max_concurrency: int = 5,
    ):
        """Initialize async streaming runner.

        Args:
            evaluator: Async or sync function to evaluate test cases.
            on_result: Callback for each result.
            continue_on_error: Whether to continue after errors.
            max_concurrency: Maximum concurrent evaluations.
        """
        self.evaluator = evaluator
        self.on_result = on_result
        self.continue_on_error = continue_on_error
        # Treat non-positive values as "sequential".
        self.max_concurrency = max(1, int(max_concurrency))

    async def iter_results(
        self,
        test_cases: AsyncIterator[T] | Iterator[T] | list[T],
    ) -> AsyncIterator[R]:
        """Async iterate over results.

        Args:
            test_cases: Iterable or async iterable of test cases.

        Yields:
            Results for successful evaluations.
        """

        async def _aiter_cases() -> AsyncIterator[T]:
            if hasattr(test_cases, "__aiter__"):
                async for tc in test_cases:
                    yield tc
            else:
                for tc in test_cases:
                    yield tc

        semaphore = asyncio.Semaphore(self.max_concurrency)

        async def _eval_one(
            tc: T,
        ) -> tuple[Literal[True], R] | tuple[Literal[False], Exception]:
            async with semaphore:
                try:
                    value = self.evaluator(tc)
                    if inspect.isawaitable(value):
                        value = await value
                    # value is R here (the awaited result or sync result).
                    return (True, value)
                except Exception as e:  # pragma: no cover (exercised via tests)
                    return (False, e)

        pending: set[
            asyncio.Task[tuple[Literal[True], R] | tuple[Literal[False], Exception]]
        ] = set()

        async def _drain_one() -> AsyncIterator[
            tuple[Literal[True], R] | tuple[Literal[False], Exception]
        ]:
            if not pending:
                return
            done, _ = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                pending.remove(task)
                yield task.result()

        async for test_case in _aiter_cases():
            pending.add(asyncio.create_task(_eval_one(test_case)))
            if len(pending) >= self.max_concurrency:
                async for outcome in _drain_one():
                    if outcome[0]:
                        result = outcome[1]
                        if self.on_result:
                            self.on_result(result)
                        yield result
                    else:
                        err = outcome[1]
                        logger.warning(f"Async streaming error: {err}")
                        if not self.continue_on_error:
                            raise err

        while pending:
            async for outcome in _drain_one():
                if outcome[0]:
                    result = outcome[1]
                    if self.on_result:
                        self.on_result(result)
                    yield result
                else:
                    err = outcome[1]
                    logger.warning(f"Async streaming error: {err}")
                    if not self.continue_on_error:
                        raise err


def run_streaming_evaluation(
    test_cases: Iterator[T] | list[T],
    evaluator: Callable[[T], R],
    callback: Callable[[R], None],
) -> None:
    """Run streaming evaluation, invoking callback for each result.

    Simple function interface for streaming evaluation.

    Args:
        test_cases: Iterable of test cases.
        evaluator: Function to evaluate a single test case.
        callback: Function to process each result as it arrives.

    Example:
        >>> results = []
        >>> run_streaming_evaluation(
        ...     test_cases=[1, 2, 3],
        ...     evaluator=lambda x: x * 2,
        ...     callback=lambda r: results.append(r)
        ... )
        >>> results
        [2, 4, 6]
    """
    runner = StreamingRunner(
        evaluator=evaluator,
        on_result=callback,
    )
    runner.run(test_cases)
