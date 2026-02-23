"""AgentBoxSandbox — Deep Agents BaseSandbox implementation backed by AgentBox.

Implements the four abstract methods required by ``BaseSandbox``:
- ``execute(command)`` — run shell commands via the AgentBox API
- ``id`` — unique sandbox identifier
- ``upload_files(files)`` — write files into the sandbox
- ``download_files(paths)`` — read files from the sandbox

Additionally overrides ``read``, ``write``, ``edit``, ``ls_info``, and
``glob_info`` to use Tier 1 shell builtins instead of ``python3 -c`` commands.
"""

from __future__ import annotations

import asyncio
import atexit
import os
import shlex
import threading
from datetime import datetime
from typing import Any, Optional

import httpx

from deepagents.backends.sandbox import (
    BaseSandbox,
    ExecuteResponse,
    FileDownloadResponse,
    FileUploadResponse,
)
from deepagents.backends.protocol import EditResult, WriteResult, FileInfo


def _sq(s: str) -> str:
    """Shell-quote a string for safe inclusion in commands."""
    return shlex.quote(s)


# ---------------------------------------------------------------------------
# Persistent background event loop — all httpx IO runs here
# ---------------------------------------------------------------------------

_bg_loop: Optional[asyncio.AbstractEventLoop] = None
_bg_thread: Optional[threading.Thread] = None
_bg_lock = threading.Lock()


def _get_loop() -> asyncio.AbstractEventLoop:
    global _bg_loop, _bg_thread
    with _bg_lock:
        if _bg_loop is None or _bg_loop.is_closed():
            _bg_loop = asyncio.new_event_loop()
            _bg_thread = threading.Thread(target=_bg_loop.run_forever, daemon=True)
            _bg_thread.start()
            atexit.register(_shutdown_loop)
    return _bg_loop


def _shutdown_loop():
    global _bg_loop
    if _bg_loop and not _bg_loop.is_closed():
        _bg_loop.call_soon_threadsafe(_bg_loop.stop)


def _run(coro):
    """Schedule *coro* on the background loop and block until done."""
    loop = _get_loop()
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    return future.result(timeout=120)


# ---------------------------------------------------------------------------
# AgentBoxSandbox
# ---------------------------------------------------------------------------

