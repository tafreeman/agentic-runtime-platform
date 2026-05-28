"""Tests for LLMClientAdapter."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from agentic_v2_eval.adapters.llm_client import LLMClientAdapter, create_llm_client


class TestLLMClientAdapter:
    """Tests for LLMClientAdapter."""

    def test_create_adapter_with_defaults(self):
        """Test creating adapter with default settings."""
        adapter = LLMClientAdapter()
        assert adapter.default_model is None
        assert adapter.default_temperature == 0.0
        assert adapter.default_max_tokens == 4096
        assert adapter.system_instruction is None

    def test_create_adapter_with_custom_settings(self):
        """Test creating adapter with custom settings."""
        adapter = LLMClientAdapter(
            default_model="gh:gpt-4o-mini",
            default_temperature=0.5,
            default_max_tokens=2048,
            system_instruction="You are a helpful assistant.",
        )
        assert adapter.default_model == "gh:gpt-4o-mini"
        assert adapter.default_temperature == 0.5
        assert adapter.default_max_tokens == 2048
        assert adapter.system_instruction == "You are a helpful assistant."

    def test_factory_function(self):
        """Test create_llm_client factory function."""
        client = create_llm_client(
            model="local:phi4",
            temperature=0.7,
            max_tokens=1024,
            system_instruction="Test system instruction",
        )
        assert isinstance(client, LLMClientAdapter)
        assert client.default_model == "local:phi4"
        assert client.default_temperature == 0.7
        assert client.default_max_tokens == 1024
        assert client.system_instruction == "Test system instruction"

    def test_generate_text_calls_llm_client(self):
        """Test that generate_text delegates to LLMClient."""
        # Create mock LLMClient class
        mock_llm_class = MagicMock()
        mock_llm_class.generate_text = MagicMock(return_value="Generated response")

        adapter = LLMClientAdapter()
        adapter._llm_client_class = mock_llm_class

        result = adapter.generate_text(
            model_name="gh:gpt-4o",
            prompt="Hello, world!",
            temperature=0.5,
        )

        assert result == "Generated response"
        mock_llm_class.generate_text.assert_called_once_with(
            model_name="gh:gpt-4o",
            prompt="Hello, world!",
            system_instruction=None,
            temperature=0.5,
            max_tokens=4096,
        )

    def test_generate_text_with_system_instruction(self):
        """Test generate_text with system instruction in kwargs."""
        mock_llm_class = MagicMock()
        mock_llm_class.generate_text = MagicMock(return_value="Response")

        adapter = LLMClientAdapter()
        adapter._llm_client_class = mock_llm_class

        adapter.generate_text(
            model_name="gh:gpt-4o",
            prompt="Test prompt",
            temperature=0.0,
            system_instruction="Custom system prompt",
        )

        mock_llm_class.generate_text.assert_called_once_with(
            model_name="gh:gpt-4o",
            prompt="Test prompt",
            system_instruction="Custom system prompt",
            temperature=0.0,
            max_tokens=4096,
        )

    def test_generate_text_uses_default_system_instruction(self):
        """Test that adapter uses default system instruction when not provided."""
        mock_llm_class = MagicMock()
        mock_llm_class.generate_text = MagicMock(return_value="Response")

        adapter = LLMClientAdapter(system_instruction="Default instruction")
        adapter._llm_client_class = mock_llm_class

        adapter.generate_text(
            model_name="gh:gpt-4o",
            prompt="Test prompt",
            temperature=0.0,
        )

        mock_llm_class.generate_text.assert_called_once_with(
            model_name="gh:gpt-4o",
            prompt="Test prompt",
            system_instruction="Default instruction",
            temperature=0.0,
            max_tokens=4096,
        )

    def test_generate_text_with_custom_max_tokens(self):
        """Test generate_text with custom max_tokens."""
        mock_llm_class = MagicMock()
        mock_llm_class.generate_text = MagicMock(return_value="Response")

        adapter = LLMClientAdapter()
        adapter._llm_client_class = mock_llm_class

        adapter.generate_text(
            model_name="gh:gpt-4o",
            prompt="Test prompt",
            temperature=0.0,
            max_tokens=512,
        )

        mock_llm_class.generate_text.assert_called_once_with(
            model_name="gh:gpt-4o",
            prompt="Test prompt",
            system_instruction=None,
            temperature=0.0,
            max_tokens=512,
        )

    def test_generate_text_uses_default_model(self):
        """Test that adapter uses default_model when model_name is empty."""
        mock_llm_class = MagicMock()
        mock_llm_class.generate_text = MagicMock(return_value="Response")

        adapter = LLMClientAdapter(default_model="local:phi4")
        adapter._llm_client_class = mock_llm_class

        adapter.generate_text(
            model_name="",
            prompt="Test prompt",
            temperature=0.0,
        )

        mock_llm_class.generate_text.assert_called_once()
        call_args = mock_llm_class.generate_text.call_args
        assert call_args.kwargs["model_name"] == "local:phi4"

    def test_generate_text_raises_without_model(self):
        """Test that generate_text raises ValueError without model."""
        mock_llm_class = MagicMock()

        adapter = LLMClientAdapter()  # No default model
        adapter._llm_client_class = mock_llm_class

        with pytest.raises(ValueError, match="No model_name provided"):
            adapter.generate_text(
                model_name="",
                prompt="Test prompt",
                temperature=0.0,
            )

    def test_generate_text_raises_when_llm_not_available(self):
        """Test that generate_text raises RuntimeError when LLMClient unavailable."""
        adapter = LLMClientAdapter()
        adapter._llm_client_class = None

        with pytest.raises(RuntimeError, match="LLMClient not available"):
            adapter.generate_text(
                model_name="gh:gpt-4o",
                prompt="Test prompt",
                temperature=0.0,
            )


class TestLLMClientProtocolCompliance:
    """Test that LLMClientAdapter satisfies LLMClientProtocol."""

    def test_has_generate_text_method(self):
        """Verify adapter has generate_text method with correct signature."""
        adapter = LLMClientAdapter()

        # Check method exists
        assert hasattr(adapter, "generate_text")
        assert callable(adapter.generate_text)

    def test_protocol_signature_compatibility(self):
        """Test that adapter matches LLMClientProtocol signature."""
        import inspect

        from agentic_v2_eval.evaluators.llm import LLMClientProtocol

        # Get protocol signature
        protocol_sig = inspect.signature(LLMClientProtocol.generate_text)
        adapter_sig = inspect.signature(LLMClientAdapter.generate_text)

        # Check required parameters match
        protocol_params = list(protocol_sig.parameters.keys())
        adapter_params = list(adapter_sig.parameters.keys())

        # Both should have self, model_name, prompt, temperature
        assert "self" in protocol_params and "self" in adapter_params
        assert "model_name" in protocol_params and "model_name" in adapter_params
        assert "prompt" in protocol_params and "prompt" in adapter_params
        assert "temperature" in protocol_params and "temperature" in adapter_params

    def test_can_be_used_as_llm_client(self):
        """Test that adapter can be passed to LLMEvaluator."""
        from agentic_v2_eval.evaluators.llm import Choice, LLMEvaluator

        mock_llm_class = MagicMock()
        mock_llm_class.generate_text = MagicMock(return_value="5")

        adapter = LLMClientAdapter()
        adapter._llm_client_class = mock_llm_class

        # Should be able to create LLMEvaluator with adapter
        evaluator = LLMEvaluator(
            model_id="gh:gpt-4o-mini",
            system_prompt="Rate the quality.",
            prompt_template="Rate this: {output}",
            choices=[
                Choice("1", 0.0),
                Choice("2", 0.25),
                Choice("3", 0.5),
                Choice("4", 0.75),
                Choice("5", 1.0),
            ],
            llm_client=adapter,
        )

        assert evaluator.llm_client is adapter
