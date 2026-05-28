"""Tier 0 transformation tools - No LLM required."""

from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

import jmespath
import yaml
from jinja2 import Template

from ..base import BaseTool, ToolResult


class JsonTransformTool(BaseTool):
    """Apply JMESPath query to JSON data."""

    @property
    def name(self) -> str:
        return "json_transform"

    @property
    def description(self) -> str:
        return "Apply a JMESPath query to transform JSON data"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "data": {
                "type": "object",
                "description": "JSON data to transform",
                "required": True,
            },
            "query": {
                "type": "string",
                "description": "JMESPath query expression",
                "required": True,
            },
        }

    @property
    def examples(self) -> list[str]:
        return [
            "json_transform(data={'a': [1, 2, 3]}, query='a[0]') → 1",
            "json_transform(data={'users': [{'name': 'Alice'}]}, query='users[0].name') → 'Alice'",
        ]

    async def execute(self, data: dict | list, query: str) -> ToolResult:
        """Execute a JMESPath query.

        Args:
            data: JSON-like object (dict or list) to query.
            query: JMESPath expression string.

        Returns:
            ToolResult with `data` set to the query result on success or
            `error` populated on failure.
        """
        try:
            result = jmespath.search(query, data)
            return ToolResult(success=True, data=result, metadata={"query": query})
        except Exception as e:
            return ToolResult(success=False, error=f"JMESPath query failed: {e!s}")


class TemplateRenderTool(BaseTool):
    """Render a Jinja2 template with variables."""

    @property
    def name(self) -> str:
        return "template_render"

    @property
    def description(self) -> str:
        return "Render a Jinja2 template string with provided variables"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "template": {
                "type": "string",
                "description": "Jinja2 template string",
                "required": True,
            },
            "variables": {
                "type": "object",
                "description": "Variables to render the template with",
                "required": True,
            },
        }

    @property
    def examples(self) -> list[str]:
        return [
            "template_render(template='Hello {{ name }}!', variables={'name': 'World'}) → 'Hello World!'",
        ]

    async def execute(self, template: str, variables: dict[str, Any]) -> ToolResult:
        """Render a Jinja2 template with provided variables.

        Args:
            template: Jinja2 template string.
            variables: Mapping of variable names to values used by the template.

        Returns:
            ToolResult containing the rendered string on success or an error message.
        """
        try:
            tmpl = Template(template)
            rendered = tmpl.render(**variables)
            return ToolResult(
                success=True,
                data=rendered,
                metadata={
                    "template_length": len(template),
                    "output_length": len(rendered),
                },
            )
        except Exception as e:
            return ToolResult(success=False, error=f"Template rendering failed: {e!s}")


class ConfigMergeTool(BaseTool):
    """Deep merge multiple configuration dictionaries."""

    @property
    def name(self) -> str:
        return "config_merge"

    @property
    def description(self) -> str:
        return "Deep merge multiple configuration dictionaries (later configs override earlier ones)"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "configs": {
                "type": "array",
                "description": "List of config dictionaries to merge (in order)",
                "required": True,
            },
        }

    @property
    def examples(self) -> list[str]:
        return [
            "config_merge(configs=[{'a': 1}, {'b': 2}]) → {'a': 1, 'b': 2}",
            "config_merge(configs=[{'a': 1}, {'a': 2}]) → {'a': 2}",
        ]

    def _deep_merge(self, base: dict, override: dict) -> dict:
        """Recursively merge two dictionaries.

        Args:
            base: The base dictionary to copy from.
            override: The dictionary whose values override `base`.

        Returns:
            A new dict with values from `override` taking precedence. Nested
            dicts are merged recursively.
        """
        result = deepcopy(base)
        for key, value in override.items():
            # If both sides are dicts, merge recursively; otherwise override.
            if (
                key in result
                and isinstance(result[key], dict)
                and isinstance(value, dict)
            ):
                result[key] = self._deep_merge(result[key], value)
            else:
                result[key] = deepcopy(value)
        return result

    async def execute(self, configs: list[dict[str, Any]]) -> ToolResult:
        """Merge a list of configuration dictionaries in order.

        Args:
            configs: List of dicts; later entries override earlier ones.

        Returns:
            ToolResult with merged dict on success or an error on failure.
        """
        try:
            if not configs:
                return ToolResult(success=False, error="No configs provided to merge")

            result = {}
            for config in configs:
                result = self._deep_merge(result, config)

            return ToolResult(
                success=True, data=result, metadata={"num_configs": len(configs)}
            )
        except Exception as e:
            return ToolResult(success=False, error=f"Config merge failed: {e!s}")


