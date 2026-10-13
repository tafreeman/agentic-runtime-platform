"""Tests for the NVIDIA NIM runtime backend (PR #132 review follow-up).

PR #132 added NVIDIA NIM *discovery* but no runtime backend, so a discovered
``nvidia:`` id silently fell through to Ollama (LangChain ``get_chat_model``) or
the OpenAI default (native ``MultiBackend``) at inference — advertised but not
runnable. These tests lock in that a discovered id now resolves to NVIDIA on
both engines, keeps its ``publisher/model`` form, and honors the cloud-vs-on-prem
key rule (cloud requires ``NVIDIA_API_KEY``; a self-hosted NIM does not).
"""

from __future__ import annotations

import json
from typing import Any

import httpx
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
    OpenAIBackend,
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

    @pytest.mark.parametrize("model", ["z-ai/glm-5.3", "z-ai/glm-5.3-flash"])
    def test_glm_also_gets_its_lowest_reasoning_effort(
        self, monkeypatch: pytest.MonkeyPatch, model: str
    ) -> None:
        """GLM ignores ``thinking: False``; ``reasoning_effort`` is what it honours."""
        captured = TestNvidiaModelBuilder._capture_chat_openai(monkeypatch)
        monkeypatch.delenv("NVIDIA_DISABLE_THINKING", raising=False)
        monkeypatch.delenv("NVIDIA_BASE_URL", raising=False)
        monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-xyz")

        build_nvidia_model(model, 0.0)

        assert captured["extra_body"] == {
            "chat_template_kwargs": {"thinking": False, "clear_thinking": True},
            "reasoning_effort": "low",
        }

    def test_env_opt_out_omits_glm_reasoning_effort_too(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured = TestNvidiaModelBuilder._capture_chat_openai(monkeypatch)
        monkeypatch.setenv("NVIDIA_DISABLE_THINKING", "0")
        monkeypatch.delenv("NVIDIA_BASE_URL", raising=False)
        monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-xyz")

        build_nvidia_model("z-ai/glm-5.3", 0.0)

        assert "extra_body" not in captured


class TestNvidiaNativeReasoningControl:
    """The native ``NvidiaBackend`` makes the builder's two accommodations too.

    Tier routing on the native engine reaches NIM through ``NvidiaBackend``,
    not ``build_nvidia_model``, so a reasoning model in a tier chain (tier 1's
    ``nvidia/nemotron-3-nano-omni-30b-a3b-reasoning``) must not answer blank
    there either.
    """

    _MODEL = "nvidia:nvidia/nemotron-3-nano-omni-30b-a3b-reasoning"

    @staticmethod
    def _backend(
        monkeypatch: pytest.MonkeyPatch,
        response_message: dict[str, Any],
        sent: list[dict[str, Any]],
    ) -> NvidiaBackend:
        monkeypatch.delenv("NVIDIA_BASE_URL", raising=False)

        def _handler(request: httpx.Request) -> httpx.Response:
            sent.append(json.loads(request.content))
            body = {
                "model": "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning",
                "choices": [{"message": response_message, "finish_reason": "stop"}],
                "usage": {},
            }
            return httpx.Response(200, json=body)

        backend = NvidiaBackend(api_key="nvapi-xyz")
        backend._client = httpx.AsyncClient(
            base_url=backend.base_url, transport=httpx.MockTransport(_handler)
        )
        return backend

    async def test_request_disables_thinking_by_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("NVIDIA_DISABLE_THINKING", raising=False)
        sent: list[dict[str, Any]] = []
        backend = self._backend(monkeypatch, {"content": "OK"}, sent)

        await backend.complete_chat(self._MODEL, [{"role": "user", "content": "hi"}])

        assert sent[0]["chat_template_kwargs"] == {"thinking": False}
        assert "reasoning_effort" not in sent[0]
        assert sent[0]["model"] == "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning"

    async def test_glm_request_sends_its_lowest_reasoning_effort(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Tier 2-5 and the default judge reach GLM through this path."""
        monkeypatch.delenv("NVIDIA_DISABLE_THINKING", raising=False)
        sent: list[dict[str, Any]] = []
        backend = self._backend(monkeypatch, {"content": "OK"}, sent)

        await backend.complete_chat(
            "nvidia:z-ai/glm-5.3", [{"role": "user", "content": "hi"}]
        )

        assert sent[0]["reasoning_effort"] == "low"
        assert sent[0]["chat_template_kwargs"] == {
            "thinking": False,
            "clear_thinking": True,
        }

    async def test_caller_reasoning_effort_overrides_the_glm_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("NVIDIA_DISABLE_THINKING", raising=False)
        sent: list[dict[str, Any]] = []
        backend = self._backend(monkeypatch, {"content": "OK"}, sent)

        await backend.complete_chat(
            "nvidia:z-ai/glm-5.3-flash",
            [{"role": "user", "content": "hi"}],
            reasoning_effort="high",
        )

        assert sent[0]["reasoning_effort"] == "high"

    async def test_env_opt_out_omits_the_field(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("NVIDIA_DISABLE_THINKING", "0")
        sent: list[dict[str, Any]] = []
        backend = self._backend(monkeypatch, {"content": "OK"}, sent)

        await backend.complete_chat(self._MODEL, [{"role": "user", "content": "hi"}])

        assert "chat_template_kwargs" not in sent[0]

    async def test_caller_kwargs_override_the_default(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("NVIDIA_DISABLE_THINKING", raising=False)
        sent: list[dict[str, Any]] = []
        backend = self._backend(monkeypatch, {"content": "OK"}, sent)

        await backend.complete_chat(
            self._MODEL,
            [{"role": "user", "content": "hi"}],
            chat_template_kwargs={"thinking": True},
        )

        assert sent[0]["chat_template_kwargs"] == {"thinking": True}

    async def test_reasoning_content_is_the_canonical_thinking_key(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sent: list[dict[str, Any]] = []
        message = {"content": "", "reasoning_content": "We need to reply OK."}
        backend = self._backend(monkeypatch, message, sent)

        result = await backend.complete_chat(
            self._MODEL, [{"role": "user", "content": "hi"}]
        )

        # ADR-023 canonical shape: content stays the answer, thinking is separate.
        assert result["content"] == ""
        assert result["thinking"] == "We need to reply OK."

    async def test_prompt_path_falls_back_to_reasoning_when_blank(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sent: list[dict[str, Any]] = []
        message = {"content": "  ", "reasoning_content": "We need to reply OK."}
        backend = self._backend(monkeypatch, message, sent)

        assert await backend.complete(self._MODEL, "hi") == "We need to reply OK."

    async def test_answer_wins_over_reasoning(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        sent: list[dict[str, Any]] = []
        message = {"content": "OK", "reasoning_content": "We need to reply OK."}
        backend = self._backend(monkeypatch, message, sent)

        assert await backend.complete(self._MODEL, "hi") == "OK"

    async def test_plain_openai_backend_sends_no_nim_field(self) -> None:
        sent: list[dict[str, Any]] = []

        def _handler(request: httpx.Request) -> httpx.Response:
            sent.append(json.loads(request.content))
            body = {"choices": [{"message": {"content": "OK"}}], "usage": {}}
            return httpx.Response(200, json=body)

        backend = OpenAIBackend(api_key="sk-test")
        backend._client = httpx.AsyncClient(
            base_url=backend.base_url, transport=httpx.MockTransport(_handler)
        )

        result = await backend.complete_chat("openai:gpt-x", [])

        assert "chat_template_kwargs" not in sent[0]
        assert "thinking" not in result


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

    def test_kept_reasoning_is_not_sent_back_on_the_next_turn(self) -> None:
        """Preserved reasoning stays local; a later request carries content only.

        GLM's template re-renders any reasoning_content it is sent (702 vs 41
        prompt tokens, probed 2026-10-12), so round-tripping it would bloat
        every ReAct turn. ``clear_thinking`` guards GLM as well, but this
        pins the cheaper invariant for every NIM model.
        """
        from langchain_core.messages import AIMessage, HumanMessage

        payload = self._model()._get_request_payload(
            [
                HumanMessage("q1"),
                AIMessage("a1", additional_kwargs={"reasoning_content": "prior"}),
                HumanMessage("q2"),
            ]
        )

        assert payload["messages"][1] == {"role": "assistant", "content": "a1"}

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
