"""LangChain / LangGraph integration for AgentBox.

Provides:
- ``AgentBoxSandbox``: BaseSandbox backend for Deep Agents / ``create_deep_agent()``.
- ``AgentBoxToolkit``: A set of LangChain tools for sandbox interaction.
- ``CodeExecutionTool``: Execute Python/shell code in a sandbox.
- ``FileWriteTool`` / ``FileReadTool``: Read/write sandbox files.
- ``AgentBoxBackend``: Deprecated — use ``AgentBoxSandbox`` instead.

Usage::

    from agentbox.langchain import AgentBoxSandbox

    sandbox = AgentBoxSandbox(base_url="http://localhost:8090")
    result = sandbox.execute("echo hello")

    # Or with create_deep_agent:
    from deepagents import create_deep_agent
    agent = create_deep_agent(backend=sandbox, model=model)
"""

from agentbox.langchain.tools import (
    AgentBoxToolkit,
    CodeExecutionTool,
    FileWriteTool,
    FileReadTool,
    ShellExecutionTool,
)
from agentbox.langchain.backend import AgentBoxBackend
from agentbox.langchain.sandbox import AgentBoxSandbox

__all__ = [
    "AgentBoxSandbox",
    "AgentBoxToolkit",
    "AgentBoxBackend",
    "CodeExecutionTool",
    "FileWriteTool",
    "FileReadTool",
    "ShellExecutionTool",
]
