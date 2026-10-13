"""React UI inventory: files, exports, import graph, routes, unused files, deps."""

from __future__ import annotations

import json
import re
from collections import defaultdict
from pathlib import PurePosixPath

from _common import (
    REPO,
    age_days,
    last_commit_dates,
    read_text,
    tracked_files,
    write_json,
)

UI = "agentic-workflows-v2/ui"
SRC = f"{UI}/src"
IMPORT_RE = re.compile(
    r"""(?:import|export)\s[^'"]*?from\s+['"]([^'"]+)['"]|import\(\s*['"]([^'"]+)['"]\s*\)"""
)
EXPORT_RE = re.compile(
    r"export\s+(?:default\s+)?(?:async\s+)?(?:function|const|class|interface|type|enum)\s+(\w+)"
)
ROUTE_RE = re.compile(r"""<Route\s+path=["']([^"']+)["']\s+element=\{<(\w+)""")
FETCH_RE = re.compile(r"""[`'"](/api/[^`'"$?]*)""")
EXTS = (".ts", ".tsx")


def _resolve(src: str, spec: str, known: set[str]) -> str | None:
    if spec.startswith("@/"):
        base = PurePosixPath(SRC) / spec[2:]
    elif spec.startswith("."):
        base = PurePosixPath(src).parent / spec
    else:
        return None
    parts: list[str] = []
    for part in base.parts:
        if part == "..":
            parts.pop()
        elif part != ".":
            parts.append(part)
    stem = "/".join(parts)
    for cand in (stem, *(stem + e for e in EXTS), *(f"{stem}/index{e}" for e in EXTS)):
        if cand in known:
            return cand
    return None


def _pkg_name(spec: str) -> str:
    parts = spec.split("/")
    return "/".join(parts[:2]) if spec.startswith("@") else parts[0]


def _is_test(path: str) -> bool:
    return "__tests__" in path or ".test." in path


def main() -> None:
    dates = last_commit_dates()
    files = [p for p in tracked_files() if p.startswith(SRC) and p.endswith(EXTS)]
    known = set(files)
    importers: dict[str, list[str]] = defaultdict(list)
    externals: dict[str, int] = defaultdict(int)
    rows = []
    for path in files:
        text = read_text(REPO / path)
        for a, b in IMPORT_RE.findall(text):
            spec = a or b
            target = _resolve(path, spec, known)
            if target:
                importers[target].append(path)
            elif not spec.startswith((".", "@/")):
                externals[_pkg_name(spec)] += 1
        rows.append(
            {
                "path": path,
                "area": path[len(SRC) + 1 :].split("/")[0],
                "loc": sum(1 for line in text.splitlines() if line.strip()),
                "exports": EXPORT_RE.findall(text)[:20],
                "api_calls": sorted(set(FETCH_RE.findall(text))),
                "is_test": _is_test(path),
                "last_commit": dates.get(path, "")[:10],
                "age_days": age_days(dates.get(path, "")),
            }
        )
    for r in rows:
        users = importers.get(r["path"], [])
        prod = sorted(u for u in users if not _is_test(u))
        r["imported_by_prod"] = prod
        r["imported_by_tests"] = sorted(u for u in users if _is_test(u))
        r["unused_candidate"] = (
            not r["is_test"]
            and not users
            and not r["path"].endswith(("main.tsx", "vite-env.d.ts"))
        )
        r["test_only"] = not r["is_test"] and not prod and bool(users)

    app = read_text(REPO / f"{SRC}/App.tsx")
    pkg = json.loads(read_text(REPO / f"{UI}/package.json") or "{}")
    write_json(
        "ui_inventory",
        {
            "routes": [{"path": p, "element": e} for p, e in ROUTE_RE.findall(app)],
            "areas": {
                a: sum(1 for r in rows if r["area"] == a)
                for a in sorted({r["area"] for r in rows})
            },
            "unused_candidates": [r["path"] for r in rows if r["unused_candidate"]],
            "test_only": [r["path"] for r in rows if r["test_only"]],
            "external_import_counts": dict(
                sorted(externals.items(), key=lambda kv: -kv[1])
            ),
            "package": {
                k: pkg.get(k)
                for k in (
                    "name",
                    "version",
                    "scripts",
                    "dependencies",
                    "devDependencies",
                    "engines",
                )
            },
            "files": rows,
        },
    )


if __name__ == "__main__":
    main()
