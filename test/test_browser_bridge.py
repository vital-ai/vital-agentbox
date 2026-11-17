"""Unit tests for the Pyodide browser bridge and the in-sandbox Browser client.

Covers: the bridge authenticates to the orchestrator with a service JWT,
skips solve_captcha's status="info" progress frames, and Browser.solve_captcha
returns the solver result rather than the response envelope.
"""

import asyncio
import json

import jwt
import pytest

from agentbox.browser import bridge
from agentbox.browser_client import Browser

SECRET = "test-service-secret"


class _FakeResponse:
    status_code = 200

    def json(self):
        return {"session_id": "s1"}


class _FakeAsyncClient:
    calls: list = []

    def __init__(self, *a, **kw):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, json=None, headers=None):
        _FakeAsyncClient.calls.append(("POST", url, headers))
        return _FakeResponse()


class _FakeWS:
    def __init__(self, frames):
        self._frames = [json.dumps(f) for f in frames]
        self.sent = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def send(self, data):
        self.sent.append(data)

    async def recv(self):
        return self._frames.pop(0)


def test_http_sends_service_token(monkeypatch):
    monkeypatch.setenv("AGENTBOX_SERVICE_SECRET", SECRET)
    monkeypatch.setattr(bridge.httpx, "AsyncClient", _FakeAsyncClient)
    _FakeAsyncClient.calls = []
    result = asyncio.run(bridge.browser_message_handler(
        {"type": "browser_request", "method": "POST", "path": "/browsers", "body": {}}))
    assert result["status"] == "ok"
    method, url, headers = _FakeAsyncClient.calls[0]
    assert url.endswith("/internal/browsers")
    token = headers["Authorization"].removeprefix("Bearer ")
    assert jwt.decode(token, SECRET, algorithms=["HS256"])["type"] == "service"


def test_no_secret_sends_no_header(monkeypatch):
    monkeypatch.delenv("AGENTBOX_SERVICE_SECRET", raising=False)
    assert bridge._auth_headers() == {}


def test_command_skips_progress_frames(monkeypatch):
    monkeypatch.setenv("AGENTBOX_SERVICE_SECRET", SECRET)
    final = {"status": "ok", "action": "solve_captcha",
             "data": {"solved": True, "method": "cloudflare_auto", "message": "ok"}}
    ws = _FakeWS([
        {"status": "ok", "action": "connected"},
        {"status": "info", "action": "solve_captcha", "message": "Challenge detected"},
        {"status": "info", "action": "solve_captcha", "message": "Cloudflare JS resolved"},
        final,
    ])
    seen = {}

    def fake_connect(url, additional_headers=None):
        seen["headers"] = additional_headers
        return ws

    import websockets
    monkeypatch.setattr(websockets, "connect", fake_connect)
    result = asyncio.run(bridge.browser_message_handler(
        {"type": "browser_command", "session_id": "s1", "command": {"action": "solve_captcha"}}))
    assert result == {"status": "ok", "data": final}
    assert seen["headers"]["Authorization"].startswith("Bearer ")


def test_solve_captcha_returns_solver_result():
    class Backend:
        async def send_command(self, session_id, command):
            return {"status": "ok", "action": "solve_captcha",
                    "data": {"solved": True, "method": "hcaptcha_solver", "message": "m"},
                    "page": {"url": "u", "title": "t"}}

    result = asyncio.run(Browser("s1", _backend=Backend()).solve_captcha())
    assert result == {"solved": True, "method": "hcaptcha_solver", "message": "m"}


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
