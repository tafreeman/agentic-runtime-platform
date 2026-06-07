"""Validate all workflow YAML definitions against the JSON schema.

Loads ``agentic-workflows-v2/schemas/workflow.schema.json`` and validates
every ``*.yaml`` file in ``agentic-workflows-v2/agentic_v2/workflows/definitions/``.

Exit 0 if all files are valid, exit 1 with per-file errors listed.

Usage:
    python scripts/validate-workflows.py
    python scripts/validate-workflows.py --schema path/to/schema.json --definitions path/to/dir/
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

import yaml

try:
    import jsonschema
    from jsonschema import Draft202012Validator, ValidationError
    from jsonschema.exceptions import SchemaError

    _JSONSCHEMA_AVAILABLE = True
except ImportError:
    _JSONSCHEMA_AVAILABLE = False


# ---------------------------------------------------------------------------
# Defaults (relative to repo root)
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SCHEMA_PATH = (
    REPO_ROOT / "agentic-workflows-v2" / "schemas" / "workflow.schema.json"
)
DEFAULT_DEFINITIONS_DIR = (
    REPO_ROOT
    / "agentic-workflows-v2"
    / "agentic_v2"
    / "workflows"
    / "definitions"
)


# ---------------------------------------------------------------------------
# Manual structural validator (fallback when jsonschema is unavailable)
# ---------------------------------------------------------------------------

REQUIRED_TOP_LEVEL = {"name", "description", "steps"}
REQUIRED_STEP_FIELDS = {"name", "agent", "description", "inputs", "outputs"}


def _manual_validate(data: Any, yaml_path: Path) -> list[str]:
    """Perform lightweight structural validation without jsonschema.

    Args:
        data: Parsed YAML document (should be a dict).
        yaml_path: Path of the file being validated (used in error messages).

    Returns:
        List of human-readable error strings. Empty list means valid.
    """
    errors: list[str] = []

    if not isinstance(data, dict):
        return [f"{yaml_path.name}: top-level value must be a mapping, got {type(data).__name__}"]

    for field in sorted(REQUIRED_TOP_LEVEL):
        if field not in data:
            errors.append(f"{yaml_path.name}: missing required top-level field '{field}'")

    steps = data.get("steps")
    if steps is None:
        # Already reported above as missing; nothing more to check.
        return errors

    if not isinstance(steps, list):
        errors.append(f"{yaml_path.name}: 'steps' must be a list, got {type(steps).__name__}")
        return errors

    if len(steps) == 0:
        errors.append(f"{yaml_path.name}: 'steps' must contain at least one step")

    for idx, step in enumerate(steps):
        prefix = f"{yaml_path.name}: step[{idx}]"
        if not isinstance(step, dict):
            errors.append(f"{prefix}: each step must be a mapping, got {type(step).__name__}")
            continue

        step_name = step.get("name", f"<index {idx}>")
        for field in sorted(REQUIRED_STEP_FIELDS):
            if field not in step:
                errors.append(
                    f"{prefix} ('{step_name}'): missing required field '{field}'"
                )

    return errors


# ---------------------------------------------------------------------------
# jsonschema-backed validator
# ---------------------------------------------------------------------------


def _jsonschema_validate(
    data: Any,
    schema: dict[str, Any],
    yaml_path: Path,
) -> list[str]:
    """Validate *data* against *schema* using jsonschema Draft 2020-12.

    Args:
        data: Parsed YAML document.
        schema: Parsed JSON schema dict.
        yaml_path: Path of the file being validated (used in error messages).

    Returns:
        List of human-readable error strings. Empty list means valid.
    """
    try:
        validator = Draft202012Validator(schema)
        raw_errors = sorted(
            validator.iter_errors(data),
            key=lambda e: list(e.absolute_path),
        )
    except SchemaError as exc:
        return [f"SCHEMA ERROR — the schema itself is invalid: {exc.message}"]

    errors: list[str] = []
    for err in raw_errors:
        path = " -> ".join(str(p) for p in err.absolute_path) or "(root)"
        errors.append(f"{yaml_path.name}: [{path}] {err.message}")
    return errors


# ---------------------------------------------------------------------------
# File loading helpers
# ---------------------------------------------------------------------------


def load_schema(schema_path: Path) -> dict[str, Any]:
    """Load and parse a JSON schema file.

    Args:
        schema_path: Absolute path to the JSON schema file.

    Returns:
        Parsed schema as a dict.
    """
    raw = schema_path.read_text(encoding="utf-8")
    return json.loads(raw)  # type: ignore[return-value]


def load_yaml(yaml_path: Path) -> Any:
    """Load and parse a YAML workflow definition file.

    Args:
        yaml_path: Absolute path to the YAML file.

    Returns:
        Parsed YAML content (typically a dict).
    """
    raw = yaml_path.read_text(encoding="utf-8")
    return yaml.safe_load(raw)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments.

    Returns:
        Parsed namespace with ``schema`` and ``definitions`` Path attributes.
    """
    parser = argparse.ArgumentParser(
        description=(
            "Validate all workflow YAML files against the workflow JSON schema."
        )
    )
    parser.add_argument(
        "--schema",
        type=Path,
        default=DEFAULT_SCHEMA_PATH,
        help=f"Path to workflow.schema.json (default: {DEFAULT_SCHEMA_PATH})",
    )
    parser.add_argument(
        "--definitions",
        type=Path,
        default=DEFAULT_DEFINITIONS_DIR,
        help=f"Directory containing workflow YAML files (default: {DEFAULT_DEFINITIONS_DIR})",
    )
    return parser.parse_args()


