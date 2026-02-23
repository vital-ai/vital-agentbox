"""Health and metrics endpoints."""

from fastapi import APIRouter, Depends

from agentbox.api.deps import get_manager
from agentbox.api.models import HealthResponse
from agentbox.manager.box_manager import BoxManager

router = APIRouter(tags=["system"])


@router.get("/health", response_model=HealthResponse)
async def health(mgr: BoxManager = Depends(get_manager)):
    m = mgr.metrics()
    return HealthResponse(status="ok", **m)


@router.get("/metrics")
async def metrics(mgr: BoxManager = Depends(get_manager)):
    return mgr.metrics()
