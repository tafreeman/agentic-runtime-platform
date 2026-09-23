"""Response sanitization for the LangGraph engine.

The native engine masks secrets in model responses inside
:class:`~agentic_v2.models.client.LLMClientWrapper`: the shared client carries
a :class:`~agentic_v2.middleware.response_sanitizer.ResponseSanitizer`
whenever ``AGENTIC_SANITIZE_AGENT_LOOP`` is on (see
``models.client._maybe_attach_agent_loop_sanitization``). The LangGraph
engine never calls that client, because its agents talk to LangChain chat
models directly. So until this module existed, a secret a model echoed on
the LangGraph path, the default for named YAML workflows, reached step
outputs, workflow context, traces and run results unmasked.

:func:`sanitize_agent_response_text` applies the same sanitizer to each
step's final response text, under the same switches as the native path,
before anything is parsed out of it. It covers what a step *records*. The
native path additionally sanitizes every turn inside its tool loop; the
LangGraph agent's intermediate turns stay inside the agent and are not
covered here.
"""

from __future__ import annotations

from functools import lru_cache

from ..middleware.response_sanitizer import ResponseSanitizer
from ..settings import get_settings, is_agentic_no_llm_enabled


@lru_cache(maxsize=1)
def _response_sanitizer() -> ResponseSanitizer:
    """One shared sanitizer: its detectors hold only compiled patterns."""
    return ResponseSanitizer()


def sanitize_agent_response_text(text: str) -> str:
    """Return ``text`` with secrets masked, as the native client masks its responses.

    A pass-through when ``AGENTIC_SANITIZE_AGENT_LOOP`` is off or under
    ``AGENTIC_NO_LLM``: the same two conditions under which the native path
    attaches no sanitizer, so one switch governs both engines.
    """
    if not text or is_agentic_no_llm_enabled():
        return text
    if not get_settings().agentic_sanitize_agent_loop:
        return text
    result = _response_sanitizer().sanitize_response_sync(text)
    return result.sanitized_text if result.sanitized_text is not None else text
