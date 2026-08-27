"""Build the ``arp-swe-own-code`` eval set from our own repositories.

Cases are ``MUT`` cases: a single semantic mutation applied to one function in
a source file that the repo's own tests already cover -- a flipped comparison,
a dropped guard, an off-by-one. A mutation only becomes a case if running the
covering test file actually fails afterwards, and the failure names a concrete
test. That failing test *is* the ground truth; no gold-patch string is ever
compared, so any repair that turns the suite green scores the same.

Nothing here calls a model. Run it before any eval.

Usage:
    python mine_cases.py --repo evk --count 50
"""

from __future__ import annotations

import argparse
import ast
import json
import random
import shutil
import subprocess
import time
import sys
from dataclasses import dataclass, field
from pathlib import Path

KIT_ROOT = Path(__file__).resolve().parent.parent
CASES_DIR = KIT_ROOT / "dataset" / "cases"

#: Comparison operators we flip, and what we flip them to.
_CMP_FLIPS: dict[type[ast.cmpop], type[ast.cmpop]] = {
    ast.Lt: ast.LtE,
    ast.LtE: ast.Lt,
    ast.Gt: ast.GtE,
    ast.GtE: ast.Gt,
    ast.Eq: ast.NotEq,
    ast.NotEq: ast.Eq,
    ast.Is: ast.IsNot,
    ast.IsNot: ast.Is,
    ast.In: ast.NotIn,
    ast.NotIn: ast.In,
}


@dataclass
class MutationSite:
    """One candidate edit: a line, a description, and the rewritten source."""

    lineno: int
    kind: str
    description: str
    mutated_source: str


class _Mutator(ast.NodeTransformer):
    """Applies exactly one mutation, selected by ordinal, and records it."""

    def __init__(self, target_ordinal: int) -> None:
        self._ordinal = target_ordinal
        self.seen = 0
        self.applied: tuple[int, str, str] | None = None

    def _take(self, node: ast.AST, kind: str, description: str) -> bool:
        """Return True when this site is the one we were asked to mutate."""
        if self.seen != self._ordinal:
            self.seen += 1
            return False
        self.seen += 1
        self.applied = (getattr(node, "lineno", 0), kind, description)
        return True

    def visit_Compare(self, node: ast.Compare) -> ast.AST:
        self.generic_visit(node)
        if len(node.ops) == 1 and type(node.ops[0]) in _CMP_FLIPS:
            original = type(node.ops[0])
            replacement = _CMP_FLIPS[original]
            if self._take(node, "compare", original.__name__ + " -> " + replacement.__name__):
                node.ops = [replacement()]
        return node

    def visit_BoolOp(self, node: ast.BoolOp) -> ast.AST:
        self.generic_visit(node)
        flipped = ast.Or if isinstance(node.op, ast.And) else ast.And
        if self._take(node, "boolop", type(node.op).__name__ + " -> " + flipped.__name__):
            node.op = flipped()
        return node

    def visit_UnaryOp(self, node: ast.UnaryOp) -> ast.AST:
        self.generic_visit(node)
        if isinstance(node.op, ast.Not) and self._take(node, "not", "dropped not"):
            return node.operand
        return node

    def visit_Constant(self, node: ast.Constant) -> ast.AST:
        if isinstance(node.value, int) and not isinstance(node.value, bool):
            if node.value in (0, 1, 2) and self._take(
                node, "offbyone", str(node.value) + " -> " + str(node.value + 1)
            ):
                return ast.Constant(value=node.value + 1)
        return node


def count_sites(source: str) -> int:
    """How many mutable sites this source has (upper bound on ordinals)."""
    counter = _Mutator(target_ordinal=-1)
    counter.visit(ast.parse(source))
    return counter.seen


def mutate(source: str, ordinal: int) -> MutationSite | None:
    tree = ast.parse(source)
    mutator = _Mutator(ordinal)
    new_tree = mutator.visit(tree)
    if mutator.applied is None:
        return None
    ast.fix_missing_locations(new_tree)
    lineno, kind, description = mutator.applied
    return MutationSite(
        lineno=lineno,
        kind=kind,
        description=description,
        mutated_source=ast.unparse(new_tree),
    )


@dataclass
class RepoSpec:
    """A repo we mine from, and how to run one of its test files."""

    name: str
    path: Path
    package_root: str
    test_root: str
    test_command: list[str]
    module_to_test: str = "test_{stem}.py"
    skip: tuple[str, ...] = field(default_factory=tuple)
    #: Where the case will be graded from. Mining may run in a throwaway
    #: worktree, but a case must name the durable repo it came from.
    canonical_path: Path | None = None
    #: Seconds one covering test file may take before the candidate is
    #: abandoned. A file that hangs is not a usable oracle at any length,
    #: so this stays short: the cost of waiting is paid on every module.
    test_timeout: int = 300


