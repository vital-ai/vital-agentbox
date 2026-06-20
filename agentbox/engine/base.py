"""ExecutionEngine protocol — the pluggable backend interface.

Any execution engine must implement this protocol. The Box layer
delegates all low-level operations (code execution, shell, filesystem)
to the engine.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class ExecutionEngine(Protocol):
    """Pluggable code execution backend.

    Implementations:
        - PyodideEngine: Playwright + Pyodide + MemFS (in-browser WASM)
        - AgentCoreEngine: AWS Bedrock AgentCore Code Interpreter (future)
    """

    async def start(self) -> None:
        """Initialize the engine (launch browser, start session, etc.)."""
        ...

    async def stop(self) -> None:
        """Shut down the engine and release resources."""
        ...

    async def execute(self, code: str, language: str = "python") -> dict:
        """Execute code. Returns {stdout, stderr, exit_code}."""
        ...

    async def execute_shell(self, command: str) -> dict:
        """Execute a shell command. Returns {stdout, stderr, exit_code}."""
        ...

    async def read_file(self, path: str) -> str | None:
        """Read a file from the engine's filesystem as UTF-8."""
        ...

    async def write_file(self, path: str, content: str) -> bool:
        """Write a UTF-8 string to a file in the engine's filesystem."""
        ...

    async def list_files(self, path: str = "/") -> list[str]:
        """List files/directories at path."""
        ...

    @property
    def engine_type(self) -> str:
        """Identifier: 'pyodide', 'agentcore', etc."""
        ...

    @property
    def started(self) -> bool:
        """Whether the engine has been started."""
        ...
