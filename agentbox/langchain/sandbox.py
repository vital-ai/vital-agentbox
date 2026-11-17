"""AgentBox sandbox backend for Deep Agents (BaseSandbox).

Implements the ``BaseSandbox`` interface from ``deepagents.backends.sandbox``
so that AgentBox can be used as a backend for ``create_deep_agent()``.

This class uses a **synchronous** httpx client internally because
``BaseSandbox`` methods are synchronous. The async variants (``aexecute``,
``aread``, etc.) are provided by ``BaseSandbox`` automatically.

Usage::

    from agentbox.langchain import AgentBoxSandbox

    # Lazy creation (sandbox created on first execute/read/write):
    sandbox = AgentBoxSandbox(base_url="http://localhost:8090", token="...")

    # Eager creation via classmethod:
    sandbox = AgentBoxSandbox.create(
        "http://localhost:8090",
        token="...",
        data_path="harper/sandbox",
        engine="agentcore",
    )

    # Use directly:
    result = sandbox.execute("echo hello")
    content = sandbox.read("/workspace/report.md")

    # Or with create_deep_agent:
    from deepagents import create_deep_agent
    agent = create_deep_agent(backend=sandbox, model=model)
"""

from __future__ import annotations

import asyncio
import re
import shlex
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
    FileData,
    ReadResult,
    LsResult,
    GlobResult,
    GrepResult,
    GrepMatch,
)


logger = logging.getLogger(__name__)


def _glob_regex(pattern: str) -> "re.Pattern[str]":
    """Translate a glob (``**``, ``*``, ``?``, ``[...]``) to a full-match regex."""
    out: list[str] = []
    i, n = 0, len(pattern)
    while i < n:
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        elif pattern[i] == "[" and "]" in pattern[i + 2:]:
            j = pattern.index("]", i + 2)
            body = pattern[i + 1:j]
            if body.startswith("!"):
                body = "^" + body[1:]
            out.append("[" + body.replace("\\", "\\\\") + "]")
            i = j + 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    return re.compile("".join(out) + r"\Z")


