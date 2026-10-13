"""Project metadata: workflows, CI jobs, ADRs, docs staleness, deps, git work state."""

from __future__ import annotations

import json
import re
import subprocess
import tomllib
from pathlib import Path

import yaml

from _common import (
    HOME_REPO,
    REPO,
    STALE_DAYS,
    age_days,
    git,
    last_commit_dates,
    read_text,
    tracked_files,
    write_json,
)

GH_REPO = "tafreeman/agentic-runtime-platform"
WF_DIR = "agentic-workflows-v2/agentic_v2/workflows/definitions"
ADR_STATUS_RE = re.compile(
    r"^\*{0,2}Status\*{0,2}\s*[:|]\s*\**\s*([A-Za-z -]+)", re.I | re.M
)
LINK_RE = re.compile(r"\]\(([^)#\s]+)")


def _workflows(files: list[str]) -> list[dict[str, object]]:
    out = []
    for p in files:
        if not (p.startswith(WF_DIR) and p.endswith((".yaml", ".yml"))):
            continue
        try:
            doc = yaml.safe_load(read_text(REPO / p)) or {}
        except yaml.YAMLError as exc:
            out.append({"path": p, "error": str(exc)[:200]})
            continue
        steps = doc.get("steps") or []
        out.append(
            {
                "path": p,
                "name": doc.get("name"),
                "description": str(doc.get("description", ""))[:240],
                "inputs": (
                    list((doc.get("inputs") or {}).keys())
                    if isinstance(doc.get("inputs"), dict)
                    else doc.get("inputs")
                ),
                "outputs": (
                    list((doc.get("outputs") or {}).keys())
                    if isinstance(doc.get("outputs"), dict)
                    else doc.get("outputs")
                ),
                "steps": [
                    {
                        "name": s.get("name"),
                        "agent": s.get("agent"),
                        "tier": s.get("tier"),
                        "depends_on": s.get("depends_on"),
                        "has_when": "when" in s,
                        "has_loop": any(
                            k in s for k in ("loop_until", "loop", "max_iterations")
                        ),
                    }
                    for s in steps
                    if isinstance(s, dict)
                ],
            }
        )
    return out


def _ci(files: list[str]) -> list[dict[str, object]]:
    out = []
    for p in files:
        if not (p.startswith(".github/workflows/") and p.endswith((".yml", ".yaml"))):
            continue
        doc = yaml.safe_load(read_text(REPO / p)) or {}
        triggers = doc.get(True) or doc.get("on")  # PyYAML parses bare `on` as True
        jobs = doc.get("jobs") or {}
        out.append(
            {
                "file": p,
                "name": doc.get("name"),
                "triggers": (
                    list(triggers.keys()) if isinstance(triggers, dict) else triggers
                ),
                "jobs": [
                    {
                        "id": j,
                        "name": (v or {}).get("name"),
                        "needs": (v or {}).get("needs"),
                    }
                    for j, v in jobs.items()
                ],
            }
        )
    return out


def _adrs(files: list[str], dates: dict[str, str]) -> list[dict[str, object]]:
    out = []
    for p in sorted(files):
        if not (p.startswith("docs/adr/ADR-") and p.endswith(".md")):
            continue
        text = read_text(REPO / p)
        title = next(
            (
                line.lstrip("# ").strip()
                for line in text.splitlines()
                if line.startswith("#")
            ),
            "",
        )
        m = ADR_STATUS_RE.search(text)
        out.append(
            {
                "file": p,
                "title": title[:140],
                "status": (m.group(1).strip() if m else "?"),
                "last_commit": dates.get(p, "")[:10],
            }
        )
    return out


def _docs(files: list[str], dates: dict[str, str]) -> list[dict[str, object]]:
    known = set(files)
    out = []
    for p in files:
        if not p.endswith(".md") or p.startswith(
            ("docs/adr/", "agentic-workflows-v2/evals/")
        ):
            continue
        text = read_text(REPO / p)
        broken = []
        for link in LINK_RE.findall(text):
            if link.startswith(("http", "mailto:")):
                continue
            target = (Path(p).parent / link).as_posix()
            norm = str(Path(target)).replace("\\", "/")
            if norm not in known and not (REPO / norm).exists():
                broken.append(link)
        age = age_days(dates.get(p, ""))
        out.append(
            {
                "file": p,
                "lines": text.count("\n"),
                "last_commit": dates.get(p, "")[:10],
                "age_days": age,
                "stale": age is not None and age > STALE_DAYS,
                "title": next(
                    (
                        line.lstrip("# ").strip()
                        for line in text.splitlines()
                        if line.startswith("#")
                    ),
                    "",
                )[:120],
                "broken_relative_links": broken[:10],
            }
        )
    return sorted(out, key=lambda r: r["file"])


