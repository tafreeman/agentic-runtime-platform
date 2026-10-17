"""Unit tests for the Azure OpenAI, Azure AI Foundry, and ONNX backends.

These were added to make the public "8+ providers" claim literally true.
HTTP request-shaping is exercised with ``httpx.MockTransport`` (no live
endpoints); the ONNX path is exercised by injecting a stub
``onnxruntime_genai`` module so the native runtime is not required.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from agentic_v2.models.backends_cloud import (
    AzureFoundryBackend,
    AzureOpenAIBackend,
)
from agentic_v2.models.backends_local import OnnxBackend, _load_onnxruntime_genai

_OPENAI_SHAPED_RESPONSE = {
    "choices": [
        {
            "message": {"content": "hello from azure", "tool_calls": None},
            "finish_reason": "stop",
        }
    ],
    "model": "served-model",
    "usage": {"total_tokens": 7},
}


def _mock_client(handler: Any, **kwargs: Any) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.MockTransport(handler), **kwargs)


# ---------------------------------------------------------------------------
# AzureOpenAIBackend
# ---------------------------------------------------------------------------


class TestAzureOpenAIBackend:
    def test_requires_key_and_endpoint(self) -> None:
        with pytest.raises(ValueError, match="AZURE_OPENAI_API_KEY"):
            AzureOpenAIBackend(api_key="", endpoint="https://r.openai.azure.com")
        with pytest.raises(ValueError, match="AZURE_OPENAI_ENDPOINT"):
            AzureOpenAIBackend(api_key="k", endpoint="")

    async def test_get_client_sets_api_key_header(self) -> None:
        backend = AzureOpenAIBackend(
            api_key="secret-key", endpoint="https://r.openai.azure.com"
        )
        client = await backend._get_client()
        assert client.headers["api-key"] == "secret-key"
        await backend.close()

    async def test_complete_chat_targets_deployment_path_with_api_version(self) -> None:
        seen: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["path"] = request.url.path
            seen["api_version"] = request.url.params.get("api-version")
            import json

            seen["body"] = json.loads(request.content)
            return httpx.Response(200, json=_OPENAI_SHAPED_RESPONSE)

        backend = AzureOpenAIBackend(
            api_key="k",
            endpoint="https://r.openai.azure.com",
            api_version="2024-10-21",
        )
        backend._client = _mock_client(handler, base_url="https://r.openai.azure.com")

        result = await backend.complete_chat(
            "azure:gpt-4o-prod", [{"role": "user", "content": "hi"}]
        )

        assert seen["path"] == "/openai/deployments/gpt-4o-prod/chat/completions"
        assert seen["api_version"] == "2024-10-21"
        # Azure carries the deployment in the URL, not the body.
        assert "model" not in seen["body"]
        assert result["content"] == "hello from azure"
        await backend.close()


# ---------------------------------------------------------------------------
# AzureFoundryBackend
# ---------------------------------------------------------------------------


class TestAzureFoundryBackend:
    def test_requires_key_and_endpoint(self) -> None:
        with pytest.raises(ValueError, match="AZURE_FOUNDRY_API_KEY"):
            AzureFoundryBackend(api_key="", endpoint="https://r.services.ai.azure.com")
        with pytest.raises(ValueError, match="AZURE_FOUNDRY_ENDPOINT"):
            AzureFoundryBackend(api_key="k", endpoint="")

    async def test_complete_chat_sends_model_in_body(self) -> None:
        seen: dict[str, Any] = {}

        def handler(request: httpx.Request) -> httpx.Response:
            import json

            seen["path"] = request.url.path
            seen["body"] = json.loads(request.content)
            return httpx.Response(200, json=_OPENAI_SHAPED_RESPONSE)

        backend = AzureFoundryBackend(
            api_key="k", endpoint="https://r.services.ai.azure.com/models"
        )
        backend._client = _mock_client(
            handler, base_url="https://r.services.ai.azure.com/models"
        )

        result = await backend.complete_chat(
            "azure-foundry:phi4mini", [{"role": "user", "content": "hi"}]
        )

        assert seen["path"].endswith("/chat/completions")
        assert seen["body"]["model"] == "phi4mini"
        assert result["content"] == "hello from azure"
        await backend.close()


# ---------------------------------------------------------------------------
# OnnxBackend (stubbed onnxruntime-genai)
# ---------------------------------------------------------------------------


class _FakeTokenizer:
    def __init__(self, model: Any) -> None:
        self.model = model

    def encode(self, text: str) -> list[int]:
        return [1, 2, 3]

    def decode(self, tokens: list[int]) -> str:
        return "decoded:" + ",".join(str(t) for t in tokens)


class _FakeGeneratorParams:
    def __init__(self, model: Any) -> None:
        self.model = model
        self.opts: dict[str, Any] = {}

    def set_search_options(self, **kwargs: Any) -> None:
        self.opts = kwargs


class _FakeGenerator:
    def __init__(self, model: Any, params: Any) -> None:
        self._seq: list[int] = []
        self._steps = 0

    def append_tokens(self, tokens: list[int]) -> None:
        self._seq = list(tokens)

    def is_done(self) -> bool:
        return self._steps >= 2

    def generate_next_token(self) -> None:
        self._seq.append(90 + self._steps)
        self._steps += 1

    def get_sequence(self, idx: int) -> list[int]:
        return self._seq


class _FakeOg:
    Model = staticmethod(lambda path: {"path": path})
    Tokenizer = _FakeTokenizer
    GeneratorParams = _FakeGeneratorParams
    Generator = _FakeGenerator


class TestOnnxBackend:
    def _patch_runtime(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "agentic_v2.models.backends_local._load_onnxruntime_genai",
            lambda: _FakeOg,
        )

    async def test_complete_decodes_only_new_tokens(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._patch_runtime(monkeypatch)
        backend = OnnxBackend(model_dir="")
        # encode -> [1,2,3]; two generated tokens -> [90, 91]; only the tail
        # (the completion) should be decoded.
        result = await backend.complete("onnx:phi4", "hi")
        assert result == "decoded:90,91"

    async def test_complete_chat_returns_canonical_shape(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._patch_runtime(monkeypatch)
        backend = OnnxBackend(model_dir="")
        result = await backend.complete_chat(
            "onnx:phi4", [{"role": "user", "content": "hi"}]
        )
        assert result["content"] == "decoded:90,91"
        assert result["finish_reason"] == "stop"
        assert result["model"] == "phi4"
        assert result["tool_calls"] is None

    def test_messages_to_prompt_tags_roles(self) -> None:
        prompt = OnnxBackend._messages_to_prompt(
            [
                {"role": "system", "content": "be brief"},
                {"role": "user", "content": "hi"},
            ]
        )
        assert "<|system|>" in prompt
        assert "<|user|>" in prompt
        assert prompt.rstrip().endswith("<|assistant|>")

    def test_model_is_cached_across_calls(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        calls = {"n": 0}

        def _model_factory(path: str) -> dict[str, str]:
            calls["n"] += 1
            return {"path": path}

        class _CountingOg(_FakeOg):
            Model = staticmethod(_model_factory)

        monkeypatch.setattr(
            "agentic_v2.models.backends_local._load_onnxruntime_genai",
            lambda: _CountingOg,
        )
        backend = OnnxBackend(model_dir="")
        backend._get_model("onnx:phi4")
        backend._get_model("onnx:phi4")
        assert calls["n"] == 1  # loaded once, reused from cache

    def test_missing_runtime_raises_actionable_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import builtins

        real_import = builtins.__import__

        def fake_import(name: str, *args: Any, **kwargs: Any) -> Any:
            if name == "onnxruntime_genai":
                raise ImportError("not installed")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", fake_import)
        with pytest.raises(RuntimeError, match="onnxruntime-genai is not installed"):
            _load_onnxruntime_genai()


class TestOnnxBackendWeightVerification:
    """OnnxBackend must honor AGENTIC_STRICT_MODEL_VERIFY before loading."""

    def _backend(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any) -> OnnxBackend:
        loaded: list[str] = []

        class _TrackingOg(_FakeOg):
            Model = staticmethod(lambda path: loaded.append(path) or {"path": path})

        monkeypatch.setattr(
            "agentic_v2.models.backends_local._load_onnxruntime_genai",
            lambda: _TrackingOg,
        )
        folder = tmp_path / "phi4"
        folder.mkdir()
        (folder / "model.onnx").write_bytes(b"weights")
        (folder / "genai_config.json").write_text("{}", encoding="utf-8")
        backend = OnnxBackend(model_dir=str(tmp_path))
        backend.loaded = loaded  # type: ignore[attr-defined]
        return backend

    async def test_strict_mode_blocks_unverified_model(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
    ) -> None:
        from agentic_v2.models.weight_integrity import ModelWeightVerificationError

        backend = self._backend(monkeypatch, tmp_path)
        monkeypatch.setenv("AGENTIC_STRICT_MODEL_VERIFY", "1")
        with pytest.raises(ModelWeightVerificationError):
            await backend.complete("onnx:phi4", "hi")
        assert backend.loaded == []  # type: ignore[attr-defined]

    async def test_verification_runs_once_per_cached_path(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
    ) -> None:
        backend = self._backend(monkeypatch, tmp_path)
        monkeypatch.delenv("AGENTIC_STRICT_MODEL_VERIFY", raising=False)
        calls: list[str] = []
        monkeypatch.setattr(
            "agentic_v2.models.backends_local._verify_weights", calls.append
        )
        await backend.complete("onnx:phi4", "hi")
        await backend.complete("onnx:phi4", "again")
        assert len(calls) == 1
        assert len(backend.loaded) == 1  # type: ignore[attr-defined]


class TestOnnxBackendHardening:
    @pytest.mark.parametrize(
        "name", ["onnx:/", "onnx:../outside", "onnx:a/../../b", ""]
    )
    def test_resolve_path_rejects_escapes(self, tmp_path: Any, name: str) -> None:
        backend = OnnxBackend(model_dir=str(tmp_path))
        with pytest.raises(ValueError):
            backend._resolve_path(name)

    def test_non_strict_verifier_errors_fail_open(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
    ) -> None:
        from agentic_v2.models import backends_local

        monkeypatch.delenv("AGENTIC_STRICT_MODEL_VERIFY", raising=False)

        def _boom(path: Any) -> None:
            raise PermissionError("unreadable")

        monkeypatch.setattr(
            "agentic_v2.models.weight_integrity.verify_model_weights", _boom
        )
        backends_local._verify_weights(str(tmp_path))  # must not raise
        monkeypatch.setenv("AGENTIC_STRICT_MODEL_VERIFY", "1")
        with pytest.raises(PermissionError):
            backends_local._verify_weights(str(tmp_path))


class TestOnnxBackendModelFolderAndCache:
    def test_non_model_directory_rejected_before_hashing(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
    ) -> None:
        monkeypatch.setattr(
            "agentic_v2.models.backends_local._load_onnxruntime_genai",
            lambda: _FakeOg,
        )
        calls: list[str] = []
        monkeypatch.setattr(
            "agentic_v2.models.backends_local._verify_weights", calls.append
        )
        backend = OnnxBackend(model_dir=str(tmp_path))
        with pytest.raises(ValueError, match="genai_config.json"):
            backend._get_model("onnx:.")
        assert calls == []

    def test_cache_evicts_least_recently_used(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Any
    ) -> None:
        monkeypatch.setattr(
            "agentic_v2.models.backends_local._load_onnxruntime_genai",
            lambda: _FakeOg,
        )
        monkeypatch.setattr(
            "agentic_v2.models.backends_local._verify_weights", lambda p: None
        )
        for name in ("a", "b"):
            (tmp_path / name).mkdir()
            (tmp_path / name / "genai_config.json").write_text("{}", encoding="utf-8")
        backend = OnnxBackend(model_dir=str(tmp_path), max_cached_models=1)
        backend._get_model("onnx:a")
        backend._get_model("onnx:b")
        assert len(backend._models) == 1
        assert next(iter(backend._models)).endswith("b")


def test_generation_is_serialized_so_eviction_cannot_unload_active_model(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    import threading

    monkeypatch.setattr(
        "agentic_v2.models.backends_local._load_onnxruntime_genai", lambda: _FakeOg
    )
    monkeypatch.setattr(
        "agentic_v2.models.backends_local._verify_weights", lambda p: None
    )
    for name in ("a", "b"):
        (tmp_path / name).mkdir()
        (tmp_path / name / "genai_config.json").write_text("{}", encoding="utf-8")
    backend = OnnxBackend(model_dir=str(tmp_path), max_cached_models=1)
    active = 0
    peak = 0
    guard = threading.Lock()
    original = backend._generate_locked

    def _tracked(*args: Any) -> str:
        nonlocal active, peak
        with guard:
            active += 1
            peak = max(peak, active)
        try:
            return original(*args)
        finally:
            with guard:
                active -= 1

    monkeypatch.setattr(backend, "_generate_locked", _tracked)
    threads = [
        threading.Thread(
            target=backend._generate_sync, args=(f"onnx:{n}", "hi", 8, 0.0)
        )
        for n in ("a", "b", "a", "b")
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert peak == 1
