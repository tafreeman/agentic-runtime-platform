"""Model-pack validation shared by the settings routes and run submission.

Intrinsic checks — empty pack or tier, unknown capability tags, unprefixed
models, provider-allowlist violations, unsatisfiable capability
requirements — depend only on the pack and settings, so run submission and
workflow binding gate on them exactly like global activation does.
Provider-availability warnings depend on the process environment and are
emitted only when the caller supplies the available-provider set; they are
advisory and never gate anything.
"""

from __future__ import annotations

from ..ui_settings import KNOWN_MODEL_CAPABILITIES, ModelPack, UiSettings
from .models_settings import ModelPackIssue


def _capability_issues(pack: ModelPack, settings: UiSettings) -> list[ModelPackIssue]:
    """Cross-check tier capability requirements against the tier's chain.

    Each chain model's effective capabilities follow the existing precedence:
    pack-level override, then the global settings override, then the registry
    default (``[model.capability]``). A model absent from all three sources
    satisfies nothing. A tier where no candidate satisfies every required tag
    is an error (activation blocks); candidates that satisfy only part of the
    requirements get a warning, since fallback routing may still pick them.
    """
    from ..models.model_registry import load_registry

    known_capabilities = set(KNOWN_MODEL_CAPABILITIES)
    registry_capabilities = {
        model.id: [model.capability] for model in load_registry().models
    }
    issues: list[ModelPackIssue] = []
    for tier, requirements in sorted(pack.capability_requirements.items()):
        chain = pack.tier_chains.get(tier, [])
        # Unknown tags already raise ``unknown_capability``; only known tags
        # participate here so one mistake does not double-report.
        required = set(requirements) & known_capabilities
        if not chain or not required:
            continue
        satisfying: list[str] = []
        for model in chain:
            capabilities = pack.model_capabilities.get(model)
            if capabilities is None:
                capabilities = settings.model_capabilities.get(model)
            if capabilities is None:
                capabilities = registry_capabilities.get(model, [])
            if required <= set(capabilities):
                satisfying.append(model)
        if not satisfying:
            issues.append(
                ModelPackIssue(
                    severity="error",
                    code="capability_unsatisfied",
                    tier=tier,
                    message=(
                        f"Tier {tier} requires capabilities {sorted(required)} "
                        "but no model in its chain provides all of them."
                    ),
                )
            )
        elif len(satisfying) < len(chain):
            for model in chain:
                if model not in satisfying:
                    issues.append(
                        ModelPackIssue(
                            severity="warning",
                            code="capability_partial",
                            tier=tier,
                            model=model,
                            message=(
                                f"Model {model!r} does not provide all of tier "
                                f"{tier}'s required capabilities; fallback "
                                "routing may still select it."
                            ),
                        )
                    )
    return issues


def validate_pack_issues(
    pack: ModelPack,
    settings: UiSettings,
    *,
    available_providers: set[str] | None = None,
) -> list[ModelPackIssue]:
    """Collect validation issues for one pack version.

    Args:
        pack: The pack version to validate.
        settings: Current settings; capability overrides participate in the
            capability cross-check.
        available_providers: When given, chain models on providers outside
            this set get an advisory ``provider_unavailable`` warning. Omit
            at gating call sites (run submit, workflow bind), which must not
            depend on the machine's provider environment.

    Returns:
        Issues in stable order; any error-severity issue means the pack must
        not route a run.
    """
    issues: list[ModelPackIssue] = []
    if not pack.tier_chains:
        issues.append(
            ModelPackIssue(
                severity="error",
                code="empty_pack",
                message="Add at least one tier chain before using this pack.",
            )
        )

    known_capabilities = set(KNOWN_MODEL_CAPABILITIES)
    for tier, requirements in pack.capability_requirements.items():
        unknown = sorted(set(requirements) - known_capabilities)
        if unknown:
            issues.append(
                ModelPackIssue(
                    severity="error",
                    code="unknown_capability",
                    tier=tier,
                    message=f"Tier {tier} has unknown capabilities: {unknown}.",
                )
            )

    for tier, chain in pack.tier_chains.items():
        if not chain:
            issues.append(
                ModelPackIssue(
                    severity="error",
                    code="empty_tier",
                    tier=tier,
                    message=f"Tier {tier} has no routing candidates.",
                )
            )
        for model in chain:
            provider = model.split(":", 1)[0] if ":" in model else ""
            if not provider:
                issues.append(
                    ModelPackIssue(
                        severity="error",
                        code="unprefixed_model",
                        tier=tier,
                        model=model,
                        message="Model IDs in packs must include a provider prefix.",
                    )
                )
                continue
            if pack.allowed_providers and provider not in pack.allowed_providers:
                issues.append(
                    ModelPackIssue(
                        severity="error",
                        code="provider_not_allowed",
                        tier=tier,
                        model=model,
                        message=f"Provider {provider!r} is outside this pack's allowed set.",
                    )
                )
            if available_providers is not None and provider not in available_providers:
                issues.append(
                    ModelPackIssue(
                        severity="warning",
                        code="provider_unavailable",
                        tier=tier,
                        model=model,
                        message=f"Provider {provider!r} is not currently available.",
                    )
                )

    issues.extend(_capability_issues(pack, settings))
    return issues


def pack_error_issues(pack: ModelPack, settings: UiSettings) -> list[ModelPackIssue]:
    """Return only the error-severity issues; an empty list means safe to route."""
    return [
        issue
        for issue in validate_pack_issues(pack, settings)
        if issue.severity == "error"
    ]