class AgentBoxSandbox(BaseSandbox):
    """Deep Agents sandbox backend powered by AgentBox.

    Owns its own ``httpx.AsyncClient`` created on the persistent background
    event loop so every HTTP call runs on the same loop — no closed-loop errors.

    Args:
        base_url: AgentBox orchestrator URL (e.g. ``http://localhost:8090``).
        sandbox_id: ID of an already-created sandbox.
        default_timeout: Default command timeout in seconds.

    Example::

        from agentbox.client import AgentBoxClient
        from agentbox.deepagents import AgentBoxSandbox
        from deepagents import create_deep_agent

        client = AgentBoxClient("http://localhost:8090")
        sandbox = client.create_sandbox_sync(box_type="git", repo_id="my-repo")

        backend = AgentBoxSandbox("http://localhost:8090", sandbox.sandbox_id)

        agent = create_deep_agent(
            backend=backend,
            system_prompt="You are a coding assistant with sandbox access.",
        )
        result = agent.invoke({"messages": [...]})
        sandbox.destroy_sync()
    """

    def __init__(
        self,
        base_url: str,
        sandbox_id: str,
        *,
        default_timeout: int = 120,
        log_file: str | None = None,
    ):
        self._base_url = base_url.rstrip("/")
        self._sandbox_id = sandbox_id
        self._default_timeout = default_timeout
        self._log_file = log_file
        # Create the httpx client *on* the background loop
        self._http: httpx.AsyncClient = _run(self._create_client())

    def _log(self, text: str) -> None:
        """Write a line to both stdout and the log file (if set)."""
        print(text, flush=True)
        if self._log_file:
            with open(self._log_file, "a") as f:
                f.write(text + "\n")

    async def _create_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self._base_url,
            timeout=float(self._default_timeout),
        )

    async def _post(self, path: str, body: dict[str, Any]) -> dict:
        resp = await self._http.post(path, json=body)
        resp.raise_for_status()
        return resp.json()

    async def _get(self, path: str, params: dict | None = None) -> dict:
        resp = await self._http.get(path, params=params)
        resp.raise_for_status()
        return resp.json()

    # --- Sandbox lifecycle (on the background loop) ---

    @classmethod
    def create(
        cls,
        base_url: str,
        *,
        box_type: str = "mem",
        repo_id: str | None = None,
        default_timeout: int = 120,
        **kwargs,
    ) -> "AgentBoxSandbox":
        """Create a new sandbox and return an AgentBoxSandbox.

        All HTTP happens on the persistent background loop.
        """
        async def _create():
            client = httpx.AsyncClient(
                base_url=base_url.rstrip("/"),
                timeout=float(default_timeout),
            )
            body: dict[str, Any] = {"box_type": box_type}
            if repo_id:
                body["repo_id"] = repo_id
            resp = await client.post("/sandboxes", json=body)
            resp.raise_for_status()
            data = resp.json()
            sandbox_id = data.get("sandbox_id", data.get("id", ""))
            # Return the client too so the sandbox can reuse it
            return sandbox_id, client

        sid, client = _run(_create())
        instance = cls(base_url, sid, default_timeout=default_timeout,
                       log_file=kwargs.get("log_file"))
        # Reuse the client already on the background loop
        instance._http = client
        instance._log(f"  [sandbox] Created {box_type} sandbox {sid[:12]}...")
        return instance

    def destroy(self) -> None:
        """Destroy this sandbox."""
        async def _destroy():
            resp = await self._http.delete(f"/sandboxes/{self._sandbox_id}")
            resp.raise_for_status()
        _run(_destroy())
        self._log(f"  [sandbox] Destroyed {self._sandbox_id[:12]}...")

    # --- BaseSandbox abstract methods ---

    @property
    def id(self) -> str:
        return self._sandbox_id

    def execute(
        self,
        command: str,
        *,
        timeout: int | None = None,
    ) -> ExecuteResponse:
        """Execute a shell command in the AgentBox sandbox."""
        # Log full command
        cmd_display = command.replace("\n", "\\n")
        self._log(f"  [sandbox] $ {cmd_display}")

        async def _exec() -> dict:
            return await self._post(
                f"/sandboxes/{self._sandbox_id}/execute",
                {"code": command, "language": "shell"},
            )

        data = _run(_exec())
        stdout = data.get("stdout", data.get("output", ""))
        stderr = data.get("stderr", "")
        exit_code = data.get("exit_code", 0)

        # Log output for human visibility
        for stream in (stdout, stderr):
            if stream and stream.strip():
                for line in stream.strip().split("\n"):
                    self._log(f"           {line}")
        status = "OK" if exit_code == 0 else f"FAIL({exit_code})"
        self._log(f"           [{status}]")

        # Return clean stdout only — BaseSandbox methods parse output as
        # structured data (JSON lines, file contents, etc.)
        return ExecuteResponse(output=stdout, exit_code=exit_code)

    def upload_files(
        self,
        files: list[tuple[str, bytes]],
    ) -> list[FileUploadResponse]:
        """Upload files into the sandbox."""
        responses = []
        for path, content in files:
            try:
                text = content.decode("utf-8")

                async def _write(p=path, c=text):
                    return await self._post(
                        f"/sandboxes/{self._sandbox_id}/files/write",
                        {"path": p, "content": c},
                    )

                data = _run(_write())
                ok = data.get("written", False)
                responses.append(FileUploadResponse(
                    path=path, error=None if ok else "unknown",
                ))
            except Exception:
                responses.append(FileUploadResponse(path=path, error="unknown"))
        return responses

    # -----------------------------------------------------------------
    # Override BaseSandbox methods to use Tier 1 shell builtins
    # instead of generating python3 -c commands (Tier 2).
    # -----------------------------------------------------------------

    def read(
        self,
        file_path: str,
        offset: int = 0,
        limit: int = 2000,
    ) -> str:
        """Read file via ``edit --view`` builtin (Tier 1)."""
        start = offset + 1  # edit uses 1-indexed lines
        end = offset + limit
        result = self.execute(f"edit {_sq(file_path)} --view --range {start}:{end}")
        if result.exit_code != 0:
            return f"Error: File '{file_path}' not found"
        return result.output.rstrip()

    def write(
        self,
        file_path: str,
        content: str,
    ) -> WriteResult:
        """Write file via ``cat`` heredoc (Tier 1).

        Uses ``cat > <file> << 'AGENTBOX_EOF'`` to avoid quoting issues
        with arbitrary content.  Falls back to ``edit --create`` for new files.
        """
        # Pick a delimiter that doesn't appear in the content
        delim = "AGENTBOX_EOF"
        while delim in content:
            delim += "_X"

        # rm first so edit --create won't fail on existing files,
        # then use cat heredoc to write (handles any content)
        cmd = f"rm -f {_sq(file_path)} ; cat > {_sq(file_path)} << '{delim}'\n{content}\n{delim}"
        result = self.execute(cmd)

        if result.exit_code != 0:
            return WriteResult(error=result.output.strip() or f"Failed to write '{file_path}'")
        return WriteResult(path=file_path, files_update=None)

    def edit(
        self,
        file_path: str,
        old_string: str,
        new_string: str,
        replace_all: bool = False,
    ) -> EditResult:
        """Edit file via ``edit --old --new`` builtin (Tier 1)."""
        cmd = f"edit {_sq(file_path)} --old {_sq(old_string)} --new {_sq(new_string)}"
        result = self.execute(cmd)

        if result.exit_code != 0:
            output = result.output.strip()
            if "No such file" in output:
                return EditResult(error=f"Error: File '{file_path}' not found")
            if "not found" in output.lower() or "no match" in output.lower():
                return EditResult(error=f"Error: String not found in file: '{old_string[:80]}'")
            if "multiple matches" in output.lower():
                return EditResult(
                    error=f"Error: String '{old_string[:80]}' appears multiple times. "
                    "Use replace_all=True to replace all occurrences.",
                )
            return EditResult(error=output or f"Error editing file '{file_path}'")

        return EditResult(path=file_path, files_update=None, occurrences=1)

    def ls_info(self, path: str) -> list[FileInfo]:
        """List directory via ``ls`` builtin (Tier 1)."""
        # Use find for structured output with type info
        result = self.execute(
            f"find {_sq(path)} -maxdepth 1 -not -path {_sq(path)}"
        )
        if result.exit_code != 0:
            return []

        file_infos: list[FileInfo] = []
        for line in result.output.strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            # find outputs paths; check if dir by trailing / or use test
            is_dir = line.endswith("/")
            p = line.rstrip("/")
            file_infos.append({"path": p, "is_dir": is_dir})

        # If find doesn't indicate dirs, fall back to ls -F
        if file_infos and not any(fi.get("is_dir") for fi in file_infos):
            result2 = self.execute(f"ls -F {_sq(path)}")
            if result2.exit_code == 0:
                file_infos = []
                for entry in result2.output.strip().split("\n"):
                    entry = entry.strip()
                    if not entry:
                        continue
                    is_d = entry.endswith("/")
                    name = entry.rstrip("/@*")
                    p = f"{path.rstrip('/')}/{name}" if path != "/" else f"/{name}"
                    file_infos.append({"path": p, "is_dir": is_d})

        return file_infos

    def glob_info(self, pattern: str, path: str = "/") -> list[FileInfo]:
        """Glob via ``find`` builtin (Tier 1)."""
        result = self.execute(f"find {_sq(path)} -name {_sq(pattern)}")
        if result.exit_code != 0:
            return []

        file_infos: list[FileInfo] = []
        for line in result.output.strip().split("\n"):
            line = line.strip()
            if not line:
                continue
            is_dir = line.endswith("/")
            file_infos.append({"path": line.rstrip("/"), "is_dir": is_dir})

        return file_infos

    # Extensions that must be downloaded as binary (base64)
    _BINARY_EXTENSIONS = frozenset({
        ".pdf", ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".ico",
        ".svg", ".tiff", ".heic", ".heif",
        ".zip", ".tar", ".gz", ".bz2", ".xz", ".7z",
        ".wasm", ".bin", ".so", ".dylib", ".dll", ".exe",
        ".pyc", ".pyo", ".class",
        ".mp3", ".mp4", ".wav", ".ogg", ".webm",
        ".ttf", ".otf", ".woff", ".woff2",
        ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    })

    def download_files(
        self,
        paths: list[str],
    ) -> list[FileDownloadResponse]:
        """Download files from the sandbox."""
        import base64 as _b64

        responses = []
        for path in paths:
            try:
                # Use binary mode for known binary extensions
                ext = ("." + path.rsplit(".", 1)[-1]).lower() if "." in path else ""
                is_binary = ext in self._BINARY_EXTENSIONS

                async def _read(p=path, binary=is_binary):
                    return await self._get(
                        f"/sandboxes/{self._sandbox_id}/files/read",
                        params={"path": p, "binary": binary},
                    )

                data = _run(_read())
                if not data.get("exists", True):
                    responses.append(FileDownloadResponse(
                        path=path, content=None, error="file_not_found",
                    ))
                elif is_binary:
                    content_b64 = data.get("content", "")
                    responses.append(FileDownloadResponse(
                        path=path,
                        content=_b64.b64decode(content_b64) if content_b64 else b"",
                        error=None,
                    ))
                else:
                    text = data.get("content", "")
                    responses.append(FileDownloadResponse(
                        path=path, content=text.encode("utf-8"), error=None,
                    ))
            except Exception:
                responses.append(FileDownloadResponse(
                    path=path, content=None, error="unknown",
                ))
        return responses
