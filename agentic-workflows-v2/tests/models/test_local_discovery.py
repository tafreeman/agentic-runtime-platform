"""Tests for LM Studio + ONNX local discovery (ADR-038).

LM Studio HTTP is mocked at ``httpx.get`` with a per-URL router so native vs
OpenAI-shim endpoints and the :1234 / :12340 candidate ports can be exercised
independently. ONNX discovery runs against real temp directory trees (no
network), with the ``~/.cache/aigallery`` default root patched to a temp path so
tests never depend on the developer's real model cache.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import httpx
import pytest

from agentic_v2.models import local_discovery
from agentic_v2.models.local_discovery import (
    LmStudioLoadError,
    LmStudioUnavailableError,
    discover_lmstudio_models,
    discover_onnx_models,
    load_lmstudio_model,
    parse_onnx_roots,
    resolve_lmstudio_host,
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in (
        "LMSTUDIO_HOST",
        "LM_STUDIO_HOST",
        "LM_API_TOKEN",
        "ONNX_MODEL_DIR",
        "AIGALLERY_CACHE",
    ):
        monkeypatch.delenv(var, raising=False)
    # resolve_lmstudio_host is lru_cached; reset between tests so env changes
    # (and the :1234/:12340 probe order) are re-evaluated per test.
    resolve_lmstudio_host.cache_clear()


# ---------------------------------------------------------------------------
# LM Studio — per-URL HTTP router
# ---------------------------------------------------------------------------

_V1 = "/api/v1/models"
_NATIVE = "/api/v0/models"
_OPENAI = "/v1/models"


class _Resp:
    """Minimal httpx-response double.

    ``status >= 400`` raises on check.
    """

    def __init__(self, payload: Any, status: int = 200) -> None:
        self._payload = payload
        self._status = status
        self.status_code = status

    def raise_for_status(self) -> None:
        if self._status >= 400:
            raise RuntimeError(f"HTTP {self._status}")

    def json(self) -> Any:
        return self._payload


def _route(monkeypatch: pytest.MonkeyPatch, routes: dict[str, _Resp]) -> list[str]:
    """Install a ``httpx.get`` that serves ``routes``; unknown URLs are 'down'.

    Returns a list that records every URL probed, in order.
    """
    calls: list[str] = []

    def _fake_get(url: str, headers: Any = None, timeout: Any = None):
        calls.append(url)
        resp = routes.get(url)
        if resp is None:
            raise httpx.ConnectError("connection refused")
        return resp

    monkeypatch.setattr(local_discovery.httpx, "get", _fake_get)
    return calls


class TestDiscoverLmStudioV1:
    def test_v1_lists_library_instances_and_capabilities(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("LMSTUDIO_HOST", "http://127.0.0.1:1234")
        calls = _route(
            monkeypatch,
            {
                f"http://127.0.0.1:1234{_V1}": _Resp(
                    {
                        "models": [
                            {
                                "key": "google/gemma-3-12b",
                                "type": "llm",
                                "loaded_instances": [{"id": "instance-1"}],
                                "capabilities": {
                                    "vision": True,
                                    "trained_for_tool_use": True,
                                    "reasoning": {"supported": True},
                                },
                            },
                            {
                                "key": "qwen/qwen3-8b",
                                "type": "llm",
                                "loaded_instances": [],
                                "capabilities": {},
                            },
                            {"key": "tts", "type": "llm"},
                            {"key": "nomic-embed-text", "type": "embedding"},
                        ]
                    }
                )
            },
        )

        result = discover_lmstudio_models()
        by_id = {info.id: info for info in result}

        assert [info.id for info in result] == [
            "lmstudio:google/gemma-3-12b",
            "lmstudio:qwen/qwen3-8b",
        ]
        assert by_id["lmstudio:google/gemma-3-12b"].running is True
        assert by_id["lmstudio:google/gemma-3-12b"].capabilities == (
            "vision",
            "tools",
            "reasoning",
        )
        assert by_id["lmstudio:qwen/qwen3-8b"].running is False
        assert calls == [f"http://127.0.0.1:1234{_V1}"]

    def test_v1_sends_optional_bearer_token(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("LMSTUDIO_HOST", "http://127.0.0.1:1234")
        monkeypatch.setenv("LM_API_TOKEN", "lm-test-token")
        seen: dict[str, Any] = {}

        def _capture(url: str, headers: Any = None, timeout: Any = None) -> _Resp:
            seen.update(url=url, headers=headers or {})
            return _Resp({"models": []})

        monkeypatch.setattr(local_discovery.httpx, "get", _capture)

        assert discover_lmstudio_models() == []
        assert seen["url"] == f"http://127.0.0.1:1234{_V1}"
        assert seen["headers"]["Authorization"] == "Bearer lm-test-token"


class TestDiscoverLmStudioNative:
    def test_native_lists_full_library_with_type_and_state(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("LMSTUDIO_HOST", "http://127.0.0.1:1234")
        _route(
            monkeypatch,
            {
                f"http://127.0.0.1:1234{_NATIVE}": _Resp(
                    {
                        "data": [
                            {
                                "id": "google/gemma-3-12b",
                                "type": "llm",
                                "state": "loaded",
                            },
                            {"id": "qwen2-vl-7b", "type": "vlm", "state": "not-loaded"},
                            {"id": "qwen3-tts", "type": "llm"},
                            {"id": "nomic-embed-text", "type": "embeddings"},
                        ]
                    }
                )
            },
        )

        result = discover_lmstudio_models()
        by_id = {info.id: info for info in result}

        # Embeddings dropped by type; chat + vision kept.
        assert [info.id for info in result] == [
            "lmstudio:google/gemma-3-12b",
            "lmstudio:qwen2-vl-7b",
        ]
        # state → running; vlm → vision badge.
        assert by_id["lmstudio:google/gemma-3-12b"].running is True
        assert by_id["lmstudio:qwen2-vl-7b"].running is False
        assert by_id["lmstudio:qwen2-vl-7b"].capabilities == ("vision",)
        assert by_id["lmstudio:google/gemma-3-12b"].capabilities == ()

    def test_unknown_type_is_kept(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A missing/unexpected ``type`` degrades to 'list it', not 'drop it'."""
        monkeypatch.setenv("LMSTUDIO_HOST", "http://127.0.0.1:1234")
        _route(
            monkeypatch,
            {f"http://127.0.0.1:1234{_NATIVE}": _Resp({"data": [{"id": "mystery"}]})},
        )
        assert [info.id for info in discover_lmstudio_models()] == ["lmstudio:mystery"]

    def test_malformed_entries_skipped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LMSTUDIO_HOST", "http://127.0.0.1:1234")
        _route(
            monkeypatch,
            {
                f"http://127.0.0.1:1234{_NATIVE}": _Resp(
                    {
                        "data": [
                            "x",
                            {"id": ""},
                            {"id": "ok", "type": "llm"},
                            {"no_id": 1},
                        ]
                    }
                )
            },
        )
        assert [info.id for info in discover_lmstudio_models()] == ["lmstudio:ok"]


