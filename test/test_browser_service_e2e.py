"""
End-to-end test for the browser worker service.

Hits the RUNNING Docker service at localhost:8070 (browser-worker
from docker-compose). Tests the full HTTP + WebSocket stack with
real Chromium browser sessions.

Usage:
    # Start the stack first:
    docker compose up --build

    # Then run:
    python -m pytest test/test_browser_service_e2e.py -xvs
"""

import asyncio
import base64
import json
import logging
import os

import httpx
import pytest
import websockets

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

# The browser-worker from docker-compose runs at port 8070
SERVICE_URL = os.environ.get("BROWSER_SERVICE_URL", "http://localhost:8070")
WS_URL = SERVICE_URL.replace("http://", "ws://").replace("https://", "wss://")


# --- Health ---

@pytest.mark.asyncio
async def test_health():
    """Service is up and healthy."""
    log.info("GET %s/health", SERVICE_URL)
    async with httpx.AsyncClient(timeout=5) as client:
        resp = await client.get(f"{SERVICE_URL}/health")
        assert resp.status_code == 200, f"Health check failed: {resp.status_code} {resp.text}"
        data = resp.json()
        log.info("Health response: %s", data)
        assert data["status"] == "ok"


# --- REST lifecycle ---

@pytest.mark.asyncio
async def test_create_list_delete_session():
    """Create a session, list it, then delete it."""
    async with httpx.AsyncClient(timeout=30) as client:
        # Create
        log.info("POST /internal/browsers — creating session")
        resp = await client.post(f"{SERVICE_URL}/internal/browsers", json={
            "config": {"headless": True, "use_system_chrome": False}
        })
        assert resp.status_code == 200, f"Create failed: {resp.status_code} {resp.text}"
        session_id = resp.json()["session_id"]
        log.info("Created session: %s", session_id)

        # List
        resp = await client.get(f"{SERVICE_URL}/internal/browsers")
        assert resp.status_code == 200
        data = resp.json()
        log.info("Listed sessions: active=%d, sessions=%s", data["active"], [s["session_id"] for s in data["sessions"]])
        assert data["active"] >= 1
        ids = [s["session_id"] for s in data["sessions"]]
        assert session_id in ids

        # Get
        resp = await client.get(f"{SERVICE_URL}/internal/browsers/{session_id}")
        assert resp.status_code == 200
        info = resp.json()
        log.info("Session info: %s", info)
        assert info["session_id"] == session_id

        # Delete
        log.info("DELETE /internal/browsers/%s", session_id)
        resp = await client.delete(f"{SERVICE_URL}/internal/browsers/{session_id}")
        assert resp.status_code == 200
        log.info("Session %s destroyed", session_id)

        # Confirm gone
        resp = await client.get(f"{SERVICE_URL}/internal/browsers/{session_id}")
        assert resp.status_code == 404
        log.info("Confirmed session %s is gone (404)", session_id)


# --- WebSocket: navigate, screenshot, evaluate ---

