"""Tests for Tier 0 tools (no LLM required)."""

from __future__ import annotations

import pytest

from agentic_v2.settings import get_settings
from agentic_v2.tools.builtin.file_ops import (
    DirectoryCreateTool,
    FileCopyTool,
    FileDeleteTool,
    FileMoveTool,
    FileReadTool,
    FileWriteTool,
)
from agentic_v2.tools.builtin.transform import (
    ConfigMergeTool,
    JsonDumpTool,
    JsonLoadTool,
    JsonTransformTool,
    TemplateRenderTool,
    YamlDumpTool,
    YamlLoadTool,
)


@pytest.fixture(autouse=True)
def _scoped_file_base_dir(request, tmp_path, monkeypatch):
    """File tools now fail-closed when AGENTIC_FILE_BASE_DIR is unset (S1-02).

    Scoped to file-tool test classes only — transform/yaml/json tests
    don't need the env var. ``_validate_path`` reads
    ``get_settings().agentic_file_base_dir`` at call time (C-14), so we set
    the env var and clear the ``get_settings`` lru_cache; the next validation
    picks up the scoped sandbox root with no module reload.
    """
    file_tool_classes = {
        "TestFileCopyTool",
        "TestFileWriteReadTools",
        "TestDirectoryCreateTool",
        "TestFileMoveTool",
        "TestFileDeleteTool",
    }
    owner = request.cls.__name__ if request.cls else ""
    if owner not in file_tool_classes:
        return
    monkeypatch.setenv("AGENTIC_FILE_BASE_DIR", str(tmp_path))
    get_settings.cache_clear()


class TestFileCopyTool:
    """Tests for FileCopyTool."""

    @pytest.mark.asyncio
    async def test_copy_file_success(self, tmp_path):
        """Test successful file copy."""
        source = tmp_path / "source.txt"
        dest = tmp_path / "dest.txt"
        source.write_text("test content")

        tool = FileCopyTool()
        result = await tool(source=str(source), destination=str(dest))

        assert result.success
        assert dest.exists()
        assert dest.read_text() == "test content"

    @pytest.mark.asyncio
    async def test_copy_file_nonexistent_source(self, tmp_path):
        """Test copy with nonexistent source."""
        source = tmp_path / "nonexistent.txt"
        dest = tmp_path / "dest.txt"

        tool = FileCopyTool()
        result = await tool(source=str(source), destination=str(dest))

        assert not result.success
        assert "does not exist" in result.error

    @pytest.mark.asyncio
    async def test_copy_file_existing_dest_no_overwrite(self, tmp_path):
        """Test copy when destination exists and overwrite=False."""
        source = tmp_path / "source.txt"
        dest = tmp_path / "dest.txt"
        source.write_text("source content")
        dest.write_text("dest content")

        tool = FileCopyTool()
        result = await tool(source=str(source), destination=str(dest), overwrite=False)

        assert not result.success
        assert "already exists" in result.error
        assert dest.read_text() == "dest content"  # Unchanged

    @pytest.mark.asyncio
    async def test_copy_file_with_overwrite(self, tmp_path):
        """Test copy with overwrite=True."""
        source = tmp_path / "source.txt"
        dest = tmp_path / "dest.txt"
        source.write_text("new content")
        dest.write_text("old content")

        tool = FileCopyTool()
        result = await tool(source=str(source), destination=str(dest), overwrite=True)

        assert result.success
        assert dest.read_text() == "new content"


class TestFileWriteReadTools:
    """Tests for FileWriteTool and FileReadTool."""

    @pytest.mark.asyncio
    async def test_write_and_read(self, tmp_path):
        """Test writing and reading a file."""
        file_path = tmp_path / "test.txt"
        content = "Hello, World!"

        # Write
        write_tool = FileWriteTool()
        write_result = await write_tool(path=str(file_path), content=content)
        assert write_result.success

        # Read
        read_tool = FileReadTool()
        read_result = await read_tool(path=str(file_path))
        assert read_result.success
        assert read_result.data["content"] == content

    @pytest.mark.asyncio
    async def test_read_nonexistent_file(self, tmp_path):
        """Test reading nonexistent file."""
        file_path = tmp_path / "nonexistent.txt"

        tool = FileReadTool()
        result = await tool(path=str(file_path))

        assert not result.success
        assert "does not exist" in result.error


