"""AgentCoreEngine — AWS Bedrock AgentCore Code Interpreter execution engine.

Delegates code execution, shell commands, and file I/O to a remote
AgentCore Code Interpreter session (a real MicroVM with Python, bash,
and full Linux userspace).

All SDK calls are synchronous (boto3). We wrap them in
``asyncio.to_thread()`` so the event loop is never blocked.
"""

from __future__ import annotations

import os
import asyncio
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Default session timeout — 30 minutes (AgentCore default is 15 min)
DEFAULT_SESSION_TIMEOUT = int(os.environ.get(
    "AGENTBOX_AGENTCORE_SESSION_TIMEOUT", "1800"
))

# AWS region for AgentCore
DEFAULT_REGION = os.environ.get("AGENTBOX_AGENTCORE_REGION", "us-east-1")

# Custom interpreter ID (None = use system default aws.codeinterpreter.v1)
DEFAULT_INTERPRETER_ID = os.environ.get("AGENTBOX_AGENTCORE_INTERPRETER_ID")


class AgentCoreEngine:
    """Execution engine backed by AWS Bedrock AgentCore Code Interpreter.

    Each engine instance maps to one AgentCore session (one MicroVM).
    Sessions persist state (variables, files, installed packages) across
    calls, similar to PyodideEngine.

    The engine exposes ``execute_shell()`` directly (real bash), unlike
    ``PyodideEngine`` which raises ``NotImplementedError`` for shell.
    """

    def __init__(
        self,
        region: str = DEFAULT_REGION,
        session_timeout: int = DEFAULT_SESSION_TIMEOUT,
        interpreter_id: str | None = DEFAULT_INTERPRETER_ID,
        timeout: int = 300,
    ):
        """
        Args:
            region: AWS region for AgentCore.
            session_timeout: Session idle timeout in seconds.
            interpreter_id: Custom interpreter ID, or None for system default.
            timeout: Per-execution timeout in seconds (applied client-side).
        """
        self._region = region
        self._session_timeout = session_timeout
        self._interpreter_id = interpreter_id
        self.timeout = timeout

        # Initialized by start()
        self._client = None  # CodeInterpreter
        self._session_id: str | None = None
        self._started = False

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def engine_type(self) -> str:
        return "agentcore"

    @property
    def started(self) -> bool:
        return self._started

    @property
    def session_id(self) -> str | None:
        return self._session_id

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Start an AgentCore Code Interpreter session."""
        if self._started:
            return

        from bedrock_agentcore.tools import CodeInterpreter

        self._client = CodeInterpreter(region=self._region)

        # start() is synchronous (boto3) — run in thread
        start_kwargs = {"session_timeout_seconds": self._session_timeout}
        if self._interpreter_id:
            start_kwargs["identifier"] = self._interpreter_id
        session_id = await asyncio.to_thread(
            self._client.start,
            **start_kwargs,
        )
        self._session_id = session_id
        self._started = True
        logger.info("AgentCore session started: %s", session_id)

    async def stop(self) -> None:
        """Stop the AgentCore session and release the MicroVM."""
        if not self._started:
            return
        try:
            if self._client:
                await asyncio.to_thread(self._client.stop)
                logger.info("AgentCore session stopped: %s", self._session_id)
        finally:
            self._client = None
            self._session_id = None
            self._started = False

    # ------------------------------------------------------------------
    # ExecutionEngine interface
    # ------------------------------------------------------------------

    async def execute(self, code: str, language: str = "python") -> dict:
        """Execute code in the AgentCore MicroVM.

        Returns:
            dict with keys: stdout, stderr, exit_code
        """
        self._ensure_started()
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(
                    self._client.execute_code,
                    code=code,
                    language=language,
                ),
                timeout=self.timeout,
            )
            return _parse_execution_result(result)
        except asyncio.TimeoutError:
            return {
                "stdout": "",
                "stderr": "TimeoutError: execution exceeded timeout\n",
                "exit_code": 124,
            }
        except Exception as e:
            return {
                "stdout": "",
                "stderr": f"AgentCore error: {e}\n",
                "exit_code": 1,
            }

    async def execute_shell(self, command: str) -> dict:
        """Execute a shell command in the AgentCore MicroVM (real bash).

        Returns:
            dict with keys: stdout, stderr, exit_code
        """
        self._ensure_started()
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(
                    self._client.execute_command,
                    command=command,
                ),
                timeout=self.timeout,
            )
            return _parse_execution_result(result)
        except asyncio.TimeoutError:
            return {
                "stdout": "",
                "stderr": "TimeoutError: execution exceeded timeout\n",
                "exit_code": 124,
            }
        except Exception as e:
            return {
                "stdout": "",
                "stderr": f"AgentCore error: {e}\n",
                "exit_code": 1,
            }

    async def read_file(self, path: str) -> str | None:
        """Read a file from the AgentCore MicroVM filesystem."""
        self._ensure_started()
        try:
            content = await asyncio.to_thread(
                self._client.download_file,
                path=_sdk_path(path),
            )
            if isinstance(content, bytes):
                return content.decode("utf-8", errors="replace")
            return content
        except FileNotFoundError:
            return None
        except Exception as e:
            logger.warning("AgentCore read_file(%s) error: %s", path, e)
            return None

    async def write_file(self, path: str, content: str) -> bool:
        """Write a file to the AgentCore MicroVM filesystem."""
        self._ensure_started()
        try:
            # Ensure parent directory exists using the SDK-relative path
            sdk_path = _sdk_path(path)
            parent = "/".join(sdk_path.split("/")[:-1])
            if parent:
                await self.execute_shell(f"mkdir -p '{parent}'")
            await asyncio.to_thread(
                self._client.upload_file,
                path=sdk_path,
                content=content,
            )
            return True
        except Exception as e:
            logger.warning("AgentCore write_file(%s) error: %s", path, e)
            return False

    async def list_files(self, path: str = "/") -> list[str]:
        """List files at path by running ls in the MicroVM."""
        self._ensure_started()
        try:
            result = await self.execute_shell(f"ls -1 {path}")
            if result["exit_code"] == 0 and result["stdout"]:
                return [f.strip() for f in result["stdout"].strip().split("\n") if f.strip()]
            return []
        except Exception:
            return []

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _ensure_started(self):
        if not self._started:
            raise RuntimeError(
                "Engine not started. Call await engine.start() first."
            )


# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------

def _sdk_path(path: str) -> str:
    """Convert an absolute path to relative for the AgentCore SDK.

    The SDK requires relative paths (no leading /). Absolute paths are
    converted by stripping the leading slash.
    """
    return path.lstrip("/") if path.startswith("/") else path


# ------------------------------------------------------------------
# Response parsing
# ------------------------------------------------------------------

def _parse_execution_result(result: dict[str, Any]) -> dict:
    """Parse AgentCore invoke response into {stdout, stderr, exit_code}.

    The AgentCore response contains a ``stream`` key which is a botocore
    ``EventStream`` iterator. Each event has a ``result`` dict with:
      - ``content``: list of {type, text} items (combined output)
      - ``structuredContent``: {stdout, stderr, exitCode, executionTime}
      - ``isError``: bool

    We prefer ``structuredContent`` for accurate stdout/stderr separation.
    Line endings are normalized from ``\\r\\n`` to ``\\n``.
    """
    stdout_parts = []
    stderr_parts = []
    exit_code = 0

    stream = result.get("stream", [])
    for event in stream:
        r = event.get("result", {})
        sc = r.get("structuredContent")

        if sc:
            # Prefer structuredContent for accurate stdout/stderr/exitCode
            stdout_parts.append(sc.get("stdout", ""))
            stderr_parts.append(sc.get("stderr", ""))
            exit_code = sc.get("exitCode", 0)
        elif "content" in r:
            # Fallback: combine all text content items as stdout
            for item in r["content"]:
                if item.get("type") == "text":
                    stdout_parts.append(item.get("text", ""))
                elif item.get("type") == "resource":
                    resource = item.get("resource", {})
                    if "text" in resource:
                        stdout_parts.append(resource["text"])
            if r.get("isError"):
                exit_code = 1

        # Handle top-level error events
        if "error" in event:
            error = event["error"]
            if isinstance(error, dict):
                stderr_parts.append(error.get("message", str(error)))
                exit_code = error.get("exitCode", 1)
            else:
                stderr_parts.append(str(error))
                exit_code = 1

    # Normalize \r\n to \n
    stdout = "".join(stdout_parts).replace("\r\n", "\n")
    stderr = "".join(stderr_parts).replace("\r\n", "\n")

    return {
        "stdout": stdout,
        "stderr": stderr,
        "exit_code": exit_code,
    }
