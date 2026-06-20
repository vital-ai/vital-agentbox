"""
Browser session lifecycle routes for the orchestrator.

Creates browser sessions on browser-capable workers, proxies
REST operations and WebSocket connections to the owning worker.
"""

import asyncio
import logging

import httpx
from fastapi import APIRouter, Request, HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel
from typing import Optional

from agentbox.orchestrator.state import OrchestratorState

log = logging.getLogger(__name__)

router = APIRouter()


class CreateBrowserSessionRequest(BaseModel):
    browser_type: str = "chrome"
    proxy: Optional[dict] = None
    viewport_width: int = 1280
    viewport_height: int = 720
    user_agent: Optional[str] = None
    locale: Optional[str] = None
    timezone_id: Optional[str] = None
    extra_args: list[str] = []
    geolocation: Optional[dict] = None


# --- Browser Session CRUD ---

@router.post("/browsers")
async def create_browser_session(req: CreateBrowserSessionRequest, request: Request):
    """Create a browser session on the best available browser worker."""
    state: OrchestratorState = request.app.state.orchestrator_state

    # Pick browser-capable worker
    worker = await state.pick_worker(worker_type="browser")
    if not worker:
        raise HTTPException(status_code=503, detail="No browser workers available")

    # Create session on worker
    body = {"config": req.model_dump()}

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            resp = await client.post(
                f"{worker.endpoint}/internal/browsers",
                json=body,
            )
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            raise HTTPException(status_code=502, detail=f"Browser worker {worker.worker_id} unreachable: {e}")

    if resp.status_code >= 400:
        try:
            detail = resp.json().get("detail", resp.text)
        except Exception:
            detail = resp.text or f"Worker returned {resp.status_code}"
        raise HTTPException(status_code=resp.status_code, detail=detail)

    result = resp.json()
    session_id = result["session_id"]

    # Store route
    await state.set_browser_route(session_id, worker.worker_id)

    return {
        "session_id": session_id,
        "worker_id": worker.worker_id,
        "config": result.get("config"),
    }


@router.get("/browsers")
async def list_browser_sessions(request: Request):
    """List browser sessions across all workers (aggregated)."""
    state: OrchestratorState = request.app.state.orchestrator_state
    workers = await state.list_workers(state="active")

    all_sessions = []
    for w in workers:
        if w.type not in ("browser", "both"):
            continue
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(f"{w.endpoint}/internal/browsers")
            if resp.status_code == 200:
                data = resp.json()
                for s in data.get("sessions", []):
                    s["worker_id"] = w.worker_id
                    all_sessions.append(s)
        except Exception:
            pass

    return {"sessions": all_sessions, "total": len(all_sessions)}


@router.get("/browsers/{session_id}")
async def get_browser_session(session_id: str, request: Request):
    """Get browser session info (proxied to owning worker)."""
    state: OrchestratorState = request.app.state.orchestrator_state

    worker_id = await state.get_browser_route(session_id)
    if not worker_id:
        raise HTTPException(status_code=404, detail=f"Browser session {session_id} not found")

    worker = await state.get_worker(worker_id)
    if not worker:
        raise HTTPException(status_code=502, detail=f"Worker {worker_id} not available")

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.get(f"{worker.endpoint}/internal/browsers/{session_id}")
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            raise HTTPException(status_code=502, detail=f"Worker unreachable: {e}")

    if resp.status_code >= 400:
        try:
            detail = resp.json().get("detail", resp.text)
        except Exception:
            detail = resp.text
        raise HTTPException(status_code=resp.status_code, detail=detail)

    return resp.json()


@router.delete("/browsers/{session_id}")
async def delete_browser_session(session_id: str, request: Request):
    """Destroy a browser session (proxied to owning worker)."""
    state: OrchestratorState = request.app.state.orchestrator_state

    worker_id = await state.get_browser_route(session_id)
    if not worker_id:
        raise HTTPException(status_code=404, detail=f"Browser session {session_id} not found")

    worker = await state.get_worker(worker_id)
    if not worker:
        raise HTTPException(status_code=502, detail=f"Worker {worker_id} not available")

    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            resp = await client.delete(f"{worker.endpoint}/internal/browsers/{session_id}")
        except (httpx.ConnectError, httpx.TimeoutException) as e:
            raise HTTPException(status_code=502, detail=f"Worker unreachable: {e}")

    # Clean up route regardless of worker response
    await state.delete_browser_route(session_id)

    if resp.status_code >= 400:
        try:
            detail = resp.json().get("detail", resp.text)
        except Exception:
            detail = resp.text
        raise HTTPException(status_code=resp.status_code, detail=detail)

    return resp.json()


# --- WebSocket Proxy ---

@router.websocket("/browsers/{session_id}/ws")
async def browser_ws_proxy(ws: WebSocket, session_id: str):
    """Proxy WebSocket connection to the browser worker that owns this session."""
    state: OrchestratorState = ws.app.state.orchestrator_state

    worker_id = await state.get_browser_route(session_id)
    if not worker_id:
        await ws.close(code=1008, reason="Session not found")
        return

    worker = await state.get_worker(worker_id)
    if not worker:
        await ws.close(code=1011, reason="Worker not available")
        return

    # Build the worker WS URL
    worker_ws_url = worker.endpoint.replace("http://", "ws://").replace("https://", "wss://")
    worker_ws_url += f"/internal/browsers/{session_id}/ws"

    await ws.accept()

    # Connect to worker WS
    import websockets
    try:
        async with websockets.connect(worker_ws_url) as worker_ws:
            # Relay frames bidirectionally
            async def client_to_worker():
                try:
                    while True:
                        data = await ws.receive_text()
                        await worker_ws.send(data)
                except WebSocketDisconnect:
                    pass
                except Exception:
                    pass

            async def worker_to_client():
                try:
                    async for message in worker_ws:
                        await ws.send_text(message)
                except Exception:
                    pass

            # Run both relay tasks concurrently
            done, pending = await asyncio.wait(
                [
                    asyncio.create_task(client_to_worker()),
                    asyncio.create_task(worker_to_client()),
                ],
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()

    except Exception as e:
        log.error("WebSocket proxy error for session %s: %s", session_id, e)
    finally:
        try:
            await ws.close()
        except Exception:
            pass
