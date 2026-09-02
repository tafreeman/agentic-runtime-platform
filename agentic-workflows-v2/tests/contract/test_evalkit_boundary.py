"""ARP-side guard for the one-way agentic-evalkit dependency boundary.

Mirror of agentic-evalkit's own ``tests/contract/test_dependency_boundary.py``,
enforced from the *consumer* side: the installed ``agentic_evalkit`` package
must never import ARP (``agentic_v2``), the shared tools package (``tools``),
or ExecutionKit (``executionkit``). If a future evalkit upgrade — or a
vendored fork — violated that invariant, ARP CI catches it here rather than
the cycle surfacing at runtime.

Skipped when the optional ``eval`` extra is not installed (the default in CI,
which cannot fetch the private evalkit repo), so it costs nothing until
evalkit is actually present in the environment.
"""

from __future__ import annotations

import ast
import importlib.util
import tomllib
from pathlib import Path

import pytest
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version

agentic_evalkit = pytest.importorskip(
    "agentic_evalkit",
    reason="optional 'eval' extra not installed; nothing to check",
)

# Import roots agentic-evalkit must never depend on. "tools" is the import
# root of the agentic-tools companion package.
FORBIDDEN_ROOTS = {"agentic_v2", "tools", "executionkit"}


def _installed_package_dir() -> Path:
    spec = importlib.util.find_spec("agentic_evalkit")
    assert spec is not None and spec.submodule_search_locations is not None
    return Path(next(iter(spec.submodule_search_locations)))


def test_installed_evalkit_does_not_import_arp_tools_or_ek() -> None:
    violations: list[str] = []
    for path in _installed_package_dir().rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            for name in names:
                if name.split(".", 1)[0] in FORBIDDEN_ROOTS:
                    violations.append(f"{path}:{node.lineno}:{name}")
    assert violations == [], (
        "agentic-evalkit imports a forbidden root (the one-way boundary is "
        f"broken): {violations}"
    )


def test_evalkit_is_installed_not_vendored() -> None:
    """Evalkit must be an external dependency, never vendored *inside* the ARP repo
    tree.

    A normal install (site-packages, including the project ``.venv``)
    and an editable install pointing at a separate sibling checkout are both
    legitimate; a copy physically under the ARP source tree is not — that would
    defeat the version pin and the one-way boundary.
    """
    installed = _installed_package_dir().resolve()
    arp_root = Path(__file__).resolve().parents[3]
    in_site_packages = "site-packages" in installed.parts
    under_arp_tree = arp_root in installed.parents
    assert in_site_packages or not under_arp_tree, (
        f"agentic_evalkit resolved at {installed}, which is inside the ARP repo "
        f"tree ({arp_root}) but not via a site-packages install — it looks "
        "vendored. It must be a pinned external dependency or an editable "
        "install of a separate checkout."
    )


def test_evalkit_version_satisfies_the_declared_pin() -> None:
    """The installed evalkit must satisfy the ``eval`` extra's own declared pin.

    Derived from ``pyproject.toml`` rather than hardcoded. This assertion used to
    read ``startswith("0.1.")``; when the pin moved to ``>=0.3.0,<0.4.0`` the
    literal silently became wrong, and nothing caught it because no CI job
    installed the ``eval`` extra. Reading the pin means the two can no longer
    disagree.
    """
    pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
    declared = tomllib.loads(pyproject.read_text(encoding="utf-8"))["project"][
        "optional-dependencies"
    ]["eval"]

    requirements = [
        requirement
        for requirement in (Requirement(entry) for entry in declared)
        if canonicalize_name(requirement.name) == "agentic-evalkit"
    ]
    assert requirements, "the `eval` extra no longer declares agentic-evalkit"

    installed = Version(agentic_evalkit.__version__)
    for requirement in requirements:
        assert installed in requirement.specifier, (
            f"installed agentic-evalkit {installed} does not satisfy the pin "
            f"'{requirement}' declared in {pyproject}"
        )
