"""Run every inventory extractor and print a one-screen digest.

Usage (inventory a clean origin/main worktree, write JSON into this checkout):
    git worktree add --detach C:/tmp/arp-main-inventory origin/main
    ARP_INVENTORY_REPO=C:/tmp/arp-main-inventory python scripts/inventory/run_all.py
"""

from __future__ import annotations

import json
import runpy
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from _common import OUT_DIR, REPO

STEPS = ("fs_inventory", "py_inventory", "ui_inventory", "meta_inventory")


def main() -> None:
    for step in STEPS:
        runpy.run_path(str(HERE / f"{step}.py"), run_name="__main__")
        print(f"ok  {step} -> {OUT_DIR / (step + '.json')}")
    py = json.loads((OUT_DIR / "py_inventory.json").read_text(encoding="utf-8"))
    ui = json.loads((OUT_DIR / "ui_inventory.json").read_text(encoding="utf-8"))
    meta = json.loads((OUT_DIR / "meta_inventory.json").read_text(encoding="utf-8"))
    print(f"\nrevision: {meta['revision']}  (repo {REPO})")
    print(f"python modules: {len(py['modules'])}  tests: {py['test_totals']}")
    print(
        f"orphan python candidates: {sum(1 for m in py['modules'] if m.get('orphan_candidate'))}"
    )
    print(
        f"ui files: {len(ui['files'])}  unused: {len(ui['unused_candidates'])}  test-only: {len(ui['test_only'])}"
    )
    print(
        f"workflows: {len(meta['workflows'])}  ci files: {len(meta['ci'])}  adrs: {len(meta['adrs'])}  docs: {len(meta['docs'])}"
    )


if __name__ == "__main__":
    main()
