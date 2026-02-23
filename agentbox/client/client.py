"""AgentBox Python client — async SDK wrapping the orchestrator REST API.

Thin httpx-based client. Only depends on ``httpx`` (no Playwright, no server deps).

Usage::

    async with AgentBoxClient("http://localhost:8090", token="...") as client:
        # Sandbox lifecycle
        sandbox = await client.create_sandbox(box_type="mem")
        print(sandbox.sandbox_id)

        # Code execution
        result = await sandbox.execute("print(2 + 2)")
        print(result.stdout)  # "4\\n"

        result = await sandbox.execute("echo hello", language="shell")
        print(result.stdout)  # "hello\\n"

        # File operations
        await sandbox.mkdir("/workspace")
        await sandbox.write_file("/workspace/data.txt", "hello world")
        content = await sandbox.read_file("/workspace/data.txt")
        entries = await sandbox.list_files("/workspace")

        # Cleanup
        await sandbox.destroy()

    # Or use the sync wrapper:
    from agentbox.client import AgentBoxClient
    client = AgentBoxClient("http://localhost:8090")
    sandbox = client.create_sandbox_sync()
    result = sandbox.execute_sync("print(42)")
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class ExecuteResult:
    """Result of a code/shell execution."""
    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0
    raw: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict) -> "ExecuteResult":
        return cls(
            stdout=d.get("stdout", d.get("output", "")),
            stderr=d.get("stderr", ""),
            exit_code=d.get("exit_code", 0),
            raw=d,
        )


@dataclass
class FileInfo:
    """File metadata from a directory listing."""
    path: str
    content: Optional[str] = None
    exists: bool = True

    @classmethod
    def from_dict(cls, d: dict) -> "FileInfo":
        return cls(
            path=d.get("path", ""),
            content=d.get("content"),
            exists=d.get("exists", True),
        )


@dataclass
class SandboxInfo:
    """Sandbox metadata."""
    sandbox_id: str
    state: str = "unknown"
    box_type: str = "mem"
    worker_id: Optional[str] = None
    created_at: Optional[float] = None
    raw: dict = field(default_factory=dict)

    @classmethod
    def from_dict(cls, d: dict) -> "SandboxInfo":
        return cls(
            sandbox_id=d.get("sandbox_id", d.get("id", "")),
            state=d.get("state", "unknown"),
            box_type=d.get("box_type", "mem"),
            worker_id=d.get("worker_id"),
            created_at=d.get("created_at"),
            raw=d,
        )


# ---------------------------------------------------------------------------
# Sandbox handle
# ---------------------------------------------------------------------------

class Sandbox:
    """High-level handle to a single sandbox.

    Obtained via ``AgentBoxClient.create_sandbox()`` or
    ``AgentBoxClient.get_sandbox()``.
    """

    def __init__(self, client: "AgentBoxClient", sandbox_id: str, info: dict | None = None):
        self._client = client
        self.sandbox_id = sandbox_id
        self._info = info or {}

    @property
    def state(self) -> str:
        return self._info.get("state", "unknown")

    @property
    def box_type(self) -> str:
        return self._info.get("box_type", "mem")

    # --- Execution ---

    async def execute(self, code: str, *, language: str = "python",
                      timeout: int | None = None) -> ExecuteResult:
        """Execute code (Python or shell) in this sandbox."""
        body: dict[str, Any] = {"code": code, "language": language}
        if timeout is not None:
            body["timeout"] = timeout
        data = await self._client._post(f"/sandboxes/{self.sandbox_id}/execute", body)
        return ExecuteResult.from_dict(data)

    async def run_python(self, code: str, **kwargs) -> ExecuteResult:
        """Shorthand for ``execute(code, language='python')``."""
        return await self.execute(code, language="python", **kwargs)

    async def run_shell(self, command: str, **kwargs) -> ExecuteResult:
        """Shorthand for ``execute(command, language='shell')``."""
        return await self.execute(command, language="shell", **kwargs)

    # --- File operations ---

    async def write_file(self, path: str, content: str) -> bool:
        """Write a text file."""
        data = await self._client._post(
            f"/sandboxes/{self.sandbox_id}/files/write",
            {"path": path, "content": content},
        )
        return data.get("written", False)

    async def read_file(self, path: str) -> Optional[str]:
        """Read a text file. Returns None if not found."""
        data = await self._client._get(
            f"/sandboxes/{self.sandbox_id}/files/read",
            params={"path": path},
        )
        if not data.get("exists", True):
            return None
        return data.get("content")

    async def list_files(self, path: str = "/", *, recursive: bool = False) -> list:
        """List directory entries."""
        params: dict[str, Any] = {"path": path}
        if recursive:
            params["recursive"] = "true"
        data = await self._client._get(
            f"/sandboxes/{self.sandbox_id}/files",
            params=params,
        )
        return data.get("entries", [])

    async def mkdir(self, path: str) -> bool:
        """Create a directory (mkdir -p)."""
        data = await self._client._post(
            f"/sandboxes/{self.sandbox_id}/files/mkdir",
            {"path": path},
        )
        return data.get("created", False)

    async def remove_file(self, path: str) -> bool:
        """Remove a file."""
        data = await self._client._delete(
            f"/sandboxes/{self.sandbox_id}/files",
            params={"path": path},
        )
        return data.get("removed", False)

    async def copy_file(self, src: str, dst: str) -> bool:
        """Copy a file."""
        data = await self._client._post(
            f"/sandboxes/{self.sandbox_id}/files/copy",
            {"src": src, "dst": dst},
        )
        return data.get("copied", False)

    # --- Lifecycle ---

    async def refresh(self) -> "Sandbox":
        """Refresh sandbox info from server."""
        data = await self._client._get(f"/sandboxes/{self.sandbox_id}")
        self._info = data
        return self

    async def destroy(self) -> None:
        """Destroy this sandbox."""
        await self._client._delete(f"/sandboxes/{self.sandbox_id}")
        self._info["state"] = "destroyed"

    # --- Sync wrappers ---

    def execute_sync(self, code: str, **kwargs) -> ExecuteResult:
        return _run(self.execute(code, **kwargs))

    def run_python_sync(self, code: str, **kwargs) -> ExecuteResult:
        return _run(self.run_python(code, **kwargs))

    def run_shell_sync(self, command: str, **kwargs) -> ExecuteResult:
        return _run(self.run_shell(command, **kwargs))

    def write_file_sync(self, path: str, content: str) -> bool:
        return _run(self.write_file(path, content))

    def read_file_sync(self, path: str) -> Optional[str]:
        return _run(self.read_file(path))

    def list_files_sync(self, path: str = "/", **kwargs) -> list:
        return _run(self.list_files(path, **kwargs))

    def mkdir_sync(self, path: str) -> bool:
        return _run(self.mkdir(path))

    def destroy_sync(self) -> None:
        return _run(self.destroy())

    def __repr__(self) -> str:
        return f"Sandbox(id={self.sandbox_id!r}, state={self.state!r})"


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class AgentBoxClient:
    """Async client for the AgentBox orchestrator / worker API.

    Args:
        base_url: Orchestrator or worker URL, e.g. ``http://localhost:8090``.
        token: Optional JWT/API token for authenticated requests.
        timeout: Default request timeout in seconds.
        headers: Extra headers to include on every request.
    """

    def __init__(
        self,
        base_url: str = "http://localhost:8090",
        *,
        token: Optional[str] = None,
        timeout: float = 60.0,
        headers: Optional[dict[str, str]] = None,
    ):
        self.base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._headers: dict[str, str] = headers or {}
        if token:
            self._headers["Authorization"] = f"Bearer {token}"
        self._client: Optional[httpx.AsyncClient] = None

    # --- Context manager ---

    async def __aenter__(self) -> "AgentBoxClient":
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            timeout=self._timeout,
            headers=self._headers,
        )
        return self

    async def __aexit__(self, *exc) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self._timeout,
                headers=self._headers,
            )
        return self._client

    async def close(self) -> None:
        """Explicitly close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    # --- Low-level HTTP ---

    async def _get(self, path: str, params: dict | None = None) -> dict:
        resp = await self._get_client().get(path, params=params)
        resp.raise_for_status()
        return resp.json()

    async def _post(self, path: str, body: dict | None = None) -> dict:
        resp = await self._get_client().post(path, json=body)
        resp.raise_for_status()
        return resp.json()

    async def _delete(self, path: str, params: dict | None = None) -> dict:
        resp = await self._get_client().delete(path, params=params)
        resp.raise_for_status()
        return resp.json()

    # --- Health ---

    async def health(self) -> dict:
        """Get orchestrator/worker health status."""
        return await self._get("/health")

    async def metrics(self) -> dict:
        """Get aggregate metrics."""
        return await self._get("/metrics")

    # --- Workers ---

    async def list_workers(self) -> list[dict]:
        """List registered workers (orchestrator only)."""
        data = await self._get("/workers")
        return data.get("workers", [])

    # --- Sandbox CRUD ---

    async def create_sandbox(
        self,
        *,
        box_type: str = "mem",
        repo_id: Optional[str] = None,
        timeout: Optional[int] = None,
        metadata: Optional[dict] = None,
    ) -> Sandbox:
        """Create a new sandbox and return a Sandbox handle."""
        body: dict[str, Any] = {"box_type": box_type}
        if repo_id:
            body["repo_id"] = repo_id
        if timeout:
            body["timeout"] = timeout
        if metadata:
            body["metadata"] = metadata
        data = await self._post("/sandboxes", body)
        sandbox_id = data.get("sandbox_id", data.get("id", ""))
        return Sandbox(self, sandbox_id, info=data)

    async def get_sandbox(self, sandbox_id: str) -> Sandbox:
        """Get an existing sandbox by ID."""
        data = await self._get(f"/sandboxes/{sandbox_id}")
        return Sandbox(self, sandbox_id, info=data)

    async def list_sandboxes(self, **filters) -> list[SandboxInfo]:
        """List sandboxes visible to the current user."""
        data = await self._get("/sandboxes", params=filters or None)
        return [SandboxInfo.from_dict(s) for s in data.get("sandboxes", [])]

    async def destroy_sandbox(self, sandbox_id: str) -> None:
        """Destroy a sandbox by ID."""
        await self._delete(f"/sandboxes/{sandbox_id}")

    # --- Convenience: one-shot execution ---

    async def run(self, code: str, *, language: str = "python",
                  box_type: str = "mem") -> ExecuteResult:
        """Create a sandbox, run code, destroy it, return the result.

        Convenient for one-shot executions::

            result = await client.run("print(2+2)")
        """
        sandbox = await self.create_sandbox(box_type=box_type)
        try:
            return await sandbox.execute(code, language=language)
        finally:
            await sandbox.destroy()

    # --- Sync wrappers ---

    def create_sandbox_sync(self, **kwargs) -> Sandbox:
        return _run(self.create_sandbox(**kwargs))

    def get_sandbox_sync(self, sandbox_id: str) -> Sandbox:
        return _run(self.get_sandbox(sandbox_id))

    def list_sandboxes_sync(self, **kwargs) -> list[SandboxInfo]:
        return _run(self.list_sandboxes(**kwargs))

    def run_sync(self, code: str, **kwargs) -> ExecuteResult:
        return _run(self.run(code, **kwargs))

    def health_sync(self) -> dict:
        return _run(self.health())

    def __repr__(self) -> str:
        return f"AgentBoxClient(base_url={self.base_url!r})"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(coro):
    """Run an async coroutine from sync context."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        # We're inside an existing event loop (e.g. Jupyter notebook).
        # Use nest_asyncio if available, otherwise create a new thread.
        try:
            import nest_asyncio
            nest_asyncio.apply()
            return loop.run_until_complete(coro)
        except ImportError:
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                return pool.submit(asyncio.run, coro).result()
    else:
        return asyncio.run(coro)
