"""``memoryctl links`` — reference resolution checks (read-only, TIER_0).

Scans topic files plus the index in each memory dir, and playbook files
under ``cfg.fleet_dir/playbooks`` when a fleet dir is configured (design
doc §6, ``links`` row; audit class C-2 "referencing files that don't
exist"):

- ``[[wiki-links]]`` in bodies must match a topic-file stem in the same
  directory, else warn ``links.wiki-unresolved``.
- Relative markdown link targets must resolve relative to the containing
  file, else error ``links.dead`` (``http``/``https``/``mailto`` and
  anchor-only targets are skipped).
- Playbook frontmatter ``entry:`` paths must exist relative to
  ``cfg.fleet_dir``, else error ``links.entry-missing``.
- ``http(s)`` URLs are counted (info ``links.external-count``) but never
  fetched.
"""

from __future__ import annotations

import re
from pathlib import Path

from agentic_v2.memoryctl._shared import (
    SEVERITY_ERROR,
    SEVERITY_INFO,
    SEVERITY_WARN,
    CommandResult,
    Finding,
    MemoryctlConfig,
    discover_memory_files,
    load_memory_doc,
)

COMMAND_NAME = "links"

CODE_WIKI_UNRESOLVED = "links.wiki-unresolved"
CODE_DEAD = "links.dead"
CODE_ENTRY_MISSING = "links.entry-missing"
CODE_EXTERNAL_COUNT = "links.external-count"

PLAYBOOKS_DIR_NAME = "playbooks"
ENTRY_META_KEY = "entry"

EXTERNAL_PREFIXES = ("http://", "https://", "mailto:")

WIKI_LINK_RE = re.compile(r"\[\[([^\[\]]+)\]\]")
MD_LINK_RE = re.compile(r"\[[^\]]*\]\(([^()]+)\)")
MD_TITLE_RE = re.compile(r'\s+"[^"]*"\s*$')
EXTERNAL_URL_RE = re.compile(r"https?://[^\s)\"'<>]+")


def run(cfg: MemoryctlConfig, *, dry_run: bool = False) -> CommandResult:
    """Check wiki-links, markdown links, and playbook entry paths.

    Read-only: ``dry_run`` is accepted for contract uniformity but has no
    effect because this command never mutates files.
    """
    del dry_run  # read-only command; accepted for the shared contract only
    findings: list[Finding] = []
    files_checked = 0
    external_total = 0
    for root in cfg.memory_dirs:
        dir_findings, dir_external, dir_count = _scan_memory_dir(root, cfg.index_name)
        findings.extend(dir_findings)
        external_total += dir_external
        files_checked += dir_count
    if cfg.fleet_dir is not None:
        pb_findings, pb_external, pb_count = _scan_playbooks(cfg.fleet_dir)
        findings.extend(pb_findings)
        external_total += pb_external
        files_checked += pb_count
    findings.append(
        Finding(
            code=CODE_EXTERNAL_COUNT,
            severity=SEVERITY_INFO,
            message=f"{external_total} external http(s) URL(s) counted, none fetched",
            data={"count": external_total},
        )
    )
    issues = sum(1 for f in findings if f.severity != SEVERITY_INFO)
    summary = (
        f"links: checked {files_checked} file(s); {issues} link issue(s); "
        f"{external_total} external URL(s)"
    )
    return CommandResult(
        name=COMMAND_NAME, findings=tuple(findings), changed=(), summary=summary
    )


def _scan_memory_dir(root: Path, index_name: str) -> tuple[list[Finding], int, int]:
    """Scan one memory dir's topic files plus its index, if present."""
    topic_files = discover_memory_files(root, index_name)
    stems = {p.stem for p in topic_files}
    targets = list(topic_files)
    index_path = root / index_name
    if index_path.is_file():
        targets.append(index_path)
    findings: list[Finding] = []
    external = 0
    for path in targets:
        file_findings, file_external = _scan_file(path, stems)
        findings.extend(file_findings)
        external += file_external
    return findings, external, len(targets)