@pytest.mark.asyncio
async def test_ws_navigate_and_screenshot():
    """Create a session, connect via WS, navigate to example.com, take a screenshot."""
    async with httpx.AsyncClient(timeout=30) as client:
        # Create session
        resp = await client.post(f"{SERVICE_URL}/internal/browsers", json={
            "config": {"headless": True, "use_system_chrome": False}
        })
        assert resp.status_code == 200, f"Create failed: {resp.text}"
        session_id = resp.json()["session_id"]

    try:
        ws_url = f"{WS_URL}/internal/browsers/{session_id}/ws"
        log.info("WS connecting to %s", ws_url)
        async with websockets.connect(ws_url, close_timeout=5) as ws:
            # Should get "connected" message
            raw = await asyncio.wait_for(ws.recv(), timeout=5)
            msg = json.loads(raw)
            assert msg["status"] == "ok", f"Expected connected, got: {msg}"
            assert msg["action"] == "connected"
            log.info("WS connected: %s", msg)

            # Navigate
            log.info("Sending navigate -> https://example.com")
            await ws.send(json.dumps({
                "action": "navigate",
                "url": "https://example.com",
            }))
            raw = await asyncio.wait_for(ws.recv(), timeout=15)
            msg = json.loads(raw)
            assert msg["status"] == "ok", f"Navigate failed: {msg}"
            assert "Example Domain" in msg["data"]
            assert "example.com" in msg["page"]["url"]
            log.info("Navigate result: title=%r url=%s html_length=%d content_hash=%s",
                     msg["data"], msg["page"]["url"], msg["page"]["html_length"], msg["page"]["content_hash"])

            # Screenshot
            log.info("Sending screenshot")
            await ws.send(json.dumps({"action": "screenshot"}))
            raw = await asyncio.wait_for(ws.recv(), timeout=10)
            msg = json.loads(raw)
            assert msg["status"] == "ok", f"Screenshot failed: {msg}"
            png = base64.b64decode(msg["data"])
            assert png[:4] == b"\x89PNG", "Not a valid PNG"
            assert len(png) > 1000, f"Screenshot too small: {len(png)} bytes"
            log.info("Screenshot: %d bytes PNG", len(png))

            # Evaluate JS
            log.info("Sending evaluate: document.title")
            await ws.send(json.dumps({
                "action": "evaluate",
                "expression": "document.title",
            }))
            raw = await asyncio.wait_for(ws.recv(), timeout=5)
            msg = json.loads(raw)
            assert msg["status"] == "ok"
            assert "Example Domain" in msg["data"]
            log.info("Evaluate result: %r", msg["data"])

    finally:
        log.info("Cleaning up session %s", session_id)
        async with httpx.AsyncClient(timeout=10) as client:
            await client.delete(f"{SERVICE_URL}/internal/browsers/{session_id}")


@pytest.mark.asyncio
async def test_ws_click_and_content():
    """Navigate, click a link, and get page content."""
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(f"{SERVICE_URL}/internal/browsers", json={
            "config": {"headless": True, "use_system_chrome": False}
        })
        assert resp.status_code == 200
        session_id = resp.json()["session_id"]

    try:
        ws_url = f"{WS_URL}/internal/browsers/{session_id}/ws"
        log.info("WS connecting to %s", ws_url)
        async with websockets.connect(ws_url, close_timeout=5) as ws:
            await asyncio.wait_for(ws.recv(), timeout=5)
            log.info("WS connected")

            # Navigate to example.com
            log.info("Sending navigate -> https://example.com")
            await ws.send(json.dumps({
                "action": "navigate",
                "url": "https://example.com",
            }))
            raw = await asyncio.wait_for(ws.recv(), timeout=15)
            msg = json.loads(raw)
            assert msg["status"] == "ok"
            log.info("Navigate result: page=%s", msg.get("page"))

            # Click the "More information..." link
            log.info("Sending click -> a")
            await ws.send(json.dumps({
                "action": "click",
                "selector": "a",
            }))
            raw = await asyncio.wait_for(ws.recv(), timeout=15)
            msg = json.loads(raw)
            assert msg["status"] == "ok"
            log.info("Click result: page=%s", msg.get("page"))

            # Wait a moment for navigation
            await ws.send(json.dumps({"action": "wait", "timeout": 2000}))
            await asyncio.wait_for(ws.recv(), timeout=10)

            # Get URL — should be iana.org now
            log.info("Sending get_url")
            await ws.send(json.dumps({"action": "get_url"}))
            raw = await asyncio.wait_for(ws.recv(), timeout=5)
            msg = json.loads(raw)
            assert msg["status"] == "ok"
            log.info("Current URL: %s", msg["data"])
            assert "iana.org" in msg["data"], f"Expected iana.org, got: {msg['data']}"

            # Get content
            log.info("Sending get_content")
            await ws.send(json.dumps({"action": "get_content"}))
            raw = await asyncio.wait_for(ws.recv(), timeout=5)
            msg = json.loads(raw)
            assert msg["status"] == "ok"
            log.info("Content length: %d chars", len(msg["data"]))
            assert len(msg["data"]) > 100

    finally:
        log.info("Cleaning up session %s", session_id)
        async with httpx.AsyncClient(timeout=10) as client:
            await client.delete(f"{SERVICE_URL}/internal/browsers/{session_id}")


