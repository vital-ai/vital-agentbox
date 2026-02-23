"""AgentBox backend for Deep Agents (LangGraph BackendProtocol).

Implements the sandbox backend protocol that Deep Agents use for
code execution, file management, and environment setup.

Usage::

    from agentbox.langchain import AgentBoxBackend

    backend = AgentBoxBackend(base_url="http://localhost:8090")

    # Deep Agent uses the backend to:
    #   - Execute code in a persistent sandbox
    #   - Read/write files
    #   - Install packages
    #   - Run shell commands

    # The backend manages sandbox lifecycle automatically.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Optional

from agentbox.client import AgentBoxClient, Sandbox, ExecuteResult


@dataclass
class BackendResult:
    """Standardized result from backend operations."""
    success: bool = True
    output: str = ""
    error: Optional[str] = None
    data: dict = field(default_factory=dict)


class AgentBoxBackend:
    """Deep Agent backend backed by AgentBox sandboxes.

    Provides a high-level interface that Deep Agents use to interact
    with a secure execution environment. Manages sandbox lifecycle
    automatically — creates on first use, reuses across calls, and
    destroys on cleanup.

    Args:
        base_url: AgentBox orchestrator URL.
        token: Optional JWT token for authentication.
        box_type: Sandbox type ('mem' or 'git').
        auto_cleanup: Whether to destroy the sandbox on close.
    """

    def __init__(
        self,
        base_url: str = "http://localhost:8090",
        *,
        token: Optional[str] = None,
        box_type: str = "mem",
        auto_cleanup: bool = True,
    ):
        self.client = AgentBoxClient(base_url, token=token)
        self._box_type = box_type
        self._auto_cleanup = auto_cleanup
        self._sandbox: Optional[Sandbox] = None

    async def _ensure_sandbox(self) -> Sandbox:
        """Lazily create a sandbox on first use."""
        if self._sandbox is None or self._sandbox.state == "destroyed":
            self._sandbox = await self.client.create_sandbox(box_type=self._box_type)
        return self._sandbox

    @property
    def sandbox_id(self) -> Optional[str]:
        """Current sandbox ID, or None if not yet created."""
        return self._sandbox.sandbox_id if self._sandbox else None

    # --- Code Execution ---

    async def execute_python(self, code: str, **kwargs) -> BackendResult:
        """Execute Python code in the sandbox."""
        sandbox = await self._ensure_sandbox()
        result = await sandbox.execute(code, language="python", **kwargs)
        return BackendResult(
            success=result.exit_code == 0,
            output=result.stdout,
            error=result.stderr if result.stderr else None,
            data=result.raw,
        )

    async def execute_shell(self, command: str, **kwargs) -> BackendResult:
        """Execute a shell command in the sandbox."""
        sandbox = await self._ensure_sandbox()
        result = await sandbox.execute(command, language="shell", **kwargs)
        return BackendResult(
            success=result.exit_code == 0,
            output=result.stdout,
            error=result.stderr if result.stderr else None,
            data=result.raw,
        )

    async def execute(self, code: str, *, language: str = "python", **kwargs) -> BackendResult:
        """Execute code in the specified language."""
        if language == "python":
            return await self.execute_python(code, **kwargs)
        elif language == "shell":
            return await self.execute_shell(code, **kwargs)
        else:
            return BackendResult(success=False, error=f"Unsupported language: {language}")

    # --- File Operations ---

    async def write_file(self, path: str, content: str) -> BackendResult:
        """Write a file to the sandbox."""
        sandbox = await self._ensure_sandbox()
        # Auto-create parent directories
        parent = "/".join(path.split("/")[:-1])
        if parent:
            await sandbox.mkdir(parent)
        ok = await sandbox.write_file(path, content)
        return BackendResult(success=ok, output=f"Written: {path}" if ok else "",
                             error=None if ok else f"Failed to write {path}")

    async def read_file(self, path: str) -> BackendResult:
        """Read a file from the sandbox."""
        sandbox = await self._ensure_sandbox()
        content = await sandbox.read_file(path)
        if content is None:
            return BackendResult(success=False, error=f"File not found: {path}")
        return BackendResult(success=True, output=content)

    async def list_files(self, path: str = "/", *, recursive: bool = False) -> BackendResult:
        """List directory contents."""
        sandbox = await self._ensure_sandbox()
        entries = await sandbox.list_files(path, recursive=recursive)
        return BackendResult(
            success=True,
            output="\n".join(str(e) for e in entries),
            data={"entries": entries},
        )

    async def mkdir(self, path: str) -> BackendResult:
        """Create a directory."""
        sandbox = await self._ensure_sandbox()
        ok = await sandbox.mkdir(path)
        return BackendResult(success=ok, output=f"Created: {path}" if ok else "",
                             error=None if ok else f"Failed to create {path}")

    # --- Environment Setup ---

    async def install_packages(self, packages: list[str]) -> BackendResult:
        """Install Python packages via pip (runs in shell)."""
        if not packages:
            return BackendResult(success=True, output="No packages to install.")
        cmd = f"pip install {' '.join(packages)}"
        return await self.execute_shell(cmd)

    # --- Lifecycle ---

    async def reset(self) -> BackendResult:
        """Destroy the current sandbox and create a fresh one."""
        if self._sandbox:
            try:
                await self._sandbox.destroy()
            except Exception:
                pass
        self._sandbox = await self.client.create_sandbox(box_type=self._box_type)
        return BackendResult(
            success=True,
            output=f"Reset sandbox: {self._sandbox.sandbox_id}",
        )

    async def close(self) -> None:
        """Clean up resources."""
        if self._auto_cleanup and self._sandbox:
            try:
                await self._sandbox.destroy()
            except Exception:
                pass
        await self.client.close()

    async def __aenter__(self) -> "AgentBoxBackend":
        await self.client.__aenter__()
        return self

    async def __aexit__(self, *exc) -> None:
        await self.close()

    def __repr__(self) -> str:
        sid = self._sandbox.sandbox_id if self._sandbox else "none"
        return f"AgentBoxBackend(sandbox={sid!r})"