class TestDirectoryCreateTool:
    """Tests for DirectoryCreateTool."""

    @pytest.mark.asyncio
    async def test_create_directory(self, tmp_path):
        """Test creating a directory."""
        dir_path = tmp_path / "subdir" / "nested"

        tool = DirectoryCreateTool()
        result = await tool(path=str(dir_path))

        assert result.success
        assert dir_path.exists()
        assert dir_path.is_dir()

    @pytest.mark.asyncio
    async def test_create_existing_directory(self, tmp_path):
        """Test creating existing directory with exist_ok=True."""
        dir_path = tmp_path / "existing"
        dir_path.mkdir()

        tool = DirectoryCreateTool()
        result = await tool(path=str(dir_path), exist_ok=True)

        assert result.success


class TestJsonTransformTool:
    """Tests for JsonTransformTool."""

    @pytest.mark.asyncio
    async def test_simple_query(self):
        """Test simple JMESPath query."""
        data = {"name": "Alice", "age": 30}

        tool = JsonTransformTool()
        result = await tool(data=data, query="name")

        assert result.success
        assert result.data == "Alice"

    @pytest.mark.asyncio
    async def test_array_query(self):
        """Test JMESPath query on array."""
        data = {"users": [{"name": "Alice"}, {"name": "Bob"}]}

        tool = JsonTransformTool()
        result = await tool(data=data, query="users[0].name")

        assert result.success
        assert result.data == "Alice"

    @pytest.mark.asyncio
    async def test_projection_query(self):
        """Test JMESPath projection."""
        data = {"users": [{"name": "Alice", "age": 30}, {"name": "Bob", "age": 25}]}

        tool = JsonTransformTool()
        result = await tool(data=data, query="users[*].name")

        assert result.success
        assert result.data == ["Alice", "Bob"]


class TestTemplateRenderTool:
    """Tests for TemplateRenderTool."""

    @pytest.mark.asyncio
    async def test_simple_template(self):
        """Test simple template rendering."""
        template = "Hello, {{ name }}!"
        variables = {"name": "World"}

        tool = TemplateRenderTool()
        result = await tool(template=template, variables=variables)

        assert result.success
        assert result.data == "Hello, World!"

    @pytest.mark.asyncio
    async def test_complex_template(self):
        """Test template with loops and conditions."""
        template = """
        {% for item in items %}
        - {{ item }}
        {% endfor %}
        """
        variables = {"items": ["apple", "banana", "cherry"]}

        tool = TemplateRenderTool()
        result = await tool(template=template, variables=variables)

        assert result.success
        assert "apple" in result.data
        assert "banana" in result.data


class TestConfigMergeTool:
    """Tests for ConfigMergeTool."""

    @pytest.mark.asyncio
    async def test_simple_merge(self):
        """Test merging two configs."""
        configs = [{"a": 1, "b": 2}, {"b": 3, "c": 4}]

        tool = ConfigMergeTool()
        result = await tool(configs=configs)

        assert result.success
        assert result.data == {"a": 1, "b": 3, "c": 4}

    @pytest.mark.asyncio
    async def test_deep_merge(self):
        """Test deep merging nested dicts."""
        configs = [{"a": {"x": 1, "y": 2}}, {"a": {"y": 3, "z": 4}}]

        tool = ConfigMergeTool()
        result = await tool(configs=configs)

        assert result.success
        assert result.data == {"a": {"x": 1, "y": 3, "z": 4}}

    @pytest.mark.asyncio
    async def test_empty_configs(self):
        """Test with empty config list."""
        tool = ConfigMergeTool()
        result = await tool(configs=[])

        assert not result.success
        assert "No configs" in result.error


class TestYamlTools:
    """Tests for YAML load/dump tools."""

    @pytest.mark.asyncio
    async def test_yaml_round_trip(self):
        """Test loading and dumping YAML."""
        data = {"name": "Alice", "age": 30, "hobbies": ["reading", "coding"]}

        # Dump
        dump_tool = YamlDumpTool()
        dump_result = await dump_tool(data=data)
        assert dump_result.success

        # Load
        load_tool = YamlLoadTool()
        load_result = await load_tool(yaml_string=dump_result.data)
        assert load_result.success
        assert load_result.data == data


