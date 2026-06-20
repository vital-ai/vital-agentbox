import uuid
import asyncio

from agentbox.box.box import Box
from agentbox.box.shell import ShellExecutor
from agentbox.engine.pyodide_engine import PyodideEngine, DEFAULT_TIMEOUT


class CodeExecutorBox(Box):
    """Ephemeral in-memory sandbox (MemBox).

    Composes a ``PyodideEngine`` for code execution and filesystem access,
    and layers on a ``ShellExecutor`` for shell command support.

    Lifecycle:
        box = CodeExecutorBox()
        await box.start()          # launch browser, load Pyodide
        result = await box.run_code("print('hello')")
        result = await box.run_shell("ls /")
        await box.stop()           # close browser

    Can also be used as an async context manager:
        async with CodeExecutorBox() as box:
            await box.run_code("print('hello')")
    """

    def __init__(self, timeout=DEFAULT_TIMEOUT, message_handler=None):
        """
        Args:
            timeout: Max seconds for a single code/shell execution.
            message_handler: Async callable for sendMessage bridge.
                Signature: async def handler(message: dict) -> dict
        """
        self.timeout = timeout
        self._engine = PyodideEngine(
            timeout=timeout,
            message_handler=message_handler,
        )
        self.shell = None

    # ------------------------------------------------------------------
    # Backward-compatible properties
    # ------------------------------------------------------------------

    @property
    def _started(self):
        return self._engine.started

    @property
    def _page(self):
        """The Playwright page — used by GitBox for isomorphic-git."""
        return self._engine.page

    @property
    def memfs(self):
        """The MemFS instance — used by ShellExecutor and tests."""
        return self._engine.memfs

    @memfs.setter
    def memfs(self, value):
        # Allow GitBox or tests to set memfs (no-op if engine manages it)
        pass

    @property
    def _message_handler(self):
        return self._engine._message_handler

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self):
        """Launch browser, load Pyodide, set up MemFS + ShellExecutor."""
        if self._started:
            return

        await self._engine.start()

        self.shell = ShellExecutor(self.memfs)
        # Default working directory
        self.shell.env.cwd = "/workspace"
        # Pre-set git author defaults so agents don't need to configure
        self.shell.env.set_variable("GIT_AUTHOR_NAME", "Agent")
        self.shell.env.set_variable("GIT_AUTHOR_EMAIL", "agent@agentbox")

    async def stop(self):
        """Close browser and release all resources."""
        if not self._started:
            return
        await self._engine.stop()
        self.shell = None

    async def __aenter__(self):
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.stop()
        return False

    # ------------------------------------------------------------------
    # Box ABC implementation
    # ------------------------------------------------------------------

    async def run_code(self, code, language="python"):
        """Execute code in the sandbox.

        Returns:
            dict with keys: stdout, stderr, exit_code
        """
        self._ensure_started()
        return await self._engine.execute(code, language=language)

    async def run_shell(self, command):
        """Execute a shell command via the tree-sitter-bash ShellExecutor.

        Returns:
            dict with keys: stdout, stderr, exit_code
        """
        self._ensure_started()
        r = await self.shell.run(command)
        return {"stdout": r.stdout, "stderr": r.stderr, "exit_code": r.exit_code}

    async def read_file(self, path):
        """Read a file from the sandbox MemFS."""
        self._ensure_started()
        return await self._engine.read_file(path)

    async def write_file(self, path, content):
        """Write a file to the sandbox MemFS."""
        self._ensure_started()
        return await self._engine.write_file(path, content)

    # ------------------------------------------------------------------
    # Backward-compatible API
    # ------------------------------------------------------------------

    def handle_code_exec(self, code_string):
        """Synchronous wrapper for code execution (legacy API).

        Creates a temporary sandbox if not already started.
        """
        code_string = "\n".join(
            line for line in code_string.splitlines()
            if "```python" not in line and "```" not in line
        )

        async def _run():
            auto_started = not self._started
            if auto_started:
                await self.start()
            try:
                result = await self.run_code(code_string)
                return {"success": result["exit_code"] == 0,
                        "output": result["stdout"],
                        "error": result["stderr"]}
            finally:
                if auto_started:
                    await self.stop()

        answer_dict = asyncio.run(_run())
        random_guid = uuid.uuid4()
        return f"{answer_dict}\nCode Execution Confirmation: {random_guid}.\n"

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _ensure_started(self):
        if not self._started:
            raise RuntimeError("Box not started. Call await box.start() first.")
