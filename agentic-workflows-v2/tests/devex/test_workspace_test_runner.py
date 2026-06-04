"""Unit tests for agentic_v2.devex.workspace_test_runner."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from agentic_v2.devex.workspace_test_runner import PACKAGES, run_all, run_package_tests

# ---------------------------------------------------------------------------
# run_package_tests
# ---------------------------------------------------------------------------


def test_run_package_tests_returns_true_on_zero_exit() -> None:
    """returncode 0 maps to (True, output)."""
    mock_result = MagicMock()
    mock_result.returncode = 0
    mock_result.stdout = "1 passed in 0.1s\n"
    mock_result.stderr = ""

    with patch("agentic_v2.devex.workspace_test_runner.subprocess.run", return_value=mock_result) as mock_run:
        passed, output = run_package_tests(PACKAGES[0])

    assert passed is True
    assert "1 passed" in output
    mock_run.assert_called_once()


def test_run_package_tests_returns_false_on_nonzero_exit() -> None:
    """returncode 1 maps to (False, output)."""
    mock_result = MagicMock()
    mock_result.returncode = 1
    mock_result.stdout = ""
    mock_result.stderr = "FAILED test_foo.py::test_bar\n"

    with patch("agentic_v2.devex.workspace_test_runner.subprocess.run", return_value=mock_result):
        passed, output = run_package_tests(PACKAGES[0])

    assert passed is False
    assert "FAILED" in output


# ---------------------------------------------------------------------------
# run_all
# ---------------------------------------------------------------------------


def test_run_all_returns_true_when_all_pass() -> None:
    """run_all returns True when every package exits 0."""
    passing = MagicMock(returncode=0, stdout="3 passed\n", stderr="")

    with patch("agentic_v2.devex.workspace_test_runner.subprocess.run", return_value=passing):
        result = run_all()

    assert result is True


def test_run_all_returns_false_when_one_fails() -> None:
    """run_all returns False when any package exits non-zero."""
    def _side_effect(cmd: list, **kwargs: object) -> MagicMock:
        mock = MagicMock()
        # Fail for the second package (agentic-v2-eval)
        mock.returncode = 1 if "agentic-v2-eval" in str(kwargs.get("cwd", "")) else 0
        mock.stdout = ""
        mock.stderr = "1 failed\n" if mock.returncode else "ok\n"
        return mock

    with patch("agentic_v2.devex.workspace_test_runner.subprocess.run", side_effect=_side_effect):
        result = run_all()

    assert result is False


def test_run_all_package_filter_runs_only_named_package() -> None:
    """--package filter invokes subprocess exactly once for the named package."""
    passing = MagicMock(returncode=0, stdout="1 passed\n", stderr="")

    with patch("agentic_v2.devex.workspace_test_runner.subprocess.run", return_value=passing) as mock_run:
        result = run_all(package_filter="agentic-workflows-v2")

    assert result is True
    assert mock_run.call_count == 1
    called_cwd = mock_run.call_args.kwargs.get("cwd") or mock_run.call_args[1].get("cwd", "")
    assert "agentic-workflows-v2" in str(called_cwd)
