"""Tests for ``agentic_v2.models.backends_claude``.

Covers the subscription-authenticated Claude backend:

* the credential scrub that keeps the CLI subprocess on the subscription
  sign-in instead of silently inheriting ``ANTHROPIC_API_KEY``;
* registration by *capability* rather than by key, so an operator with a
  subscription and no API key finally gets a Claude backend;
* the canonical response shape ``MultiBackend`` callers already expect;
* the two limits this transport cannot honour (sampling controls, caller-run
  tools), surfaced rather than emulated.

Runs offline: ``query`` is monkeypatched and the SDK's own message dataclasses
are replayed, so no CLI, sign-in, or network is involved. Using the real
dataclasses means an upstream field rename fails these tests rather than
passing them and failing in production.

The module skips without the optional ``claude`` extra; the
``claude-subscription-tests`` CI job installs it and hard-guards the import so
that skip cannot go green unnoticed.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

pytest.importorskip("claude_agent_sdk", reason="requires the [claude] extra")

from claude_agent_sdk import (
    AssistantMessage,
    RateLimitEvent,
    ResultMessage,
    TextBlock,
)
from claude_agent_sdk.types import RateLimitInfo

from agentic_v2.models import backends_claude
from agentic_v2.models.backends import PREFIX_MAP
from agentic_v2.models.backends_claude import (
    ClaudeSubscriptionBackend,
    ClaudeSubscriptionError,
    subscription_env,
)

# ---------------------------------------------------------------------------
# Builders
# ---------------------------------------------------------------------------


def assistant(text: str, *, error: str | None = None) -> AssistantMessage:
    return AssistantMessage(
        content=[TextBlock(text=text)],
        model="claude-opus-5",
        error=error,  # type: ignore[arg-type]
    )


def result(
    *,
    is_error: bool = False,
    usage: dict[str, Any] | None = None,
    cost: float | None = None,
    stop_reason: str | None = "end_turn",
    errors: list[str] | None = None,
) -> ResultMessage:
    return ResultMessage(
        subtype="success",
        duration_ms=1,
        duration_api_ms=1,
        is_error=is_error,
        num_turns=1,
        session_id="s1",
        stop_reason=stop_reason,
        total_cost_usd=cost,
        usage=usage,
        errors=errors,
    )


def rate_limit(status: str) -> RateLimitEvent:
    return RateLimitEvent(
        rate_limit_info=RateLimitInfo(
            status=status,  # type: ignore[arg-type]
            resets_at=1_800_000_000,
            rate_limit_type="five_hour",
        ),
        uuid="u1",
        session_id="s1",
    )


def patch_query(monkeypatch: pytest.MonkeyPatch, *messages: Any) -> list[dict[str, Any]]:
    """Swap the lazily-loaded SDK for one whose ``query`` replays *messages*.

    The module resolves SDK names through ``_load_sdk()`` rather than importing
    at module scope (see its comment: the real ``mcp`` import breaks pytest's
    collection of ``tests/integrations/mcp``). So the seam to patch is the
    cached module object, not a module-level ``query`` attribute. Everything
    except ``query`` is the genuine SDK, so the ``isinstance`` dispatch under
    test runs against the real dataclasses.
    """
    calls: list[dict[str, Any]] = []

    async def _query(*, prompt: str, options: Any):  # type: ignore[no-untyped-def]
        calls.append({"prompt": prompt, "options": options})
        for message in messages:
            yield message

    monkeypatch.setattr(backends_claude, "_SDK", _sdk_stub(_query))
    return calls


def _sdk_stub(query_fn: Any) -> Any:
    """The real SDK module with ``query`` swapped out."""
    import claude_agent_sdk

    return SimpleNamespace(
        query=query_fn,
        AssistantMessage=claude_agent_sdk.AssistantMessage,
        ResultMessage=claude_agent_sdk.ResultMessage,
        RateLimitEvent=claude_agent_sdk.RateLimitEvent,
        TextBlock=claude_agent_sdk.TextBlock,
        CLINotFoundError=claude_agent_sdk.CLINotFoundError,
        ClaudeAgentOptions=claude_agent_sdk.ClaudeAgentOptions,
    )


USER = [{"role": "user", "content": "hi"}]


# ---------------------------------------------------------------------------
# Credential scrub -- the reason this backend exists at all
# ---------------------------------------------------------------------------


def test_subscription_env_blanks_both_credential_vars() -> None:
    """Blank, not absent: ClaudeAgentOptions.env merges over os.environ.

    The SDK spawns the CLI with ``{**os.environ, **options.env}``, so an entry
    can override a value but can never remove the key. An empty value is what
    the CLI treats as absent.
    """
    env = subscription_env()
    assert env == {"ANTHROPIC_API_KEY": "", "ANTHROPIC_AUTH_TOKEN": ""}


def test_subscription_env_lets_an_explicit_override_win() -> None:
    """Deliberate API-key billing stays possible -- it just has to be said."""
    env = subscription_env({"ANTHROPIC_API_KEY": "explicit"})
    assert env["ANTHROPIC_API_KEY"] == "explicit"
    assert env["ANTHROPIC_AUTH_TOKEN"] == ""


async def test_cli_subprocess_cannot_inherit_an_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The regression this backend was built around.

    ``auto_configure_backend`` puts ANTHROPIC_API_KEY into os.environ while
    resolving secrets. Without the scrub the CLI child inherits it and
    authenticates with the API key -- a silent credential-class switch that
    bills the wrong account and 401s outright when that key is unfunded.
    """
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-should-never-reach-the-cli")
    calls = patch_query(monkeypatch, assistant("ok"), result())

    await ClaudeSubscriptionBackend().complete_chat("claude:claude-opus-5", USER)

    assert calls[0]["options"].env["ANTHROPIC_API_KEY"] == ""


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------


