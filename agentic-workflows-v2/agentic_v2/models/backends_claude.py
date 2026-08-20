"""Claude backend authenticated by a Claude subscription sign-in.

Every other cloud backend in :mod:`agentic_v2.models.backends_cloud` is
registered only when its API key is present in the environment.
:class:`~agentic_v2.models.backends_cloud.AnthropicBackend` is no exception: it
sends ``x-api-key`` and ``_register_cloud_backends`` skips it entirely without
``ANTHROPIC_API_KEY``. The practical consequence is that an operator who pays
for a **Claude subscription** rather than API credits has no Claude backend at
all -- the router reports no cloud provider configured even though they are
signed in to Claude on the same machine.

This backend closes that gap. It drives ``claude-agent-sdk``, which runs a
locally installed Claude Code CLI, and the CLI resolves the subscription
credentials itself. Nothing here reads, stores, or forwards a credential, and
no API key is involved at any point.

Registration is capability-probed rather than key-probed, the same way
:class:`~agentic_v2.models.backends_local.OnnxBackend` is registered on
``onnxruntime-genai`` being importable: if the SDK imports, the backend is
available. It is additive -- ``AnthropicBackend`` and the ``anthropic:`` prefix
are untouched, so an operator holding both a key and a subscription keeps both
paths and chooses per call which one to spend.

Route to it with the ``claude:`` model prefix::

    backend = auto_configure_backend()
    text = await backend.complete("claude:claude-opus-5", "Summarise this...")

Two limits, surfaced rather than emulated:

* **No sampling controls.** ``ClaudeAgentOptions`` has no temperature, so the
  ``temperature`` argument every :class:`~agentic_v2.models.backends_base.LLMBackend`
  takes cannot be honoured here. It is accepted and ignored, with one debug log
  per call, because refusing it would make this backend undispatchable through
  :class:`~agentic_v2.models.backends.MultiBackend`, which always passes one.
* **No caller-executed tools.** The Agent SDK runs its own tools rather than
  returning tool calls for the runtime's registry to execute, which inverts what
  the tool-dispatch path expects. Passing ``tools`` raises rather than silently
  producing a response with no ``tool_calls``, which the caller would read as
  "the model chose not to call a tool".

**API-key env vars are scrubbed from the CLI subprocess.** This is load-bearing,
not defensive tidying. ``auto_configure_backend`` resolves secrets through
:mod:`agentic_v2.models.secrets`, which puts ``ANTHROPIC_API_KEY`` into
``os.environ``; the SDK spawns the CLI with ``{**os.environ, **options.env}``, so
the child would inherit that key and authenticate with it. The observed effect
is a silent credential-class switch: the call bills the API account instead of
the subscription, and fails outright when the key is invalid or unfunded. Since
``options.env`` can override a value but cannot delete a key, both credential
variables are blanked -- verified against the CLI, which treats an empty value
as absent and falls through to the signed-in account.

Requires the ``claude`` extra: ``pip install 'agentic-workflows-v2[claude]'``.
"""

from __future__ import annotations

import importlib.util
import logging
from dataclasses import dataclass, field
from typing import Any

from .backends_base import LLMBackend

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# claude-agent-sdk availability probe (spec lookup only -- no import)
# ---------------------------------------------------------------------------
#
# ``find_spec`` rather than a try/except import, and the real import deferred to
# first use, for two reasons.
#
# The first is scope: ``agentic_v2.models.backends`` imports this module, so an
# import here is paid by everything that touches the model registry, whether or
# not anyone routes a ``claude:`` call.
#
# The second is a concrete collision. ``claude-agent-sdk`` depends on ``mcp``,
# and ``tests/integrations/mcp/`` is a package directory whose parent is not,
# so pytest names its conftest ``mcp.conftest``. Importing the real ``mcp``
# during collection makes that name resolve to the installed distribution and
# collection dies with ``No module named 'mcp.conftest'``. Deferring keeps the
# import out of collection entirely.

_SDK: Any = None


def _load_sdk() -> Any:
    """Import ``claude_agent_sdk`` on first use and cache the module.

    Raises:
        ValueError: If the ``claude`` extra is not installed. ValueError
            specifically, because ``_try_register_backend`` treats it as
            "backend unavailable" and skips registration silently.
    """
    global _SDK
    if _SDK is None:
        try:
            import claude_agent_sdk
        except ImportError as exc:  # pragma: no cover - needs the extra absent
            raise ValueError(_INSTALL_HINT) from exc
        _SDK = claude_agent_sdk
    return _SDK

CLAUDE_PREFIX = "claude:"
DEFAULT_CLAUDE_MODEL = "claude-opus-5"

_INSTALL_HINT = (
    "claude-agent-sdk is required for the subscription-authenticated Claude "
    "backend: pip install 'agentic-workflows-v2[claude]'"
)

