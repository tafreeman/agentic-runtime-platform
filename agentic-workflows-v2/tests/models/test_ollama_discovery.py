"""Tests for live Ollama discovery via the raw REST API (ADR-037).

Network is always mocked at ``httpx.get``. Covers local-only discovery, the
key-gated cloud source, cloud classification (remote_host vs suffix), the
``running`` flag from /api/ps, and best-effort failure handling.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from agentic_v2.models import ollama_discovery
from agentic_v2.models.ollama_discovery import discover_ollama_models

_LOCAL_TAGS = "http://localhost:11434/api/tags"
_LOCAL_PS = "http://localhost:11434/api/ps"
_CLOUD_TAGS = "https://ollama.com/api/tags"


class _FakeResponse:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:  # pragma: no cover - trivial
        return None

    def json(self) -> dict[str, Any]:
        return self._payload


def _install_fake_get(
    monkeypatch: pytest.MonkeyPatch,
    routes: dict[str, dict[str, Any]],
    calls: list[tuple[str, dict[str, str] | None]],
) -> None:
    """Patch ollama_discovery.httpx.get to serve ``routes`` and record calls."""

    def _fake_get(url: str, headers: dict[str, str] | None = None, timeout: Any = None):
        calls.append((url, headers))
        if url not in routes:
            raise httpx.ConnectError(f"unreachable: {url}")
        return _FakeResponse(routes[url])

    monkeypatch.setattr(ollama_discovery.httpx, "get", _fake_get)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OLLAMA_API_KEY", raising=False)
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)


@pytest.mark.unit
def test_local_only_parses_capabilities_and_running(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No key: only the local server is queried; capabilities + running parsed."""
    calls: list[tuple[str, dict[str, str] | None]] = []
    routes = {
        _LOCAL_PS: {"models": [{"name": "gemma4:31b"}]},
        _LOCAL_TAGS: {
            "models": [
                {
                    "name": "gemma4:31b",
                    "capabilities": ["completion", "tools", "thinking"],
                    "size": 19868981791,
                },
                {"name": "qwen3-coder:30b", "capabilities": ["completion"]},
            ]
        },
    }
    _install_fake_get(monkeypatch, routes, calls)

    result = discover_ollama_models()

    ids = [m.id for m in result]
    assert ids == ["ollama:gemma4:31b", "ollama:qwen3-coder:30b"]
    gemma = result[0]
    assert gemma.cloud is False
    assert gemma.running is True  # present in /api/ps
    assert gemma.capabilities == ("completion", "tools", "thinking")
    assert gemma.size == 19868981791
    assert result[1].running is False
    # Cloud endpoint must not be touched without a key.
    assert all(url != _CLOUD_TAGS for url, _ in calls)


@pytest.mark.unit
def test_cloud_merged_and_forced_cloud_when_key_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With a key: local + cloud merge, dups drop, cloud entries marked cloud."""
    monkeypatch.setenv("OLLAMA_API_KEY", "secret-key")
    calls: list[tuple[str, dict[str, str] | None]] = []
    routes = {
        _LOCAL_PS: {"models": []},
        _LOCAL_TAGS: {"models": [{"name": "qwen3-coder:30b"}]},
        _CLOUD_TAGS: {
            "models": [
                {"name": "gpt-oss:120b-cloud"},
                {"name": "qwen3-coder:30b"},  # duplicate of local — dropped
            ]
        },
    }
    _install_fake_get(monkeypatch, routes, calls)

    result = discover_ollama_models()

    ids = [m.id for m in result]
    assert ids == ["ollama:qwen3-coder:30b", "ollama:gpt-oss:120b-cloud"]
    cloud = result[1]
    assert cloud.cloud is True  # forced for the hosted source
    # The cloud request carried a bearer token.
    cloud_call = next((h for url, h in calls if url == _CLOUD_TAGS), None)
    assert cloud_call is not None
    assert cloud_call.get("Authorization") == "Bearer secret-key"


@pytest.mark.unit
def test_remote_host_marks_local_entry_as_cloud(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A local /api/tags entry with remote_host (signed-in proxy) is cloud."""
    calls: list[tuple[str, dict[str, str] | None]] = []
    routes = {
        _LOCAL_PS: {"models": []},
        _LOCAL_TAGS: {
            "models": [{"name": "glm-4.7", "remote_host": "ollama.com"}],
        },
    }
    _install_fake_get(monkeypatch, routes, calls)

    result = discover_ollama_models()

    assert len(result) == 1
    assert result[0].id == "ollama:glm-4.7"
    assert result[0].cloud is True
    assert result[0].remote_host == "ollama.com"


@pytest.mark.unit
@pytest.mark.parametrize("name", ["foo:cloud", "bar-cloud"])
def test_suffix_fallback_marks_cloud(
    monkeypatch: pytest.MonkeyPatch, name: str
) -> None:
    """Without remote markers, the :cloud / -cloud suffix classifies as cloud."""
    calls: list[tuple[str, dict[str, str] | None]] = []
    routes = {_LOCAL_PS: {"models": []}, _LOCAL_TAGS: {"models": [{"name": name}]}}
    _install_fake_get(monkeypatch, routes, calls)

    result = discover_ollama_models()
    assert result[0].cloud is True