def _scan_playbooks(fleet_dir: Path) -> tuple[list[Finding], int, int]:
    """Scan playbook files under ``fleet_dir/playbooks``."""
    playbook_dir = fleet_dir / PLAYBOOKS_DIR_NAME
    if not playbook_dir.is_dir():
        return [], 0, 0
    paths = sorted(playbook_dir.glob("*.md"))
    stems = {p.stem for p in paths}
    findings: list[Finding] = []
    external = 0
    for path in paths:
        doc = load_memory_doc(path)
        findings.extend(_wiki_findings(path, doc.body, stems))
        findings.extend(_dead_link_findings(path, doc.body))
        findings.extend(_entry_findings(path, doc.meta, fleet_dir))
        external += len(EXTERNAL_URL_RE.findall(doc.raw))
    return findings, external, len(paths)


def _scan_file(path: Path, stems: set[str]) -> tuple[list[Finding], int]:
    """Wiki/markdown link findings for one file plus its external-URL count."""
    doc = load_memory_doc(path)
    findings = [
        *_wiki_findings(path, doc.body, stems),
        *_dead_link_findings(path, doc.body),
    ]
    return findings, len(EXTERNAL_URL_RE.findall(doc.raw))


def _wiki_findings(path: Path, body: str, stems: set[str]) -> list[Finding]:
    """One ``links.wiki-unresolved`` warning per unresolved ``[[target]]``."""
    out: list[Finding] = []
    for match in WIKI_LINK_RE.finditer(body):
        target = match.group(1).split("|", 1)[0].strip()
        if target in stems:
            continue
        out.append(
            Finding(
                code=CODE_WIKI_UNRESOLVED,
                severity=SEVERITY_WARN,
                message=f"wiki-link [[{target}]] matches no topic-file stem",
                path=path,
                data={"target": target},
            )
        )
    return out


def _dead_link_findings(path: Path, body: str) -> list[Finding]:
    """One ``links.dead`` error per markdown link that fails to resolve.

    Relative targets resolve against the containing file's directory.
    Absolute targets are checked as-is: memory files are agent/user-
    authored local pointers in the same trust domain as ``verify:``
    commands (design doc §4.1), and pointer resolution — does the
    referenced machine path still exist? — is exactly the guarantee this
    command provides (restorable compression, P2). Targets are never
    re-rooted against a repository root: memory directories are not
    repositories, so a rooted target like ``/docs/x.md`` simply fails to
    resolve and is flagged for cleanup.
    """
    out: list[Finding] = []
    for match in MD_LINK_RE.finditer(body):
        target = _normalize_md_target(match.group(1))
        if target is None:
            continue
        target_path = Path(target)
        resolved = target_path if target_path.is_absolute() else path.parent / target
        if not resolved.exists():
            out.append(
                Finding(
                    code=CODE_DEAD,
                    severity=SEVERITY_ERROR,
                    message=f"markdown link target does not resolve: {target}",
                    path=path,
                    data={"target": target},
                )
            )
    return out


def _normalize_md_target(raw: str) -> str | None:
    """Cleaned relative link target, or None when the link is skippable.

    Strips optional link titles, surrounding angle brackets, and
    ``#fragment`` suffixes; returns None for external (``http``/``https``/
    ``mailto``) and anchor-only targets.
    """
    target = MD_TITLE_RE.sub("", raw.strip()).strip("<>").strip()
    if target.lower().startswith(EXTERNAL_PREFIXES):
        return None
    target = target.split("#", 1)[0]
    if not target:
        return None
    return target


def _entry_findings(
    path: Path, meta: dict[str, object], fleet_dir: Path
) -> list[Finding]:
    """``links.entry-missing`` error when a playbook entry path does not exist."""
    entry = meta.get(ENTRY_META_KEY)
    if entry is None:
        return []
    entry_text = str(entry)
    if (fleet_dir / entry_text).exists():
        return []
    return [
        Finding(
            code=CODE_ENTRY_MISSING,
            severity=SEVERITY_ERROR,
            message=f"playbook entry not found under fleet dir: {entry_text}",
            path=path,
            data={"entry": entry_text},
        )
    ]
