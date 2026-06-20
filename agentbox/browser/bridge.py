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
    url = f"{ORCHESTRATOR_URL}{path}"

    log.info("Browser bridge HTTP: %s %s", method, url)

    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            if method == "POST":
                resp = await client.post(url, json=body)
            elif method == "DELETE":
                resp = await client.delete(url)
            else:
                resp = await client.get(url)

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
    ws_url += f"/browsers/{session_id}/ws"

    log.info("Browser bridge WS: %s → %s", command.get("action"), ws_url)

    try:
        async with websockets.connect(ws_url) as ws:
            # Consume the "connected" message
            connected = await asyncio.wait_for(ws.recv(), timeout=5)
            log.debug("WS connected: %s", connected)

            # Send command
            await ws.send(json.dumps(command))

            # Receive response
            raw = await asyncio.wait_for(ws.recv(), timeout=30)
            result = json.loads(raw)

        return {"status": "ok", "data": result}
    except Exception as e:
        log.error("Browser bridge WS error: %s", e)
        return {"status": "error", "detail": str(e)}