@pytest.mark.unit
def test_ps_failure_does_not_break_tags(monkeypatch: pytest.MonkeyPatch) -> None:
    """An unreachable /api/ps yields running=False but tags still parse."""
    calls: list[tuple[str, dict[str, str] | None]] = []
    routes = {_LOCAL_TAGS: {"models": [{"name": "gemma4:31b"}]}}  # no /api/ps route
    _install_fake_get(monkeypatch, routes, calls)

    result = discover_ollama_models()
    assert [m.id for m in result] == ["ollama:gemma4:31b"]
    assert result[0].running is False


@pytest.mark.unit
def test_unreachable_local_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    """A totally unreachable local server yields an empty list, not an error."""
    calls: list[tuple[str, dict[str, str] | None]] = []
    _install_fake_get(monkeypatch, routes={}, calls=calls)

    assert discover_ollama_models() == []


@pytest.mark.unit
def test_to_dict_is_json_shaped() -> None:
    """OllamaModelInfo.to_dict exposes the API-facing field names."""
    info = ollama_discovery.OllamaModelInfo(
        id="ollama:x", name="x", cloud=True, capabilities=("tools",), running=True
    )
    assert info.to_dict() == {
        "id": "ollama:x",
        "name": "x",
        "cloud": True,
        "capabilities": ["tools"],
        "running": True,
        "size": None,
        "remote_host": None,
    }


@pytest.mark.unit
def test_malformed_entries_degrade_gracefully(monkeypatch: pytest.MonkeyPatch) -> None:
    """Untrusted wire shapes never raise and never produce garbage:

    non-dict entries, non-string/empty names, a bare-string ``capabilities``
    (must not split into characters), and empty capability strings.
    """
    routes = {
        _LOCAL_PS: {"models": []},
        _LOCAL_TAGS: {
            "models": [
                "not-a-dict",  # skipped
                {"name": 123},  # non-string name -> skipped (would crash startswith)
                {"name": ""},  # empty name -> skipped
                {"name": "good:1b", "capabilities": "tools"},  # string -> () not chars
                {"name": "good:2b", "capabilities": ["completion", "", "tools"]},
                {"name": "good:3b", "size": "not-an-int"},  # bad size -> None
            ]
        },
    }
    _install_fake_get(monkeypatch, routes, [])

    result = discover_ollama_models()

    assert [m.id for m in result] == [
        "ollama:good:1b",
        "ollama:good:2b",
        "ollama:good:3b",
    ]
    assert result[0].capabilities == ()  # bare string not iterated char-by-char
    assert result[1].capabilities == ("completion", "tools")  # empty string dropped
    assert result[2].size is None


@pytest.mark.unit
def test_non_dict_json_response_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A JSON array/scalar body (not an object) yields no models, no error."""

    class _ListResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> Any:
            return ["a", "b"]  # not a dict

    monkeypatch.setattr(
        ollama_discovery.httpx,
        "get",
        lambda url, headers=None, timeout=None: _ListResponse(),
    )

    assert discover_ollama_models() == []


@pytest.mark.unit
def test_remote_model_marks_cloud(monkeypatch: pytest.MonkeyPatch) -> None:
    """remote_model (without remote_host) also classifies a model as cloud."""
    routes = {
        _LOCAL_PS: {"models": []},
        _LOCAL_TAGS: {"models": [{"name": "glm-4.7", "remote_model": "glm-4.7"}]},
    }
    _install_fake_get(monkeypatch, routes, [])

    result = discover_ollama_models()
    assert result[0].cloud is True


@pytest.mark.unit
def test_ps_running_fallback_to_model_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """/api/ps entries keyed by 'model' (not 'name') still set running."""
    routes = {
        _LOCAL_PS: {"models": [{"model": "llama2:7b"}]},
        _LOCAL_TAGS: {"models": [{"name": "llama2:7b"}]},
    }
    _install_fake_get(monkeypatch, routes, [])

    result = discover_ollama_models()
    assert result[0].running is True


@pytest.mark.unit
def test_empty_and_missing_models_return_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Missing 'models' key and null 'models' both degrade to an empty list."""
    routes = {_LOCAL_PS: {}, _LOCAL_TAGS: {"models": None}}
    _install_fake_get(monkeypatch, routes, [])

    assert discover_ollama_models() == []


@pytest.mark.unit
def test_timeout_is_passed_to_httpx(monkeypatch: pytest.MonkeyPatch) -> None:
    """Each probe call carries the bounded timeout so the endpoint can't hang."""
    captured: dict[str, Any] = {}

    class _Resp:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return {"models": []}

    def _fake_get(url: str, headers: Any = None, timeout: Any = None):
        captured["timeout"] = timeout
        return _Resp()

    monkeypatch.setattr(ollama_discovery.httpx, "get", _fake_get)

    discover_ollama_models()
    assert captured["timeout"] == 5.0


@pytest.mark.unit
def test_api_key_never_appears_in_logs(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """The bearer key must never reach the debug logs, even on the error path."""
    import logging

    monkeypatch.setenv("OLLAMA_API_KEY", "super-secret-token")

    def _boom(url: str, headers: Any = None, timeout: Any = None):
        raise httpx.ConnectError("boom")

    monkeypatch.setattr(ollama_discovery.httpx, "get", _boom)

    with caplog.at_level(logging.DEBUG, logger="agentic_v2.models.ollama_discovery"):
        result = discover_ollama_models()

    assert result == []
    assert "super-secret-token" not in caplog.text