_SIGN_IN_HINT = (
    "The Claude Code CLI was not found. Install it and sign in once -- this "
    "backend authenticates with a Claude subscription, not an API key."
)

# Assistant-level SDK errors that will never succeed on retry. Kept aligned with
# the runtime's own retryable/terminal split so the router's circuit breakers
# see the same classification they would from an HTTP backend.
_TERMINAL_SDK_ERRORS = frozenset(
    {"authentication_failed", "billing_error", "invalid_request"}
)


#: Credential variables blanked in the CLI subprocess so it cannot fall back to
#: API-key auth. Empty rather than absent because ``ClaudeAgentOptions.env`` is
#: merged over ``os.environ`` and so can only override, never unset.
_API_KEY_ENV_VARS = ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")


def subscription_env(overrides: dict[str, str] | None = None) -> dict[str, str]:
    """Build the child-process env that pins the CLI to subscription auth.

    Caller *overrides* are applied last, so an operator who deliberately wants
    API-key billing in this process can still say so explicitly -- but they have
    to say it, rather than getting it by accident from an inherited variable.
    """
    env = dict.fromkeys(_API_KEY_ENV_VARS, "")
    if overrides:
        env.update(overrides)
    return env


def claude_sdk_available() -> bool:
    """Whether ``claude-agent-sdk`` imported, i.e. whether this backend can run.

    The credential check is deliberately *not* part of this: the CLI owns
    credential resolution, and probing it here would mean either shelling out on
    every registration or reading a credential store this module must never
    touch. A signed-out CLI surfaces at call time as a ``RuntimeError`` carrying
    the sign-in instruction.
    """
    return importlib.util.find_spec("claude_agent_sdk") is not None


class ClaudeSubscriptionError(RuntimeError):
    """Raised when the subscription-authenticated Claude path cannot proceed."""


def _flatten_messages(messages: list[dict[str, Any]]) -> tuple[str | None, str]:
    """Split OpenAI-style *messages* into an Agent SDK ``(system, prompt)`` pair.

    System turns become the harness's ``system_prompt``. A lone user turn is
    passed through verbatim; a real multi-turn history is rendered as a labelled
    transcript, because the SDK's streaming-input mode accepts only *user*
    messages -- a prior assistant turn has no lossless representation.
    """
    system_parts: list[str] = []
    turns: list[tuple[str, str]] = []
    for message in messages:
        role = str(message.get("role", "user"))
        content = message.get("content")
        text = "" if content is None else str(content)
        if role == "system":
            system_parts.append(text)
        else:
            turns.append((role, text))

    system = "\n\n".join(part for part in system_parts if part) or None
    if len(turns) == 1:
        return system, turns[0][1]
    labels = {"user": "Human", "assistant": "Assistant"}
    transcript = "\n\n".join(
        f"{labels.get(role, role.capitalize())}: {text}" for role, text in turns
    )
    return system, transcript


def _stop_reason_to_finish_reason(stop_reason: str | None) -> str:
    """Map an SDK stop reason onto the OpenAI-flavoured shape callers expect."""
    return {
        "end_turn": "stop",
        "max_tokens": "length",
        "tool_use": "tool_calls",
        "stop_sequence": "stop",
        None: "stop",
    }.get(stop_reason, stop_reason or "stop")