class AgentBoxSandbox(BaseSandbox):
    """Deep Agents sandbox backend backed by AgentBox.

    Manages a single sandbox on an AgentBox orchestrator/worker.
    Creates the sandbox lazily on first ``execute()`` call.

    Args:
        base_url: AgentBox orchestrator URL.
        token: Optional JWT token for authentication.
        headers: Optional extra headers for every request.
        box_type: Sandbox type (``'mem'``, ``'git'``, or ``'file'``).
        repo_id: Optional persist_id / repo_id for persistent storage.
        engine: Execution engine (``'pyodide'`` or ``'agentcore'``).
        data_path: S3 data path (required for Mode 2/3).
        timeout: HTTP request timeout in seconds.
        auto_cleanup: Destroy sandbox on ``close()``.
    """

    def __init__(
        self,
        base_url: str = "http://localhost:8090",
        *,
        token: Optional[str] = None,
        headers: Optional[dict[str, str]] = None,
        box_type: str = "mem",
        repo_id: Optional[str] = None,
        engine: Optional[str] = None,
        data_path: Optional[str] = None,
        timeout: float = 60.0,
        auto_cleanup: bool = True,
    ):
        self._base_url = base_url.rstrip("/")
        self._box_type = box_type
        self._repo_id = repo_id
        self._engine = engine
        self._data_path = data_path
        self._auto_cleanup = auto_cleanup
        self._sandbox_id: Optional[str] = None

        _headers: dict[str, str] = headers.copy() if headers else {}
        if token:
            _headers["Authorization"] = f"Bearer {token}"
        self._http = httpx.Client(
            base_url=self._base_url,
            timeout=timeout,
            headers=_headers,
        )

    @classmethod
    def create(
        cls,
        base_url: str = "http://localhost:8090",
        *,
        token: Optional[str] = None,
        headers: Optional[dict[str, str]] = None,
        box_type: str = "mem",
        repo_id: Optional[str] = None,
        engine: Optional[str] = None,
        data_path: Optional[str] = None,
        timeout: float = 60.0,
        auto_cleanup: bool = True,
    ) -> "AgentBoxSandbox":
        """Create a sandbox immediately and return the handle.

        Convenience classmethod that triggers sandbox creation up front
        instead of lazily on first ``execute()``.
        """
        instance = cls(
            base_url,
            token=token,
            headers=headers,
            box_type=box_type,
            repo_id=repo_id,
            engine=engine,
            data_path=data_path,
            timeout=timeout,
            auto_cleanup=auto_cleanup,
        )
        instance._ensure_sandbox()
        return instance

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
            path = self._normalize_path(path)
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
            path = self._normalize_path(path)
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
        file_path = self._normalize_path(file_path)
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
        file_path = self._normalize_path(file_path)
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
        file_path = self._normalize_path(file_path)
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
        path = self._normalize_path(path)
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

    def glob(self, pattern: str, path: str | None = None) -> GlobResult:
        """Glob files via shell ``find`` — avoids base64-encoded python3 scripts.

        ``find -name`` matches basenames only, so ``**/*.py`` or ``src/*.py``
        would never match; instead list files under the search path and match
        the pattern against each path relative to it, with ``glob.glob``
        recursive semantics (``**`` spans directories, ``*`` does not).
        """
        search = self._normalize_path(path or ".")
        result = self.execute(f"find {shlex.quote(search)} -type f 2>/dev/null")
        if result.exit_code != 0:
            return GlobResult(error="glob_failed", matches=[])
        regex = _glob_regex(pattern)
        prefix = search.rstrip("/") + "/"
        matches: list[FileInfo] = []
        for line in result.output.strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            rel = line[len(prefix):] if line.startswith(prefix) else line
            if regex.match(rel):
                matches.append(FileInfo(path=line, is_dir=False))
        return GlobResult(error=None, matches=matches)

    def grep(
        self,
        pattern: str,
        path: str | None = None,
        glob: str | None = None,
    ) -> GrepResult:
        """Grep via shell ``grep -rHnF`` — avoids base64-encoded python3 scripts."""
        search = self._normalize_path(path or ".")
        cmd = f"grep -rHnFZ {shlex.quote(pattern)}"
        if glob:
            cmd += f" --include={shlex.quote(glob)}"
        cmd += f" {shlex.quote(search)} 2>/dev/null || true"
        result = self.execute(cmd)
        matches: list[GrepMatch] = []
        for line in result.output.strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            # grep -HnZ output: file\0line_no:text
            if "\x00" in line:
                file_part, rest = line.split("\x00", 1)
                if ":" in rest:
                    line_no_str, text = rest.split(":", 1)
                    try:
                        matches.append(GrepMatch(
                            path=file_part, line=int(line_no_str), text=text,
                        ))
                    except ValueError:
                        pass
            elif ":" in line:
                # Fallback: file:line_no:text
                parts = line.split(":", 2)
                if len(parts) >= 3:
                    try:
                        matches.append(GrepMatch(
                            path=parts[0], line=int(parts[1]), text=parts[2],
                        ))
                    except ValueError:
                        pass
        return GrepResult(error=None, matches=matches)

    # ------------------------------------------------------------------
    # Async overrides — delegate to sync methods (which use REST API
    # with _normalize_path) instead of inherited aexecute-based
    # implementations that generate base64 python3 scripts.
    # ------------------------------------------------------------------

    async def aread(
        self, file_path: str, offset: int = 0, limit: int = 2000,
    ) -> ReadResult:
        content = await asyncio.to_thread(self.read, file_path, offset, limit)
        if isinstance(content, str) and content.startswith("Error:"):
            return ReadResult(error=content)
        return ReadResult(file_data=FileData(content=content, encoding="utf-8"))

    async def awrite(self, file_path: str, content: str) -> WriteResult:
        return await asyncio.to_thread(self.write, file_path, content)

    async def aedit(
        self,
        file_path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
    ) -> EditResult:
        return await asyncio.to_thread(
            self.edit, file_path, old_string, new_string, replace_all,
        )

    async def als(self, path: str) -> LsResult:
        entries = await asyncio.to_thread(self.ls_info, path)
        return LsResult(error=None, entries=entries)

    async def aglob(self, pattern: str, path: str | None = None) -> GlobResult:
        return await asyncio.to_thread(self.glob, pattern, path)

    async def agrep(
        self,
        pattern: str,
        path: str | None = None,
        glob: str | None = None,
    ) -> GrepResult:
        return await asyncio.to_thread(self.grep, pattern, path, glob)

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

    def _normalize_path(self, path: str) -> str:
        """On AgentCore, strip leading ``/`` so paths are relative to the sandbox cwd.

        The AgentCore MicroVM root filesystem is read-only.  All file
        API paths are resolved relative to the writable cwd
        (``/opt/amazon/genesis1p-tools/var``).  Stripping the leading
        slash ensures ``/report.txt`` → ``report.txt`` → written to
        ``{cwd}/report.txt``; the root itself (``/``) maps to ``.``.

        Other engines keep absolute paths: the Pyodide file API resolves
        relative paths against the Emscripten cwd, not the shell's
        ``/workspace``, so stripping would misplace files there.
        """
        if self._engine != "agentcore":
            return path
        return path.lstrip("/") or "."

    def _ensure_sandbox(self) -> None:
        """Lazily create the sandbox on first use."""
        if self._sandbox_id is not None:
            return
        body: dict = {"box_type": self._box_type}
        if self._repo_id:
            body["repo_id"] = self._repo_id
        if self._engine:
            body["engine"] = self._engine
        if self._data_path:
            body["data_path"] = self._data_path
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
