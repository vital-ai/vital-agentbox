"""Sandbox CRUD endpoints."""

from fastapi import APIRouter, Depends, HTTPException

from agentbox.api.deps import get_manager
from agentbox.api.models import CreateSandboxRequest, SandboxResponse
from agentbox.manager.box_manager import BoxManager

router = APIRouter(prefix="/sandboxes", tags=["sandboxes"])


@router.post("", response_model=SandboxResponse, status_code=201)
async def create_sandbox(req: CreateSandboxRequest,
                         mgr: BoxManager = Depends(get_manager)):
    try:
        info = await mgr.create_sandbox(
            sandbox_id=req.sandbox_id,
            box_type=req.box_type,
            timeout=req.timeout,
        )
        return SandboxResponse(**info)
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.get("", response_model=list[SandboxResponse])
async def list_sandboxes(mgr: BoxManager = Depends(get_manager)):
    items = await mgr.list_sandboxes()
    return [SandboxResponse(**i) for i in items]


@router.get("/{sandbox_id}", response_model=SandboxResponse)
async def get_sandbox(sandbox_id: str,
                      mgr: BoxManager = Depends(get_manager)):
    info = await mgr.get_sandbox(sandbox_id)
    if info is None:
        raise HTTPException(status_code=404, detail=f"Sandbox {sandbox_id!r} not found.")
    return SandboxResponse(**info)


@router.delete("/{sandbox_id}", status_code=204)
async def destroy_sandbox(sandbox_id: str,
                          mgr: BoxManager = Depends(get_manager)):
    destroyed = await mgr.destroy_sandbox(sandbox_id)
    if not destroyed:
        raise HTTPException(status_code=404, detail=f"Sandbox {sandbox_id!r} not found.")