def covering_test_file(repo: RepoSpec, module: Path) -> Path | None:
    """Find the test file that conventionally covers *module*."""
    stem = module.stem
    if stem == "__init__":
        return None
    wanted = repo.module_to_test.format(stem=stem)
    matches = sorted((repo.path / repo.test_root).rglob(wanted))
    return matches[0] if matches else None


def run_pytest(repo: RepoSpec, test_file: Path, timeout: int | None = None) -> tuple[int, str]:
    command = [*repo.test_command, test_file.relative_to(repo.path).as_posix()]
    try:
        proc = subprocess.run(
            command,
            cwd=repo.path,
            capture_output=True,
            text=True,
            timeout=timeout or repo.test_timeout,
        )
    except subprocess.TimeoutExpired:
        # Report as a non-zero run with no parseable failures, which makes
        # the caller skip this module rather than mine a case whose oracle
        # cannot finish.
        return 124, "TIMEOUT"
    return proc.returncode, (proc.stdout + proc.stderr)[-20000:]


def failing_test_ids(output: str) -> list[str]:
    ids: list[str] = []
    for raw in output.splitlines():
        line = raw.strip()
        if line.startswith("FAILED ") or line.startswith("ERROR "):
            ids.append(line.split(" ", 1)[1].split(" - ")[0].strip())
    return ids


def symptom_excerpt(output: str, limit: int = 1800) -> str:
    """The failing-test evidence the agent is allowed to see.

    Deliberately the assertion and traceback, never the mutation description:
    an agent told what was broken is not solving the task.
    """
    marker = output.find("=========================== FAILURES")
    body = output[marker:] if marker != -1 else output
    return body[:limit]


def emit_case(
    case_id: str,
    repo: RepoSpec,
    module: Path,
    test_file: Path,
    original: str,
    broken: str,
    failing: list[str],
    output: str,
    kind: str,
    mutation: MutationSite | None,
) -> dict:
    case_dir = CASES_DIR / case_id
    case_dir.mkdir(parents=True, exist_ok=True)
    (case_dir / "broken.py").write_text(broken, encoding="utf-8")
    (case_dir / "gold.py").write_text(original, encoding="utf-8")
    rel_module = module.relative_to(repo.path).as_posix()
    rel_test = test_file.relative_to(repo.path).as_posix()
    oracle = {
        "case_id": case_id,
        "kind": kind,
        "source_repo": repo.name,
        "repo_path": (repo.canonical_path or repo.path).as_posix(),
        "target_file": rel_module,
        "test_file": rel_test,
        "test_command": repo.test_command,
        "failing_tests": failing,
        "max_changed_lines": 40,
        "mutation": None
        if mutation is None
        else {
            "line": mutation.lineno,
            "kind": mutation.kind,
            "what": mutation.description,
        },
        "contamination_risk": "medium",
    }
    (case_dir / "oracle.json").write_text(json.dumps(oracle, indent=2), encoding="utf-8")
    (case_dir / "failure.txt").write_text(symptom_excerpt(output), encoding="utf-8")
    return {
        "sample_id": case_id,
        "input": {
            "bug_report": (
                "Test `"
                + failing[0]
                + "` fails in "
                + repo.name
                + ". Repair the source so it passes.\n\n"
                + symptom_excerpt(output)
            ),
            "code_file": rel_module,
            "repo_path": case_dir.as_posix(),
            "failing_test": failing[0],
        },
        "reference": None,
        "metadata": {
            "kind": kind,
            "source_repo": repo.name,
            "contamination_risk": "medium",
            "max_changed_lines": 40,
            "test_file": rel_test,
        },
    }


