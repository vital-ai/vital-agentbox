"""Code and shell execution endpoints."""

from fastapi import APIRouter, Depends, HTTPException

from agentbox.api.deps import get_manager
from agentbox.api.models import ExecuteRequest, ExecuteResponse
from agentbox.manager.box_manager import BoxManager

router = APIRouter(prefix="/sandboxes/{sandbox_id}", tags=["execute"])


@router.post("/execute", response_model=ExecuteResponse)
async def execute(sandbox_id: str, req: ExecuteRequest,
                  mgr: BoxManager = Depends(get_manager)):
    try:
        if req.language == "python":
            result = await mgr.run_code(sandbox_id, req.code, language="python")
        elif req.language == "shell":
            result = await mgr.run_shell(sandbox_id, req.code)
        else:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported language: {req.language!r}. Use 'python' or 'shell'."
            )
        return ExecuteResponse(**result)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Sandbox {sandbox_id!r} not found.")
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))
