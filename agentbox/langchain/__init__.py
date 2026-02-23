"""LangChain / LangGraph integration for AgentBox.

Provides:
- ``AgentBoxToolkit``: A set of LangChain tools for sandbox interaction.
- ``CodeExecutionTool``: Execute Python/shell code in a sandbox.
- ``FileWriteTool`` / ``FileReadTool``: Read/write sandbox files.
- ``AgentBoxBackend``: BackendProtocol for Deep Agents.

Usage::

    from agentbox.langchain import AgentBoxToolkit

    toolkit = AgentBoxToolkit(base_url="http://localhost:8090")
    tools = toolkit.get_tools()  # list of LangChain tools
"""

from agentbox.langchain.tools import (
    AgentBoxToolkit,
    CodeExecutionTool,
    FileWriteTool,
    FileReadTool,
    ShellExecutionTool,
)
from agentbox.langchain.backend import AgentBoxBackend

__all__ = [
    "AgentBoxToolkit",
    "AgentBoxBackend",
    "CodeExecutionTool",
    "FileWriteTool",
    "FileReadTool",
    "ShellExecutionTool",
]
