"""LangChain-native agentic workflow engine.

Standard LangChain/LangGraph implementation powered by YAML workflow
definitions.  This replaces the bespoke DAG/BaseAgent engine with
idiomatic LangChain patterns:

- ``@tool`` decorated functions for tool definitions
- ``ChatModel`` + ``bind_tools`` for agent LLM calls
- ``StateGraph`` for multi-step workflow orchestration
- ``MemorySaver`` / ``SqliteSaver`` for checkpointing

Quick start::

    from agentic_v2.langchain import WorkflowRunner

    runner = WorkflowRunner()
    result = await runner.run("code_review", code_file="main.py")
"""

from __future__ import annotations

from .config import WorkflowConfig, list_workflows, load_workflow_config

__all__ = [
    "WorkflowConfig",
    "WorkflowRunner",
    "compile_workflow",
    "get_chat_model",
    "get_model_for_tier",
    "list_workflows",
    "load_workflow_config",
]


def __getattr__(name: str):
    if name == "compile_workflow":
        from .graph import compile_workflow

        return compile_workflow
    if name == "get_chat_model":
        from .models import get_chat_model

        return get_chat_model
    if name == "get_model_for_tier":
        from .models import get_model_for_tier

        return get_model_for_tier
    if name == "WorkflowRunner":
        from .runner import WorkflowRunner

        return WorkflowRunner
    raise AttributeError(name)
