"""AgentBox sandbox backend for Deep Agents (BaseSandbox).

Implements the ``BaseSandbox`` interface from ``deepagents.backends.sandbox``
so that AgentBox can be used as a backend for ``create_deep_agent()``.

This class uses a **synchronous** httpx client internally because
``BaseSandbox`` methods are synchronous. The async variants (``aexecute``,
``aread``, etc.) are provided by ``BaseSandbox`` automatically.

Usage::

    from agentbox.langchain import AgentBoxSandbox

    sandbox = AgentBoxSandbox(base_url="http://localhost:8090")

    # Use directly:
    result = sandbox.execute("echo hello")
    content = sandbox.read("/workspace/report.md")

    # Or with create_deep_agent:
    from deepagents import create_deep_agent
    agent = create_deep_agent(backend=sandbox, model=model)
"""

from __future__ import annotations

import uuid
import logging
from typing import Optional

import httpx

from deepagents.backends.sandbox import BaseSandbox
from deepagents.backends.protocol import (
    ExecuteResponse,
    FileUploadResponse,
    FileDownloadResponse,
    WriteResult,
    EditResult,
    FileInfo,
)


logger = logging.getLogger(__name__)


class AgentBoxSandbox(BaseSandbox):
    """Deep Agents sandbox backend backed by AgentBox.

    Manages a single sandbox on an AgentBox orchestrator/worker.
    Creates the sandbox lazily on first ``execute()`` call.

    Args:
        base_url: AgentBox orchestrator URL.
        token: Optional JWT token for authentication.
        box_type: Sandbox type (``'mem'``, ``'git'``, or ``'file'``).
        repo_id: Optional persist_id / repo_id for persistent storage.
        timeout: HTTP request timeout in seconds.
        auto_cleanup: Destroy sandbox on ``close()``.
    """

    def __init__(
        self,
        base_url: str = "http://localhost:8090",
        *,
        token: Optional[str] = None,
        box_type: str = "mem",
        repo_id: Optional[str] = None,
        timeout: float = 60.0,
        auto_cleanup: bool = True,
    ):
        self._base_url = base_url.rstrip("/")
        self._box_type = box_type
        self._repo_id = repo_id
        self._auto_cleanup = auto_cleanup
        self._sandbox_id: Optional[str] = None

        headers = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        self._http = httpx.Client(
            base_url=self._base_url,
            timeout=timeout,
            headers=headers,
        )

    # ------------------------------------------------------------------
    # BaseSandbox required: id property
    # ------------------------------------------------------------------

    @property
    def id(self) -> str:
        """Unique sandbox identifier."""
        if self._sandbox_id is None:
            self._ensure_sandbox()
        return self._sandbox_id  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # BaseSandbox required: execute
    # ------------------------------------------------------------------

    def execute(self, command: str, *, timeout: int | None = None) -> ExecuteResponse:
        """Execute a shell command in the sandbox.

        ``BaseSandbox`` methods (``read``, ``write``, ``edit``, ``glob_info``,
        ``grep_raw``) call this with Python scripts wrapped in
        ``python3 -c "..."``. We route through the AgentBox execute endpoint
        with ``language="shell"``.

        For the Pyodide engine, inherited file methods are overridden below
        to use the REST API directly (since ``python3`` is not available).
        """
        self._ensure_sandbox()
        body: dict = {"code": command, "language": "shell"}
        if timeout is not None:
            body["timeout"] = timeout
        data = self._post(f"/sandboxes/{self._sandbox_id}/execute", body)
        stdout = data.get("stdout", data.get("output", ""))
        stderr = data.get("stderr", "")
        exit_code = data.get("exit_code", 0)
        output = stdout
        if stderr:
            output = f"{stdout}{stderr}" if stdout else stderr
        return ExecuteResponse(
            output=output,
            exit_code=exit_code,
            truncated=False,
        )

    # ------------------------------------------------------------------
    # BaseSandbox required: upload_files / download_files
    # ------------------------------------------------------------------

    def upload_files(
        self, files: list[tuple[str, bytes]]
    ) -> list[FileUploadResponse]:
        """Upload files to the sandbox filesystem."""
        self._ensure_sandbox()
        results = []
        for path, content in files:
            try:
                # Auto-create parent directory
                parent = "/".join(path.split("/")[:-1])
                if parent:
                    self._post(
                        f"/sandboxes/{self._sandbox_id}/files/mkdir",
                        {"path": parent},
                    )
                # Write file content (decode bytes to str for the REST API)
                text = content.decode("utf-8", errors="replace")
                self._post(
                    f"/sandboxes/{self._sandbox_id}/files/write",
                    {"path": path, "content": text},
                )
                results.append(FileUploadResponse(path=path, error=None))
            except Exception as e:
                logger.warning("upload_files failed for %s: %s", path, e)
                results.append(FileUploadResponse(path=path, error="permission_denied"))
        return results

    def download_files(
        self, paths: list[str]
    ) -> list[FileDownloadResponse]:
        """Download files from the sandbox filesystem."""
        self._ensure_sandbox()
        results = []
        for path in paths:
            try:
                data = self._get(
                    f"/sandboxes/{self._sandbox_id}/files/read",
                    params={"path": path},
                )
                if not data.get("exists", True):
                    results.append(
                        FileDownloadResponse(path=path, content=None, error="file_not_found")
                    )
                else:
                    content_str = data.get("content", "")
                    results.append(
                        FileDownloadResponse(
                            path=path,
                            content=content_str.encode("utf-8"),
                            error=None,
                        )
                    )
            except Exception as e:
                logger.warning("download_files failed for %s: %s", path, e)
                results.append(
                    FileDownloadResponse(path=path, content=None, error="file_not_found")
                )
        return results

    # ------------------------------------------------------------------
    # Overridden file operations — use REST API directly
    # ------------------------------------------------------------------

    def read(self, file_path: str, offset: int = 0, limit: int = 2000) -> str:
        """Read a file via AgentBox REST API.

        Overrides ``BaseSandbox.read()`` which would use
        ``execute('python3 -c "..."')`` — not available in Pyodide engine.
        """
        self._ensure_sandbox()
        data = self._get(
            f"/sandboxes/{self._sandbox_id}/files/read",
            params={"path": file_path},
        )
        if not data.get("exists", True):
            return f"Error: file '{file_path}' not found"
        content = data.get("content", "")
        lines = content.splitlines(keepends=True)
        if offset or limit < len(lines):
            lines = lines[offset:offset + limit]
        return "".join(lines)

    def write(self, file_path: str, content: str) -> WriteResult:
        """Write a file via AgentBox REST API."""
        self._ensure_sandbox()
        # Auto-create parent directory
        parent = "/".join(file_path.split("/")[:-1])
        if parent:
            self._post(
                f"/sandboxes/{self._sandbox_id}/files/mkdir",
                {"path": parent},
            )
        try:
            self._post(
                f"/sandboxes/{self._sandbox_id}/files/write",
                {"path": file_path, "content": content},
            )
            return WriteResult(error=None, path=file_path)
        except Exception as e:
            return WriteResult(error=str(e), path=file_path)

    def edit(
        self,
        file_path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
    ) -> EditResult:
        """Edit a file via read-modify-write through the REST API."""
        self._ensure_sandbox()
        # Read current content
        data = self._get(
            f"/sandboxes/{self._sandbox_id}/files/read",
            params={"path": file_path},
        )
        if not data.get("exists", True):
            return EditResult(error=f"File '{file_path}' not found", path=file_path)
        content = data.get("content", "")
        if old_string not in content:
            return EditResult(
                error=f"String not found in '{file_path}'", path=file_path
            )
        if replace_all:
            count = content.count(old_string)
            new_content = content.replace(old_string, new_string)
        else:
            count = 1
            new_content = content.replace(old_string, new_string, 1)
        self._post(
            f"/sandboxes/{self._sandbox_id}/files/write",
            {"path": file_path, "content": new_content},
        )
        return EditResult(error=None, path=file_path, occurrences=count)

    def ls_info(self, path: str) -> list[FileInfo]:
        """List directory contents via AgentBox REST API."""
        self._ensure_sandbox()
        data = self._get(
            f"/sandboxes/{self._sandbox_id}/files",
            params={"path": path},
        )
        entries = data.get("entries", [])
        result = []
        for e in entries:
            if isinstance(e, str):
                # Entries are plain filenames
                result.append(FileInfo(path=e, is_dir=False, size=0))
            else:
                # Entries are dicts with metadata
                result.append(FileInfo(
                    path=e.get("name", e.get("path", "")),
                    is_dir=e.get("is_dir", False),
                    size=e.get("size", 0),
                ))
        return result

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def close(self) -> None:
        """Destroy the sandbox and close the HTTP client."""
        if self._auto_cleanup and self._sandbox_id:
            try:
                self._http.delete(f"/sandboxes/{self._sandbox_id}")
            except Exception:
                pass
        self._http.close()

    def __enter__(self) -> "AgentBoxSandbox":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass

    def __repr__(self) -> str:
        sid = self._sandbox_id or "not-created"
        return f"AgentBoxSandbox(id={sid!r}, box_type={self._box_type!r})"

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_sandbox(self) -> None:
        """Lazily create the sandbox on first use."""
        if self._sandbox_id is not None:
            return
        body: dict = {"box_type": self._box_type}
        if self._repo_id:
            body["repo_id"] = self._repo_id
        data = self._post("/sandboxes", body)
        self._sandbox_id = data.get("sandbox_id", data.get("id", ""))
        logger.info("Created sandbox %s (box_type=%s)", self._sandbox_id, self._box_type)

    def _get(self, path: str, params: dict | None = None) -> dict:
        resp = self._http.get(path, params=params)
        resp.raise_for_status()
        return resp.json()

    def _post(self, path: str, body: dict | None = None) -> dict:
        resp = self._http.post(path, json=body)
        resp.raise_for_status()
        return resp.json()
