"""
Internal browser routes for the unified worker.

These are the endpoints the orchestrator proxies to:
- POST   /internal/browsers              → Create session
- GET    /internal/browsers              → List sessions
- GET    /internal/browsers/{id}         → Session status
- DELETE /internal/browsers/{id}         → Destroy session
- WS     /internal/browsers/{id}/ws     → Command channel
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException
from pydantic import ValidationError

from agentbox.browser.models import (
    BrowserCommand,
    BrowserResponse,
    CreateBrowserRequest,
    PageState,
    ResponseStatus,
    SessionInfo,
    ServiceStatus,
)
from agentbox.browser.pool import SessionPool, SessionPoolFull, SessionNotFound
from agentbox.browser.ws_handler import handle_command

log = logging.getLogger(__name__)

router = APIRouter(prefix="/internal/browsers", tags=["browsers"])

# The pool is set at startup by the worker app
_pool: SessionPool | None = None


def set_pool(pool: SessionPool):
    """Set the session pool (called from worker startup)."""
    global _pool
    _pool = pool


def get_pool() -> SessionPool:
    """Get the session pool."""
    if _pool is None:
        raise HTTPException(status_code=503, detail="Browser pool not initialized")
    return _pool


# --- REST endpoints ---

@router.post("")
async def create_browser_session(req: CreateBrowserRequest | None = None):
    """Create a new browser session."""
    pool = get_pool()
    config = req.config if req else None
    try:
        session = await pool.create_session(config=config)
    except SessionPoolFull as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return {
        "session_id": session.session_id,
        "config": session.config.model_dump() if session.config else None,
    }


@router.get("")
async def list_browser_sessions():
    """List all active browser sessions."""
    pool = get_pool()
    return {
        "sessions": [SessionInfo(**s) for s in pool.list_sessions()],
        "active": pool.active_count,
        "max": pool.max_sessions,
    }


@router.get("/{session_id}")
async def get_browser_session(session_id: str):
    """Get a specific browser session's status."""
    pool = get_pool()
    try:
        session = await pool.get_session(session_id)
    except SessionNotFound:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")
    return {
        "session_id": session.session_id,
        "idle_seconds": round(session.idle_seconds, 1),
        "request_count": session.request_count,
        "config": session.config.model_dump() if session.config else None,
    }


@router.delete("/{session_id}")
async def delete_browser_session(session_id: str):
    """Force-close a browser session."""
    pool = get_pool()
    try:
        await pool.close_session(session_id)
    except SessionNotFound:
        raise HTTPException(status_code=404, detail=f"Session not found: {session_id}")
    return {"status": "closed", "session_id": session_id}


# --- WebSocket endpoint ---

def _make_progress_sender(ws: WebSocket, session):
    """Create an async callback that sends progress messages over the WebSocket."""
    async def _send_progress(message: str):
        try:
            page_state = await session.get_page_state()
            await ws.send_json(
                BrowserResponse(
                    status=ResponseStatus.INFO,
                    action="solve_captcha",
                    message=message,
                    page=PageState(**page_state),
                ).model_dump()
            )
        except Exception:
            pass
    return _send_progress


@router.websocket("/{session_id}/ws")
async def browser_ws(ws: WebSocket, session_id: str):
    """WebSocket command channel for an existing browser session."""
    pool = get_pool()
    await ws.accept()

    try:
        session = await pool.get_session(session_id)
    except SessionNotFound:
        await ws.send_json(
            BrowserResponse(
                status=ResponseStatus.ERROR, message=f"Session not found: {session_id}"
            ).model_dump()
        )
        await ws.close(code=1008, reason="Session not found")
        return

    log.info("[%s] WebSocket connected", session_id)
    await ws.send_json(
        BrowserResponse(
            status=ResponseStatus.OK,
            action="connected",
            data={"session_id": session_id},
        ).model_dump()
    )

    progress_sender = _make_progress_sender(ws, session)

    try:
        while True:
            raw = await ws.receive_json()

            try:
                command = BrowserCommand(**raw)
            except ValidationError as exc:
                await ws.send_json(
                    BrowserResponse(
                        status=ResponseStatus.ERROR,
                        message=f"Invalid command: {exc.error_count()} errors",
                    ).model_dump()
                )
                continue

            if command.action == "close":
                await ws.send_json(
                    BrowserResponse(status=ResponseStatus.OK, action="close", data="session_closed").model_dump()
                )
                break

            response = await handle_command(session, command, send_progress=progress_sender)
            await ws.send_json(response.model_dump())

    except WebSocketDisconnect:
        log.info("[%s] WebSocket disconnected", session_id)
    except Exception as exc:
        log.error("[%s] WebSocket error: %s", session_id, exc, exc_info=True)
