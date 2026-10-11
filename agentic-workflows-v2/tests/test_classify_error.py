"""Tests for ``agentic_v2.core.errors.classify_error``.

The 410 cases replay the body NVIDIA NIM returned on 2026-10-11 for a model it
had retired. Before ``MODEL_RETIRED`` existed that body fell through to the
``TRANSIENT`` default, so callers retried a model that can never answer again.
"""

from __future__ import annotations

import pytest

from agentic_v2.core.errors import ErrorCode, classify_error
from agentic_v2.models.retry_utils import compute_retry_delay

_NIM_410 = (
    "APIStatusError: Error code: 410 - {'type': 'about:blank', 'title': 'Gone', "
    "'status': 410, 'detail': \"The model 'meta/llama-3.1-8b-instruct' has "
    'reached its end of life on 2026-08-26T09:00:00Z and is no longer available."}'
)


class TestModelRetired:
    def test_nim_410_body_is_retired_and_not_retryable(self) -> None:
        assert classify_error(_NIM_410) == (ErrorCode.MODEL_RETIRED, False)

    def test_end_of_life_wording_without_a_status_is_retired(self) -> None:
        message = "The model 'x/y' has reached its end of life and is gone."
        assert classify_error(message) == (ErrorCode.MODEL_RETIRED, False)

    @pytest.mark.parametrize(
        "message",
        ["upstream stalled after 4100ms", "request id 84102 failed", "port 14103"],
    )
    def test_410_inside_a_longer_number_is_not_retired(self, message: str) -> None:
        assert classify_error(message) == (ErrorCode.TRANSIENT, True)

    def test_rate_limit_wins_over_a_stray_410(self) -> None:
        message = "429 Too Many Requests: retry after 410 seconds"
        assert classify_error(message) == (ErrorCode.RATE_LIMITED, True)

    def test_404_is_still_not_found(self) -> None:
        message = "Error code: 404 - Function 'abc': Not found for account"
        assert classify_error(message) == (ErrorCode.NOT_FOUND, False)

    def test_wire_value_is_stable(self) -> None:
        # ChatErrorEvent.category carries this string to the UI.
        assert ErrorCode.MODEL_RETIRED.value == "model_retired"


class TestRetryLoopStopsOnRetiredModel:
    def test_compute_retry_delay_reraises_a_410(self) -> None:
        error = RuntimeError(_NIM_410)
        with pytest.raises(RuntimeError, match="end of life"):
            compute_retry_delay(
                error,
                attempt=0,
                max_retries=3,
                base_delay=1.0,
                max_delay=30.0,
                jitter=0.0,
                func_name="test",
            )
