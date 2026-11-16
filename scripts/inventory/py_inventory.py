"""Python inventory via AST: modules, symbols, contracts, routes, import graph, usage."""

from __future__ import annotations

import ast
import re
from collections import defaultdict
from pathlib import Path

from _common import (
    REPO,
    last_commit_dates,
    age_days,
    read_text,
    tracked_files,
    write_json,
)

PACKAGES = {
    "agentic_v2": "agentic-workflows-v2/agentic_v2",
    "agentic_v2_eval": "agentic-v2-eval/src/agentic_v2_eval",
    "tools": "tools",
}
TEST_ROOTS = (
    "agentic-workflows-v2/tests",
    "agentic-v2-eval/tests",
    "tools/tests",
    "tests",
)
MARKER_RE = re.compile(r"#\s*(TODO|FIXME|XXX|HACK|DEPRECATED)\b[:\s]*(.*)", re.I)
ENV_RE = re.compile(
    r"""(?:os\.environ(?:\.get)?|os\.getenv|getenv)\s*[\[(]\s*["']([A-Z][A-Z0-9_]+)["']"""
)
ROUTE_DECOS = {"get", "post", "put", "patch", "delete", "websocket", "api_route"}
SPECIAL_BASES = {
    "BaseModel": "pydantic",
    "BaseSettings": "pydantic-settings",
    "Protocol": "protocol",
    "Enum": "enum",
    "StrEnum": "enum",
    "TypedDict": "typeddict",
    "ABC": "abstract",
    "Exception": "exception",
}


def _module_name(path: str) -> str | None:
    for pkg, root in PACKAGES.items():
        if path.startswith(root + "/") and path.endswith(".py"):
            rel = path[len(root) + 1 : -3].replace("/", ".")
            rel = rel.removesuffix(".__init__").removesuffix("__init__")
            return f"{pkg}.{rel}".rstrip(".") if rel else pkg
    return None


def _base_names(node: ast.ClassDef) -> list[str]:
    names = []
    for b in node.bases:
        if isinstance(b, ast.Name):
            names.append(b.id)
        elif isinstance(b, ast.Attribute):
            names.append(b.attr)
        elif isinstance(b, ast.Subscript) and isinstance(b.value, ast.Name):
            names.append(b.value.id)
    return names


def _doc1(node: ast.AST) -> str:
    doc = (
        ast.get_docstring(node)
        if isinstance(
            node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
        )
        else None
    )
    return (doc or "").strip().splitlines()[0][:160] if doc else ""


def _routes(tree: ast.Module) -> list[dict[str, str]]:
    prefix = ""
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "APIRouter":
            for kw in node.keywords:
                if kw.arg == "prefix" and isinstance(kw.value, ast.Constant):
                    prefix = str(kw.value.value)
    out = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for deco in node.decorator_list:
            if not (
                isinstance(deco, ast.Call) and isinstance(deco.func, ast.Attribute)
            ):
                continue
            if deco.func.attr not in ROUTE_DECOS or not deco.args:
                continue
            arg = deco.args[0]
            if isinstance(arg, ast.Constant):
                out.append(
                    {
                        "method": deco.func.attr.upper(),
                        "path": prefix + str(arg.value),
                        "handler": node.name,
                        "doc": _doc1(node),
                    }
                )
    return out


def _imports(tree: ast.Module, modname: str, is_pkg: bool) -> set[str]:
    """Absolute and relative imports, including lazy ones inside functions."""
    found: set[str] = set()
    pkg_parts = modname.split(".")
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                # `from . import x` in pkg/__init__.py resolves to pkg itself
                base = pkg_parts[: len(pkg_parts) - node.level + (1 if is_pkg else 0)]
                mod = ".".join(base + ([node.module] if node.module else []))
            else:
                mod = node.module or ""
            found.add(mod)
            found.update(f"{mod}.{a.name}" for a in node.names)
    return found


