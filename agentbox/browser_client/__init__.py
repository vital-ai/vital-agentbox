"""
In-sandbox browser client for controlling remote Chromium via the browser-worker.

Works in both Pyodide (sendMessage bridge) and AgentCore (native websockets).

Usage (inside a sandbox)::

    from agentbox.browser_client import Browser

    b = await Browser.create()
    await b.goto("https://example.com")
    title = await b.title()
    html = await b.content()
    await b.click("#login-btn")
    await b.fill("input[name='email']", "user@example.com")
    screenshot = await b.screenshot()   # base64 PNG
    result = await b.evaluate("document.title")
    await b.close()
"""

import json

# Runtime detection: Pyodide vs native Python (AgentCore)
try:
    from js import WebSocket as _JSWebSocket  # noqa: F401
    _RUNTIME = "pyodide"
except ImportError:
    _RUNTIME = "native"


class BrowserError(Exception):
    """Raised when a browser command returns an error."""
    pass


class Browser:
    """High-level browser automation client.

    In Pyodide: uses the ``messaging.send()`` bridge (sendMessage).
    In AgentCore: uses ``websockets`` library with a persistent connection.
    """

    def __init__(self, session_id: str, _backend=None):
        self.session_id = session_id
        self._backend = _backend
        self._closed = False

    @classmethod
    async def create(cls, config: dict | None = None) -> "Browser":
        """Create a new browser session and return a Browser handle.

        Args:
            config: Optional session config dict passed to the browser-worker.
                    Keys like ``browser_type``, ``headless``, ``proxy``, etc.
        """
        if _RUNTIME == "pyodide":
            backend = _PyodideBackend()
        else:
            backend = await _NativeBackend.connect()

        session_id = await backend.create_session(config=config)
        return cls(session_id, _backend=backend)

    # --- Navigation ---

    async def goto(self, url: str, wait_until: str = "domcontentloaded") -> dict:
        """Navigate to a URL. Returns page info dict."""
        return await self._cmd({
            "action": "navigate", "url": url, "wait_until": wait_until,
        })

    async def back(self) -> dict:
        """Go back in browser history."""
        return await self._cmd({"action": "back"})

    async def forward(self) -> dict:
        """Go forward in browser history."""
        return await self._cmd({"action": "forward"})

    async def reload(self) -> dict:
        """Reload the current page."""
        return await self._cmd({"action": "reload"})

    # --- Interaction ---

    async def click(self, selector: str) -> dict:
        """Click an element matching the CSS selector."""
        return await self._cmd({"action": "click", "selector": selector})

    async def fill(self, selector: str, value: str) -> dict:
        """Fill an input element with text."""
        return await self._cmd({
            "action": "fill", "selector": selector, "value": value,
        })

    async def type(self, selector: str, text: str, delay: int = 0) -> dict:
        """Type text into an element, key by key."""
        return await self._cmd({
            "action": "type", "selector": selector, "text": text, "delay": delay,
        })

    async def press(self, selector: str, key: str) -> dict:
        """Press a keyboard key on an element."""
        return await self._cmd({
            "action": "press", "selector": selector, "key": key,
        })

    async def select(self, selector: str, value: str) -> dict:
        """Select an option from a <select> element."""
        return await self._cmd({
            "action": "select", "selector": selector, "value": value,
        })

    async def hover(self, selector: str) -> dict:
        """Hover over an element."""
        return await self._cmd({"action": "hover", "selector": selector})

    async def click_and_wait_for_navigation(
        self, selector: str, wait_until: str = "domcontentloaded", timeout: int = 30000,
    ) -> dict:
        """Click an element and wait for the page to navigate."""
        return await self._cmd({
            "action": "click_and_wait",
            "selector": selector,
            "wait_until": wait_until,
            "timeout": timeout,
        })

    # --- Content ---

    async def title(self) -> str:
        """Get the current page title."""
        result = await self._cmd({"action": "get_title"})
        return result.get("data", "")

    async def content(self) -> str:
        """Get the full HTML content of the page."""
        result = await self._cmd({"action": "get_content"})
        return result.get("data", "")

    async def url(self) -> str:
        """Get the current page URL."""
        result = await self._cmd({"action": "get_url"})
        return result.get("data", "")

    async def text(self, selector: str) -> str:
        """Get the text content of an element."""
        result = await self._cmd({
            "action": "evaluate",
            "expression": f"document.querySelector('{selector}')?.textContent || ''",
        })
        return result.get("data", "")

    # --- Screenshot ---

    async def screenshot(self, full_page: bool = False) -> str:
        """Take a screenshot. Returns base64-encoded PNG."""
        cmd = {"action": "screenshot"}
        if full_page:
            cmd["full_page"] = True
        result = await self._cmd(cmd)
        return result.get("data", "")

    # --- JavaScript ---

    async def evaluate(self, expression: str):
        """Evaluate a JavaScript expression and return the result."""
        result = await self._cmd({
            "action": "evaluate", "expression": expression,
        })
        return result.get("data")

    # --- Captcha ---

    async def solve_captcha(self) -> dict:
        """Attempt to solve a captcha on the current page."""
        return await self._cmd({"action": "solve_captcha"})

    # --- Lifecycle ---

    async def close(self):
        """Close the browser session and release resources."""
        if self._closed:
            return
        self._closed = True
        await self._backend.delete_session(self.session_id)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()
        return False

    # --- Internal ---

    async def _cmd(self, command: dict) -> dict:
        """Send a command to the browser session."""
        if self._closed:
            raise BrowserError("Browser session is closed")
        result = await self._backend.send_command(self.session_id, command)
        if result.get("status") == "error":
            raise BrowserError(result.get("message", result.get("data", "Unknown error")))
        return result