def test_claude_prefix_is_registered() -> None:
    assert PREFIX_MAP["claude:"] == "claude"


def test_registration_is_capability_probed_not_key_probed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A subscription operator has no API key, so a key probe would skip this."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert backends_claude.claude_sdk_available() is True
    assert ClaudeSubscriptionBackend() is not None


def test_missing_extra_raises_value_error_so_registration_skips_quietly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """_try_register_backend swallows ValueError -- that is the intended path."""
    monkeypatch.setattr(backends_claude, "claude_sdk_available", lambda: False)
    with pytest.raises(ValueError, match=r"agentic-workflows-v2\[claude\]"):
        ClaudeSubscriptionBackend()


# ---------------------------------------------------------------------------
# Response shape
# ---------------------------------------------------------------------------


async def test_complete_chat_returns_the_canonical_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_query(
        monkeypatch,
        assistant("hello"),
        result(usage={"input_tokens": 9, "output_tokens": 2}, cost=0.5),
    )
    out = await ClaudeSubscriptionBackend().complete_chat("claude:claude-opus-5", USER)

    assert out["content"] == "hello"
    assert out["tool_calls"] is None
    assert out["finish_reason"] == "stop"
    assert out["model"] == "claude-opus-5"
    assert out["usage"]["input_tokens"] == 9
    assert out["usage"]["total_cost_usd"] == 0.5


