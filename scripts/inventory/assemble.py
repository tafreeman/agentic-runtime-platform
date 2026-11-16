"""Concatenate docs/inventory/sections/*.md into the dated master inventory document."""

from __future__ import annotations

import json
import re
import sys
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from _common import HOME_REPO

INV = HOME_REPO / "docs" / "inventory"
SECTIONS = INV / "sections"
HEADING_RE = re.compile(r"^## (.+)$", re.M)
# Snapshot declarations in the front matter and sections, in the forms the
# narrative uses: "revision `h`", "rev h", "at h", "against `h`", "source: h",
# "origin/main @ `h`", "origin/main = `h`", and "main (`h`)".
# Branch-tip mentions such as "branch @ `h`" are not declarations: "@" and
# "=" only count directly after main or origin/main.
DECLARED_REV_RE = re.compile(
    r"\b(?:revision|rev|at|against|source)\b\s*[`\uff20@ ]{0,3}([0-9a-f]{7,40})\b"
    r"|\b(?:origin/)?main\b[`*_ ]*(?:[@\uff20=]|\bat\b|\bagainst\b|\()?\s*`?"
    r"([0-9a-f]{7,40})\b",
    re.IGNORECASE,
)


def _check_revision(texts: list[str]) -> None:
    """Refuse to assemble narrative that describes a different revision than the data.

    The sections are hand-written against one revision; the JSON is
    regenerated per run. Mixing them produces a report dated today whose
    body describes an older tree than its numbers. Every declaration in
    the front matter and in each section is checked, not just the first
    form.
    """
    data = json.loads(
        (INV / "data" / "meta_inventory.json").read_text(encoding="utf-8")
    )
    rev = str(data["revision"]).split()[0]
    declared = {g1 or g2 for g1, g2 in DECLARED_REV_RE.findall("\n".join(texts))}
    stale = sorted(d for d in declared if not (rev.startswith(d) or d.startswith(rev)))
    if stale:
        raise SystemExit(
            f"sections declare revision {', '.join(stale)} but the data is {rev}; "
            "update the sections for the new revision before assembling"
        )


def _anchor(title: str) -> str:
    slug = re.sub(r"[^\w\- ]", "", title.lower()).strip()
    return re.sub(r"\s+", "-", slug)


def main() -> None:
    parts = sorted(SECTIONS.glob("*.md"))
    bodies = [p.read_text(encoding="utf-8").strip() for p in parts]
    front = (INV / "_front.md").read_text(encoding="utf-8").strip()
    _check_revision([front, *bodies])
    toc = []
    for body in bodies:
        m = HEADING_RE.search(body)
        if m:
            toc.append(f"- [{m.group(1)}](#{_anchor(m.group(1))})")
    doc = "\n\n".join([front, "## Contents", "\n".join(toc), *bodies]) + "\n"
    out = INV / f"ARP-REPO-INVENTORY-{date.today().isoformat()}.md"
    out.write_text(doc, encoding="utf-8")
    print(f"wrote {out} ({doc.count(chr(10))} lines, {len(parts)} sections)")


if __name__ == "__main__":
    main()