class TestDiscoverLmStudioFallback:
    def test_falls_back_to_openai_shim_when_native_absent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Older servers without /api/v0 still surface via /v1 (name-filtered)."""
        monkeypatch.setenv("LMSTUDIO_HOST", "http://127.0.0.1:1234")
        calls = _route(
            monkeypatch,
            {
                f"http://127.0.0.1:1234{_NATIVE}": _Resp(None, status=404),
                f"http://127.0.0.1:1234{_OPENAI}": _Resp(
                    {"data": [{"id": "gemma-3-12b"}, {"id": "text-embedding-nomic"}]}
                ),
            },
        )
        result = discover_lmstudio_models()
        # Current v1 and legacy v0 are tried before the OpenAI shim.
        assert calls == [
            f"http://127.0.0.1:1234{_V1}",
            f"http://127.0.0.1:1234{_NATIVE}",
            f"http://127.0.0.1:1234{_OPENAI}",
        ]
        assert [info.id for info in result] == ["lmstudio:gemma-3-12b"]
        # The shim lists only loaded models, so every record is running;
        # it carries no type field, so no capability badges.
        assert result[0].running is True
        assert result[0].capabilities == ()

    def test_catalog_records_which_api_answered(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The catalog pins the API variant so load actions can be gated.

        Regression: the load route POSTed the v1 load endpoint even when
        discovery had fallen back to a pre-v1 API where it can only 404.
        """
        monkeypatch.setenv("LMSTUDIO_HOST", "http://127.0.0.1:1234")
        _route(
            monkeypatch,
            {
                f"http://127.0.0.1:1234{_NATIVE}": _Resp(
                    {
                        "data": [
                            {"id": "gemma-3-4b", "type": "llm", "state": "not-loaded"}
                        ]
                    }
                ),
            },
        )
        catalog = local_discovery.discover_lmstudio_catalog()
        assert catalog.api == "v0"
        assert catalog.supports_load is False
        assert [info.id for info in catalog.models] == ["lmstudio:gemma-3-4b"]

        _route(
            monkeypatch,
            {
                f"http://127.0.0.1:1234{_OPENAI}": _Resp(
                    {"data": [{"id": "gemma-3-12b"}]}
                ),
            },
        )
        catalog = local_discovery.discover_lmstudio_catalog()
        assert catalog.api == "openai"
        assert catalog.supports_load is False

        _route(
            monkeypatch,
            {
                f"http://127.0.0.1:1234{_V1}": _Resp(
                    {"models": [{"key": "gemma-3-4b", "type": "llm"}]}
                ),
            },
        )
        catalog = local_discovery.discover_lmstudio_catalog()
        assert catalog.api == "v1"
        assert catalog.supports_load is True

    def test_server_down_returns_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LMSTUDIO_HOST", "http://127.0.0.1:1234")
        _route(monkeypatch, {})  # every URL → ConnectError
        assert discover_lmstudio_models() == []


