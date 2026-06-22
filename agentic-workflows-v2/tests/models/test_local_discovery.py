"""Tests for LM Studio + ONNX local discovery (ADR-038).

LM Studio HTTP is mocked at ``httpx.get``; ONNX discovery runs against a real
temp directory tree (no network). Covers happy paths, malformed payloads, and
best-effort failure handling.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest

from agentic_v2.models import local_discovery
from agentic_v2.models.local_discovery import (
    discover_lmstudio_models,
    discover_onnx_models,
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("LMSTUDIO_HOST", "LM_STUDIO_HOST", "ONNX_MODEL_DIR", "AIGALLERY_CACHE"):
        monkeypatch.delenv(var, raising=False)


# ---------------------------------------------------------------------------
# LM Studio
# ---------------------------------------------------------------------------


class _Resp:
    def __init__(self, payload: Any) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> Any:
        return self._payload


class TestDiscoverLmStudio:
    def test_lists_models_from_openai_endpoint(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("LMSTUDIO_HOST", "http://127.0.0.1:1234")
        calls: list[str] = []

        def _fake_get(url: str, timeout: Any = None):
            calls.append(url)
            return _Resp({"data": [{"id": "gemma-3-12b-it"}, {"id": "qwen3.6-27b"}]})

        monkeypatch.setattr(local_discovery.httpx, "get", _fake_get)

        result = discover_lmstudio_models()
        assert result == ["lmstudio:gemma-3-12b-it", "lmstudio:qwen3.6-27b"]
        assert calls == ["http://127.0.0.1:1234/v1/models"]

    def test_server_down_returns_empty(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def _boom(url: str, timeout: Any = None):
            raise httpx.ConnectError("down")

        monkeypatch.setattr(local_discovery.httpx, "get", _boom)
        assert discover_lmstudio_models() == []

    def test_malformed_entries_skipped(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LMSTUDIO_HOST", "http://127.0.0.1:1234")
        monkeypatch.setattr(
            local_discovery.httpx,
            "get",
            lambda url, timeout=None: _Resp(
                {"data": ["not-a-dict", {"id": ""}, {"id": "ok"}, {"no_id": 1}]}
            ),
        )
        assert discover_lmstudio_models() == ["lmstudio:ok"]

    def test_default_host_matches_lmstudio_backend(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """With no env host, discovery probes the single host the lmstudio
        backend resolves to (``http://127.0.0.1:12340``) — never a port the
        backend won't query, so discovered ids stay runnable."""
        calls: list[str] = []

        def _fake_get(url: str, timeout: Any = None):
            calls.append(url)
            return _Resp({"data": [{"id": "m"}]})

        monkeypatch.setattr(local_discovery.httpx, "get", _fake_get)
        result = discover_lmstudio_models()
        assert result == ["lmstudio:m"]
        assert calls == ["http://127.0.0.1:12340/v1/models"]

    def test_lm_studio_host_alias_is_not_honored(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Only ``LMSTUDIO_HOST`` is read — the same var ``build_lmstudio_model``
        reads. The ``LM_STUDIO_HOST`` alias is ignored so discovery never
        advertises models from a host the backend won't query."""
        monkeypatch.setenv("LM_STUDIO_HOST", "http://127.0.0.1:9999")
        calls: list[str] = []

        def _fake_get(url: str, timeout: Any = None):
            calls.append(url)
            return _Resp({"data": [{"id": "m"}]})

        monkeypatch.setattr(local_discovery.httpx, "get", _fake_get)
        discover_lmstudio_models()
        assert calls == ["http://127.0.0.1:12340/v1/models"]

    def test_filters_embedding_and_tts_models(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Embedding / TTS / etc. ids LM Studio reports are excluded; chat kept."""
        monkeypatch.setenv("LMSTUDIO_HOST", "http://127.0.0.1:1234")
        monkeypatch.setattr(
            local_discovery.httpx,
            "get",
            lambda url, timeout=None: _Resp(
                {
                    "data": [
                        {"id": "google/gemma-3-12b"},
                        {"id": "text-embedding-nomic-embed-text-v1.5"},
                        {"id": "tts"},
                        {"id": "qwen3-1.7b-multilingual-tts"},
                        {"id": "whisper-large-v3"},
                        {"id": "qwen/qwen3.6-27b"},
                    ]
                }
            ),
        )
        assert discover_lmstudio_models() == [
            "lmstudio:google/gemma-3-12b",
            "lmstudio:qwen/qwen3.6-27b",
        ]


# ---------------------------------------------------------------------------
# ONNX
# ---------------------------------------------------------------------------


class TestDiscoverOnnx:
    def test_finds_genai_config_models(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        # Two real model folders + one unrelated folder.
        (tmp_path / "Microsoft" / "qwen3-14b" / "v2").mkdir(parents=True)
        (tmp_path / "Microsoft" / "qwen3-14b" / "v2" / "genai_config.json").write_text(
            "{}", encoding="utf-8"
        )
        (tmp_path / "phi4-mini").mkdir(parents=True)
        (tmp_path / "phi4-mini" / "genai_config.json").write_text(
            "{}", encoding="utf-8"
        )
        (tmp_path / "not-a-model").mkdir(parents=True)
        (tmp_path / "not-a-model" / "weights.onnx").write_text("x", encoding="utf-8")

        monkeypatch.setenv("ONNX_MODEL_DIR", str(tmp_path))

        result = sorted(discover_onnx_models())
        assert result == [
            "onnx:Microsoft/qwen3-14b/v2",
            "onnx:phi4-mini",
        ]

    def test_missing_root_returns_empty(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.setenv("ONNX_MODEL_DIR", str(tmp_path / "does-not-exist"))
        assert discover_onnx_models() == []

    def test_no_configured_root_discovers_nothing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """With neither ONNX_MODEL_DIR nor AIGALLERY_CACHE set, OnnxBackend
        resolves ``onnx:<name>`` relative to the CWD, so there is no catalog
        root to scan and discovery advertises nothing (rather than listing
        non-runnable ids from a default the backend never uses)."""
        monkeypatch.setattr(
            local_discovery, "get_first_secret", lambda *names, default="": default
        )
        assert discover_onnx_models() == []

    def test_relpath_resolves_against_onnx_backend_root(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        """The id's relpath is what OnnxBackend joins to model_dir — round-trip."""
        model_dir = tmp_path / "a" / "b" / "v1"
        model_dir.mkdir(parents=True)
        (model_dir / "genai_config.json").write_text("{}", encoding="utf-8")
        monkeypatch.setenv("ONNX_MODEL_DIR", str(tmp_path))

        result = discover_onnx_models()
        assert result == ["onnx:a/b/v1"]
        # OnnxBackend does Path(model_dir) / id.removeprefix("onnx:")
        resolved = tmp_path / result[0].removeprefix("onnx:")
        assert (resolved / "genai_config.json").is_file()
