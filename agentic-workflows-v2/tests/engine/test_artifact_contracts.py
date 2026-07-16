"""Unit and engine-parity coverage for typed workflow artifact contracts."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from agentic_v2.artifact_contracts import (
    ArtifactContract,
    ArtifactContractConfigError,
    ArtifactContractError,
    expected_output_keys,
    parse_artifact_contracts,
    validate_and_normalize_artifacts,
)
from agentic_v2.engine.context import ExecutionContext
from agentic_v2.engine.step import RetryConfig, StepDefinition, StepExecutor
from agentic_v2.langchain.config import StepConfig
from agentic_v2.langchain.graph_wiring import resolve_inputs_into_context
from agentic_v2.langchain.state import initial_state


def _contract(*, aliases: tuple[str, ...] = ()) -> ArtifactContract:
    return ArtifactContract(kind="code_artifact", aliases=aliases)


@pytest.mark.parametrize(
    "value",
    [
        {"Program.cs": "var builder = WebApplication.CreateBuilder(args);"},
        "FILE: src/main.py\nprint('ok')\nENDFILE",
    ],
)
def test_code_artifact_accepts_file_map_or_complete_sentinel(value: object) -> None:
    normalized = validate_and_normalize_artifacts(
        {"backend_code": value},
        {"backend_code": _contract()},
    )

    assert normalized["backend_code"] == value


@pytest.mark.parametrize(
    ("value", "code"),
    [
        ({}, "empty"),
        ({"Program.cs": "   "}, "empty_source"),
        ({"../Program.cs": "code"}, "unsafe_path"),
        ({"C:\\temp\\Program.cs": "code"}, "unsafe_path"),
        ({"src/./Program.cs": "code"}, "unsafe_path"),
        ({"Program.cs.": "code"}, "unsafe_path"),
        ({"Program.cs ": "code"}, "unsafe_path"),
        ({"Program.cs:stream": "code"}, "unsafe_path"),
        ({"CON": "code"}, "unsafe_path"),
        ({"src/COM1.txt": "code"}, "unsafe_path"),
        ({"src/Pro\x01gram.cs": "code"}, "unsafe_path"),
        ({"message": "backend code is elsewhere"}, "placeholder_object"),
        ({"Program.cs": "No backend code was available."}, "placeholder"),
        (
            "OpenAPI spec not generated here; see backend_code for implementation",
            "placeholder",
        ),
        ("I cannot provide the backend code.", "placeholder"),
        ("The implementation is in another response.", "invalid_format"),
        ("FILE: main.py\nprint('ok')\nENDFILE\ntrailing prose", "invalid_format"),
        ("leading prose\nFILE: main.py\nprint('ok')\nENDFILE", "invalid_format"),
    ],
)
def test_code_artifact_rejects_hollow_unsafe_or_prose_values(
    value: object,
    code: str,
) -> None:
    with pytest.raises(ArtifactContractError) as exc_info:
        validate_and_normalize_artifacts(
            {"backend_code": value},
            {"backend_code": _contract()},
        )

    assert any(item.code == code for item in exc_info.value.diagnostics)
    assert exc_info.value.diagnostics[0].as_dict()["kind"] == "code_artifact"


@pytest.mark.parametrize("as_mapping", [False, True])
def test_code_artifact_rejects_oversize_content(as_mapping: bool) -> None:
    content = "x" * 262145
    value: object = {"main.py": content} if as_mapping else content

    with pytest.raises(ArtifactContractError) as exc_info:
        validate_and_normalize_artifacts(
            {"backend_code": value},
            {"backend_code": _contract()},
        )

    assert any(item.code == "too_large" for item in exc_info.value.diagnostics)


def test_multi_file_payload_with_two_blocks_is_accepted() -> None:
    payload = (
        "FILE: src/main.py\n"
        "print('main')\n"
        "ENDFILE\n"
        "\n"
        "FILE: src/util.py\n"
        "print('util')\n"
        "ENDFILE"
    )

    normalized = validate_and_normalize_artifacts(
        {"backend_code": payload},
        {"backend_code": _contract()},
    )

    assert normalized["backend_code"] == payload


def test_multi_file_payload_with_trailing_prose_is_rejected() -> None:
    payload = (
        "FILE: src/main.py\n"
        "print('main')\n"
        "ENDFILE\n"
        "\n"
        "FILE: src/util.py\n"
        "print('util')\n"
        "ENDFILE\n"
        "trailing notes about the change"
    )

    with pytest.raises(ArtifactContractError) as exc_info:
        validate_and_normalize_artifacts(
            {"backend_code": payload},
            {"backend_code": _contract()},
        )

    assert any(item.code == "invalid_format" for item in exc_info.value.diagnostics)


def test_missing_required_artifact_has_structured_diagnostic() -> None:
    with pytest.raises(ArtifactContractError) as exc_info:
        validate_and_normalize_artifacts({}, {"backend_code": _contract()})

    diagnostic = exc_info.value.diagnostics[0]
    assert diagnostic.field == "backend_code"
    assert diagnostic.code == "missing"


def test_valid_canonical_wins_over_placeholder_alias() -> None:
    backend = {"Program.cs": "var app = builder.Build();"}

    normalized = validate_and_normalize_artifacts(
        {
            "backend_code": backend,
            "api_code": "OpenAPI spec not generated here; see backend_code",
        },
        {"backend_code": _contract(aliases=("api_code",))},
    )

    assert normalized["backend_code"] is backend
    assert "api_code" not in normalized


def test_valid_legacy_alias_is_promoted_when_canonical_is_invalid() -> None:
    backend = {"Program.cs": "var app = builder.Build();"}

    normalized = validate_and_normalize_artifacts(
        {
            "backend_code": "not generated",
            "api_code": backend,
        },
        {"backend_code": _contract(aliases=("api_code",))},
    )

    assert normalized["backend_code"] is backend


def test_optional_contract_field_absent_is_not_required() -> None:
    """``required: false`` and the field is entirely missing: passes through."""
    normalized = validate_and_normalize_artifacts(
        {},
        {"backend_code": ArtifactContract(kind="code_artifact", required=False)},
    )

    assert "backend_code" not in normalized


def test_optional_contract_field_present_but_invalid_still_raises() -> None:
    """``required: false`` does not waive validation once the field is present.

    ``validate_and_normalize_artifacts`` only skips a contract when the field
    (and all its aliases) are absent; a present-but-invalid value for an
    optional field is rejected exactly like a required one.
    """
    with pytest.raises(ArtifactContractError) as exc_info:
        validate_and_normalize_artifacts(
            {"backend_code": "not generated"},
            {"backend_code": ArtifactContract(kind="code_artifact", required=False)},
        )

    diagnostic = exc_info.value.diagnostics[0]
    assert diagnostic.field == "backend_code"
    assert diagnostic.code == "placeholder"


def test_contract_parser_returns_frozen_model_and_rejects_unknown_kind() -> None:
    parsed = parse_artifact_contracts(
        {
            "backend_code": {
                "kind": "code_artifact",
                "aliases": ["api_code"],
            }
        },
        location="steps.generate_api.output_contracts",
    )

    assert parsed["backend_code"].aliases == ("api_code",)
    with pytest.raises(FrozenInstanceError):
        parsed["backend_code"].required = False  # type: ignore[misc]
    with pytest.raises(ArtifactContractConfigError, match="kind"):
        parse_artifact_contracts(
            {"backend_code": {"kind": "unknown"}},
            location="steps.generate_api.output_contracts",
        )


def test_contract_parser_rejects_alias_collisions() -> None:
    with pytest.raises(ArtifactContractConfigError, match="collides"):
        parse_artifact_contracts(
            {
                "backend_code": {
                    "kind": "code_artifact",
                    "aliases": ["api_code"],
                },
                "api_code": {"kind": "code_artifact"},
            },
            location="steps.generate_api.output_contracts",
        )


@pytest.mark.parametrize(
    ("raw", "match"),
    [
        (["not", "a", "mapping"], "must be a mapping"),
        ({123: {"kind": "code_artifact"}}, "non-empty strings"),
        ({"   ": {"kind": "code_artifact"}}, "non-empty strings"),
        ({"backend_code": ["code_artifact"]}, "must be a mapping or contract kind"),
        (
            {"backend_code": {"kind": "code_artifact", "bogus": True}},
            "unknown fields",
        ),
        (
            {"backend_code": {"kind": "code_artifact", "required": "yes"}},
            "required must be a boolean",
        ),
        (
            {"backend_code": {"kind": "code_artifact", "aliases": "api_code"}},
            "aliases must be a list of strings",
        ),
        (
            {"backend_code": {"kind": "code_artifact", "aliases": [123]}},
            "aliases must be a list of strings",
        ),
        (
            {"backend_code": {"kind": "code_artifact", "aliases": [""]}},
            "aliases must be a list of strings",
        ),
        (
            {"backend_code": {"kind": "code_artifact", "aliases": ["backend_code"]}},
            "cannot alias itself",
        ),
    ],
)
def test_parse_artifact_contracts_rejects_invalid_config(
    raw: object,
    match: str,
) -> None:
    with pytest.raises(ArtifactContractConfigError, match=match):
        parse_artifact_contracts(
            raw,
            location="steps.generate_api.output_contracts",
        )


def test_expected_output_keys_includes_defensive_canonical_and_alias() -> None:
    keys = expected_output_keys(
        {},
        {"backend_code": _contract(aliases=("api_code",))},
    )

    assert keys == ["backend_code", "api_code"]


async def test_native_input_contract_fails_before_invocation() -> None:
    invoked = False

    async def should_not_run(_ctx: ExecutionContext) -> dict[str, object]:
        nonlocal invoked
        invoked = True
        return {}

    step = StepDefinition(
        name="review_code",
        func=should_not_run,
        input_mapping={"backend": "backend"},
        input_contracts={"backend": _contract()},
    )
    ctx = ExecutionContext()
    await ctx.set("backend", "No backend code was available for review.")

    result = await StepExecutor().execute(step, ctx)

    assert result.is_failed
    assert result.error_type == "ArtifactContractError"
    assert invoked is False
    assert result.metadata["contract_diagnostics"][0]["field"] == "backend"


async def test_native_input_contract_failure_runs_error_hook() -> None:
    hook_calls: list[str] = []

    async def error_hook(_ctx: ExecutionContext, step: StepDefinition) -> None:
        hook_calls.append(step.name)

    step = StepDefinition(
        name="review_code",
        func=lambda _ctx: None,  # type: ignore[arg-type]
        input_mapping={"backend": "backend"},
        input_contracts={"backend": _contract()},
        error_hooks=[error_hook],
    )

    result = await StepExecutor().execute(step, ExecutionContext())

    assert result.is_failed
    assert hook_calls == ["review_code"]


async def test_native_output_contract_rejects_placeholder_success() -> None:
    async def generate(_ctx: ExecutionContext) -> dict[str, object]:
        return {"backend_code": "not generated; see api spec"}

    step = StepDefinition(
        name="generate_api",
        func=generate,
        retry=RetryConfig(max_retries=0),
        output_mapping={"backend_code": "backend_code"},
        output_contracts={"backend_code": _contract()},
    )

    result = await StepExecutor().execute(step, ExecutionContext())

    assert result.is_failed
    assert result.error_type == "ArtifactContractError"
    assert result.metadata["contract_diagnostics"][0]["field"] == "backend_code"
    assert result.output_data == {}


async def test_native_alias_promoted_into_context_before_invocation() -> None:
    """A valid alias is promoted into the canonical key before the step runs.

    Both the canonical field and its alias are declared in ``input_mapping``
    (mirroring how a real step reads a legacy checkpoint key). When the
    canonical value is invalid but the alias holds a valid file map, the
    executor must promote the alias into the canonical context key *before*
    invoking the step function, so the function only ever observes the
    canonical key.
    """
    backend = {"Program.cs": "var app = builder.Build();"}
    received: dict[str, object] = {}

    async def review(child_ctx: ExecutionContext) -> dict[str, object]:
        received["backend"] = await child_ctx.get("backend")
        return {}

    step = StepDefinition(
        name="review_code",
        func=review,
        input_mapping={"backend": "backend", "legacy_backend": "legacy_backend"},
        input_contracts={"backend": _contract(aliases=("legacy_backend",))},
    )
    ctx = ExecutionContext()
    await ctx.set("backend", "No backend code was available for review.")
    await ctx.set("legacy_backend", backend)

    result = await StepExecutor().execute(step, ctx)

    assert result.is_success
    assert received["backend"] == backend
    assert result.input_data["backend"] == backend
    assert "legacy_backend" not in result.input_data


async def test_native_retry_clears_stale_contract_failure_state() -> None:
    calls = 0
    backend = {"Program.cs": "var app = builder.Build();"}

    async def generate(_ctx: ExecutionContext) -> dict[str, object]:
        nonlocal calls
        calls += 1
        if calls == 1:
            return {"api_code": "not generated"}
        return {"api_code": backend}

    step = StepDefinition(
        name="generate_api",
        func=generate,
        retry=RetryConfig(max_retries=1, base_delay_seconds=0, jitter=0),
        output_mapping={"backend_code": "backend_code"},
        output_contracts={"backend_code": _contract(aliases=("api_code",))},
    )

    result = await StepExecutor().execute(step, ExecutionContext())

    assert result.is_success
    assert result.output_data == {"backend_code": backend}
    assert result.error is None
    assert result.error_type is None
    assert "contract_diagnostics" not in result.metadata


async def test_native_loop_refresh_contract_failure_returns_failed_result() -> None:
    ctx = ExecutionContext()
    await ctx.set("backend", {"Program.cs": "var app = builder.Build();"})

    async def invalidate_for_refresh(_child: ExecutionContext) -> dict[str, object]:
        await ctx.set("backend", "not generated")
        return {"review_status": "NEEDS_FIXES"}

    step = StepDefinition(
        name="refine",
        func=invalidate_for_refresh,
        loop_until="${steps.refine.outputs.review_status} == 'APPROVED'",
        loop_max=2,
        input_mapping={"backend": "backend"},
        input_contracts={"backend": _contract()},
        output_mapping={"review_status": "review_status"},
    )

    result = await StepExecutor().execute(step, ctx)

    assert result.is_failed
    assert result.error_type == "ArtifactContractError"
    assert result.output_data == {}


def test_langchain_input_contract_matches_native_rejection() -> None:
    step = StepConfig(
        name="review_code",
        inputs={"backend": "${steps.generate_api.outputs.backend_code}"},
        input_contracts={"backend": _contract()},
    )
    state = initial_state()
    state["steps"]["generate_api"] = {
        "status": "success",
        "outputs": {"backend_code": "No backend code was available for review."},
    }

    with pytest.raises(ArtifactContractError) as exc_info:
        resolve_inputs_into_context(step, state)

    assert exc_info.value.diagnostics[0].field == "backend"