class TestDiscoverLmStudioPorts:
    def test_probes_1234_before_12340(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """With no LMSTUDIO_HOST, the standard port wins over the legacy one."""
        _route(
            monkeypatch,
            {
                f"http://127.0.0.1:1234{_NATIVE}": _Resp(
                    {"data": [{"id": "a", "type": "llm"}]}
                ),
                f"http://127.0.0.1:12340{_NATIVE}": _Resp(
                    {"data": [{"id": "b", "type": "llm"}]}
                ),
            },
        )
        assert [info.id for info in discover_lmstudio_models()] == ["lmstudio:a"]

    def test_falls_through_to_12340_when_1234_down(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _route(
            monkeypatch,
            {
                f"http://127.0.0.1:12340{_NATIVE}": _Resp(
                    {"data": [{"id": "b", "type": "llm"}]}
                )
            },
        )
        assert [info.id for info in discover_lmstudio_models()] == ["lmstudio:b"]

    def test_explicit_host_strips_v1_suffix(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """LMSTUDIO_HOST given with /v1 is normalized before paths are appended."""
        monkeypatch.setenv("LMSTUDIO_HOST", "http://127.0.0.1:4321/v1/")
        calls = _route(
            monkeypatch,
            {f"http://127.0.0.1:4321{_NATIVE}": _Resp({"data": [{"id": "m"}]})},
        )
        assert [info.id for info in discover_lmstudio_models()] == ["lmstudio:m"]
        assert calls[:2] == [
            f"http://127.0.0.1:4321{_V1}",
            f"http://127.0.0.1:4321{_NATIVE}",
        ]


class TestResolveLmStudioHost:
    def test_explicit_host_honored_without_probing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("LMSTUDIO_HOST", "http://127.0.0.1:9999/v1")
        calls = _route(monkeypatch, {})  # would ConnectError if probed
        assert resolve_lmstudio_host() == "http://127.0.0.1:9999"
        assert calls == []  # pinned host → no probe

    def test_result_is_cached_no_reprobe_per_call(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Repeated calls (the backend's per-request path) probe only once."""
        calls = _route(
            monkeypatch,
            {f"http://127.0.0.1:1234{_NATIVE}": _Resp({"data": []})},
        )
        first = resolve_lmstudio_host()
        second = resolve_lmstudio_host()
        assert first == second == "http://127.0.0.1:1234"
        # Second call hit the lru_cache — no additional network probe.
        assert calls == [
            f"http://127.0.0.1:1234{_V1}",
            f"http://127.0.0.1:1234{_NATIVE}",
        ]

    def test_returns_first_reachable_default_port(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _route(
            monkeypatch,
            {f"http://127.0.0.1:12340{_NATIVE}": _Resp({"data": []})},
        )
        assert resolve_lmstudio_host() == "http://127.0.0.1:12340"

    def test_falls_back_to_1234_when_nothing_reachable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _route(monkeypatch, {})
        assert resolve_lmstudio_host() == "http://127.0.0.1:1234"


class TestLoadLmStudioModel:
    def test_posts_native_v1_load_with_optional_auth(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("LMSTUDIO_HOST", "http://127.0.0.1:12340")
        monkeypatch.setenv("LM_API_TOKEN", "lm-test-token")
        captured: dict[str, Any] = {}

        def _fake_post(
            url: str,
            *,
            headers: Any = None,
            json: Any = None,
            timeout: Any = None,
        ) -> _Resp:
            captured.update(url=url, headers=headers, json=json, timeout=timeout)
            return _Resp(
                {
                    "type": "model_load_result",
                    "instance_id": "gemma-instance",
                    "load_time_seconds": 1.25,
                    "status": "loaded",
                }
            )

        monkeypatch.setattr(local_discovery.httpx, "post", _fake_post)

        result = load_lmstudio_model("google/gemma-3-4b")

        assert result["instance_id"] == "gemma-instance"
        assert captured["url"] == "http://127.0.0.1:12340/api/v1/models/load"
        assert captured["headers"] == {"Authorization": "Bearer lm-test-token"}
        assert captured["json"] == {"model": "google/gemma-3-4b"}
        assert captured["timeout"] == 300.0

    def test_unreachable_server_raises_typed_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("LMSTUDIO_HOST", "http://127.0.0.1:12340")

        def _unreachable(*args: Any, **kwargs: Any) -> None:
            raise httpx.ConnectError("connection refused")

        monkeypatch.setattr(local_discovery.httpx, "post", _unreachable)

        with pytest.raises(LmStudioUnavailableError, match="unavailable"):
            load_lmstudio_model("google/gemma-3-4b")

    def test_invalid_success_payload_raises_typed_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("LMSTUDIO_HOST", "http://127.0.0.1:12340")
        monkeypatch.setattr(
            local_discovery.httpx,
            "post",
            lambda *args, **kwargs: _Resp({"status": "loading"}),
        )

        with pytest.raises(LmStudioLoadError, match="invalid"):
            load_lmstudio_model("google/gemma-3-4b")


class TestResolveLmStudioHostContinued:
    def test_failed_resolution_not_cached(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A fallback result is not cached, so a server that starts later is still
        discovered."""
        calls = _route(monkeypatch, {})
        assert resolve_lmstudio_host() == "http://127.0.0.1:1234"
        # Each candidate host is probed on v1, v0, and OpenAI-compatible paths.
        assert len(calls) == 6  # 2 hosts × 3 paths

        # Server comes up on the legacy port — the next call must re-probe and find it.
        _route(
            monkeypatch,
            {f"http://127.0.0.1:12340{_NATIVE}": _Resp({"data": []})},
        )
        assert resolve_lmstudio_host() == "http://127.0.0.1:12340"

    def test_rescan_evicts_cached_resolution(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A rescan must drop the cached host so inference re-targets the new port.

        Without eviction, a process that first resolved :12340 keeps
        sending inference there even after LM Studio restarts on :1234
        and a rescan surfaces the :1234 models (Codex review #132).
        """
        # First inference resolves to :12340 (only it is up) and caches it.
        _route(
            monkeypatch,
            {f"http://127.0.0.1:12340{_NATIVE}": _Resp({"data": []})},
        )
        assert resolve_lmstudio_host() == "http://127.0.0.1:12340"

        # LM Studio moves to :1234. A rescan lists the new host's models...
        _route(
            monkeypatch,
            {f"http://127.0.0.1:1234{_NATIVE}": _Resp({"data": [{"id": "moved"}]})},
        )
        assert [info.id for info in discover_lmstudio_models()] == ["lmstudio:moved"]

        # ...and inference must follow it there, not the stale cached :12340.
        assert resolve_lmstudio_host() == "http://127.0.0.1:1234"


class TestLmStudioModelBuilder:
    def test_authenticated_server_uses_lm_api_token(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        langchain_openai = pytest.importorskip("langchain_openai")
        captured: dict[str, Any] = {}
        monkeypatch.setattr(
            langchain_openai,
            "ChatOpenAI",
            lambda **kwargs: captured.update(kwargs) or object(),
        )
        monkeypatch.setenv("LMSTUDIO_HOST", "http://127.0.0.1:1234")
        monkeypatch.setenv("LM_API_TOKEN", "lm-test-token")

        from agentic_v2.langchain.model_builders import build_lmstudio_model

        build_lmstudio_model("google/gemma-3-12b", 0.2)

        assert captured["model"] == "google/gemma-3-12b"
        assert captured["base_url"] == "http://127.0.0.1:1234/v1"
        assert captured["api_key"] == "lm-test-token"
        assert captured["temperature"] == 0.2


# ---------------------------------------------------------------------------
# ONNX
# ---------------------------------------------------------------------------


@pytest.fixture
def _isolated_default_root(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Point the aigallery default at an empty temp dir for deterministic tests."""
    default_root = tmp_path / "_default_aigallery"
    monkeypatch.setattr(local_discovery, "_ONNX_DEFAULT_ROOT", str(default_root))
    return default_root


def _make_model(root: Path, rel: str) -> None:
    folder = root / rel
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "genai_config.json").write_text("{}", encoding="utf-8")


class TestDiscoverOnnx:
    def test_finds_genai_config_models(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        _isolated_default_root: Path,
    ) -> None:
        root = tmp_path / "models"
        _make_model(root, "Microsoft/qwen3-14b/v2")
        _make_model(root, "phi4-mini")
        (root / "not-a-model").mkdir(parents=True)
        (root / "not-a-model" / "weights.onnx").write_text("x", encoding="utf-8")

        monkeypatch.setenv("ONNX_MODEL_DIR", str(root))

        result = sorted(info.id for info in discover_onnx_models())
        assert result == ["onnx:Microsoft/qwen3-14b/v2", "onnx:phi4-mini"]

    def test_scans_multiple_roots(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        _isolated_default_root: Path,
    ) -> None:
        """A pathsep-separated ONNX_MODEL_DIR surfaces models from every root."""
        root_a = tmp_path / "aitk"
        root_b = tmp_path / "foundry"
        _make_model(root_a, "Phi-4-mini-instruct")
        _make_model(root_b, "qwen3-0.6b")

        monkeypatch.setenv(
            "ONNX_MODEL_DIR", os.pathsep.join([str(root_a), str(root_b)])
        )

        result = sorted(info.id for info in discover_onnx_models())
        assert result == ["onnx:Phi-4-mini-instruct", "onnx:qwen3-0.6b"]

    def test_default_aigallery_root_scanned_when_unset(
        self, monkeypatch: pytest.MonkeyPatch, _isolated_default_root: Path
    ) -> None:
        """With no env override, the ~/.cache/aigallery default is scanned."""
        _make_model(_isolated_default_root, "Phi-3.5-mini")
        result = [info.id for info in discover_onnx_models()]
        assert result == ["onnx:Phi-3.5-mini"]

    def test_missing_root_returns_empty(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        _isolated_default_root: Path,
    ) -> None:
        monkeypatch.setenv("ONNX_MODEL_DIR", str(tmp_path / "does-not-exist"))
        assert discover_onnx_models() == []


class TestParseOnnxRoots:
    def test_appends_default_dedups_and_expands(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(local_discovery, "_ONNX_DEFAULT_ROOT", "~/.cache/aigallery")
        roots = parse_onnx_roots(os.pathsep.join(["/x", "/x", "~/y"]))
        assert roots[0] == Path("/x")
        assert roots[1] == Path("~/y").expanduser()
        # aigallery default appended last, expanded, exactly once.
        assert roots[-1] == Path("~/.cache/aigallery").expanduser()
        assert len(roots) == 3

    def test_empty_spec_yields_only_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(local_discovery, "_ONNX_DEFAULT_ROOT", "~/.cache/aigallery")
        roots = parse_onnx_roots("")
        assert roots == [Path("~/.cache/aigallery").expanduser()]


class TestOnnxRoundTripsToBackend:
    def test_discovered_relpath_resolves_under_a_scanned_root(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
        _isolated_default_root: Path,
    ) -> None:
        """A discovered onnx:<relpath> is loadable from the root it was found in."""
        root = tmp_path / "models"
        _make_model(root, "a/b/v1")
        monkeypatch.setenv("ONNX_MODEL_DIR", str(root))

        discovered = discover_onnx_models()
        assert [info.id for info in discovered] == ["onnx:a/b/v1"]

        # The backend joins the relpath under one of the same roots and finds it.
        from agentic_v2.models.backends_local import OnnxBackend

        resolved = Path(OnnxBackend()._resolve_path(discovered[0].id))
        assert (resolved / "genai_config.json").is_file()
        assert resolved == root / "a/b/v1"
