"""Tests for the NVIDIA NIM runtime backend (PR #132 review follow-up).

PR #132 added NVIDIA NIM *discovery* but no runtime backend, so a discovered
``nvidia:`` id silently fell through to Ollama (LangChain ``get_chat_model``) or
the OpenAI default (native ``MultiBackend``) at inference — advertised but not
runnable. These tests lock in that a discovered id now resolves to NVIDIA on
both engines, keeps its ``publisher/model`` form, and honors the cloud-vs-on-prem
key rule (cloud requires ``NVIDIA_API_KEY``; a self-hosted NIM does not).
"""

from __future__ import annotations

from typing import Any

import pytest

from agentic_v2.langchain.graph_wiring import extract_agent_response_text
from agentic_v2.langchain.model_builders import (
    _get_nim_chat_model_cls,
    _nim_extra_body,
    build_nvidia_model,
)
from agentic_v2.langchain.models import _KNOWN_PREFIXES, _PREFIX_BUILDERS
from agentic_v2.models.backends import (
    PREFIX_MAP,
    NvidiaBackend,
    auto_configure_backend,
)

_CLOUD_BASE = "https://integrate.api.nvidia.com/v1"


class TestNvidiaLangChainDispatch:
    """The bug itself: nvidia: must be a known prefix with a builder, not Ollama."""

    def test_nvidia_prefix_is_registered(self) -> None:
        assert "nvidia:" in _KNOWN_PREFIXES
        assert ("nvidia:", build_nvidia_model) in _PREFIX_BUILDERS


