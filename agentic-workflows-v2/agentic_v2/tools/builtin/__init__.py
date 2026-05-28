"""Built-in tools for Tier 0-2 operations."""

from __future__ import annotations

from .build_ops import BuildAppTool
from .code_analysis import AstDumpTool, CodeAnalysisTool
from .code_execution import CodeExecutionTool

# Import all tool classes
from .context_ops import ContextTrimTool, TokenEstimateTool
from .file_ops import (
    DirectoryCreateTool,
    FileCopyTool,
    FileDeleteTool,
    FileMoveTool,
    FileReadTool,
    FileWriteTool,
)
from .git_ops import GitDiffTool, GitStatusTool, GitTool
from .http_ops import HttpGetTool, HttpPostTool, HttpTool
from .memory_ops import (
    MemoryClearTool,
    MemoryDeleteTool,
    MemoryGetTool,
    MemoryListTool,
    MemorySearchTool,
    MemoryUpsertTool,
)
from .search_ops import GrepTool, SearchTool
from .shell_ops import ShellExecTool, ShellTool
from .transform import (
    ConfigMergeTool,
    JsonDumpTool,
    JsonLoadTool,
    JsonTransformTool,
    TemplateRenderTool,
    YamlDumpTool,
    YamlLoadTool,
)

__all__ = [
    # Context utilities
    "TokenEstimateTool",
    "ContextTrimTool",
    # File operations
    "FileCopyTool",
    "FileDeleteTool",
    "FileMoveTool",
    "FileReadTool",
    "FileWriteTool",
    "DirectoryCreateTool",
    # Persistent memory
    "MemoryUpsertTool",
    "MemoryGetTool",
    "MemoryListTool",
    "MemorySearchTool",
    "MemoryDeleteTool",
    "MemoryClearTool",
    # Git operations
    "GitTool",
    "GitStatusTool",
    "GitDiffTool",
    # HTTP operations
    "HttpTool",
    "HttpGetTool",
    "HttpPostTool",
    # Shell operations
    "ShellTool",
    "ShellExecTool",
    # Code analysis
    "CodeAnalysisTool",
    "AstDumpTool",
    # Code execution
    "CodeExecutionTool",
    # Build verification
    "BuildAppTool",
    # Search operations
    "SearchTool",
    "GrepTool",
    # Transform operations
    "JsonTransformTool",
    "JsonLoadTool",
    "JsonDumpTool",
    "YamlLoadTool",
    "YamlDumpTool",
    "TemplateRenderTool",
    "ConfigMergeTool",
]
