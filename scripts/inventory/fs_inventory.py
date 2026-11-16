"""Directory-level inventory: tracked/untracked/ignored, sizes, staleness, orphans."""

from __future__ import annotations

import os
from collections import Counter, defaultdict
from pathlib import Path

from _common import (
    REPO,
    SKIP_DIRS,
    STALE_DAYS,
    age_days,
    git,
    last_commit_dates,
    tracked_files,
    untracked_files,
    write_json,
)

DEPTH = 3
LARGE_FILE_BYTES = 1_000_000


def _dir_key(path: str, depth: int = DEPTH) -> str:
    parts = path.split("/")[:-1]
    return "/".join(parts[:depth]) or "."


def _ignored_top_level() -> list[dict[str, object]]:
    """Top-level entries on disk that git ignores (caches, artifacts, local state)."""
    out = git("status", "--ignored", "--porcelain", "-uno", "--", ".")
    rows = []
    for line in git(
        "ls-files", "--others", "--ignored", "--exclude-standard", "--directory"
    ).splitlines():
        if line.count("/") <= 1:
            rows.append({"path": line})
    del out
    return rows


def _orphan_pycache_dirs() -> list[str]:
    """Package dirs holding only __pycache__ — leftovers of deleted modules."""
    orphans = []
    for root in ("agentic-workflows-v2/agentic_v2", "agentic-v2-eval/src", "tools"):
        base = REPO / root
        for dirpath, dirnames, filenames in os.walk(base):
            dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS - {"__pycache__"}]
            if set(dirnames) == {"__pycache__"} and not filenames:
                orphans.append(Path(dirpath).relative_to(REPO).as_posix())
    return orphans


def _dir_size(path: Path) -> int:
    total = 0
    for dirpath, dirnames, files in os.walk(path):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for f in files:
            try:
                total += (Path(dirpath) / f).stat().st_size
            except OSError:
                continue
    return total


def main() -> None:
    tracked = tracked_files()
    untracked = untracked_files()
    dates = last_commit_dates()

    dirs: dict[str, dict[str, object]] = defaultdict(
        lambda: {
            "tracked": 0,
            "untracked": 0,
            "bytes": 0,
            "exts": Counter(),
            "newest": "",
            "oldest": "",
        }
    )
    large = []
    for path in tracked:
        d = dirs[_dir_key(path)]
        d["tracked"] = int(d["tracked"]) + 1  # type: ignore[call-overload]
        full = REPO / path
        size = full.stat().st_size if full.exists() else 0
        d["bytes"] = int(d["bytes"]) + size  # type: ignore[call-overload]
        d["exts"][Path(path).suffix or "(none)"] += 1  # type: ignore[index]
        when = dates.get(path, "")
        if when and (not d["newest"] or when > str(d["newest"])):
            d["newest"] = when
        if when and (not d["oldest"] or when < str(d["oldest"])):
            d["oldest"] = when
        if size >= LARGE_FILE_BYTES:
            large.append({"path": path, "bytes": size})
    for path in untracked:
        dirs[_dir_key(path)]["untracked"] = int(dirs[_dir_key(path)]["untracked"]) + 1  # type: ignore[call-overload]

    rows = []
    for key, d in sorted(dirs.items()):
        newest_age = age_days(str(d["newest"]))
        rows.append(
            {
                "dir": key,
                "tracked": d["tracked"],
                "untracked": d["untracked"],
                "kb": round(int(d["bytes"]) / 1024, 1),  # type: ignore[call-overload]
                "top_exts": dict(d["exts"].most_common(4)),  # type: ignore[attr-defined]
                "last_commit": str(d["newest"])[:10],
                "last_commit_age_days": newest_age,
                "stale": newest_age is not None and newest_age > STALE_DAYS,
            }
        )

    top_level = []
    for entry in sorted(REPO.iterdir()):
        if entry.name in SKIP_DIRS:
            size = None
        else:
            size = (
                round(_dir_size(entry) / 1024, 1)
                if entry.is_dir()
                else round(entry.stat().st_size / 1024, 1)
            )
        n_tracked = sum(
            1 for p in tracked if p == entry.name or p.startswith(entry.name + "/")
        )
        n_untracked = sum(
            1 for p in untracked if p == entry.name or p.startswith(entry.name + "/")
        )
        top_level.append(
            {
                "name": entry.name + ("/" if entry.is_dir() else ""),
                "kb": size,
                "tracked": n_tracked,
                "untracked": n_untracked,
                "status": (
                    "tracked"
                    if n_tracked
                    else ("untracked" if n_untracked else "ignored/local-only")
                ),
            }
        )

    write_json(
        "fs_inventory",
        {
            "totals": {"tracked": len(tracked), "untracked": len(untracked)},
            "top_level": top_level,
            "dirs": rows,
            "untracked_files": untracked,
            "large_tracked_files": sorted(large, key=lambda r: -int(r["bytes"])),
            "orphan_pycache_dirs": _orphan_pycache_dirs(),
            "ignored_entries": _ignored_top_level(),
        },
    )


if __name__ == "__main__":
    main()
