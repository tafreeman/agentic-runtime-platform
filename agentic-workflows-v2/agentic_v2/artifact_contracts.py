"""Typed content contracts for artifacts passed between workflow steps.

Artifact contracts are opt-in.  Workflows without ``input_contracts`` or
``output_contracts`` retain their existing key-only behavior.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any

CODE_ARTIFACT = "code_artifact"
_SUPPORTED_KINDS = frozenset({CODE_ARTIFACT})
_PLACEHOLDER_KEYS = frozenset(
    {"description", "error", "message", "note", "placeholder", "status"}
)
_PLACEHOLDER_TEXT_RE = re.compile(
    r"\b(?:"
    r"not (?:available|generated|included|provided)|"
    r"no (?:backend |source )?code|"
    r"placeholder|"
    r"see [\w.-]+ for (?:implementation|details)|"
    r"refer to [\w.-]+|"
    r"cannot (?:generate|provide)|"
    r"unable to (?:generate|provide)"
    r")\b",
    flags=re.IGNORECASE,
)
_FILE_BLOCK_RE = re.compile(
    r"^FILE:[ \t]*(?P<path>[^\r\n]+)\r?\n" r"(?P<content>.*?)^ENDFILE[ \t]*(?:\r?\n|$)",
    re.DOTALL | re.MULTILINE,
)
_MAX_ARTIFACT_LENGTH = 262144
_WINDOWS_DEVICE_RE = re.compile(
    r"^(?:con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?$", re.I
)


@dataclass(frozen=True, slots=True)
class ArtifactContract:
    """Immutable declaration for one canonical artifact value."""

    kind: str
    required: bool = True
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ContractDiagnostic:
    """Machine-readable reason an artifact failed its declared contract."""

    field: str
    kind: str
    code: str
    message: str

    def as_dict(self) -> dict[str, str]:
        """Return a JSON-serializable diagnostic."""
        return {
            "field": self.field,
            "kind": self.kind,
            "code": self.code,
            "message": self.message,
        }


class ArtifactContractError(ValueError):
    """Raised when required step inputs or outputs violate their contracts."""

    def __init__(self, diagnostics: list[ContractDiagnostic]) -> None:
        self.diagnostics = tuple(diagnostics)
        summary = "; ".join(
            f"{item.field}: {item.message}" for item in self.diagnostics
        )
        super().__init__(f"Artifact contract validation failed: {summary}")


class ArtifactContractConfigError(ValueError):
    """Raised when a workflow declares an invalid artifact contract."""


def parse_artifact_contracts(
    raw: Any,
    *,
    location: str,
) -> dict[str, ArtifactContract]:
    """Parse an optional YAML contract mapping.

    The supported shape is::

        backend_code:
          kind: code_artifact
          required: true
          aliases: [api_code]
    """
    if raw is None:
        return {}
    if not isinstance(raw, Mapping):
        raise ArtifactContractConfigError(f"{location} must be a mapping")

    contracts: dict[str, ArtifactContract] = {}
    owners: dict[str, str] = {}
    for field_name, declaration in raw.items():
        if not isinstance(field_name, str) or not field_name.strip():
            raise ArtifactContractConfigError(
                f"{location} field names must be non-empty strings"
            )
        if isinstance(declaration, str):
            declaration = {"kind": declaration}
        if not isinstance(declaration, Mapping):
            raise ArtifactContractConfigError(
                f"{location}.{field_name} must be a mapping or contract kind"
            )

        unknown = set(declaration) - {"kind", "required", "aliases"}
        if unknown:
            raise ArtifactContractConfigError(
                f"{location}.{field_name} has unknown fields: {sorted(unknown)}"
            )
        kind = declaration.get("kind")
        if kind not in _SUPPORTED_KINDS:
            raise ArtifactContractConfigError(
                f"{location}.{field_name}.kind must be one of "
                f"{sorted(_SUPPORTED_KINDS)}"
            )
        required = declaration.get("required", True)
        if not isinstance(required, bool):
            raise ArtifactContractConfigError(
                f"{location}.{field_name}.required must be a boolean"
            )
        raw_aliases = declaration.get("aliases", [])
        if not isinstance(raw_aliases, list) or not all(
            isinstance(alias, str) and alias.strip() for alias in raw_aliases
        ):
            raise ArtifactContractConfigError(
                f"{location}.{field_name}.aliases must be a list of strings"
            )
        aliases = tuple(dict.fromkeys(raw_aliases))
        if field_name in aliases:
            raise ArtifactContractConfigError(
                f"{location}.{field_name} cannot alias itself"
            )
        for contract_name in (field_name, *aliases):
            owner = owners.get(contract_name)
            if owner is not None:
                raise ArtifactContractConfigError(
                    f"{location}.{field_name} name {contract_name!r} collides "
                    f"with contract {owner!r}"
                )
            owners[contract_name] = field_name
        contracts[field_name] = ArtifactContract(
            kind=kind,
            required=required,
            aliases=aliases,
        )
    return contracts


def validate_contract_bindings(
    contracts: Mapping[str, ArtifactContract],
    declared_keys: Mapping[str, Any],
    *,
    location: str,
) -> None:
    """Reject canonical contracts that do not bind to a declared step field."""
    unbound = sorted(set(contracts) - set(declared_keys))
    if unbound:
        raise ArtifactContractConfigError(
            f"{location} keys must exist in the corresponding mapping: {unbound}"
        )


def _diagnostic(
    field_name: str,
    code: str,
    message: str,
) -> ContractDiagnostic:
    return ContractDiagnostic(
        field=field_name,
        kind=CODE_ARTIFACT,
        code=code,
        message=message,
    )


def _safe_relative_path(path_value: str) -> bool:
    """Return whether a model-supplied artifact path stays relative."""
    if not path_value or path_value != path_value.strip():
        return False
    if any(ord(char) < 32 or ord(char) == 127 for char in path_value):
        return False
    normalized = path_value.replace("\\", "/")
    if normalized.startswith("/") or ":" in normalized:
        return False
    raw_parts = normalized.split("/")
    if any(
        part in {"", ".", ".."}
        or part.endswith((".", " "))
        or _WINDOWS_DEVICE_RE.fullmatch(part) is not None
        for part in raw_parts
    ):
        return False
    return not PurePosixPath(normalized).is_absolute()


def _mapping_diagnostics(
    field_name: str,
    value: Mapping[Any, Any],
) -> list[ContractDiagnostic]:
    if not value:
        return [_diagnostic(field_name, "empty", "must contain at least one file")]

    diagnostics: list[ContractDiagnostic] = []
    total_size = 0
    for path_value, source in value.items():
        if not isinstance(path_value, str) or not _safe_relative_path(path_value):
            diagnostics.append(
                _diagnostic(
                    field_name,
                    "unsafe_path",
                    f"contains unsafe or non-relative file path {path_value!r}",
                )
            )
            continue
        if path_value.casefold() in _PLACEHOLDER_KEYS:
            diagnostics.append(
                _diagnostic(
                    field_name,
                    "placeholder_object",
                    f"contains metadata key {path_value!r} instead of a file path",
                )
            )
        if not isinstance(source, str) or not source.strip():
            diagnostics.append(
                _diagnostic(
                    field_name,
                    "empty_source",
                    f"file {path_value!r} must contain non-blank source text",
                )
            )
        elif _PLACEHOLDER_TEXT_RE.search(source):
            diagnostics.append(
                _diagnostic(
                    field_name,
                    "placeholder",
                    f"file {path_value!r} contains placeholder or refusal prose",
                )
            )
        if isinstance(path_value, str):
            total_size += len(path_value)
        if isinstance(source, str):
            total_size += len(source)
    if total_size > _MAX_ARTIFACT_LENGTH:
        diagnostics.append(
            _diagnostic(
                field_name,
                "too_large",
                f"total file-map content exceeds {_MAX_ARTIFACT_LENGTH} characters",
            )
        )
    return diagnostics


def _parse_complete_file_payload(text: str) -> dict[str, str] | None:
    """Parse FILE blocks only when they consume the complete payload."""
    matches = list(_FILE_BLOCK_RE.finditer(text))
    if not matches:
        return None
    cursor = 0
    files: dict[str, str] = {}
    for match in matches:
        if text[cursor : match.start()].strip():
            return None
        files[match.group("path").strip()] = match.group("content")
        cursor = match.end()
    if text[cursor:].strip():
        return None
    return files


def validate_code_artifact(
    field_name: str,
    value: Any,
) -> list[ContractDiagnostic]:
    """Validate a relative-path file map or complete FILE/ENDFILE payload."""
    if value is None:
        return [_diagnostic(field_name, "missing", "is required but missing")]

    if isinstance(value, Mapping):
        return _mapping_diagnostics(field_name, value)

    if isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return [_diagnostic(field_name, "empty", "must not be blank")]
        if len(stripped) > _MAX_ARTIFACT_LENGTH:
            return [
                _diagnostic(
                    field_name,
                    "too_large",
                    f"exceeds {_MAX_ARTIFACT_LENGTH} characters",
                )
            ]
        files = _parse_complete_file_payload(stripped)
        if files:
            return _mapping_diagnostics(field_name, files)
        if _PLACEHOLDER_TEXT_RE.search(stripped):
            return [
                _diagnostic(
                    field_name,
                    "placeholder",
                    "contains placeholder, refusal, or reference-only prose",
                )
            ]
        return [
            _diagnostic(
                field_name,
                "invalid_format",
                "must be a file map or complete FILE/ENDFILE payload",
            )
        ]

    return [
        _diagnostic(
            field_name,
            "invalid_type",
            f"must be a file map or FILE/ENDFILE string, got {type(value).__name__}",
        )
    ]


def _validate_value(
    field_name: str,
    value: Any,
    contract: ArtifactContract,
) -> list[ContractDiagnostic]:
    if contract.kind == CODE_ARTIFACT:
        return validate_code_artifact(field_name, value)
    raise AssertionError(f"Unsupported artifact contract kind: {contract.kind}")


def validate_and_normalize_artifacts(
    values: Mapping[str, Any],
    contracts: Mapping[str, ArtifactContract],
) -> dict[str, Any]:
    """Validate artifact values and promote independently valid aliases.

    A valid canonical value always wins.  An alias is considered only when
    the canonical value is missing or invalid, and is never promoted unless
    it independently satisfies the canonical field's contract.
    """
    normalized = dict(values)
    all_diagnostics: list[ContractDiagnostic] = []

    for field_name, contract in contracts.items():
        present_candidates = [
            candidate
            for candidate in (field_name, *contract.aliases)
            if candidate in values
        ]
        candidate_diagnostics: list[ContractDiagnostic] = []
        selected: str | None = None
        for candidate in present_candidates:
            diagnostics = _validate_value(candidate, values[candidate], contract)
            if not diagnostics:
                selected = candidate
                break
            candidate_diagnostics.extend(diagnostics)

        if selected is not None:
            normalized[field_name] = values[selected]
            continue
        if contract.required or present_candidates:
            if candidate_diagnostics:
                all_diagnostics.extend(candidate_diagnostics)
            else:
                all_diagnostics.append(
                    _diagnostic(field_name, "missing", "is required but missing")
                )

    if all_diagnostics:
        raise ArtifactContractError(all_diagnostics)
    for contract in contracts.values():
        for alias in contract.aliases:
            normalized.pop(alias, None)
    return normalized


def expected_output_keys(
    output_keys: Mapping[str, Any],
    contracts: Mapping[str, ArtifactContract],
) -> list[str]:
    """Return canonical prompt outputs plus parse-only migration aliases."""
    keys = list(output_keys)
    for canonical, contract in contracts.items():
        if canonical not in keys:
            keys.append(canonical)
        for alias in contract.aliases:
            if alias not in keys:
                keys.append(alias)
    return keys
