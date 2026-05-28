"""Unit tests for the ``AGENTIC_NO_LLM=1`` short-circuit in ``models/client.py``.

Covers:
  - ``Settings.agentic_no_llm`` field driving ``get_client()``
  - ``MockBackend`` installation under the flag (with the shared
    ``PLACEHOLDER_RESPONSE_TEXT`` from ``models/backends.py``)
  - No-regression sentinels for the flag-unset path, including a probe-
    was-called assertion that closes the keyless-box trivial-pass gap
    (MED-3 from the Sprint B #5 review)
"""

from __future__ import annotations

import pytest

from agentic_v2.settings import get_settings
from agentic_v2.models.client import get_client, reset_client
from agentic_v2.models.backends import MockBackend

_PLACEHOLDER_PREFIX = "[AGENTIC_NO_LLM placeholder]"


@pytest.fixture(autouse=True)
def _isolate_client_and_settings(monkeypatch):
    """Reset all singleton state before and after every test in this module.

    The autouse=True on the root conftest._reset_llm_client fixture still
    fires, but that fixture calls get_client(auto_configure=False).  We need
    full reset so env changes are visible; we add a second teardown here that
    is scoped only to these tests.
    """
    get_settings.cache_clear()
    reset_client()
    yield
    get_settings.cache_clear()
    reset_client()


@pytest.mark.unit
def test_flag_installs_mock_backend_and_placeholder_prefix(monkeypatch):
    """AGENTIC_NO_LLM=1 must cause get_client() to install a MockBackend
    whose default_response starts with the placeholder prefix.

    FAILS today: Settings has no agentic_no_llm field; get_client() never
    installs MockBackend based on that flag.
    """
    monkeypatch.setenv("AGENTIC_NO_LLM", "1")
    get_settings.cache_clear()
    reset_client()

    client = get_client(auto_configure=True)

    assert isinstance(client.backend, MockBackend), (
        f"Expected MockBackend when AGENTIC_NO_LLM=1, got {type(client.backend)}"
    )
    assert client.backend.default_response.startswith(_PLACEHOLDER_PREFIX), (
        f"default_response {client.backend.default_response!r} does not start "
        f"with {_PLACEHOLDER_PREFIX!r}"
    )


@pytest.mark.unit
def test_flag_unset_still_probes_providers(monkeypatch):
    """When AGENTIC_NO_LLM is absent, get_client(auto_configure=True) must
    actually attempt provider probing AND must NOT install MockBackend.

    This is a no-regression control.  MED-3 from Sprint B #5 review: the
    previous version of this test only asserted ``not isinstance(MockBackend)``,
    which passes vacuously on a keyless developer box (backend = None because
    auto_configure_backend raised a swallowed RuntimeError).  To catch a
    regression where someone installs MockBackend unconditionally BEFORE the
    probe path, we now monkeypatch ``auto_configure_backend`` and assert it
    was called, so the test also proves the branch was taken.
    """
    monkeypatch.delenv("AGENTIC_NO_LLM", raising=False)
    get_settings.cache_clear()
    reset_client()

    from agentic_v2.models import backends

    probe_calls: list[bool] = []
    original = backends.auto_configure_backend

    def _tracked() -> object:
        probe_calls.append(True)
        return original()

    monkeypatch.setattr(backends, "auto_configure_backend", _tracked)

    client = get_client(auto_configure=True)

    assert probe_calls, (
        "auto_configure_backend was never called — get_client() skipped the "
        "probe path entirely (regression: MockBackend may have been installed "
        "unconditionally before the probe branch)."
    )
    assert not isinstance(client.backend, MockBackend), (
        "MockBackend must NOT be installed when AGENTIC_NO_LLM is unset"
    )


@pytest.mark.unit
async def test_complete_chat_returns_placeholder_under_flag(monkeypatch):
    """complete_chat() on the MockBackend installed under the flag must return
    a dict with content starting with the placeholder prefix and tool_calls=None.

    FAILS today: MockBackend is never installed by the flag path.
    """
    monkeypatch.setenv("AGENTIC_NO_LLM", "1")
    get_settings.cache_clear()
    reset_client()

    client = get_client(auto_configure=True)

    assert isinstance(client.backend, MockBackend), (
        "Prerequisite: MockBackend must be installed — failing due to missing "
        "production code for AGENTIC_NO_LLM flag."
    )

    result = await client.backend.complete_chat(
        "fake-model",
        [{"role": "user", "content": "hi"}],
    )

    assert isinstance(result, dict), f"Expected dict, got {type(result)}"
    assert result["content"].startswith(_PLACEHOLDER_PREFIX), (
        f"content {result['content']!r} does not start with {_PLACEHOLDER_PREFIX!r}"
    )
    assert result["tool_calls"] is None, (
        f"tool_calls should be None, got {result['tool_calls']!r}"
    )


@pytest.mark.unit
def test_reset_client_plus_cache_clear_reflects_env_change(monkeypatch):
    """Flipping AGENTIC_NO_LLM and calling cache_clear() + reset_client()
    must switch the installed backend from non-Mock to Mock.

    FAILS today: same root cause as test 1 — flag path not wired.
    """
    # Phase A: flag absent — should NOT be MockBackend
    monkeypatch.delenv("AGENTIC_NO_LLM", raising=False)
    get_settings.cache_clear()
    reset_client()

    client_before = get_client(auto_configure=True)
    assert not isinstance(client_before.backend, MockBackend), (
        "Phase A: MockBackend must NOT be installed when flag is absent"
    )

    # Phase B: flip flag on, bust caches, get a fresh client
    monkeypatch.setenv("AGENTIC_NO_LLM", "1")
    get_settings.cache_clear()
    reset_client()

    client_after = get_client(auto_configure=True)
    assert isinstance(client_after.backend, MockBackend), (
        "Phase B: MockBackend must be installed after AGENTIC_NO_LLM=1 + cache_clear() + reset_client()"
    )


# ---------------------------------------------------------------------------
# P2 (Sprint B #5 follow-up): AGENTIC_NO_LLM truthiness
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "raw, expected",
    [
        # True literals (case-insensitive)
        ("1", True),
        ("true", True),
        ("True", True),
        ("TRUE", True),
        ("yes", True),
        ("on", True),
        # False literals
        ("0", False),
        ("false", False),
        ("False", False),
        ("no", False),
        ("off", False),
        ("", False),
        # Surrounding whitespace (common in shell env exports)
        ("  1  ", True),
        (" false ", False),
        # Unknown values: coerce to False with a logged warning
        ("2", False),
        ("yess", False),
        ("gibberish", False),
    ],
)
def test_agentic_no_llm_truthiness(monkeypatch, raw, expected):
    """The ``agentic_no_llm`` field validator must normalise common bool-ish
    strings and coerce unknowns to False rather than raise ``ValidationError``
    (P2 from Sprint B #5 follow-up review).
    """
    monkeypatch.setenv("AGENTIC_NO_LLM", raw)
    get_settings.cache_clear()

    assert get_settings().agentic_no_llm is expected, (
        f"AGENTIC_NO_LLM={raw!r} should coerce to {expected}"
    )
