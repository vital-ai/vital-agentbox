"""
Browser bridge — sendMessage handler for browser operations from Pyodide.

When code running in a Pyodide sandbox needs to control a browser, it calls
``messaging.send({"type": "browser_request", ...})`` which is handled here.
The handler makes HTTP/WS calls to the orchestrator on behalf of the sandbox.

Message format:
    {"type": "browser_request", "method": "POST", "path": "/browsers", "body": {...}}
    {"type": "browser_request", "method": "GET",  "path": "/browsers/{id}"}
    {"type": "browser_request", "method": "DELETE", "path": "/browsers/{id}"}
    {"type": "browser_command", "session_id": "...", "command": {"action": "navigate", "url": "..."}}
"""

import json
import logging
import os

import httpx

log = logging.getLogger(__name__)

ORCHESTRATOR_URL = os.environ.get("AGENTBOX_ORCHESTRATOR_URL", "http://localhost:8090")

# Must cover the slowest browser action: navigate defaults to 60s on the worker,
# and solve_captcha runs Cloudflare polling plus the hCaptcha solver.
COMMAND_TIMEOUT = float(os.environ.get("AGENTBOX_BROWSER_COMMAND_TIMEOUT", "180"))


def _auth_headers() -> dict:
    """Mint a short-lived service JWT for bridge→orchestrator calls.

    The orchestrator's JWT middleware covers /internal/browsers too, so the
    bridge must authenticate like every other internal hop. The secret stays
    in the worker process; sandbox code never sees it.
    """
    secret = os.environ.get("AGENTBOX_SERVICE_SECRET")
    if not secret:
        return {}
    from agentbox.api.auth import mint_service_token
    token = mint_service_token(secret, subject="browser-bridge", ttl=60)
    return {"Authorization": f"Bearer {token}"}


async def browser_message_handler(message: dict) -> dict:
    """Handle sendMessage calls from Pyodide for browser operations.

    Proxies HTTP requests to the orchestrator's /browsers endpoints and
    browser commands via a single WS round-trip.
    """
    msg_type = message.get("type", "")

    if msg_type == "browser_request":
        return await _handle_http(message)
    elif msg_type == "browser_command":
        return await _handle_command(message)
    else:
        return {"reply": "Message received", "original": message}


async def _handle_http(message: dict) -> dict:
    """Proxy an HTTP request to the orchestrator's browser endpoints."""
    method = message.get("method", "GET").upper()
    path = message.get("path", "")
    body = message.get("body")
    url = f"{ORCHESTRATOR_URL}/internal{path}"

    log.info("Browser bridge HTTP: %s %s", method, url)

    try:
        headers = _auth_headers()
        async with httpx.AsyncClient(timeout=30.0) as client:
            if method == "POST":
                resp = await client.post(url, json=body, headers=headers)
            elif method == "DELETE":
                resp = await client.delete(url, headers=headers)
            else:
                resp = await client.get(url, headers=headers)

        if resp.status_code >= 400:
            return {"status": "error", "code": resp.status_code, "detail": resp.text}

        return {"status": "ok", "code": resp.status_code, "data": resp.json()}
    except Exception as e:
        log.error("Browser bridge HTTP error: %s", e)
        return {"status": "error", "detail": str(e)}


async def _handle_command(message: dict) -> dict:
    """Send a single browser command via WebSocket to the orchestrator."""
    import asyncio
    import websockets

    session_id = message.get("session_id")
    command = message.get("command", {})

    if not session_id:
        return {"status": "error", "detail": "session_id required"}

    ws_url = ORCHESTRATOR_URL.replace("http://", "ws://").replace("https://", "wss://")
    ws_url += f"/internal/browsers/{session_id}/ws"

    log.info("Browser bridge WS: %s → %s", command.get("action"), ws_url)

    try:
        async with websockets.connect(ws_url, additional_headers=_auth_headers() or None) as ws:
            # Consume the "connected" message
            connected = await asyncio.wait_for(ws.recv(), timeout=5)
            log.debug("WS connected: %s", connected)

            # Send command
            await ws.send(json.dumps(command))

            # Long-running actions (solve_captcha) stream status="info" progress
            # frames before the final ok/error response; skip them.
            while True:
                raw = await asyncio.wait_for(ws.recv(), timeout=COMMAND_TIMEOUT)
                result = json.loads(raw)
                if result.get("status") != "info":
                    break
                log.info("Browser bridge progress [%s]: %s", command.get("action"), result.get("message"))

        return {"status": "ok", "data": result}
    except Exception as e:
        log.error("Browser bridge WS error: %s", e)
        return {"status": "error", "detail": str(e)}
