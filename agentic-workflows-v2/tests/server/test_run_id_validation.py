"""Regression tests for WorkflowRunRequest.run_id path-traversal protection.

The field_validator at ``server/models.py:81-90`` uses
``^[a-zA-Z0-9_-]{1,128}$`` which rejects anything outside alphanumeric +
hyphen + underscore. These tests form the canonical negative corpus that
locks in regression coverage against path-traversal attempts via a
user-supplied ``run_id`` in ``POST /api/run``.

Ticket: Sprint 1 — S1-03 (closes Test H5).
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from agentic_v2.server.models import WorkflowRunRequest

pytestmark = pytest.mark.security


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_request(run_id: str | None) -> WorkflowRunRequest:
    """Instantiate a minimal ``WorkflowRunRequest`` with the given ``run_id``.

    All other fields default, so the validator under test is exercised in
    isolation.
    """
    return WorkflowRunRequest(workflow="test_wf", run_id=run_id)


# ---------------------------------------------------------------------------
# Positive cases (must NOT raise)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "valid_id",
    [
        "my-run_01",
        "abc",
        "A1-B2_C3",
        "a" * 128,  # max length
        "RUN-2026-04-27",
        "sprint1_ticket03",
        "valid-id_123",  # minimum positive control from ticket brief
    ],
)
def test_valid_run_id_accepted(valid_id: str) -> None:
    """Valid ``run_id`` values pass through the validator unchanged."""
    req = _make_request(valid_id)
    assert req.run_id == valid_id


def test_none_run_id_accepted() -> None:
    """``None`` is explicitly allowed by the validator (auto-generated later)."""
    req = _make_request(None)
    assert req.run_id is None


# ---------------------------------------------------------------------------
# Path traversal corpus (must ALL raise ValidationError)
# ---------------------------------------------------------------------------


_PATH_TRAVERSAL_CORPUS = [
    "../etc/passwd",
    "../../etc/passwd",  # POSIX traversal (from ticket brief minimum corpus)
    "../../windows/system32",
    "..\\..\\windows",  # Windows traversal (from ticket brief minimum corpus)
    "../../.env",
    "../../../root/.ssh/id_rsa",
    ".",
    "..",
    "../",
    "./",
    "/etc/passwd",
    "/root",
    "\\..\\..\\windows",
    "run/../../../etc",
    "a/b/c",  # slash (from ticket brief minimum corpus)
]


@pytest.mark.parametrize("bad_id", _PATH_TRAVERSAL_CORPUS)
def test_path_traversal_rejected(bad_id: str) -> None:
    """Every path-traversal attempt raises ``ValidationError``."""
    with pytest.raises(ValidationError):
        _make_request(bad_id)


# ---------------------------------------------------------------------------
# Injection corpus
# ---------------------------------------------------------------------------


_INJECTION_CORPUS = [
    "run; rm -rf /",  # shell metachar
    "run && cat /etc/passwd",  # chained command
    "run`id`",  # backtick substitution
    "run$(id)",  # dollar substitution
    "run\x00etc",  # null byte
    "\x00xyz",  # null byte prefix (from ticket brief minimum corpus)
    "run\necho injected",  # newline injection
    "\uff52\uff55\uff4e",  # unicode fullwidth (r-u-n)
    "run<script>",  # HTML injection
    "a" * 129,  # exceeds max length
    "a" * 65,  # boundary case from ticket brief minimum corpus (still > 64,
    # within 128 allowed — note: this is a POSITIVE case per the live
    # validator; see the separate positive test below).
    "",  # empty string (from ticket brief minimum corpus)
    " ",  # whitespace only
    "run id",  # space in id
]


# The ticket summary lists ``"a" * 65`` as "too long" under a 64-char limit,
# but the live validator uses a 1-128 limit (per the ticket Scope section:
# "128 limit is already deployed; do not regress existing behavior"). So
# ``"a" * 65`` must ACTUALLY be accepted. Move it out of the reject corpus.
_INJECTION_CORPUS = [value for value in _INJECTION_CORPUS if value != "a" * 65]


@pytest.mark.parametrize("bad_id", _INJECTION_CORPUS)
def test_injection_corpus_rejected(bad_id: str) -> None:
    """Every injection attempt raises ``ValidationError``."""
    with pytest.raises(ValidationError):
        _make_request(bad_id)


def test_65_char_run_id_accepted_under_128_char_limit() -> None:
    """The live validator allows up to 128 chars, so ``"a" * 65`` is valid.

    The ticket orchestrator's summary listed ``"a" * 65`` as "too long",
    but that reflects a superseded 64-char limit. The Scope section of the
    ticket brief pins the live behavior at 128 — this test locks that in.
    """
    req = _make_request("a" * 65)
    assert req.run_id == "a" * 65
