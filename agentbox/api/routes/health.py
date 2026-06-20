"""Health and metrics endpoints."""

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from agentbox.api.deps import get_manager
from agentbox.api.models import HealthResponse
from agentbox.manager.box_manager import BoxManager

router = APIRouter(tags=["system"])


def _try_get_manager():
    """Return BoxManager or None (browser-only mode has no BoxManager)."""
    try:
        return get_manager()
    except RuntimeError:
        return None


@router.get("/health")
async def health(request: Request):
    # Check heartbeat health (orchestrator connectivity)
    fc = getattr(request.app.state, "heartbeat_failure_count", None)
    if fc is not None:
        from agentbox.api.app import HEARTBEAT_UNHEALTHY_THRESHOLD
        if fc["value"] >= HEARTBEAT_UNHEALTHY_THRESHOLD:
            return JSONResponse(
                status_code=503,
                content={
                    "status": "unhealthy",
                    "reason": "orchestrator_unreachable",
                    "consecutive_failures": fc["value"],
                },
            )

    mgr = _try_get_manager()
    if mgr:
        m = mgr.metrics()
        return HealthResponse(status="ok", **m)
    return {"status": "ok"}


@router.get("/metrics")
async def metrics():
    mgr = _try_get_manager()
    if mgr:
        return mgr.metrics()
    return {"status": "ok", "sandboxes": 0}