def _analyse(path: str, text: str) -> dict[str, object]:
    modname = _module_name(path) or path
    try:
        tree = ast.parse(text)
    except SyntaxError as exc:
        return {"module": modname, "path": path, "parse_error": str(exc)}
    classes, functions = [], []
    for node in tree.body:
        if isinstance(node, ast.ClassDef):
            bases = _base_names(node)
            kinds = sorted({SPECIAL_BASES[b] for b in bases if b in SPECIAL_BASES})
            fields = [
                t.target.id
                for t in node.body
                if isinstance(t, ast.AnnAssign) and isinstance(t.target, ast.Name)
            ]
            classes.append(
                {
                    "name": node.name,
                    "bases": bases,
                    "kinds": kinds,
                    "fields": fields[:25],
                    "doc": _doc1(node),
                }
            )
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            functions.append(
                {
                    "name": node.name,
                    "async": isinstance(node, ast.AsyncFunctionDef),
                    "doc": _doc1(node),
                }
            )
    markers = [
        {"line": i + 1, "tag": m.group(1).upper(), "text": m.group(2)[:140]}
        for i, line in enumerate(text.splitlines())
        if (m := MARKER_RE.search(line))
    ]
    return {
        "module": modname,
        "path": path,
        "loc": sum(1 for line in text.splitlines() if line.strip()),
        "doc": _doc1(tree),
        "classes": classes,
        "functions": functions,
        "routes": _routes(tree),
        "imports": sorted(_imports(tree, modname, path.endswith("__init__.py"))),
        "env_vars": sorted(set(ENV_RE.findall(text))),
        "markers": markers,
    }


def _usage(
    modules: list[dict[str, object]], test_texts: dict[str, str], all_text: str
) -> None:
    """Annotate each module with importers and test references."""
    importers: dict[str, set[str]] = defaultdict(set)
    for m in modules:
        for imp in m.get("imports", []):  # type: ignore[union-attr]
            importers[str(imp)].add(str(m["module"]))
    for m in modules:
        name = str(m["module"])
        users = set()
        for imp, who in importers.items():
            if imp == name or imp.startswith(name + "."):
                users |= who
        users.discard(name)
        m["imported_by"] = sorted(users)
        stem = name.rsplit(".", 1)[-1]
        m["test_refs"] = sorted(p for p, t in test_texts.items() if name in t)[:8]
        # string references catch importlib/entry-point/registry wiring. Remove
        # only the module's own mentions; a module that never names itself keeps
        # its full count, so a single real reference is not turned into zero.
        own = read_text(REPO / str(m["path"])) if m.get("path") else ""
        m["string_refs"] = all_text.count(name) - own.count(name)
        is_test = ".tests" in name or stem.startswith(("test_", "conftest"))
        m["is_test"] = is_test
        m["orphan_candidate"] = (
            not is_test
            and not users
            and not m["test_refs"]
            and m["string_refs"] <= 0
            and stem not in {"__init__", "__main__"}
            and not name.endswith(("cli", "app", "main"))
        )


def main() -> None:
    files = tracked_files()
    dates = last_commit_dates()
    modules = []
    for path in files:
        if _module_name(path):
            info = _analyse(path, read_text(REPO / path))
            info["last_commit"] = dates.get(path, "")[:10]
            info["age_days"] = age_days(dates.get(path, ""))
            modules.append(info)
    test_paths = [p for p in files if p.endswith(".py") and p.startswith(TEST_ROOTS)]
    test_texts = {p: read_text(REPO / p) for p in test_paths}
    # Generated reports describe previous results; counting them would make
    # each rerun change the analysis it is reporting on.
    extra = [
        p
        for p in files
        if p.endswith((".py", ".toml", ".yaml", ".yml", ".md"))
        and not p.startswith("docs/inventory/")
    ]
    all_text = "\n".join(read_text(REPO / p) for p in extra)
    _usage(modules, test_texts, all_text)

    tests = []
    for p, text in test_texts.items():
        tests.append(
            {
                "path": p,
                "tests": len(re.findall(r"^\s*(?:async\s+)?def test_", text, re.M)),
                "markers": sorted(set(re.findall(r"pytest\.mark\.(\w+)", text))),
                "last_commit": dates.get(p, "")[:10],
            }
        )

    by_pkg: dict[str, dict[str, int]] = defaultdict(lambda: {"modules": 0, "loc": 0})
    for m in modules:
        key = ".".join(str(m["module"]).split(".")[:2])
        by_pkg[key]["modules"] += 1
        by_pkg[key]["loc"] += int(m.get("loc", 0))  # type: ignore[call-overload]

    write_json(
        "py_inventory",
        {
            "subpackages": dict(sorted(by_pkg.items())),
            "modules": modules,
            "tests": tests,
            "test_totals": {
                "files": len(tests),
                "functions": sum(t["tests"] for t in tests),
            },
        },
    )


if __name__ == "__main__":
    main()
