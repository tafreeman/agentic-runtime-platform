"""Schema lint over memory topic files (``memoryctl validate``).

Checks every topic file discovered in each configured memory directory
against the frontmatter schema in the design doc (AGENT_CONTEXT_SYSTEM.md
section 4.1). Read-only: this command never mutates any file, so malformed
files are reported deterministically before they ever reach a model.
"""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path

from agentic_v2.memoryctl._shared import (
    DATE_FORMAT,
    REQUIRED_META_KEYS,
    SEVERITY_ERROR,
    SEVERITY_WARN,
    STATUS_ACTIVE,
    STATUS_SUPERSEDED_PREFIX,
    VALID_SUBTYPES,
    VALID_TYPES,
    CommandResult,
    Finding,
    MemoryctlConfig,
    discover_memory_files,
    load_memory_doc,
)

COMMAND_NAME = "validate"
DESCRIPTION_MAX_CHARS = 200
TYPE_SEMANTIC = "semantic"
VERIFY_KEY = "verify"
DATE_KEYS = ("created", "updated")


def _is_valid_date(value: object) -> bool:
    """True when ``value`` is a date/datetime or a valid YYYY-MM-DD string.

    ``yaml.safe_load`` turns bare dates into :class:`datetime.date`
    instances (and timestamps into :class:`datetime.datetime`, a
    ``date`` subclass), so both are accepted alongside valid strings.
    """
    if isinstance(value, date):
        return True
    if isinstance(value, str):
        try:
            datetime.strptime(value, DATE_FORMAT)
        except ValueError:
            return False
        return True
    return False


def _required_key_errors(path: Path, meta: dict[str, object]) -> list[Finding]:
    """Errors for required frontmatter keys that are absent or null."""
    missing = [key for key in REQUIRED_META_KEYS if meta.get(key) is None]
    if not missing:
        return []
    return [
        Finding(
            code="schema.missing-keys",
            severity=SEVERITY_ERROR,
            message=f"missing required frontmatter keys: {', '.join(missing)}",
            path=path,
            data={"missing": missing},
        )
    ]


def _type_errors(path: Path, meta: dict[str, object]) -> list[Finding]:
    """Errors for an invalid ``type`` or a bad semantic ``subtype``."""
    findings: list[Finding] = []
    doc_type = meta.get("type")
    if doc_type is not None and doc_type not in VALID_TYPES:
        findings.append(
            Finding(
                code="schema.invalid-type",
                severity=SEVERITY_ERROR,
                message=f"type {doc_type!r} not one of {VALID_TYPES}",
                path=path,
                data={"type": str(doc_type)},
            )
        )
    if doc_type == TYPE_SEMANTIC and meta.get("subtype") not in VALID_SUBTYPES:
        subtype = meta.get("subtype")
        findings.append(
            Finding(
                code="schema.invalid-subtype",
                severity=SEVERITY_ERROR,
                message=(
                    f"semantic file needs subtype in {VALID_SUBTYPES}, got {subtype!r}"
                ),
                path=path,
                data={"subtype": str(subtype)},
            )
        )
    return findings


def _date_errors(path: Path, meta: dict[str, object]) -> list[Finding]:
    """Errors for ``created``/``updated`` values that are not dates."""
    findings: list[Finding] = []
    for key in DATE_KEYS:
        value = meta.get(key)
        if value is not None and not _is_valid_date(value):
            findings.append(
                Finding(
                    code="schema.invalid-date",
                    severity=SEVERITY_ERROR,
                    message=f"{key} is not a YYYY-MM-DD date: {value!r}",
                    path=path,
                    data={"key": key, "value": str(value)},
                )
            )
    return findings


def _status_errors(path: Path, meta: dict[str, object]) -> list[Finding]:
    """Errors for a ``status`` outside active/superseded-by semantics."""
    status = meta.get("status")
    if status is None or status == STATUS_ACTIVE:
        return []
    if isinstance(status, str) and status.startswith(STATUS_SUPERSEDED_PREFIX):
        return []
    return [
        Finding(
            code="schema.invalid-status",
            severity=SEVERITY_ERROR,
            message=(
                f"status must be {STATUS_ACTIVE!r} or start with "
                f"{STATUS_SUPERSEDED_PREFIX!r}, got {status!r}"
            ),
            path=path,
            data={"status": str(status)},
        )
    ]


def _warn_findings(path: Path, meta: dict[str, object]) -> list[Finding]:
    """Non-fatal quality warnings: naming, description, verify hygiene."""
    findings: list[Finding] = []
    name = meta.get("name")
    if name is not None and str(name) != path.stem:
        findings.append(
            Finding(
                code="schema.name-mismatch",
                severity=SEVERITY_WARN,
                message=f"name {name!r} != filename stem {path.stem!r}",
                path=path,
                data={"name": str(name), "stem": path.stem},
            )
        )
    description = meta.get("description")
    if description is not None:
        text = str(description).strip()
        if not text or len(text) > DESCRIPTION_MAX_CHARS:
            findings.append(
                Finding(
                    code="schema.description-length",
                    severity=SEVERITY_WARN,
                    message=(
                        f"description empty or over {DESCRIPTION_MAX_CHARS} chars "
                        f"({len(text)})"
                    ),
                    path=path,
                    data={"length": len(text)},
                )
            )
    if meta.get("type") == TYPE_SEMANTIC and VERIFY_KEY not in meta:
        findings.append(
            Finding(
                code="schema.no-verify",
                severity=SEVERITY_WARN,
                message="semantic fact has no verify command (use 'manual')",
                path=path,
            )
        )
    return findings


def _file_findings(path: Path) -> list[Finding]:
    """All schema findings for one topic file."""
    doc = load_memory_doc(path)
    if not doc.meta:
        return [
            Finding(
                code="schema.missing-frontmatter",
                severity=SEVERITY_ERROR,
                message="missing or empty YAML frontmatter",
                path=path,
            )
        ]
    findings: list[Finding] = []
    findings.extend(_required_key_errors(path, doc.meta))
    findings.extend(_type_errors(path, doc.meta))
    findings.extend(_date_errors(path, doc.meta))
    findings.extend(_status_errors(path, doc.meta))
    findings.extend(_warn_findings(path, doc.meta))
    return findings


def run(cfg: MemoryctlConfig, *, dry_run: bool = False) -> CommandResult:
    """Lint frontmatter of every topic file in ``cfg.memory_dirs``.

    Read-only; ``dry_run`` is accepted for contract uniformity but has
    no effect because validation never mutates anything.
    """
    del dry_run  # never mutates, so dry-run and real runs are identical
    findings: list[Finding] = []
    file_count = 0
    for memory_dir in cfg.memory_dirs:
        for path in discover_memory_files(memory_dir, cfg.index_name):
            file_count += 1
            findings.extend(_file_findings(path))
    error_count = sum(1 for f in findings if f.severity == SEVERITY_ERROR)
    warn_count = sum(1 for f in findings if f.severity == SEVERITY_WARN)
    return CommandResult(
        name=COMMAND_NAME,
        findings=tuple(findings),
        changed=(),
        summary=f"{file_count} files, {error_count} errors, {warn_count} warnings",
    )