def mine_mutations(repo: RepoSpec, wanted: int, seed: int = 20260827) -> list[dict]:
    rng = random.Random(seed)
    package = repo.path / repo.package_root
    modules = [
        m
        for m in sorted(package.rglob("*.py"))
        if m.stem != "__init__" and not any(s in m.as_posix() for s in repo.skip)
    ]
    rng.shuffle(modules)
    rows: list[dict] = []
    index = 0
    for module in modules:
        if len(rows) >= wanted:
            break
        test_file = covering_test_file(repo, module)
        if test_file is None:
            continue
        original = module.read_text(encoding="utf-8")
        try:
            sites = count_sites(original)
        except SyntaxError:
            continue
        if sites == 0:
            continue
        # Baseline: the test file must be green before we break anything, or
        # a "failure" afterwards proves nothing.
        baseline_started = time.monotonic()
        code, output = run_pytest(repo, test_file)
        baseline_seconds = time.monotonic() - baseline_started
        if code != 0:
            print("  skip " + module.name + ": test file already red", flush=True)
            continue
        # A mutation that hangs the suite is not a usable oracle at any
        # length, so bound it by what this file just proved it needs.
        mutation_timeout = max(30, min(repo.test_timeout, int(baseline_seconds * 10) + 20))
        for ordinal in rng.sample(range(sites), min(sites, 4)):
            if len(rows) >= wanted:
                break
            site = mutate(original, ordinal)
            if site is None:
                continue
            module.write_text(site.mutated_source, encoding="utf-8")
            try:
                code, output = run_pytest(repo, test_file, timeout=mutation_timeout)
            finally:
                module.write_text(original, encoding="utf-8")
            if output == "TIMEOUT":
                print(
                    "  skip "
                    + module.name
                    + ":"
                    + str(site.lineno)
                    + " hung the suite (>"
                    + str(mutation_timeout)
                    + "s); not a usable oracle",
                    flush=True,
                )
                continue
            failing = failing_test_ids(output)
            if code == 0 or not failing:
                continue
            index += 1
            case_id = repo.name.upper() + "-MUT-" + format(index, "03d")
            rows.append(
                emit_case(
                    case_id,
                    repo,
                    module,
                    test_file,
                    original,
                    site.mutated_source,
                    failing,
                    output,
                    "MUT",
                    site,
                )
            )
            print(
                "  + "
                + case_id
                + " "
                + module.name
                + ":"
                + str(site.lineno)
                + " "
                + site.description
                + " -> "
                + str(len(failing))
                + " failing",
                flush=True,
            )
    return rows


REPOS = {
    "evk": RepoSpec(
        name="evk",
        path=Path("C:/Users/tandf/source/agentic-evalkit"),
        package_root="src/agentic_evalkit",
        test_root="tests",
        test_command=["uv", "run", "pytest", "-x", "-q", "--no-cov"],
        skip=("benchmarks/swebench_docker",),
    ),
    "ek": RepoSpec(
        name="ek",
        path=Path("C:/Users/tandf/source/executionkit"),
        package_root="executionkit",
        test_root="tests",
        # EK's own interpreter, invoked with cwd set to the checkout being
        # mined. sys.path[0] is that checkout, so the mutated copy shadows
        # whatever is installed in site-packages. If that ever stopped being
        # true the miner would simply find zero cases -- a safe failure, since
        # an unmutated import can never make a green test go red.
        test_command=[
            "C:/Users/tandf/source/executionkit/.venv/Scripts/python.exe",
            "-m", "pytest", "-x", "-q", "--no-cov", "-m", "not live",
            "-p", "no:cacheprovider",
        ],
        skip=("_mock.py", "claude_sdk.py"),
        test_timeout=150,
    ),
    "arp": RepoSpec(
        name="arp",
        path=Path("C:/Users/tandf/source/agentic-runtime-platform/agentic-workflows-v2"),
        package_root="agentic_v2",
        test_root="tests",
        test_command=[
            "C:/Users/tandf/source/agentic-runtime-platform/.venv/Scripts/python.exe",
            "-m", "pytest", "-x", "-q", "--no-cov", "-p", "no:cacheprovider",
        ],
        # Anything that reaches a provider, a container, or the network is not
        # a deterministic oracle, so it cannot host a case.
        skip=("langchain/", "integrations/mcp", "server/", "memoryctl/"),
        test_timeout=240,
    ),
    "memoryctl": RepoSpec(
        name="memoryctl",
        path=Path("C:/Users/tandf/source/repos/memoryctl"),
        package_root="memoryctl",
        test_root="tests",
        test_command=["python", "-m", "pytest", "-x", "-q", "--no-cov"],
    ),
}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default="evk", choices=sorted(REPOS))
    parser.add_argument("--count", type=int, default=50)
    parser.add_argument("--out", default=str(KIT_ROOT / "dataset" / "cases.jsonl"))
    parser.add_argument("--fresh", action="store_true", help="delete existing cases first")
    parser.add_argument("--path", default=None, help="mine from this checkout instead")
    parser.add_argument(
        "--append",
        action="store_true",
        help="add to the existing cases.jsonl rather than replacing it",
    )
    args = parser.parse_args()

    if args.fresh and CASES_DIR.exists():
        shutil.rmtree(CASES_DIR)
    CASES_DIR.mkdir(parents=True, exist_ok=True)

    repo = REPOS[args.repo]
    if args.path:
        repo = RepoSpec(
            name=repo.name,
            path=Path(args.path),
            package_root=repo.package_root,
            test_root=repo.test_root,
            test_command=repo.test_command,
            module_to_test=repo.module_to_test,
            skip=repo.skip,
            canonical_path=REPOS[args.repo].path,
        )
    print("mining " + str(args.count) + " cases from " + repo.name, flush=True)
    rows = mine_mutations(repo, args.count)
    print("mined " + str(len(rows)) + " cases from " + repo.name)
    print("now run: python tools/rebuild_index.py")
    return 0 if rows else 1


if __name__ == "__main__":
    sys.exit(main())