def _validate_one_file(yaml_path: Path, schema: dict) -> list[str]:
    """Validate a single workflow YAML file and return its error list."""
    try:
        data = load_yaml(yaml_path)
    except yaml.YAMLError as exc:
        print(f"  FAIL  {yaml_path.name} (YAML parse error)")
        return [f"{yaml_path.name}: YAML parse error — {exc}"]

    if _JSONSCHEMA_AVAILABLE:
        errors = _jsonschema_validate(data, schema, yaml_path)
    else:
        errors = _manual_validate(data, yaml_path)

    if errors:
        print(f"  FAIL  {yaml_path.name}")
    else:
        print(f"  OK    {yaml_path.name}")
    return errors


def _validate_all_files(
    yaml_files: list[Path], schema: dict
) -> dict[str, list[str]]:
    """Validate each YAML file, returning a ``{filename: errors}`` mapping."""
    all_errors: dict[str, list[str]] = {}
    for yaml_path in yaml_files:
        errors = _validate_one_file(yaml_path, schema)
        if errors:
            all_errors[yaml_path.name] = errors
    return all_errors


def _print_error_report(all_errors: dict[str, list[str]]) -> None:
    """Print all validation errors grouped by file to stderr."""
    total_errors = sum(len(v) for v in all_errors.values())
    print(
        f"VALIDATION FAILED — {total_errors} error(s) across "
        f"{len(all_errors)} file(s):\n",
        file=sys.stderr,
    )
    for filename, errors in all_errors.items():
        print(f"  {filename}:", file=sys.stderr)
        for err in errors:
            print(f"    - {err}", file=sys.stderr)
        print(file=sys.stderr)


def main() -> int:
    """Run the workflow YAML validation.

    Returns:
        0 if all files pass validation, 1 if any fail, 2 on configuration
        errors.
    """
    args = parse_args()

    schema_path: Path = args.schema.resolve()
    definitions_dir: Path = args.definitions.resolve()

    # Validate CLI inputs.
    if not schema_path.is_file():
        print(
            f"ERROR: schema file not found: {schema_path}",
            file=sys.stderr,
        )
        return 2

    if not definitions_dir.is_dir():
        print(
            f"ERROR: definitions directory not found: {definitions_dir}",
            file=sys.stderr,
        )
        return 2

    yaml_files = sorted(definitions_dir.glob("*.yaml"))
    if not yaml_files:
        print(
            f"WARNING: no *.yaml files found in {definitions_dir}",
            file=sys.stderr,
        )
        return 0

    # Load schema once.
    try:
        schema = load_schema(schema_path)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"ERROR: failed to load schema: {exc}", file=sys.stderr)
        return 2

    if _JSONSCHEMA_AVAILABLE:
        print("Validator: jsonschema (Draft 2020-12)")
    else:
        print(
            "Validator: built-in structural check "
            "(install jsonschema for full JSON Schema validation)"
        )

    print(f"Schema:    {schema_path}")
    print(f"Directory: {definitions_dir}")
    print(f"Files:     {len(yaml_files)} workflow(s) found\n")

    all_errors = _validate_all_files(yaml_files, schema)

    print()

    if not all_errors:
        print(f"All {len(yaml_files)} workflow(s) passed schema validation.")
        return 0

    _print_error_report(all_errors)
    return 1


if __name__ == "__main__":
    sys.exit(main())