@dataclass
class ClaudeSubscriptionBackend(LLMBackend):
    """Claude via ``claude-agent-sdk``, authenticated by a subscription sign-in.

    Attributes:
        default_model: Model used when the caller passes a bare ``claude:``.
        effort: Harness reasoning-depth knob, the nearest analogue to the
            sampling controls this transport lacks.
        max_turns: Turn ceiling. ``1`` keeps the harness to a single completion,
            which is what a backend-shaped call means.
        max_budget_usd: Optional hard per-call spend ceiling.
        system_prompt: Optional instructions prepended to every call.
    """

    default_model: str = DEFAULT_CLAUDE_MODEL
    effort: str | None = None
    max_turns: int = 1
    max_budget_usd: float | None = None
    system_prompt: str | None = None
    env: dict[str, str] = field(default_factory=dict)
    _warned_temperature: bool = field(default=False, repr=False)

    def __post_init__(self) -> None:
        # ValueError, not a custom type: _try_register_backend treats it as
        # "this backend is unavailable" and skips registration silently, which
        # is exactly the desired behaviour without the extra.
        if not claude_sdk_available():
            raise ValueError(_INSTALL_HINT)

    # -- LLMBackend --------------------------------------------------------

    async def complete(
        self,
        model: str,
        prompt: str,
        max_tokens: int = 4096,
        temperature: float = 0.7,
        **kwargs: Any,
    ) -> str:
        messages = [{"role": "user", "content": prompt}]
        result = await self.complete_chat(
            model, messages, max_tokens, temperature, **kwargs
        )
        content = result.get("content", "")
        return content if isinstance(content, str) else ""

    async def complete_chat(
        self,
        model: str,
        messages: list[dict[str, Any]],
        max_tokens: int = 4096,
        temperature: float = 0.7,
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        if tools:
            raise ClaudeSubscriptionError(
                "The subscription-authenticated Claude backend cannot accept "
                "tool schemas: the Agent SDK executes its own tools rather "
                "than returning tool calls for the runtime to run. Use the "
                "'anthropic:' prefix (AnthropicBackend) for tool-calling work."
            )
        self._note_ignored_sampling(temperature)

        model_name = model.removeprefix(CLAUDE_PREFIX) or self.default_model
        system, prompt = _flatten_messages(messages)
        options = self._build_options(model_name, system)

        sdk = _load_sdk()
        text_parts: list[str] = []
        result: Any = None
        try:
            async for message in sdk.query(prompt=prompt, options=options):
                if isinstance(message, sdk.RateLimitEvent):
                    self._raise_for_rate_limit(message)
                elif isinstance(message, sdk.AssistantMessage):
                    self._raise_for_assistant_error(message)
                    text_parts.extend(
                        block.text
                        for block in message.content
                        if isinstance(block, sdk.TextBlock)
                    )
                elif isinstance(message, sdk.ResultMessage):
                    self._raise_for_result(message)
                    result = message
        except sdk.CLINotFoundError as exc:
            raise ClaudeSubscriptionError(_SIGN_IN_HINT) from exc

        usage = dict(result.usage) if result is not None and result.usage else {}
        if result is not None and result.total_cost_usd is not None:
            usage["total_cost_usd"] = result.total_cost_usd

        return {
            "content": "".join(text_parts),
            # Always None: this backend rejects tool schemas outright, so a
            # caller can never be left reading an absent tool call as a choice
            # the model made.
            "tool_calls": None,
            "finish_reason": _stop_reason_to_finish_reason(
                result.stop_reason if result is not None else None
            ),
            "model": model_name,
            "usage": usage,
            "_raw_claude_sdk": result,
        }

    # -- helpers -----------------------------------------------------------

    def _note_ignored_sampling(self, temperature: float) -> None:
        """Log once that ``temperature`` has no Agent SDK equivalent.

        MultiBackend always passes a temperature, so raising would make this
        backend undispatchable. Logging once per instance keeps a fan-out from
        emitting one line per sample while still leaving the fact in the record.
        """
        if not self._warned_temperature:
            self._warned_temperature = True
            logger.debug(
                "Claude subscription backend ignores temperature=%s: the Agent "
                "SDK exposes no sampling controls. Use effort=%s instead.",
                temperature,
                self.effort or "high",
            )

    def _build_options(self, model_name: str, system: str | None) -> Any:
        merged_system = "\n\n".join(
            part for part in (self.system_prompt, system) if part
        )
        options: dict[str, Any] = {
            "model": model_name,
            # Empty tool set and allow-list: a backend-shaped call is a plain
            # completion and must not gain filesystem, shell, or network reach.
            "tools": [],
            "allowed_tools": [],
            "max_turns": self.max_turns,
            "permission_mode": "default",
            # Without this the CLI inherits ANTHROPIC_API_KEY from os.environ
            # and silently bills the API account instead of the subscription.
            "env": subscription_env(self.env),
        }
        if merged_system:
            options["system_prompt"] = merged_system
        if self.effort is not None:
            options["effort"] = self.effort
        if self.max_budget_usd is not None:
            options["max_budget_usd"] = self.max_budget_usd
        return _load_sdk().ClaudeAgentOptions(**options)

    @staticmethod
    def _raise_for_rate_limit(event: Any) -> None:
        """Fail the call when the subscription's usage window is exhausted."""
        info = event.rate_limit_info
        if info.status != "rejected":
            return
        window = info.rate_limit_type or "unknown window"
        raise ClaudeSubscriptionError(
            f"Claude subscription rate limit reached ({window}). This is a "
            "subscription usage window, not an API rate limit."
        )

    @staticmethod
    def _raise_for_assistant_error(message: Any) -> None:
        """Fail the call on an assistant-level SDK error."""
        error = message.error
        if error is None:
            return
        detail = f"Claude Agent SDK reported {error!r}."
        if error in _TERMINAL_SDK_ERRORS:
            raise ClaudeSubscriptionError(detail)
        raise ClaudeSubscriptionError(f"{detail} This may succeed on retry.")

    @staticmethod
    def _raise_for_result(result: Any) -> None:
        """Fail the call when the harness reports the run itself failed."""
        if not result.is_error:
            return
        detail = "; ".join(result.errors or []) or result.subtype
        raise ClaudeSubscriptionError(f"Claude Agent SDK run failed: {detail}")


__all__ = [
    "CLAUDE_PREFIX",
    "DEFAULT_CLAUDE_MODEL",
    "ClaudeSubscriptionBackend",
    "ClaudeSubscriptionError",
    "claude_sdk_available",
    "subscription_env",
]
