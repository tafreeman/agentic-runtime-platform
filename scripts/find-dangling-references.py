"""Find dangling references to deleted files across the codebase.

Usage:
    python scripts/find-dangling-references.py

Checks for references to recently deleted prompts, workflows, and modules.
Reports file:line for each dangling reference found.
"""

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
SKIP_DIRS = {
    "node_modules",
    ".venv",
    "__pycache__",
    ".git",
    "storybook-static",
    ".venv314",
}

# Deleted prompt persona names (removed in d921ba0f)
DELETED_PROMPTS = [
    "analyst",
    "antagonist_implementation",
    "antagonist_systemic",
    "containment_checker",
    "debugger",
    "generator",
    "judge",
    "reasoner",
    "researcher",
    "task_planner",
    "vision",
    "writer",
]

# Deleted workflow definition names (removed in d921ba0f)
DELETED_WORKFLOWS = [
    "deep_research",
    "fullstack_generation_bounded_rereview",
    "multi_agent_codegen_e2e_single_loop",
    "multi_agent_codegen_e2e",
    "plan_implementation",
    "tdd_codegen_e2e",
]

# Build patterns: references to deleted prompts as file paths or agent names
PATTERNS = []
for name in DELETED_PROMPTS:
    # Match: prompts/analyst.md, agent: analyst, "analyst"
    PATTERNS.append((name, re.compile(rf"\bprompts/{name}\.md\b")))
    PATTERNS.append((name, re.compile(rf'\bagent:\s*["\']?{name}["\']?\b')))

for name in DELETED_WORKFLOWS:
    # Match: definitions/deep_research.yaml, workflow: deep_research
    PATTERNS.append((name, re.compile(rf"\bdefinitions/{name}\.yaml\b")))
    PATTERNS.append((name, re.compile(rf'\bworkflow:\s*["\']?{name}["\']?\b')))

EXTENSIONS = {
    ".py",
    ".yaml",
    ".yml",
    ".md",
    ".json",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".toml",
}


def should_skip(path: pathlib.Path) -> bool:
    return any(part in SKIP_DIRS for part in path.parts)


def main() -> None:
    findings: list[tuple[str, str, int, str]] = []  # (name, file, line, text)

    for ext in EXTENSIONS:
        for path in ROOT.rglob(f"*{ext}"):
            if should_skip(path):
                continue
            # Skip this script itself
            if path.resolve() == pathlib.Path(__file__).resolve():
                continue

            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except (OSError, UnicodeDecodeError):
                continue

            for line_num, line in enumerate(text.splitlines(), 1):
                for name, pattern in PATTERNS:
                    if pattern.search(line):
                        rel = path.relative_to(ROOT)
                        findings.append((name, str(rel), line_num, line.strip()))

    if findings:
        print(f"Found {len(findings)} dangling reference(s):\n")
        current_name = None
        for name, file, line_num, text in sorted(findings):
            if name != current_name:
                print(f"\n  [{name}]")
                current_name = name
            print(f"    {file}:{line_num}  {text[:100]}")
        sys.exit(1)
    else:
        print("No dangling references found.")
        sys.exit(0)


if __name__ == "__main__":
    main()