def _deps(files: list[str]) -> dict[str, object]:
    out: dict[str, object] = {}
    for p in files:
        if p.endswith("pyproject.toml"):
            data = tomllib.loads(read_text(REPO / p))
            proj = data.get("project", {})
            out[p] = {
                "name": proj.get("name"),
                "version": proj.get("version"),
                "requires_python": proj.get("requires-python"),
                "dependencies": proj.get("dependencies", []),
                "optional": proj.get("optional-dependencies", {}),
                "scripts": proj.get("scripts", {}),
            }
        elif p.endswith("package.json") and "node_modules" not in p:
            data = json.loads(read_text(REPO / p) or "{}")
            out[p] = {
                k: data.get(k)
                for k in ("name", "dependencies", "devDependencies", "scripts")
            }
    return out


def _gh(*args: str) -> object:
    proc = subprocess.run(
        ["gh", *args, "-R", GH_REPO],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    try:
        return (
            json.loads(proc.stdout)
            if proc.returncode == 0
            else {"error": proc.stderr[:300]}
        )
    except json.JSONDecodeError:
        return {"error": "bad json"}


def _git_state() -> dict[str, object]:
    """Branch/worktree/PR state, read from the live checkout (shared .git)."""

    def g(*a: str) -> str:
        return git(*a, cwd=HOME_REPO)

    branches = []
    fmt = "%(refname:short)|%(committerdate:short)|%(upstream:track)|%(subject)"
    for line in g(
        "for-each-ref", f"--format={fmt}", "refs/heads", "refs/remotes/origin"
    ).splitlines():
        name, date, track, subject = [*line.split("|", 3), "", "", ""][:4]
        if name in {"origin", "origin/HEAD"}:
            continue
        ahead = g("rev-list", "--count", f"origin/main..{name}")
        files = g("diff", "--name-only", f"origin/main...{name}").split()
        residual = (
            g("diff", "--shortstat", "origin/main", name, "--", *files)
            if files and ahead != "0"
            else ""
        )
        branches.append(
            {
                "branch": name,
                "last_commit": date,
                "track": track,
                "subject": subject[:100],
                "ahead_of_main": int(ahead or 0),
                "residual_diff_vs_main": residual,
                "age_days": age_days(date + "T00:00:00+00:00") if date else None,
            }
        )
    return {
        "head": g("rev-parse", "--short", "origin/main"),
        "branches": branches,
        "worktrees": g("worktree", "list").splitlines(),
        "stash_count": len(g("stash", "list").splitlines()),
        "open_prs": _gh(
            "pr",
            "list",
            "--state",
            "open",
            "--limit",
            "50",
            "--json",
            "number,title,headRefName,createdAt,isDraft,mergeStateStatus",
        ),
        "recent_merged_prs": _gh(
            "pr",
            "list",
            "--state",
            "merged",
            "--limit",
            "40",
            "--json",
            "number,title,mergedAt",
        ),
        "open_issues": _gh(
            "issue",
            "list",
            "--state",
            "open",
            "--limit",
            "100",
            "--json",
            "number,title,labels,createdAt",
        ),
    }


def _env_example() -> list[str]:
    return sorted(
        set(
            re.findall(
                r"^#?\s*([A-Z][A-Z0-9_]{2,})=", read_text(REPO / ".env.example"), re.M
            )
        )
    )


def main() -> None:
    files = tracked_files()
    dates = last_commit_dates()
    write_json(
        "meta_inventory",
        {
            "revision": git("log", "-1", "--format=%h %cI %s"),
            "workflows": _workflows(files),
            "ci": _ci(files),
            "adrs": _adrs(files, dates),
            "docs": _docs(files, dates),
            "deps": _deps(files),
            "env_example_keys": _env_example(),
            "git": _git_state(),
        },
    )


if __name__ == "__main__":
    main()
