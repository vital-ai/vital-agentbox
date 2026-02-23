"""LangChain tools for AgentBox sandbox interaction.

Each tool wraps the AgentBoxClient SDK and can be used standalone or
as part of an ``AgentBoxToolkit`` for LangGraph agents.

Requirements::

    pip install vital-agentbox[client] langchain-core

Usage with LangGraph::

    from agentbox.langchain import AgentBoxToolkit

    toolkit = AgentBoxToolkit(base_url="http://localhost:8090")
    tools = toolkit.get_tools()
    # Pass `tools` to your LangGraph agent or ReAct loop.
"""

from __future__ import annotations

import asyncio
from typing import Any, Optional, Type

from langchain_core.tools import BaseTool
from langchain_core.callbacks import CallbackManagerForToolRun, AsyncCallbackManagerForToolRun
from pydantic import BaseModel, Field

from agentbox.client import AgentBoxClient, Sandbox


# ---------------------------------------------------------------------------
# Input schemas
# ---------------------------------------------------------------------------

class CodeExecutionInput(BaseModel):
    code: str = Field(description="Python code to execute in the sandbox.")
    language: str = Field(default="python", description="Language: 'python' or 'shell'.")


class ShellExecutionInput(BaseModel):
    command: str = Field(description="Shell command to execute in the sandbox.")


class FileWriteInput(BaseModel):
    path: str = Field(description="Absolute path in the sandbox filesystem.")
    content: str = Field(description="File content to write.")


class FileReadInput(BaseModel):
    path: str = Field(description="Absolute path of the file to read.")


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

class CodeExecutionTool(BaseTool):
    """Execute Python or shell code in an AgentBox sandbox.

    The tool maintains a persistent sandbox across invocations, so state
    (variables, files) is preserved between calls.
    """

    name: str = "execute_code"
    description: str = (
        "Execute Python or shell code in a secure sandbox. "
        "The sandbox persists between calls — variables, files, and installed "
        "packages are retained. Use language='python' for Python code or "
        "language='shell' for shell commands. Returns stdout, stderr, and exit_code."
    )
    args_schema: Type[BaseModel] = CodeExecutionInput

    client: AgentBoxClient
    sandbox: Optional[Sandbox] = None

    model_config = {"arbitrary_types_allowed": True}

    async def _ensure_sandbox(self) -> Sandbox:
        if self.sandbox is None or self.sandbox.state == "destroyed":
            self.sandbox = await self.client.create_sandbox()
        return self.sandbox

    def _run(self, code: str, language: str = "python",
             run_manager: Optional[CallbackManagerForToolRun] = None) -> str:
        return asyncio.run(self._arun(code, language=language))

    async def _arun(self, code: str, language: str = "python",
                    run_manager: Optional[AsyncCallbackManagerForToolRun] = None) -> str:
        sandbox = await self._ensure_sandbox()
        result = await sandbox.execute(code, language=language)
        parts = []
        if result.stdout:
            parts.append(result.stdout)
        if result.stderr:
            parts.append(f"[stderr] {result.stderr}")
        if result.exit_code != 0:
            parts.append(f"[exit_code={result.exit_code}]")
        return "\n".join(parts) if parts else "(no output)"


class ShellExecutionTool(BaseTool):
    """Execute shell commands in an AgentBox sandbox."""

    name: str = "execute_shell"
    description: str = (
        "Execute a shell command in the sandbox. "
        "Useful for file operations, installing packages, running scripts. "
        "Returns stdout, stderr, and exit_code."
    )
    args_schema: Type[BaseModel] = ShellExecutionInput

    client: AgentBoxClient
    sandbox: Optional[Sandbox] = None

    model_config = {"arbitrary_types_allowed": True}

    async def _ensure_sandbox(self) -> Sandbox:
        if self.sandbox is None or self.sandbox.state == "destroyed":
            self.sandbox = await self.client.create_sandbox()
        return self.sandbox

    def _run(self, command: str,
             run_manager: Optional[CallbackManagerForToolRun] = None) -> str:
        return asyncio.run(self._arun(command))

    async def _arun(self, command: str,
                    run_manager: Optional[AsyncCallbackManagerForToolRun] = None) -> str:
        sandbox = await self._ensure_sandbox()
        result = await sandbox.execute(command, language="shell")
        parts = []
        if result.stdout:
            parts.append(result.stdout)
        if result.stderr:
            parts.append(f"[stderr] {result.stderr}")
        if result.exit_code != 0:
            parts.append(f"[exit_code={result.exit_code}]")
        return "\n".join(parts) if parts else "(no output)"