class TestNvidiaModelBuilder:
    """build_nvidia_model wires ChatOpenAI at the right host/key/model."""

    @staticmethod
    def _capture_chat_openai(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
        """Swap ``ChatOpenAI`` for a stub that records its constructor kwargs.

        The stub must be a *class*, not a lambda: ``build_nvidia_model``
        derives its NIM subclass from whatever ``ChatOpenAI`` resolves to.
        """
        langchain_openai = pytest.importorskip("langchain_openai")
        captured: dict[str, Any] = {}

        class _StubChatOpenAI:
            def __init__(self, **kwargs: Any) -> None:
                captured.update(kwargs)

        monkeypatch.setattr(langchain_openai, "ChatOpenAI", _StubChatOpenAI)
        return captured

    def test_cloud_keeps_publisher_segment_and_uses_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured = self._capture_chat_openai(monkeypatch)
        monkeypatch.delenv("NVIDIA_BASE_URL", raising=False)
        monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-xyz")

        build_nvidia_model("meta/llama-3.3-70b-instruct", 0.3)

        # NIM expects the full publisher/model id — the segment must NOT be stripped.
        assert captured["model"] == "meta/llama-3.3-70b-instruct"
        assert captured["base_url"] == _CLOUD_BASE
        assert captured["api_key"] == "nvapi-xyz"
        assert captured["temperature"] == 0.3

    def test_on_prem_without_key_uses_placeholder_and_appends_v1(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured = self._capture_chat_openai(monkeypatch)
        monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
        monkeypatch.setenv("NVIDIA_BASE_URL", "http://nim.local:8000")

        build_nvidia_model("meta/llama-3.1-8b-instruct", 0.0)

        assert captured["base_url"] == "http://nim.local:8000/v1"
        assert captured["api_key"]  # non-empty placeholder local NIM ignores
        assert captured["model"] == "meta/llama-3.1-8b-instruct"

    def test_cloud_without_key_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        pytest.importorskip("langchain_openai")
        monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
        monkeypatch.delenv("NVIDIA_BASE_URL", raising=False)

        with pytest.raises(ValueError, match="NVIDIA_API_KEY"):
            build_nvidia_model("meta/llama-3.3-70b-instruct", 0.0)


class TestNvidiaNativeBackend:
    """The native MultiBackend path resolves nvidia: too."""

    def test_prefix_map_routes_nvidia(self) -> None:
        assert PREFIX_MAP["nvidia:"] == "nvidia"

    def test_cloud_defaults_and_strips_only_provider_prefix(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("NVIDIA_BASE_URL", raising=False)
        backend = NvidiaBackend(api_key="nvapi-xyz")
        # Only the nvidia: prefix is stripped on the wire, never the publisher.
        assert backend._provider_prefix == "nvidia:"
        assert backend.base_url == _CLOUD_BASE

    def test_on_prem_without_key_uses_placeholder(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
        monkeypatch.setenv("NVIDIA_BASE_URL", "http://nim.local:8000")
        backend = NvidiaBackend(api_key="")
        assert backend.base_url == "http://nim.local:8000/v1"
        assert backend.api_key  # non-empty placeholder

    def test_cloud_without_key_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
        monkeypatch.delenv("NVIDIA_BASE_URL", raising=False)
        with pytest.raises(ValueError, match="NVIDIA_API_KEY"):
            NvidiaBackend(api_key="")

    def test_auto_configure_registers_nvidia_when_keyed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-xyz")
        monkeypatch.delenv("NVIDIA_BASE_URL", raising=False)
        backend = auto_configure_backend()
        assert "nvidia" in backend.backends  # type: ignore[attr-defined]


class TestNvidiaReasoningControl:
    """NIM reasoning models must not silently return empty content.

    Several NIM-hosted models (``deepseek-ai/deepseek-v4-flash-0731``, the
    ``nvidia/nemotron-3`` family, ``moonshotai/kimi-k3``) run an internal
    chain-of-thought phase first, so a modest ``max_tokens`` is spent entirely
    on reasoning and the answer comes back blank — indistinguishable from a
    model failure. The builder disables that phase at the request level and
    keeps the reasoning channel as a last-resort fallback.
    """

    def test_extra_body_disables_thinking_by_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured = TestNvidiaModelBuilder._capture_chat_openai(monkeypatch)
        monkeypatch.delenv("NVIDIA_DISABLE_THINKING", raising=False)
        monkeypatch.delenv("NVIDIA_BASE_URL", raising=False)
        monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-xyz")

        build_nvidia_model("deepseek-ai/deepseek-v4-flash-0731", 0.0)

        assert captured["extra_body"] == {"chat_template_kwargs": {"thinking": False}}

    @pytest.mark.parametrize("value", ["0", "false", "No", " off "])
    def test_env_opt_out_omits_extra_body(
        self, monkeypatch: pytest.MonkeyPatch, value: str
    ) -> None:
        captured = TestNvidiaModelBuilder._capture_chat_openai(monkeypatch)
        monkeypatch.setenv("NVIDIA_DISABLE_THINKING", value)
        monkeypatch.delenv("NVIDIA_BASE_URL", raising=False)
        monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-xyz")

        build_nvidia_model("deepseek-ai/deepseek-v4-flash-0731", 0.0)

        assert "extra_body" not in captured

    def test_env_truthy_keeps_extra_body(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured = TestNvidiaModelBuilder._capture_chat_openai(monkeypatch)
        monkeypatch.setenv("NVIDIA_DISABLE_THINKING", "1")
        monkeypatch.delenv("NVIDIA_BASE_URL", raising=False)
        monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-xyz")

        build_nvidia_model("deepseek-ai/deepseek-v4-flash-0731", 0.0)

        assert captured["extra_body"] == {"chat_template_kwargs": {"thinking": False}}

    def test_extra_body_is_not_shared_mutable_state(self) -> None:
        first = _nim_extra_body()
        first["chat_template_kwargs"]["thinking"] = True
        assert _nim_extra_body() == {"chat_template_kwargs": {"thinking": False}}


class TestNimReasoningContentPreserved:
    """Stock ChatOpenAI drops ``reasoning_content``; the NIM subclass keeps it.

    ``langchain-openai`` documents that non-standard provider fields are not
    extracted, so without this there is nothing for the empty-content fallback
    to fall back *to*.
    """

    @staticmethod
    def _nim_cls() -> Any:
        langchain_openai = pytest.importorskip("langchain_openai")
        return _get_nim_chat_model_cls(langchain_openai.ChatOpenAI)

    def _model(self) -> Any:
        return self._nim_cls()(
            model="deepseek-ai/deepseek-v4-flash-0731",
            base_url=_CLOUD_BASE,
            api_key="nvapi-xyz",
            temperature=0.0,
        )

    def test_subclass_is_a_chat_openai(self) -> None:
        langchain_openai = pytest.importorskip("langchain_openai")
        assert issubclass(self._nim_cls(), langchain_openai.ChatOpenAI)

    def test_same_class_returned_for_same_base(self) -> None:
        assert self._nim_cls() is self._nim_cls()

    def test_reasoning_content_lands_in_additional_kwargs(self) -> None:
        # Shape of a real NIM turn that spent its whole budget reasoning.
        response = {
            "id": "chatcmpl-1",
            "model": "deepseek-ai/deepseek-v4-flash-0731",
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "length",
                    "message": {
                        "role": "assistant",
                        "content": "",
                        "reasoning_content": "We need to reply exactly OK.",
                    },
                }
            ],
            "usage": {"prompt_tokens": 9, "completion_tokens": 12, "total_tokens": 21},
        }

        result = self._model()._create_chat_result(response)

        message = result.generations[0].message
        assert message.content == ""
        assert (
            message.additional_kwargs["reasoning_content"]
            == "We need to reply exactly OK."
        )

    def test_absent_reasoning_content_adds_no_key(self) -> None:
        response = {
            "id": "chatcmpl-2",
            "model": "meta/llama-3.3-70b-instruct",
            "choices": [
                {
                    "index": 0,
                    "finish_reason": "stop",
                    "message": {"role": "assistant", "content": "OK"},
                }
            ],
        }

        result = self._model()._create_chat_result(response)

        message = result.generations[0].message
        assert message.content == "OK"
        assert "reasoning_content" not in message.additional_kwargs

    def test_streaming_delta_preserves_reasoning_content(self) -> None:
        from langchain_core.messages import AIMessageChunk

        chunk = {
            "id": "chatcmpl-3",
            "model": "deepseek-ai/deepseek-v4-flash-0731",
            "choices": [
                {
                    "index": 0,
                    "finish_reason": None,
                    "delta": {
                        "role": "assistant",
                        "content": "",
                        "reasoning_content": "We need",
                    },
                }
            ],
        }

        generation = self._model()._convert_chunk_to_generation_chunk(
            chunk, AIMessageChunk, None
        )

        assert generation is not None
        assert generation.message.additional_kwargs["reasoning_content"] == "We need"


class TestEmptyContentFallback:
    """``extract_agent_response_text`` degrades to reasoning, never to ""."""

    @staticmethod
    def _payload(content: Any, **extras: Any) -> dict[str, Any]:
        from langchain_core.messages import AIMessage

        return {"messages": [AIMessage(content=content, additional_kwargs=extras)]}

    def test_blank_content_falls_back_to_reasoning_content(self) -> None:
        payload = self._payload("", reasoning_content="We need to reply exactly OK.")
        assert extract_agent_response_text(payload) == "We need to reply exactly OK."

    def test_blank_content_falls_back_to_ollama_thinking(self) -> None:
        payload = self._payload("   ", thinking="chain of thought")
        assert extract_agent_response_text(payload) == "chain of thought"

    def test_reasoning_content_wins_over_thinking(self) -> None:
        payload = self._payload("", reasoning_content="primary", thinking="secondary")
        assert extract_agent_response_text(payload) == "primary"

    def test_real_content_is_never_replaced(self) -> None:
        payload = self._payload("OK", reasoning_content="We need to reply exactly OK.")
        assert extract_agent_response_text(payload) == "OK"

    def test_blank_with_no_reasoning_channel_stays_blank(self) -> None:
        assert extract_agent_response_text(self._payload("")) == ""

    def test_no_ai_messages_still_returns_empty(self) -> None:
        assert extract_agent_response_text({"messages": []}) == ""
