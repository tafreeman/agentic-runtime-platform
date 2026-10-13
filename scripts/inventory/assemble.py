"""Concatenate docs/inventory/sections/*.md into the dated master inventory document."""

from __future__ import annotations

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


def _anchor(title: str) -> str:
    slug = re.sub(r"[^\w\- ]", "", title.lower()).strip()
    return re.sub(r"\s+", "-", slug)


def main() -> None:
    parts = sorted(SECTIONS.glob("*.md"))
    bodies = [p.read_text(encoding="utf-8").strip() for p in parts]
    toc = []
    for body in bodies:
        m = HEADING_RE.search(body)
        if m:
            toc.append(f"- [{m.group(1)}](#{_anchor(m.group(1))})")
    front = (INV / "_front.md").read_text(encoding="utf-8").strip()
    doc = "\n\n".join([front, "## Contents", "\n".join(toc), *bodies]) + "\n"
    out = INV / f"ARP-REPO-INVENTORY-{date.today().isoformat()}.md"
    out.write_text(doc, encoding="utf-8")
    print(f"wrote {out} ({doc.count(chr(10))} lines, {len(parts)} sections)")


if __name__ == "__main__":
    main()
