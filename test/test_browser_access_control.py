"""Unit tests for WebSocket JWT enforcement and browser-session ownership."""

import asyncio
from types import SimpleNamespace

import jwt
import pytest
from fastapi import FastAPI, HTTPException, WebSocket
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from agentbox.api.auth import (
    JWTConfig, JWTMiddleware, TokenClaims, WebSocketJWTMiddleware, mint_service_token,
)
from agentbox.browser import bridge
from agentbox.orchestrator.routes import browsers

SECRET = "test-service-secret"


def _app(enabled=True):
    config = JWTConfig(enabled=enabled, service_secret=SECRET)
    app = FastAPI()
    app.add_middleware(JWTMiddleware, config=config)
    app.add_middleware(WebSocketJWTMiddleware, config=config)

    @app.websocket("/ws")
    async def ws_route(ws: WebSocket):
        await ws.accept()
        await ws.send_json({"sub": ws.state.claims.sub})
        await ws.close()

    return app


def test_ws_without_token_is_rejected():
    with pytest.raises(WebSocketDisconnect) as exc:
        with TestClient(_app()).websocket_connect("/ws"):
            pass
    assert exc.value.code == 1008


def test_ws_with_bad_token_is_rejected():
    bad = mint_service_token("wrong-secret", subject="x")
    with pytest.raises(WebSocketDisconnect):
        with TestClient(_app()).websocket_connect("/ws", headers={"Authorization": f"Bearer {bad}"}):
            pass


def test_ws_with_service_token_gets_claims():
    token = mint_service_token(SECRET, subject="sandbox:abc")
    with TestClient(_app()).websocket_connect("/ws", headers={"Authorization": f"Bearer {token}"}) as ws:
        assert ws.receive_json() == {"sub": "sandbox:abc"}


def test_ws_open_when_jwt_disabled():
    with TestClient(_app(enabled=False)).websocket_connect("/ws") as ws:
        assert ws.receive_json() == {"sub": None}


class _State:
    def __init__(self, owners):
        self.owners = owners

    async def get_browser_owner(self, session_id):
        return self.owners.get(session_id)


def _conn(claims):
    app = SimpleNamespace(state=SimpleNamespace(jwt_config=JWTConfig(admin_role="admin")))
    return SimpleNamespace(app=app, state=SimpleNamespace(claims=claims))


@pytest.mark.parametrize("owner,claims,allowed", [
    ("sandbox:a", TokenClaims(sub="sandbox:a", roles=["service"]), True),
    ("sandbox:a", TokenClaims(sub="sandbox:b", roles=["service"]), False),
    ("user-1", TokenClaims(sub="user-2", roles=[]), False),
    ("user-1", TokenClaims(sub="ops", roles=["admin"]), True),
    (None, TokenClaims(sub="anyone"), True),
])
def test_may_access(owner, claims, allowed):
    state = _State({"s1": owner} if owner else {})
    assert asyncio.run(browsers._may_access(state, "s1", _conn(claims))) is allowed


def test_require_access_hides_others_sessions():
    state = _State({"s1": "user-1"})
    with pytest.raises(HTTPException) as exc:
        asyncio.run(browsers._require_access(state, "s1", _conn(TokenClaims(sub="user-2"))))
    assert exc.value.status_code == 404


def test_bridge_token_subject_is_sandbox(monkeypatch):
    monkeypatch.setenv("AGENTBOX_SERVICE_SECRET", SECRET)
    token = bridge._auth_headers("abc")["Authorization"].removeprefix("Bearer ")
    assert jwt.decode(token, SECRET, algorithms=["HS256"])["sub"] == "sandbox:abc"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
