from abc import ABC, abstractmethod


class Box(ABC):
    """Abstract base class for all sandbox types.

    Subclasses:
        - CodeExecutorBox (MemBox): ephemeral in-memory sandbox
        - GitBox: sandbox with isomorphic-git + persistent storage
        - FileSystemBox: local dev-only, backed by host directory
    """

    @abstractmethod
    async def start(self):
        """Initialize the sandbox (browser, Pyodide, FS)."""
        ...

    @abstractmethod
    async def stop(self):
        """Tear down the sandbox and release resources."""
        ...

    @abstractmethod
    async def run_code(self, code: str, language: str = "python") -> dict:
        """Execute code in the sandbox. Returns dict with stdout, stderr, exit_code."""
        ...

    @abstractmethod
    async def run_shell(self, command: str) -> dict:
        """Execute a shell command. Returns dict with stdout, stderr, exit_code."""
        ...

    @abstractmethod
    async def read_file(self, path: str) -> str | None:
        """Read a file from the sandbox filesystem."""
        ...

    @abstractmethod
    async def write_file(self, path: str, content: str) -> bool:
        """Write a file to the sandbox filesystem."""
        ...
