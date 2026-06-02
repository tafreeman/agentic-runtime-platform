"""ADR-023 Phase 6a/6c: delegate the INNER LLM mechanics of a step to EK patterns.

This module is the *step-layer* counterpart to Phase 5b (``models.client``). Where
Phase 5b re-pointed the plain-text ``LLMClientWrapper.complete`` seam onto the EK
provider shim, Phase 6 re-points the **chat-completion turn** that lives inside an
LLM-backed step (``engine.agent_resolver._make_llm_step`` ->
``engine.tool_execution.complete_chat_with_fallback``) onto EK pattern primitives:

* **6a — plain completion** flows through EK ``_TrackedProvider`` /
  ``checked_complete`` over a :class:`~agentic_v2.models.ek_provider.SmartRouterProvider`.
  The TrackedProvider is budget-checked (EK ``CostTracker`` two-phase
  ``reserve_call()`` / ``record_without_call()``), retry-wrapped (EK
  ``RetryConfig``), and truncation-tracked, sharing **one** ``CostTracker`` per
  step so multi-turn tool loops accumulate against a single ledger.
* **6c — structured/JSON extraction** flows through EK ``structured()``
  (``extract_json`` 3-strategy). The runtime ``ReviewStatus.normalize`` STILL
  runs at the DAG/gating layer (``engine.step`` / ``engine.llm_output_parsing``)
  *after* this — it is intentionally NOT performed here.

Hard constraints (ADR-023 functionality-preservation + accepted decisions):

* **Flag-gated, default OFF.** Nothing here runs unless
  ``settings.agentic_ek_provider`` is true. The caller
  (``complete_chat_with_fallback``) keeps its legacy branch byte-for-byte for
  the OFF case; this module adds a new code path only.
* **Budget precedence (ACCEPTED): layer, do not merge.** On each
  ``LLMResponse`` the runtime :class:`~agentic_v2.models.client.TokenBudget`
  owns the token-sum ceiling — ``TokenBudget.consume(total_tokens)`` runs FIRST
  and raises ``BudgetExhaustedError`` on cap. The EK ``CostTracker`` owns the
  ``llm_calls`` dimension via the ``reserve_call()`` / ``record_without_call()``
  two-phase ordering inside ``checked_complete``. We interpose a thin
  budget-enforcing provider so ``consume`` fires before EK records the response;
  a cache hit (handled by the caller, not here) counts as a 0-token recorded
  call upstream.
* **Reliability preserved.** All circuit-breaker / bulkhead / rate-limit /
  cross-tier / Redis-CAS behaviour lives inside ``SmartRouterProvider.complete``
  (Phase 5a) — this module never re-implements it. ``supports_tools`` delegation
  is likewise inherited from the provider.
* **No mapping reimplementation.** Token totals come from the EK ``LLMResponse``
  value type (Phase 4 adapter output); the canonical dict the caller expects is
  reconstructed via :func:`ek_adapters.llm_response_to_dict`.
* **Tool path (6b — ACCEPTED): EK ``react_loop`` is the DEFAULT tool-calling
  loop.** When the flag is ON and a step does NOT opt out with
  ``tool_path: native``, its multi-turn tool-use loop runs through EK
  :func:`~executionkit.patterns.react_loop.react_loop` over the same
  :class:`BudgetEnforcingProvider` / :class:`SmartRouterProvider` stack (see
  :func:`run_tool_loop_via_ek`). Runtime :class:`~agentic_v2.tools.base.BaseTool`
  instances are wrapped as EK :class:`~executionkit.types.Tool` value types via
  :func:`wrap_runtime_tool`. ``supports_tools`` is honoured: a Gemini route
  (``supports_tools=False``) makes ``react_loop`` REFUSE (raise ``TypeError``)
  rather than silently dropping tools. A step that sets ``tool_path: native``
  keeps the bespoke ``engine.tool_execution.run_tool_calls`` loop UNCHANGED.
  Single-owner: a migrated step uses ``react_loop`` OR ``run_tool_calls``, never
  both mid-thread.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from executionkit.cost import CostTracker
from executionkit.patterns.base import _TrackedProvider
from executionkit.patterns.react_loop import react_loop as ek_react_loop
from executionkit.patterns.structured import structured as ek_structured
from executionkit.provider import BudgetExhaustedError
from executionkit.provider import LLMResponse as EKProviderResponse
from executionkit.types import Tool as EKTool

from ..models import ek_adapters
from ..models.ek_provider import SmartRouterProvider

if TYPE_CHECKING:
    from collections.abc import Sequence

    from ..models.client import TokenBudget
    from ..models.router import ModelTier

__all__ = [
    "BudgetEnforcingProvider",
    "complete_turn_via_ek",
    "run_tool_loop_via_ek",
    "structured_via_ek",
    "wrap_runtime_tool",
]


class BudgetEnforcingProvider:
    """Interpose runtime :class:`TokenBudget` enforcement before EK records cost.

    Wraps an inner EK ``LLMProvider`` (a :class:`SmartRouterProvider`) so that on
    every successful ``complete`` the runtime ``TokenBudget`` consumes the
    response's ``total_tokens`` FIRST and raises ``BudgetExhaustedError`` on cap
    — *before* the surrounding ``checked_complete`` records the response on the
    EK ``CostTracker``. This is the load-bearing piece of the ACCEPTED budget
    precedence: the runtime budget owns the token-sum ceiling; the EK tracker
    owns the ``llm_calls`` dimension. The two are layered, never merged.

    ``supports_tools`` is delegated (F-04) to the inner provider so a wrapper
    never over-claims capability.
    """

    def __init__(
        self,
        inner: SmartRouterProvider,
        budget: TokenBudget | None,
    ) -> None:
        self._inner = inner
        self._budget = budget

    @property
    def supports_tools(self) -> bool:
        """Delegate capability to the inner provider (never hardcode)."""
        return self._inner.supports_tools

    async def complete(
        self,
        messages: Sequence[dict[str, Any]],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        tools: Sequence[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> EKProviderResponse:
        """Route to the inner provider, then enforce the runtime budget FIRST.

        Raises:
            BudgetExhaustedError: When ``TokenBudget.consume(total_tokens)``
                reports the cap is hit. Raised AFTER the physical call (the
                tokens were really spent) but BEFORE EK records the response,
                so the runtime budget is the authoritative token-sum ceiling.
        """
        # ``SmartRouterProvider.complete`` returns
        # ``executionkit.provider.LLMResponse`` — the SAME value type EK's
        # ``LLMProvider`` protocol (consumed by ``_TrackedProvider`` /
        # ``structured`` / ``react_loop``) is typed to. Under ADR-023 Option A′
        # there is a single value-type set, so no boundary cast is needed.
        response = await self._inner.complete(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            tools=tools,
            **kwargs,
        )
        if self._budget is not None and not self._budget.consume(response.total_tokens):
            raise BudgetExhaustedError(
                f"Token budget exhausted: "
                f"{self._budget.used_tokens}/{self._budget.max_tokens}",
            )
        return response


async def complete_turn_via_ek(
    *,
    router: Any,
    backend: Any,
    tier: ModelTier,
    messages: list[dict[str, Any]],
    max_tokens: int,
    tools: list[dict[str, Any]] | None,
    budget: TokenBudget | None,
    tracker: CostTracker,
    metadata: dict[str, Any],
) -> tuple[dict[str, Any], str, int]:
    """Run ONE plain-completion turn through EK ``_TrackedProvider``.

    Phase 6a inner-mechanics delegation. The provider stack is:

        BudgetEnforcingProvider(SmartRouterProvider(router, backend, tier))

    wrapped by EK ``_TrackedProvider`` so the call is budget-checked (call
    dimension), retry-wrapped, and truncation-tracked while sharing the
    caller-supplied ``tracker`` and ``metadata`` across the step's turns.

    The runtime ``TokenBudget`` (token-sum ceiling) is enforced inside
    :class:`BudgetEnforcingProvider` BEFORE EK records the response on
    ``tracker`` — preserving the ACCEPTED budget precedence and EK's
    ``reserve_call()`` / ``record_without_call()`` ordering.

    Returns:
        A ``(response_dict, model_name, tokens_used)`` triple matching the
        legacy :func:`complete_chat_with_fallback` contract so the caller's
        downstream parsing is untouched. ``response_dict`` is the canonical
        Phase-3 shape rebuilt from the EK ``LLMResponse`` via
        ``ek_adapters.llm_response_to_dict`` (preserving content / tool_calls /
        finish_reason / usage).

    Raises:
        BudgetExhaustedError: When the runtime token-sum cap is hit.
        ExecutionKitError: Translated provider errors (RateLimitError /
            PermanentError / ProviderError) so the caller can map them onto
            ``StepResult.error`` after passing through the error hooks.
    """
    inner = SmartRouterProvider(router, backend, tier)
    budgeted = BudgetEnforcingProvider(inner, budget)
    tracked = _TrackedProvider(
        budgeted,
        tracker,
        metadata,
        budget=None,  # EK call-budget is None here; runtime owns token ceiling.
        retry=None,  # EK DEFAULT_RETRY inside checked_complete.
        context="step.complete_turn",
    )

    # ``_TrackedProvider.complete`` returns ``executionkit.provider.LLMResponse``
    # and forwards the wrapped provider's return verbatim. Under ADR-023
    # Option A′ that is the SAME value type ``ek_adapters.llm_response_to_dict``
    # consumes (``SmartRouterProvider`` -> ``dict_to_llm_response`` produced it),
    # so no boundary cast is needed.
    response = await tracked.complete(
        messages,
        max_tokens=max_tokens,
        tools=tools,
    )

    response_dict = ek_adapters.llm_response_to_dict(response)

    model_used = ""
    raw = getattr(response, "raw", None)
    if isinstance(raw, dict):
        model_used = str(raw.get("model") or "")
        # Preserve the canonical raw dict's model key on the rebuilt dict so the
        # caller's metadata stays loss-less.
        if "model" not in response_dict and model_used:
            response_dict["model"] = model_used
    if not model_used:
        model_used = router.get_model_for_tier(tier) or ""

    return response_dict, model_used, int(response.total_tokens)


async def structured_via_ek(
    *,
    router: Any,
    backend: Any,
    tier: ModelTier,
    prompt: str,
    budget: TokenBudget | None,
    tracker: CostTracker,
    max_tokens: int,
    max_retries: int = 3,
) -> tuple[dict[str, Any] | list[Any], int]:
    """Extract structured JSON via EK ``structured()`` (6c, 3-strategy).

    Delegates JSON extraction to EK's ``structured`` pattern (``extract_json``
    with markdown-fence / bracket-span fallbacks plus bounded repair). The
    runtime ``ReviewStatus.normalize`` is intentionally NOT applied here — it
    still runs at the DAG/gating layer afterward.

    ``structured`` owns its own ``CostTracker`` internally; we fold its reported
    usage into the caller's shared ``tracker`` via ``add_usage`` so the step's
    cumulative ledger stays accurate, then enforce the runtime ``TokenBudget``
    token-sum ceiling FIRST (raising ``BudgetExhaustedError`` on cap).

    Returns:
        A ``(value, tokens_used)`` tuple where ``value`` is the parsed JSON
        object/array.

    Raises:
        BudgetExhaustedError: When the runtime token-sum cap is hit.
        PatternError: When EK could not produce valid structured output.
    """
    provider = BudgetEnforcingProvider(
        SmartRouterProvider(router, backend, tier), budget=None
    )
    result = await ek_structured(
        provider,
        prompt,
        max_retries=max_retries,
        max_tokens=max_tokens,
    )
    tokens_used = result.cost.input_tokens + result.cost.output_tokens
    tracker.add_usage(result.cost)

    if budget is not None and not budget.consume(tokens_used):
        raise BudgetExhaustedError(
            f"Token budget exhausted: {budget.used_tokens}/{budget.max_tokens}",
        )
    return result.value, int(tokens_used)


# ---------------------------------------------------------------------------
# 6b — EK react_loop as the DEFAULT tool-calling loop
# ---------------------------------------------------------------------------


def wrap_runtime_tool(
    tool: Any,
    parameters_schema: dict[str, Any],
) -> EKTool:
    """Wrap a runtime :class:`~agentic_v2.tools.base.BaseTool` as an EK ``Tool``.

    The EK :class:`~executionkit.types.Tool` value type pairs a name /
    description / JSON-schema ``parameters`` object with an async ``execute``
    callable returning a ``str`` observation. The runtime tool's ``execute``
    returns a :class:`~agentic_v2.tools.base.ToolResult`; we serialize it with
    the SAME compact-JSON contract the native loop uses
    (``tool_execution.serialize_tool_result``) so the observation the LLM sees
    is byte-identical regardless of which loop drove the call. Validation and
    unknown-tool / exception handling are owned by ``react_loop`` itself.

    Args:
        tool: A runtime tool instance (``BaseTool``) exposing ``name``,
            ``description``, async ``execute(**kwargs)`` -> ``ToolResult``.
        parameters_schema: The JSON-schema ``parameters`` object already built
            for this tool by
            :func:`~agentic_v2.engine.tool_execution.build_tool_contracts`
            (``{"type": "object", "properties": {...}, "required": [...]}``).
            Reused verbatim — no schema reimplementation.

    Returns:
        A frozen EK :class:`~executionkit.types.Tool`.
    """
    # Local import keeps this module import-light and avoids any import cycle
    # with the engine package at module load.
    from .tool_execution import serialize_tool_result

    async def _execute(**kwargs: Any) -> str:
        tool_result = await tool.execute(**kwargs)
        return serialize_tool_result(tool_result)

    return EKTool(
        name=tool.name,
        description=tool.description,
        parameters=parameters_schema,
        execute=_execute,
    )


def _ek_tools_from_contracts(
    tool_schemas: list[dict[str, Any]],
    bound_tools: dict[str, Any],
) -> list[EKTool]:
    """Pair ``build_tool_contracts`` schemas with bound tools into EK ``Tool``s.

    Reuses the OpenAI ``function.parameters`` object already computed by
    :func:`~agentic_v2.engine.tool_execution.build_tool_contracts` so the EK
    ``Tool.parameters`` JSON schema matches the native path exactly.
    """
    ek_tools: list[EKTool] = []
    for schema in tool_schemas:
        function = schema.get("function", {})
        name = str(function.get("name", ""))
        tool = bound_tools.get(name)
        if tool is None:
            continue
        parameters_schema = function.get("parameters") or {"type": "object"}
        ek_tools.append(wrap_runtime_tool(tool, parameters_schema))
    return ek_tools


async def run_tool_loop_via_ek(
    *,
    router: Any,
    backend: Any,
    tier: ModelTier,
    prompt: str,
    tool_schemas: list[dict[str, Any]],
    bound_tools: dict[str, Any],
    max_tokens: int,
    budget: TokenBudget | None,
    max_rounds: int = 8,
    max_observation_chars: int = 12000,
) -> tuple[str, str, int, int]:
    """Drive a step's multi-turn tool loop through EK ``react_loop`` (6b default).

    Provider stack mirrors :func:`complete_turn_via_ek`::

        BudgetEnforcingProvider(SmartRouterProvider(router, backend, tier))

    so the runtime :class:`TokenBudget` token-sum ceiling is enforced FIRST on
    every physical call (``BudgetEnforcingProvider.complete`` raises
    ``BudgetExhaustedError`` before EK records the response) and ALL router
    reliability — circuit breaker, bulkhead, rate-limit cooldown, cross-tier
    fallback, Redis-CAS — keeps working inside ``SmartRouterProvider.complete``.

    ``supports_tools`` is honoured: when the resolved route cannot do tools
    (Gemini), ``react_loop`` REFUSES by raising ``TypeError`` rather than
    silently dropping the tools. The caller treats that as a step failure
    (placeholder output) just like any other provider error.

    Single-owner contract: this runs ``react_loop`` for the WHOLE step. The
    native ``run_tool_calls`` loop is NOT used for the same step (the caller
    selects exactly one path per step).

    Args:
        prompt: The fully-assembled user prompt for the step.
        tool_schemas: OpenAI function schemas from ``build_tool_contracts``.
        bound_tools: ``{name: BaseTool}`` from ``build_tool_contracts``.
        max_rounds: Max think-act-observe cycles (8, matching the native loop).
        max_observation_chars: Per-tool-result truncation (12000, matching the
            native loop's ``MAX_TOOL_RESULT_CHARS``).

    Returns:
        A ``(final_text, model_used, tokens_used, tool_calls_made)`` tuple. The
        caller parses ``final_text`` exactly as it parses the legacy loop's
        terminal assistant content.

    Raises:
        TypeError: When the resolved route does not support tools (Gemini) —
            ``react_loop`` refuses. Propagated to the caller.
        BudgetExhaustedError: When the runtime token-sum cap is hit mid-loop.
        MaxIterationsError / ExecutionKitError: Surfaced from ``react_loop``.
    """
    provider = BudgetEnforcingProvider(
        SmartRouterProvider(router, backend, tier),
        budget,
    )
    ek_tools = _ek_tools_from_contracts(tool_schemas, bound_tools)

    # ``BudgetEnforcingProvider`` structurally satisfies EK's runtime_checkable
    # ``ToolCallingProvider`` (it exposes ``complete`` + ``supports_tools``);
    # react_loop verifies this with an ``isinstance`` check at runtime and
    # REFUSES (raises TypeError) on a Gemini route. mypy cannot see the implicit
    # Protocol conformance through the wrapper, so the cast is annotated here.
    result = await ek_react_loop(
        provider,  # type: ignore[arg-type]
        prompt,
        ek_tools,
        max_rounds=max_rounds,
        max_observation_chars=max_observation_chars,
        max_tokens=max_tokens,
    )

    cost = result.cost
    tokens_used = int(cost.input_tokens + cost.output_tokens)
    tool_calls_made = int(result.metadata.get("tool_calls_made", 0))

    model_used = router.get_model_for_tier(tier) or ""

    final_text = result.value if isinstance(result.value, str) else str(result.value)
    return final_text, model_used, tokens_used, tool_calls_made
