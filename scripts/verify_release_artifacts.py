"""Validate the release manifest and smoke-test built wheels in isolation.

The smoke environment installs only the three release wheels and their declared
dependencies. Imports run with ``python -I`` from a temporary directory so the
repository checkout cannot mask missing package files or optional-dependency
leaks.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import tomllib
import venv
import zipfile
from email.parser import Parser
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = REPO_ROOT / "release-manifest.toml"


def _load_toml(path: Path) -> dict[str, Any]:
    with path.open("rb") as handle:
        return tomllib.load(handle)


def _wheel_metadata(path: Path) -> tuple[str, str]:
    with zipfile.ZipFile(path) as archive:
        metadata_names = [
            name for name in archive.namelist() if name.endswith(".dist-info/METADATA")
        ]
        if len(metadata_names) != 1:
            raise ValueError(
                f"{path} contains {len(metadata_names)} METADATA files; expected one"
            )
        raw = archive.read(metadata_names[0]).decode("utf-8")
    metadata = Parser().parsestr(raw)
    return metadata["Name"], metadata["Version"]


def _validate_manifest(manifest_path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    manifest = _load_toml(manifest_path)
    release = manifest.get("release", {})
    components = manifest.get("components", [])
    if manifest.get("schema_version") != 1:
        raise ValueError("release manifest schema_version must be 1")
    bundle_version = release.get("bundle_version")
    if not bundle_version or release.get("tag") != f"v{bundle_version}":
        raise ValueError("release tag must equal 'v' plus bundle_version")
    if release.get("channel") != "github-prerelease":
        raise ValueError("Phase 1 release channel must be github-prerelease")
    if not isinstance(components, list) or not components:
        raise ValueError("release manifest must declare at least one component")

    root = manifest_path.parent
    seen: set[str] = set()
    for component in components:
        distribution = component.get("distribution")
        if not distribution or distribution in seen:
            raise ValueError(f"invalid or duplicate distribution: {distribution!r}")
        seen.add(distribution)
        project_dir = (root / component["path"]).resolve()
        pyproject = _load_toml(project_dir / "pyproject.toml")["project"]
        expected = (distribution, component.get("version"))
        actual = (pyproject.get("name"), pyproject.get("version"))
        if actual != expected:
            raise ValueError(
                f"manifest mismatch for {project_dir}: expected {expected}, got {actual}"
            )
    return release, components


def _find_wheels(root: Path, components: list[dict[str, Any]]) -> list[Path]:
    selected: list[Path] = []
    for component in components:
        matches: list[Path] = []
        for candidate in root.glob(component["wheel_glob"]):
            name, version = _wheel_metadata(candidate)
            if (name, version) == (
                component["distribution"],
                component["version"],
            ):
                matches.append(candidate.resolve())
        if len(matches) != 1:
            raise ValueError(
                f"expected one wheel for {component['distribution']} "
                f"{component['version']}, found {matches}"
            )
        selected.append(matches[0])
    return selected


def _venv_executable(env_dir: Path, name: str) -> Path:
    scripts_dir = env_dir / ("Scripts" if os.name == "nt" else "bin")
    suffix = ".exe" if os.name == "nt" else ""
    return scripts_dir / f"{name}{suffix}"


def _run(
    command: list[str],
    *,
    cwd: Path,
    capture_output: bool = True,
) -> subprocess.CompletedProcess[str]:
    print("+", subprocess.list2cmdline(command))
    return subprocess.run(
        command,
        cwd=cwd,
        check=True,
        text=True,
        capture_output=capture_output,
    )


def verify_release(manifest_path: Path, *, expected_tag: str | None = None) -> None:
    release, components = _validate_manifest(manifest_path)
    if expected_tag is not None and release["tag"] != expected_tag:
        raise ValueError(
            f"workflow tag {expected_tag!r} does not match manifest tag "
            f"{release['tag']!r}"
        )
    wheels = _find_wheels(manifest_path.parent, components)

    with tempfile.TemporaryDirectory(prefix="arp-release-smoke-") as raw_temp:
        temp_dir = Path(raw_temp)
        env_dir = temp_dir / "venv"
        venv.EnvBuilder(with_pip=True, clear=True).create(env_dir)
        python = _venv_executable(env_dir, "python")
        _run(
            [
                str(python),
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                *[str(wheel) for wheel in wheels],
            ],
            cwd=temp_dir,
            capture_output=False,
        )

        expectations = {
            component["distribution"]: {
                "version": component["version"],
                "import_name": component["import_name"],
            }
            for component in components
        }
        smoke_code = """
import importlib
import importlib.metadata
import json
import sys

expectations = json.loads(sys.argv[1])
for distribution, expected in expectations.items():
    actual = importlib.metadata.version(distribution)
    if actual != expected["version"]:
        raise SystemExit(f"{distribution}: expected {expected['version']}, got {actual}")
    module = importlib.import_module(expected["import_name"])
    print(f"{distribution}=={actual} imported from {module.__file__}")
"""
        result = _run(
            [str(python), "-I", "-c", smoke_code, json.dumps(expectations)],
            cwd=temp_dir,
        )
        print(result.stdout, end="")

        for component in components:
            smoke_command = component.get("smoke_command")
            if not smoke_command:
                continue
            executable = _venv_executable(env_dir, smoke_command[0])
            result = _run(
                [str(executable), *smoke_command[1:]],
                cwd=temp_dir,
            )
            output = result.stdout + result.stderr
            if component["version"] not in output:
                raise ValueError(
                    f"{smoke_command[0]} output did not include "
                    f"{component['version']}: {output!r}"
                )
            print(output, end="")

    print(
        f"Release bundle {release['tag']} passed isolated wheel and CLI smoke checks."
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_MANIFEST,
        help="release manifest path",
    )
    parser.add_argument(
        "--expected-tag",
        help="fail unless the manifest declares this workflow/release tag",
    )
    args = parser.parse_args()
    try:
        verify_release(args.manifest.resolve(), expected_tag=args.expected_tag)
    except subprocess.CalledProcessError as exc:
        if exc.stdout:
            print(exc.stdout, file=sys.stderr, end="")
        if exc.stderr:
            print(exc.stderr, file=sys.stderr, end="")
        print(
            f"release verification command failed with exit code {exc.returncode}",
            file=sys.stderr,
        )
        return 1
    except (OSError, KeyError, ValueError, zipfile.BadZipFile) as exc:
        print(f"release verification failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