async def test_complete_returns_plain_text(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_query(monkeypatch, assistant("four"), result())
    out = await ClaudeSubscriptionBackend().complete("claude:claude-opus-5", "2+2?")
    assert out == "four"


async def test_bare_prefix_falls_back_to_the_default_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = patch_query(monkeypatch, assistant("ok"), result())
    await ClaudeSubscriptionBackend().complete_chat("claude:", USER)
    assert calls[0]["options"].model == "claude-opus-5"


@pytest.mark.parametrize(
    ("stop_reason", "expected"),
    [
        ("end_turn", "stop"),
        ("max_tokens", "length"),
        ("stop_sequence", "stop"),
        (None, "stop"),
    ],
)
async def test_stop_reason_maps_to_openai_finish_reason(
    monkeypatch: pytest.MonkeyPatch, stop_reason: str | None, expected: str
) -> None:
    patch_query(monkeypatch, assistant("x"), result(stop_reason=stop_reason))
    out = await ClaudeSubscriptionBackend().complete_chat("claude:claude-opus-5", USER)
    assert out["finish_reason"] == expected


# ---------------------------------------------------------------------------
# Message flattening
# ---------------------------------------------------------------------------


async def test_system_turns_become_the_harness_system_prompt(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = patch_query(monkeypatch, assistant("ok"), result())
    await ClaudeSubscriptionBackend().complete_chat(
        "claude:claude-opus-5",
        [{"role": "system", "content": "be terse"}, {"role": "user", "content": "go"}],
    )
    assert calls[0]["options"].system_prompt == "be terse"
    assert calls[0]["prompt"] == "go"


async def test_multi_turn_history_becomes_a_labelled_transcript(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = patch_query(monkeypatch, assistant("ok"), result())
    await ClaudeSubscriptionBackend().complete_chat(
        "claude:claude-opus-5",
        [
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "reply"},
            {"role": "user", "content": "second"},
        ],
    )
    assert calls[0]["prompt"] == "Human: first\n\nAssistant: reply\n\nHuman: second"


# ---------------------------------------------------------------------------
# Limits, surfaced not emulated
# ---------------------------------------------------------------------------


async def test_tool_schemas_are_rejected_rather_than_silently_dropped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A response with no tool_calls would read as 'the model declined'."""
    patch_query(monkeypatch, assistant("ok"), result())
    with pytest.raises(ClaudeSubscriptionError, match="tool schemas"):
        await ClaudeSubscriptionBackend().complete_chat(
            "claude:claude-opus-5", USER, tools=[{"function": {"name": "f"}}]
        )


async def test_temperature_is_accepted_and_ignored(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """MultiBackend always passes one, so raising would make this undispatchable."""
    patch_query(monkeypatch, assistant("ok"), result())
    out = await ClaudeSubscriptionBackend().complete_chat(
        "claude:claude-opus-5", USER, temperature=0.9
    )
    assert out["content"] == "ok"


async def test_tools_are_disabled_on_the_harness(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = patch_query(monkeypatch, assistant("ok"), result())
    await ClaudeSubscriptionBackend().complete_chat("claude:claude-opus-5", USER)
    options = calls[0]["options"]
    assert options.tools == []
    assert options.allowed_tools == []
    assert options.max_turns == 1


# ---------------------------------------------------------------------------
# Failure translation
# ---------------------------------------------------------------------------


async def test_rejected_rate_limit_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_query(monkeypatch, rate_limit("rejected"))
    with pytest.raises(ClaudeSubscriptionError, match="subscription rate limit"):
        await ClaudeSubscriptionBackend().complete_chat("claude:claude-opus-5", USER)


async def test_warning_rate_limit_does_not_raise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_query(monkeypatch, rate_limit("allowed_warning"), assistant("ok"), result())
    out = await ClaudeSubscriptionBackend().complete_chat("claude:claude-opus-5", USER)
    assert out["content"] == "ok"


@pytest.mark.parametrize(
    "error", ["authentication_failed", "billing_error", "invalid_request", "server_error"]
)
async def test_assistant_errors_raise(
    monkeypatch: pytest.MonkeyPatch, error: str
) -> None:
    patch_query(monkeypatch, assistant("", error=error))
    with pytest.raises(ClaudeSubscriptionError, match=error):
        await ClaudeSubscriptionBackend().complete_chat("claude:claude-opus-5", USER)


async def test_retryable_assistant_error_says_so(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_query(monkeypatch, assistant("", error="server_error"))
    with pytest.raises(ClaudeSubscriptionError, match="may succeed on retry"):
        await ClaudeSubscriptionBackend().complete_chat("claude:claude-opus-5", USER)


async def test_failed_run_raises_with_detail(monkeypatch: pytest.MonkeyPatch) -> None:
    patch_query(monkeypatch, result(is_error=True, errors=["boom"]))
    with pytest.raises(ClaudeSubscriptionError, match="boom"):
        await ClaudeSubscriptionBackend().complete_chat("claude:claude-opus-5", USER)


async def test_missing_cli_becomes_a_sign_in_instruction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from claude_agent_sdk import CLINotFoundError

    async def _boom(*, prompt: str, options: Any):  # type: ignore[no-untyped-def]
        raise CLINotFoundError("nope")
        yield  # pragma: no cover - unreachable, makes this an async generator

    monkeypatch.setattr(backends_claude, "_SDK", _sdk_stub(_boom))
    with pytest.raises(ClaudeSubscriptionError, match="not an API key"):
        await ClaudeSubscriptionBackend().complete_chat("claude:claude-opus-5", USER)


# ---------------------------------------------------------------------------
# Import weight
# ---------------------------------------------------------------------------


def test_importing_the_registry_does_not_import_the_sdk() -> None:
    """The SDK import must stay out of pytest collection.

    claude-agent-sdk depends on `mcp`, and tests/integrations/mcp/ is a package
    whose parent is not, so pytest names its conftest `mcp.conftest`. If the
    real `mcp` is already imported, that name resolves to the installed
    distribution and collection dies with "No module named 'mcp.conftest'".
    Importing the registry must therefore stay SDK-free.
    """
    import subprocess
    import sys

    probe = (
        "import sys; import agentic_v2.models.backends; "
        "print('mcp' in sys.modules or 'claude_agent_sdk' in sys.modules)"
    )
    out = subprocess.run(
        [sys.executable, "-c", probe], capture_output=True, text=True, check=True
    )
    assert out.stdout.strip() == "False"
