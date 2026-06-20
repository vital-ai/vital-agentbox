"""PyodideEngine — Playwright + Pyodide + MemFS execution engine.

Extracted from CodeExecutorBox to separate the execution primitives
(code execution, filesystem) from the feature layer (shell builtins,
git, editing, messaging bridge).
"""

from __future__ import annotations

import os
import asyncio

from playwright.async_api import async_playwright


PYODIDE_VERSION = "0.29.3"
PYODIDE_CDN = f"https://cdn.jsdelivr.net/pyodide/v{PYODIDE_VERSION}/full/pyodide.js"

# Override with AGENTBOX_PYODIDE_URL env var for local bundling
# e.g. "http://localhost:8000/static/pyodide/pyodide.js"
PYODIDE_URL = os.environ.get("AGENTBOX_PYODIDE_URL", PYODIDE_CDN)

# Default timeout for code execution (seconds)
DEFAULT_TIMEOUT = 30


class PyodideEngine:
    """Execution engine backed by Playwright + Pyodide + MemFS.

    Manages the browser lifecycle and provides code execution and
    filesystem access via the Emscripten FS in the Pyodide page.

    The ``page`` and ``memfs`` properties are exposed for use by
    higher-level layers (ShellExecutor, GitBox, etc.).
    """

    def __init__(self, timeout: int = DEFAULT_TIMEOUT,
                 message_handler=None):
        """
        Args:
            timeout: Max seconds for a single code execution.
            message_handler: Async callable for sendMessage bridge.
                Signature: async def handler(message: dict) -> dict
        """
        self.timeout = timeout
        self._message_handler = message_handler or self._default_message_handler

        # Initialized by start()
        self._playwright = None
        self._browser = None
        self._page = None
        self._memfs = None  # MemFS instance, set by start()
        self._started = False

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def engine_type(self) -> str:
        return "pyodide"

    @property
    def started(self) -> bool:
        return self._started

    @property
    def page(self):
        """The Playwright page — needed by GitBox, ShellExecutor, etc."""
        return self._page

    @property
    def memfs(self) -> MemFS | None:
        """The MemFS instance — needed by ShellExecutor."""
        return self._memfs

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Launch browser, load Pyodide, set up MemFS."""
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

        from agentbox.box.memfs.memfs import MemFS
        self._memfs = MemFS(self._page)

        # Pre-create standard directories agents expect
        for d in ("/workspace", "/data", "/var", "/etc"):
            await self._memfs.mkdir_p(d)

        # Inject the browser_client module so sandbox code can do:
        #   from agentbox.browser_client import Browser
        await self._inject_browser_client()

        # Write tool module source files to the Emscripten FS so agents
        # can import them after installing deps (pydantic, beautifulsoup4).
        await self._inject_tools()

        self._started = True

    async def stop(self) -> None:
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
            self._memfs = None
            self._started = False

    # ------------------------------------------------------------------
    # ExecutionEngine interface
    # ------------------------------------------------------------------

    async def execute(self, code: str, language: str = "python") -> dict:
        """Execute code in the Pyodide sandbox.

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

    async def execute_shell(self, command: str) -> dict:
        """Not implemented at engine level — shell runs via ShellExecutor.

        The ShellExecutor (tree-sitter-bash) operates on top of MemFS and
        is wired up by the Box layer, not the engine. This method exists
        to satisfy the ExecutionEngine protocol for future engines
        (AgentCore) that have real bash.

        Raises:
            NotImplementedError: Always. Use ShellExecutor instead.
        """
        raise NotImplementedError(
            "PyodideEngine does not support execute_shell() directly. "
            "Use ShellExecutor (wired by CodeExecutorBox) instead."
        )

    async def read_file(self, path: str) -> str | None:
        """Read a file from the Emscripten MemFS."""
        self._ensure_started()
        return await self._memfs.read_file(path)

    async def write_file(self, path: str, content: str) -> bool:
        """Write a file to the Emscripten MemFS."""
        self._ensure_started()
        return await self._memfs.write_file(path, content)

    async def list_files(self, path: str = "/") -> list[str]:
        """List files/directories at path in MemFS."""
        self._ensure_started()
        result = await self._memfs.list_dir(path)
        if isinstance(result, str) and result.startswith("Error"):
            return []
        return result

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _ensure_started(self):
        if not self._started:
            raise RuntimeError("Engine not started. Call await engine.start() first.")

    async def _inject_browser_client(self):
        """Inject browser_client module into Pyodide so it's importable."""
        import pathlib
        src = (pathlib.Path(__file__).parent.parent / "browser_client" / "__init__.py").read_text()

        # Escape for Python triple-quoted string
        escaped = src.replace("\\", "\\\\").replace("'''", "\\'\\'\\'")

        # Use types.ModuleType to register the module in sys.modules
        bootstrap = f"""
import types, sys
_pkg = types.ModuleType('agentbox')
_pkg.__path__ = ['agentbox']
_pkg.__package__ = 'agentbox'
sys.modules['agentbox'] = _pkg

_mod_src = '''{escaped}'''
_mod = types.ModuleType('agentbox.browser_client')
_mod.__package__ = 'agentbox.browser_client'
_mod.__path__ = ['agentbox/browser_client']
exec(compile(_mod_src, 'agentbox/browser_client/__init__.py', 'exec'), _mod.__dict__)
sys.modules['agentbox.browser_client'] = _mod
_pkg.browser_client = _mod
del _pkg, _mod, _mod_src
"""
        await self._page.evaluate(
            "async (code) => { await pyodide.runPythonAsync(code); }",
            bootstrap,
        )

    async def _inject_tools(self):
        """Write agentbox.tools source files to Emscripten FS for lazy import.

        Tool modules depend on external packages (pydantic, beautifulsoup4)
        that agents install via micropip. The source files are written to the
        filesystem at startup so they're importable once deps are ready::

            import micropip
            await micropip.install(['pydantic', 'beautifulsoup4'])
            from agentbox.tools.nyscef.session_manager import NyscefSessionManager

        Files ending in ``_tool.py`` are skipped because they import
        ``kgraphplanner`` / ``langchain_core`` which are not available in Pyodide.
        """
        import pathlib

        tools_dir = pathlib.Path(__file__).parent.parent / "tools"
        if not tools_dir.is_dir():
            return

        # Collect .py files, skipping kgraphplanner-dependent tool wrappers
        files = {}
        for py_file in tools_dir.rglob("*.py"):
            if py_file.name.endswith("_tool.py"):
                continue
            # Relative path from agentbox/ parent, e.g. "agentbox/tools/nyscef/models.py"
            rel = str(py_file.relative_to(tools_dir.parent.parent))
            files[rel] = py_file.read_text()

        if not files:
            return

        # Pass files dict to JS context, then write to Emscripten FS from Python
        await self._page.evaluate(
            "(data) => { window.__agentbox_tools = data; }", files
        )
        await self._page.evaluate("""async () => {
            await pyodide.runPythonAsync(`
import sys, os
from js import window

_files = window.__agentbox_tools.to_py()
for rel_path, content in _files.items():
    full = '/agentbox_lib/' + rel_path
    os.makedirs(os.path.dirname(full), exist_ok=True)
    with open(full, 'w') as f:
        f.write(content)

if '/agentbox_lib' not in sys.path:
    sys.path.insert(0, '/agentbox_lib')

# Extend agentbox package path so tools sub-packages are discoverable
if 'agentbox' in sys.modules:
    _pkg = sys.modules['agentbox']
    _tools_path = '/agentbox_lib/agentbox'
    if _tools_path not in getattr(_pkg, '__path__', []):
        _pkg.__path__.append(_tools_path)

del _files, _pkg, _tools_path
`);
        }""")
        # Clean up JS global
        await self._page.evaluate("() => { delete window.__agentbox_tools; }")

    @staticmethod
    async def _default_message_handler(message):
        """Default sendMessage handler — echo back."""
        return {"reply": "Message received", "original": message}