class FileWriteTool(BaseTool):
    """Write a file in the AgentBox sandbox."""

    name: str = "write_file"
    description: str = (
        "Write content to a file in the sandbox. "
        "Creates parent directories automatically. "
        "Use absolute paths like /workspace/data.csv."
    )
    args_schema: Type[BaseModel] = FileWriteInput

    client: AgentBoxClient
    sandbox: Optional[Sandbox] = None

    model_config = {"arbitrary_types_allowed": True}

    async def _ensure_sandbox(self) -> Sandbox:
        if self.sandbox is None or self.sandbox.state == "destroyed":
            self.sandbox = await self.client.create_sandbox()
        return self.sandbox

    def _run(self, path: str, content: str,
             run_manager: Optional[CallbackManagerForToolRun] = None) -> str:
        return asyncio.run(self._arun(path, content))

    async def _arun(self, path: str, content: str,
                    run_manager: Optional[AsyncCallbackManagerForToolRun] = None) -> str:
        sandbox = await self._ensure_sandbox()
        # Ensure parent directory exists
        parent = "/".join(path.split("/")[:-1])
        if parent:
            await sandbox.mkdir(parent)
        ok = await sandbox.write_file(path, content)
        return f"Written to {path}" if ok else f"Failed to write {path}"


class FileReadTool(BaseTool):
    """Read a file from the AgentBox sandbox."""

    name: str = "read_file"
    description: str = (
        "Read the contents of a file in the sandbox. "
        "Returns the file content as a string, or an error if not found."
    )
    args_schema: Type[BaseModel] = FileReadInput

    client: AgentBoxClient
    sandbox: Optional[Sandbox] = None

    model_config = {"arbitrary_types_allowed": True}

    async def _ensure_sandbox(self) -> Sandbox:
        if self.sandbox is None or self.sandbox.state == "destroyed":
            self.sandbox = await self.client.create_sandbox()
        return self.sandbox

    def _run(self, path: str,
             run_manager: Optional[CallbackManagerForToolRun] = None) -> str:
        return asyncio.run(self._arun(path))

    async def _arun(self, path: str,
                    run_manager: Optional[AsyncCallbackManagerForToolRun] = None) -> str:
        sandbox = await self._ensure_sandbox()
        content = await sandbox.read_file(path)
        if content is None:
            return f"File not found: {path}"
        return content


# ---------------------------------------------------------------------------
# Toolkit
# ---------------------------------------------------------------------------

class AgentBoxToolkit:
    """Toolkit that bundles AgentBox tools for LangGraph agents.

    Creates a shared sandbox across all tools so state persists between
    code execution, file writes, and file reads within a single agent run.

    Usage::

        toolkit = AgentBoxToolkit(base_url="http://localhost:8090")
        tools = toolkit.get_tools()
        # tools = [CodeExecutionTool, ShellExecutionTool, FileWriteTool, FileReadTool]

    Pass ``tools`` to a LangGraph agent, ReAct loop, or tool-calling chain.
    """

    def __init__(
        self,
        base_url: str = "http://localhost:8090",
        *,
        token: Optional[str] = None,
        sandbox: Optional[Sandbox] = None,
        include: Optional[list[str]] = None,
    ):
        """
        Args:
            base_url: AgentBox orchestrator/worker URL.
            token: Optional JWT token for authenticated access.
            sandbox: Optional pre-existing Sandbox to reuse.
            include: Optional list of tool names to include. Default: all.
        """
        self.client = AgentBoxClient(base_url, token=token)
        self._sandbox = sandbox
        self._include = include

    def get_tools(self) -> list[BaseTool]:
        """Return the list of LangChain tools."""
        all_tools = {
            "execute_code": CodeExecutionTool(
                client=self.client, sandbox=self._sandbox,
            ),
            "execute_shell": ShellExecutionTool(
                client=self.client, sandbox=self._sandbox,
            ),
            "write_file": FileWriteTool(
                client=self.client, sandbox=self._sandbox,
            ),
            "read_file": FileReadTool(
                client=self.client, sandbox=self._sandbox,
            ),
        }
        if self._include:
            return [t for name, t in all_tools.items() if name in self._include]
        return list(all_tools.values())

    async def cleanup(self) -> None:
        """Destroy the shared sandbox and close the client."""
        for tool in self.get_tools():
            if hasattr(tool, "sandbox") and tool.sandbox:
                try:
                    await tool.sandbox.destroy()
                except Exception:
                    pass
        await self.client.close()
