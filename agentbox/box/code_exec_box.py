import os
import uuid
import asyncio
from playwright.async_api import async_playwright

from agentbox.box.box import Box
from agentbox.box.memfs.memfs import MemFS
from agentbox.box.shell import ShellExecutor


PYODIDE_VERSION = "0.29.3"
PYODIDE_CDN = f"https://cdn.jsdelivr.net/pyodide/v{PYODIDE_VERSION}/full/pyodide.js"

# Override with AGENTBOX_PYODIDE_URL env var for local bundling
# e.g. "http://localhost:8000/static/pyodide/pyodide.js"
PYODIDE_URL = os.environ.get("AGENTBOX_PYODIDE_URL", PYODIDE_CDN)

# Default timeout for code execution (seconds)
DEFAULT_TIMEOUT = 30


class CodeExecutorBox(Box):
    """Ephemeral in-memory sandbox (MemBox).

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
        self._message_handler = message_handler or self._default_message_handler

        # Initialized by start()
        self._playwright = None
        self._browser = None
        self._page = None
        self.memfs = None
        self.shell = None
        self._started = False

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self):
        """Launch browser, load Pyodide, set up MemFS + ShellExecutor."""
        if self._started:
            return

        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=True)
        self._page = await self._browser.new_page()

        # Expose the sendMessage bridge before loading any content
        await self._page.expose_function("sendMessage", self._message_handler)

        # Load Pyodide — navigate to a real page first so Chromium has a
        # proper origin and can load scripts/wasm via HTTP.
        pyodide_base = PYODIDE_URL.rsplit("/", 1)[0]
        await self._page.goto(f"{pyodide_base}/sandbox.html")
        await self._page.add_script_tag(url=PYODIDE_URL)
        await self._page.evaluate("""async () => {
            window.pyodide = await loadPyodide();
            await pyodide.loadPackage("micropip");

            // Set up the messaging helper in Pyodide
            window.pyodide.runPython(`
import json
import js
from io import StringIO

class Messaging:
    async def send(self, message):
        json_message = json.dumps(message)
        js_message = js.JSON.parse(json_message)
        result = await js.sendMessage(js_message)
        try:
            return result.to_py()
        except AttributeError:
            return result

messaging = Messaging()
`);
        }""")

        self.memfs = MemFS(self._page)

        # Pre-create standard directories agents expect
        for d in ("/workspace", "/data", "/var", "/etc"):
            await self.memfs.mkdir_p(d)

        self.shell = ShellExecutor(self.memfs)
        # Default working directory
        self.shell.env.cwd = "/workspace"
        # Pre-set git author defaults so agents don't need to configure
        self.shell.env.set_variable("GIT_AUTHOR_NAME", "Agent")
        self.shell.env.set_variable("GIT_AUTHOR_EMAIL", "agent@agentbox")
        self._started = True

    async def stop(self):
        """Close browser and release all resources."""
        if not self._started:
            return
        try:
            if self._browser:
                await self._browser.close()
            if self._playwright:
                await self._playwright.stop()
        finally:
            self._playwright = None
            self._browser = None
            self._page = None
            self.memfs = None
            self.shell = None
            self._started = False

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

        if language != "python":
            return {"stdout": "", "stderr": f"Unsupported language: {language}", "exit_code": 1}

        try:
            result = await asyncio.wait_for(
                self._page.evaluate("""async (code) => {
                    const pyodide = window.pyodide;
                    try {
                        pyodide.runPython(`
import sys
from io import StringIO
sys.stdout = StringIO()
sys.stderr = StringIO()
`);
                        await pyodide.runPythonAsync(code);
                        const stdout = pyodide.runPython("sys.stdout.getvalue()");
                        const stderr = pyodide.runPython("sys.stderr.getvalue()");
                        pyodide.runPython("sys.stdout = sys.__stdout__; sys.stderr = sys.__stderr__");
                        return { stdout, stderr, exit_code: 0 };
                    } catch (error) {
                        let stderr = "";
                        try { stderr = pyodide.runPython("sys.stderr.getvalue()"); } catch(e) {}
                        try { pyodide.runPython("sys.stdout = sys.__stdout__; sys.stderr = sys.__stderr__"); } catch(e) {}
                        return { stdout: "", stderr: (stderr || "") + error.message + "\\n", exit_code: 1 };
                    }
                }""", code),
                timeout=self.timeout
            )
        except asyncio.TimeoutError:
            result = {"stdout": "", "stderr": "TimeoutError: execution exceeded timeout\n", "exit_code": 124}

        return result

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
        return await self.memfs.read_file(path)

    async def write_file(self, path, content):
        """Write a file to the sandbox MemFS."""
        self._ensure_started()
        return await self.memfs.write_file(path, content)

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

    @staticmethod
    async def _default_message_handler(message):
        """Default sendMessage handler — echo back."""
        return {"reply": "Message received", "original": message}
