"""Sanitization dispatch helpers for LLM prompt and response filtering.

Pure async functions that apply the optional inbound and outbound sanitizers
used by :class:`~agentic_v2.models.client.LLMClientWrapper`.  Extracted from
``client.py`` so the sanitization pipeline is independently testable and the
coverage gate applies to it.

All functions are no-op pass-throughs when the corresponding sanitizer is
``None``.

Public surface:
    ``sanitize_prompt``           — inbound text prompt
    ``sanitize_messages``         — inbound chat message list
    ``sanitize_content_blocks``   — inbound list-of-blocks content value
    ``sanitize_response_text``    — outbound response text
    ``sanitize_response_blocks``  — outbound list-of-blocks response content
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..middleware.response_sanitizer import ResponseSanitizer
    from ..middleware.sanitization import SanitizationMiddleware

from .router import ModelTier


async def sanitize_prompt(
    prompt: str,
    *,
    source: str,
    tier: ModelTier,
    sanitization: SanitizationMiddleware | None,
) -> str:
    """Run the inbound prompt sanitizer, returning the effective prompt.

    A no-op pass-through when *sanitization* is ``None``.

    Args:
        prompt: Raw user prompt.
        source: Caller label for audit logs (e.g. ``"llm_complete"``).
        tier: Model tier context forwarded to the sanitizer.
        sanitization: Optional :class:`SanitizationMiddleware` instance.

    Returns:
        The (possibly rewritten) safe prompt text.

    Raises:
        ValueError: If the sanitizer classifies the prompt as unsafe.
    """
    if sanitization is None:
        return prompt
    san_result = await sanitization.process(prompt, {"source": source, "tier": tier.name})
    if not san_result.is_safe:
        raise ValueError(
            f"Prompt blocked by sanitization: {san_result.classification.value}"
        )
    if san_result.sanitized_text is not None:
        return san_result.sanitized_text
    return prompt


async def sanitize_content_blocks(
    blocks: list[Any],
    *,
    source: str,
    tier: ModelTier,
    sanitization: SanitizationMiddleware | None,
) -> tuple[list[Any], bool]:
    """Sanitize text within a list-of-blocks content value.

    LLM APIs (OpenAI, Anthropic) allow message content to be a list of
    typed content blocks, e.g. ``[{"type": "text", "text": "..."}]``.
    This function iterates through those blocks and sanitizes any text
    blocks, closing the bypass vector where an attacker wraps a prompt
    injection payload inside a non-string content structure.

    Returns:
        ``(cleaned_blocks, mutated)`` — the caller only copies the message
        dict when ``mutated`` is ``True``.
    """
    cleaned: list[Any] = []
    mutated = False
    for block in blocks:
        if (
            isinstance(block, dict)
            and block.get("type") == "text"
            and isinstance(block.get("text"), str)
        ):
            text = block["text"]
            cleaned_text = await sanitize_prompt(
                text, source=source, tier=tier, sanitization=sanitization
            )
            if cleaned_text != text:
                cleaned.append({**block, "text": cleaned_text})
                mutated = True
            else:
                cleaned.append(block)
        else:
            cleaned.append(block)
    return cleaned, mutated


async def sanitize_messages(
    messages: list[dict[str, Any]],
    *,
    source: str,
    tier: ModelTier,
    sanitization: SanitizationMiddleware | None,
) -> list[dict[str, Any]]:
    """Run inbound sanitization over each chat message's content.

    A no-op pass-through when *sanitization* is ``None``.
    This is the chat-path analogue of :func:`sanitize_prompt` and closes the
    indirect prompt-injection vector: tool outputs and retrieved content fed
    back into the agent loop as chat messages.  Fails closed — an unsafe
    message raises ``ValueError`` (parity with the text path).

    Returns a new message list; input messages are not mutated.

    Raises:
        ValueError: If any message content is classified as unsafe.
    """
    if sanitization is None:
        return messages
    sanitized: list[dict[str, Any]] = []
    for msg in messages:
        content = msg.get("content")
        if isinstance(content, str) and content:
            cleaned = await sanitize_prompt(
                content, source=source, tier=tier, sanitization=sanitization
            )
            if cleaned == content:
                sanitized.append(msg)
            else:
                sanitized.append({**msg, "content": cleaned})
        elif isinstance(content, list):
            cleaned_blocks, mutated = await sanitize_content_blocks(
                content, source=source, tier=tier, sanitization=sanitization
            )
            if mutated:
                sanitized.append({**msg, "content": cleaned_blocks})
            else:
                sanitized.append(msg)
        else:
            sanitized.append(msg)
    return sanitized


async def sanitize_response_text(
    response: str,
    *,
    response_sanitizer: ResponseSanitizer | None,
) -> str:
    """Run the outbound response sanitizer, returning the effective text.

    A no-op pass-through when *response_sanitizer* is ``None``.
    """
    if response_sanitizer is None:
        return response
    resp_result = await response_sanitizer.sanitize_response(response)
    if resp_result.sanitized_text is not None:
        return resp_result.sanitized_text
    return response


async def sanitize_response_blocks(
    blocks: list[Any],
    *,
    response_sanitizer: ResponseSanitizer | None,
) -> list[Any]:
    """Sanitize text within a list-of-blocks response content value.

    Outbound counterpart of :func:`sanitize_content_blocks`.  Iterates through
    content blocks returned by the LLM and runs the response sanitizer over
    any ``{"type": "text", "text": "..."}`` blocks.  This closes the bypass
    vector where model output structured as a list of content blocks would
    skip outbound secret/PII scrubbing.
    """
    cleaned: list[Any] = []
    for block in blocks:
        if (
            isinstance(block, dict)
            and block.get("type") == "text"
            and isinstance(block.get("text"), str)
        ):
            cleaned_text = await sanitize_response_text(
                block["text"], response_sanitizer=response_sanitizer
            )
            cleaned.append({**block, "text": cleaned_text})
        else:
            cleaned.append(block)
    return cleaned
