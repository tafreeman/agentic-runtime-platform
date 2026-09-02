"""Check that every mined case still reproduces.

A case claims two things: with ``broken.py`` in place a specific named test
fails, and with ``gold.py`` in place the covering file is green. Both are
claims about execution, so both are checked by executing them.

This matters more than it looks. A case can be silently invalid in ways that
are invisible to inspection:

* the mutated module is shadowed by an installed copy, so the test that
  "failed" failed for some unrelated reason;
* the covering test is flaky, and the miner caught a red run;
* the source repo moved on and the mutation no longer applies.

Any of those turns a case into noise that an A/B will faithfully measure and
report as a real difference. Run this after mining, and before trusting a
result.

    python tools/verify_cases.py              # broken-side check, every case
    python tools/verify_cases.py --full       # also re-check the gold side
    python tools/verify_cases.py --repo ek    # one repo
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

KIT_ROOT = Path(__file__).resolve().parent.parent
CASES_DIR = KIT_ROOT / "dataset" / "cases"
SCRATCH = Path(
    "C:/Users/tandf/AppData/Local/Temp/claude/"
    "C--Users-tandf-source-agentic-evalkit/98683646-eaf6-4196-85d4-372846e7317f/scratchpad"
)

#: Where each source repo's cases are exercised. These are the same throwaway
#: worktrees mining used -- never a live checkout.
WORKTREES: dict[str, Path] = {
    "evk": SCRATCH / "evk-mine",
    "ek": SCRATCH / "ek-mine",
    "arp": SCRATCH / "arp-mine/agentic-workflows-v2",
    "memoryctl": SCRATCH / "mc-mine",
}

TIMEOUT_SECONDS = 300


@dataclass
class Verdict:
    case_id: str
    repo: str
    ok: bool
    reason: str


def run_tests(worktree: Path, command: list[str], test_file: str) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            [*command, test_file],
            cwd=worktree,
            capture_output=True,
            text=True,
            timeout=TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired:
        return 124, "TIMEOUT"
    except OSError as error:
        return 125, f"could not run: {error}"
    return proc.returncode, (proc.stdout + proc.stderr)[-8000:]


def verify(case_dir: Path, *, full: bool) -> Verdict | None:
    oracle_path = case_dir / "oracle.json"
    if not oracle_path.is_file():
        return None
    oracle = json.loads(oracle_path.read_text(encoding="utf-8"))
    case_id = oracle["case_id"]
    repo = oracle["source_repo"]
    worktree = WORKTREES.get(repo)
    if worktree is None or not worktree.is_dir():
        return Verdict(case_id, repo, False, f"no worktree for {repo}")

    target = worktree / oracle["target_file"]
    if not target.is_file():
        return Verdict(case_id, repo, False, f"target missing: {oracle['target_file']}")

    expected = str((oracle.get("failing_tests") or [""])[0])
    expected_node = expected.rsplit("::", 1)[-1]
    command = list(oracle["test_command"])
    test_file = oracle["test_file"]
    broken = (case_dir / "broken.py").read_text(encoding="utf-8")
    original = target.read_text(encoding="utf-8")

    try:
        target.write_text(broken, encoding="utf-8")
        code, output = run_tests(worktree, command, test_file)
        if code == 0:
            return Verdict(case_id, repo, False, "broken source did not fail the tests")
        if code in (124, 125):
            return Verdict(case_id, repo, False, output[:60])
        if expected_node and expected_node not in output:
            return Verdict(
                case_id, repo, False, f"failed, but not at {expected_node}"
            )

        if full:
            gold = (case_dir / "gold.py").read_text(encoding="utf-8")
            target.write_text(gold, encoding="utf-8")
            code, output = run_tests(worktree, command, test_file)
            if code != 0:
                return Verdict(case_id, repo, False, "gold source is not green")
    finally:
        target.write_text(original, encoding="utf-8")

    return Verdict(case_id, repo, True, "reproduces")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default=None, choices=sorted(WORKTREES))
    parser.add_argument(
        "--full",
        action="store_true",
        help="also confirm the gold source is green (doubles the runtime)",
    )
    parser.add_argument(
        "--prune",
        action="store_true",
        help="delete case directories that fail verification",
    )
    args = parser.parse_args()

    verdicts: list[Verdict] = []
    for case_dir in sorted(CASES_DIR.iterdir()):
        if not case_dir.is_dir():
            continue
        if args.repo and not case_dir.name.lower().startswith(args.repo.lower() + "-"):
            continue
        verdict = verify(case_dir, full=args.full)
        if verdict is None:
            continue
        verdicts.append(verdict)
        mark = "ok  " if verdict.ok else "BAD "
        print(f"  {mark} {verdict.case_id:<20} {verdict.reason}", flush=True)

    good = [v for v in verdicts if v.ok]
    bad = [v for v in verdicts if not v.ok]
    print(f"\n{len(good)}/{len(verdicts)} cases reproduce")
    for repo, count in sorted(Counter(v.repo for v in good).items()):
        print(f"  {repo:<12} {count}")
    if bad:
        print(f"\n{len(bad)} did not:")
        for verdict in bad:
            print(f"  {verdict.case_id:<20} {verdict.reason}")
        if args.prune:
            import shutil

            for verdict in bad:
                shutil.rmtree(CASES_DIR / verdict.case_id, ignore_errors=True)
            print(f"\npruned {len(bad)} case directories; rerun tools/rebuild_index.py")
    return 0 if not bad else 1


if __name__ == "__main__":
    sys.exit(main())
