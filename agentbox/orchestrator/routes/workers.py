"""
Worker management routes for the orchestrator.

Handles worker self-registration, heartbeat, deregistration,
and admin worker listing/scaling.
"""

import time

from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel
from typing import Optional

from agentbox.orchestrator.state import WorkerInfo


router = APIRouter()


class WorkerRegisterRequest(BaseModel):
    worker_id: str
    endpoint: str
    type: str = "code"  # code, browser, both
    max_sandboxes: int = 50
    active_sandboxes: int = 0
    max_sessions: int = 0
    active_sessions: int = 0


class WorkerHeartbeatRequest(BaseModel):
    worker_id: str
    type: str = "code"
    active_sandboxes: int = 0
    active_sessions: int = 0
    state: str = "active"


class ScaleRequest(BaseModel):
    desired_workers: int


# --- Internal: worker self-registration ---

@router.post("/internal/workers/register")
async def register_worker(req: WorkerRegisterRequest, request: Request):
    """Worker calls this on startup to join the pool."""
    state = request.app.state.orchestrator_state
    info = WorkerInfo(
        worker_id=req.worker_id,
        endpoint=req.endpoint,
        type=req.type,
        max_sandboxes=req.max_sandboxes,
        active_sandboxes=req.active_sandboxes,
        max_sessions=req.max_sessions,
        active_sessions=req.active_sessions,
        state="active",
        last_heartbeat=time.time(),
        registered_at=time.time(),
    )
    await state.register_worker(info, ttl=60)
    return {"status": "registered", "worker_id": req.worker_id}


@router.post("/internal/workers/heartbeat")
async def worker_heartbeat(req: WorkerHeartbeatRequest, request: Request):
    """Worker calls this periodically to update capacity and stay alive."""
    state = request.app.state.orchestrator_state
    existing = await state.get_worker(req.worker_id)
    if not existing:
        raise HTTPException(status_code=404, detail=f"Worker {req.worker_id} not registered")
    existing.active_sandboxes = req.active_sandboxes
    existing.active_sessions = req.active_sessions
    existing.state = req.state
    existing.last_heartbeat = time.time()
    await state.register_worker(existing, ttl=60)
    return {"status": "ok", "worker_id": req.worker_id}


@router.post("/internal/workers/deregister")
async def deregister_worker(req: WorkerHeartbeatRequest, request: Request):
    """Worker calls this on graceful shutdown (SIGTERM)."""
    state = request.app.state.orchestrator_state
    await state.deregister_worker(req.worker_id)
    return {"status": "deregistered", "worker_id": req.worker_id}


# --- Admin: worker management ---

@router.get("/workers")
async def list_workers(request: Request, state_filter: Optional[str] = None):
    """List all registered workers with capacity info."""
    orch_state = request.app.state.orchestrator_state
    workers = await orch_state.list_workers(state=state_filter)
    return {
        "workers": [
            {
                "worker_id": w.worker_id,
                "endpoint": w.endpoint,
                "type": w.type,
                "max_sandboxes": w.max_sandboxes,
                "active_sandboxes": w.active_sandboxes,
                "available": w.available,
                "max_sessions": w.max_sessions,
                "active_sessions": w.active_sessions,
                "available_sessions": w.available_sessions,
                "state": w.state,
                "last_heartbeat": w.last_heartbeat,
            }
            for w in workers
        ],
        "total": len(workers),
    }