class TestJsonTools:
    """Tests for JSON load/dump tools."""

    @pytest.mark.asyncio
    async def test_json_round_trip(self):
        """Test loading and dumping JSON."""
        data = {"name": "Alice", "age": 30, "active": True}

        # Dump
        dump_tool = JsonDumpTool()
        dump_result = await dump_tool(data=data)
        assert dump_result.success

        # Load
        load_tool = JsonLoadTool()
        load_result = await load_tool(json_string=dump_result.data)
        assert load_result.success
        assert load_result.data == data

    @pytest.mark.asyncio
    async def test_json_invalid_input(self):
        """Test JSON loading with invalid input."""
        load_tool = JsonLoadTool()
        result = await load_tool(json_string="not valid json {")

        assert not result.success
        assert "JSON parsing failed" in result.error


class TestFileMoveTool:
    """Tests for FileMoveTool."""

    @pytest.mark.asyncio
    async def test_move_file_success(self, tmp_path):
        """Move a file from source to destination."""
        source = tmp_path / "source.txt"
        dest = tmp_path / "dest.txt"
        source.write_text("move me")

        tool = FileMoveTool()
        result = await tool(source=str(source), destination=str(dest))

        assert result.success
        assert not source.exists()
        assert dest.exists()
        assert dest.read_text() == "move me"

    @pytest.mark.asyncio
    async def test_move_nonexistent_source(self, tmp_path):
        """Source doesn't exist returns error."""
        source = tmp_path / "nonexistent.txt"
        dest = tmp_path / "dest.txt"

        tool = FileMoveTool()
        result = await tool(source=str(source), destination=str(dest))

        assert not result.success
        assert "does not exist" in result.error

    @pytest.mark.asyncio
    async def test_move_existing_dest_no_overwrite(self, tmp_path):
        """Destination exists, overwrite=False returns error."""
        source = tmp_path / "source.txt"
        dest = tmp_path / "dest.txt"
        source.write_text("source content")
        dest.write_text("dest content")

        tool = FileMoveTool()
        result = await tool(source=str(source), destination=str(dest), overwrite=False)

        assert not result.success
        assert "already exists" in result.error
        assert dest.read_text() == "dest content"  # Unchanged

    @pytest.mark.asyncio
    async def test_move_with_overwrite(self, tmp_path):
        """Overwrite=True replaces destination."""
        source = tmp_path / "source.txt"
        dest = tmp_path / "dest.txt"
        source.write_text("new content")
        dest.write_text("old content")

        tool = FileMoveTool()
        result = await tool(source=str(source), destination=str(dest), overwrite=True)

        assert result.success
        assert not source.exists()
        assert dest.read_text() == "new content"

    @pytest.mark.asyncio
    async def test_move_creates_parent_dirs(self, tmp_path):
        """Parent directories are created if needed."""
        source = tmp_path / "source.txt"
        dest = tmp_path / "sub" / "dir" / "dest.txt"
        source.write_text("nested")

        tool = FileMoveTool()
        result = await tool(source=str(source), destination=str(dest))

        assert result.success
        assert dest.exists()
        assert dest.read_text() == "nested"


class TestFileDeleteTool:
    """Tests for FileDeleteTool."""

    @pytest.mark.asyncio
    async def test_delete_existing_file(self, tmp_path):
        """Delete an existing file."""
        target = tmp_path / "to_delete.txt"
        target.write_text("delete me")

        tool = FileDeleteTool()
        result = await tool(path=str(target))

        assert result.success
        assert result.data["deleted"] is True
        assert not target.exists()

    @pytest.mark.asyncio
    async def test_delete_nonexistent_file(self, tmp_path):
        """missing_ok=False returns error for missing file."""
        target = tmp_path / "nonexistent.txt"

        tool = FileDeleteTool()
        result = await tool(path=str(target), missing_ok=False)

        assert not result.success
        assert "does not exist" in result.error

    @pytest.mark.asyncio
    async def test_delete_nonexistent_file_missing_ok(self, tmp_path):
        """missing_ok=True returns success for missing file."""
        target = tmp_path / "nonexistent.txt"

        tool = FileDeleteTool()
        result = await tool(path=str(target), missing_ok=True)

        assert result.success
        assert result.data["deleted"] is False