class YamlLoadTool(BaseTool):
    """Load YAML string to dictionary."""

    @property
    def name(self) -> str:
        return "yaml_load"

    @property
    def description(self) -> str:
        return "Parse a YAML string into a Python dictionary"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "yaml_string": {
                "type": "string",
                "description": "YAML content to parse",
                "required": True,
            },
        }

    async def execute(self, yaml_string: str) -> ToolResult:
        """Parse a YAML string into Python objects.

        Args:
            yaml_string: YAML content as a string.

        Returns:
            ToolResult with the parsed Python object (dict/list) or an error.
        """
        try:
            data = yaml.safe_load(yaml_string)
            return ToolResult(
                success=True, data=data, metadata={"input_length": len(yaml_string)}
            )
        except yaml.YAMLError as e:
            return ToolResult(success=False, error=f"YAML parsing failed: {e!s}")


class YamlDumpTool(BaseTool):
    """Dump dictionary to YAML string."""

    @property
    def name(self) -> str:
        return "yaml_dump"

    @property
    def description(self) -> str:
        return "Convert a Python dictionary to a YAML string"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "data": {
                "type": "object",
                "description": "Data to convert to YAML",
                "required": True,
            },
            "indent": {
                "type": "number",
                "description": "Indentation level (default: 2)",
                "required": False,
                "default": 2,
            },
        }

    async def execute(self, data: Any, indent: int = 2) -> ToolResult:
        """Dump Python data structures to a YAML-formatted string.

        Args:
            data: Python object to serialize (typically dict/list).
            indent: Number of spaces to use for indentation.

        Returns:
            ToolResult containing the YAML string or an error message.
        """
        try:
            yaml_string = yaml.dump(data, indent=indent, default_flow_style=False)
            return ToolResult(
                success=True,
                data=yaml_string,
                metadata={"output_length": len(yaml_string)},
            )
        except Exception as e:
            return ToolResult(success=False, error=f"YAML dumping failed: {e!s}")


class JsonLoadTool(BaseTool):
    """Parse JSON string to Python object."""

    @property
    def name(self) -> str:
        return "json_load"

    @property
    def description(self) -> str:
        return "Parse a JSON string into a Python object"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "json_string": {
                "type": "string",
                "description": "JSON content to parse",
                "required": True,
            },
        }

    async def execute(self, json_string: str) -> ToolResult:
        """Parse a JSON string into a Python object.

        Args:
            json_string: JSON content as a string.

        Returns:
            ToolResult containing parsed Python object or an error message.
        """
        try:
            data = json.loads(json_string)
            return ToolResult(
                success=True, data=data, metadata={"input_length": len(json_string)}
            )
        except json.JSONDecodeError as e:
            return ToolResult(success=False, error=f"JSON parsing failed: {e!s}")


class JsonDumpTool(BaseTool):
    """Convert Python object to JSON string."""

    @property
    def name(self) -> str:
        return "json_dump"

    @property
    def description(self) -> str:
        return "Convert a Python object to a JSON string"

    @property
    def parameters(self) -> dict[str, Any]:
        return {
            "data": {
                "type": "object",
                "description": "Data to convert to JSON",
                "required": True,
            },
            "indent": {
                "type": "number",
                "description": "Indentation level (default: 2, None for compact)",
                "required": False,
                "default": 2,
            },
        }

    async def execute(self, data: Any, indent: int | None = 2) -> ToolResult:
        """Serialize a Python object to JSON string.

        Args:
            data: Python object to serialize (dict/list/etc.).
            indent: Number of spaces for pretty-printing (None for compact).

        Returns:
            ToolResult with JSON string on success or an error message.
        """
        try:
            json_string = json.dumps(data, indent=indent)
            return ToolResult(
                success=True,
                data=json_string,
                metadata={"output_length": len(json_string)},
            )
        except Exception as e:
            return ToolResult(success=False, error=f"JSON dumping failed: {e!s}")