@pytest.mark.asyncio
async def test_ws_fill():
    """Navigate to a page and fill a form field."""
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(f"{SERVICE_URL}/internal/browsers", json={
            "config": {"headless": True, "use_system_chrome": False}
        })
        assert resp.status_code == 200
        session_id = resp.json()["session_id"]

    try:
        ws_url = f"{WS_URL}/internal/browsers/{session_id}/ws"
        log.info("WS connecting to %s", ws_url)
        async with websockets.connect(ws_url, close_timeout=5) as ws:
            await asyncio.wait_for(ws.recv(), timeout=5)
            log.info("WS connected")

            # Inject an input field
            log.info("Injecting input field via evaluate")
            await ws.send(json.dumps({
                "action": "evaluate",
                "expression": "document.body.innerHTML = '<input id=\"test-input\" type=\"text\" />'; 'done'",
            }))
            raw = await asyncio.wait_for(ws.recv(), timeout=5)
            msg = json.loads(raw)
            assert msg["status"] == "ok"
            log.info("Evaluate result: %r", msg["data"])

            # Fill the input
            log.info("Sending fill -> #test-input = 'hello browser worker'")
            await ws.send(json.dumps({
                "action": "fill",
                "selector": "#test-input",
                "value": "hello browser worker",
            }))
            raw = await asyncio.wait_for(ws.recv(), timeout=5)
            msg = json.loads(raw)
            assert msg["status"] == "ok"
            log.info("Fill result: page=%s", msg.get("page"))

            # Read the value back via evaluate
            log.info("Reading input value back via evaluate")
            await ws.send(json.dumps({
                "action": "evaluate",
                "expression": "document.querySelector('#test-input').value",
            }))
            raw = await asyncio.wait_for(ws.recv(), timeout=5)
            msg = json.loads(raw)
            assert msg["status"] == "ok"
            log.info("Input value: %r", msg["data"])
            assert msg["data"] == "hello browser worker"

    finally:
        log.info("Cleaning up session %s", session_id)
        async with httpx.AsyncClient(timeout=10) as client:
            await client.delete(f"{SERVICE_URL}/internal/browsers/{session_id}")


# --- Pool capacity ---

@pytest.mark.asyncio
async def test_pool_capacity():
    """Creating more sessions than MAX_SESSIONS returns 503."""
    created = []
    max_sessions = int(os.environ.get("MAX_SESSIONS", "3"))
    log.info("Testing pool capacity (max_sessions=%d)", max_sessions)
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            for i in range(max_sessions):
                resp = await client.post(f"{SERVICE_URL}/internal/browsers", json={
                    "config": {"headless": True, "use_system_chrome": False}
                })
                assert resp.status_code == 200, f"Session {i+1} create failed: {resp.text}"
                sid = resp.json()["session_id"]
                created.append(sid)
                log.info("Created session %d/%d: %s", i + 1, max_sessions, sid)

            # Next one should fail
            log.info("Creating session %d (should fail with 503)", max_sessions + 1)
            resp = await client.post(f"{SERVICE_URL}/internal/browsers", json={
                "config": {"headless": True, "use_system_chrome": False}
            })
            log.info("Response: %d %s", resp.status_code, resp.text)
            assert resp.status_code == 503, f"Expected 503, got {resp.status_code}: {resp.text}"
    finally:
        async with httpx.AsyncClient(timeout=10) as client:
            for sid in created:
                await client.delete(f"{SERVICE_URL}/internal/browsers/{sid}")
                log.info("Cleaned up session %s", sid)


if __name__ == "__main__":
    pytest.main([__file__, "-xvs"])