# ---------------------------------------------------------------------------
# Pyodide backend — uses sendMessage bridge
# ---------------------------------------------------------------------------

class _PyodideBackend:
    """Backend for Pyodide: uses messaging.send() to proxy through the host."""

    async def create_session(self, config: dict | None = None) -> str:
        import __main__
        messaging = __main__.__dict__.get("messaging")
        if messaging is None:
            raise BrowserError("messaging not available — not running in a Pyodide sandbox")
        result = await messaging.send({
            "type": "browser_request",
            "method": "POST",
            "path": "/browsers",
            "body": config or {},
        })
        if result.get("status") == "error":
            raise BrowserError(f"Failed to create session: {result}")
        return result["data"]["session_id"]

    async def send_command(self, session_id: str, command: dict) -> dict:
        import __main__
        messaging = __main__.__dict__.get("messaging")
        if messaging is None:
            raise BrowserError("messaging not available")
        result = await messaging.send({
            "type": "browser_command",
            "session_id": session_id,
            "command": command,
        })
        if result.get("status") == "error":
            raise BrowserError(f"Command failed: {result}")
        return result.get("data", {})

    async def delete_session(self, session_id: str):
        import __main__
        messaging = __main__.__dict__.get("messaging")
        if messaging is None:
            return
        await messaging.send({
            "type": "browser_request",
            "method": "DELETE",
            "path": f"/browsers/{session_id}",
        })


# ---------------------------------------------------------------------------
# Native backend — uses websockets + httpx (for AgentCore / real Python)
# ---------------------------------------------------------------------------

class _NativeBackend:
    """Backend for AgentCore: uses httpx for HTTP and websockets for WS."""

    def __init__(self, orchestrator_url: str):
        self._url = orchestrator_url
        self._ws_url = orchestrator_url.replace("http://", "ws://").replace("https://", "wss://")
        self._connections: dict = {}  # session_id → ws

    @classmethod
    async def connect(cls, orchestrator_url: str = None) -> "_NativeBackend":
        import os
        url = orchestrator_url or os.environ.get(
            "AGENTBOX_ORCHESTRATOR_URL", "http://localhost:8090"
        )
        return cls(url)

    async def create_session(self, config: dict | None = None) -> str:
        import httpx
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(f"{self._url}/browsers", json=config or {})
        if resp.status_code >= 400:
            raise BrowserError(f"Failed to create session: {resp.status_code} {resp.text}")
        return resp.json()["session_id"]

    async def send_command(self, session_id: str, command: dict) -> dict:
        import asyncio

        # Get or create persistent WS connection
        ws = self._connections.get(session_id)
        if ws is None:
            import websockets
            ws_url = f"{self._ws_url}/browsers/{session_id}/ws"
            ws = await websockets.connect(ws_url)
            # Consume "connected" message
            await asyncio.wait_for(ws.recv(), timeout=5)
            self._connections[session_id] = ws

        await ws.send(json.dumps(command))
        raw = await asyncio.wait_for(ws.recv(), timeout=30)
        return json.loads(raw)

    async def delete_session(self, session_id: str):
        # Close WS if open
        ws = self._connections.pop(session_id, None)
        if ws:
            try:
                await ws.close()
            except Exception:
                pass
        # Delete via REST
        import httpx
        async with httpx.AsyncClient(timeout=10) as client:
            await client.delete(f"{self._url}/browsers/{session_id}")
