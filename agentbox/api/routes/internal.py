"""
Internal routes for worker — exposed under /internal/ prefix.

These mirror the public sandbox/execute/files routes but are only
accessible from the orchestrator (internal network). No auth required.
"""

from fastapi import APIRouter, Depends, HTTPException, Query

from agentbox.api.deps import get_manager
from agentbox.api.models import (
    CreateSandboxRequest, SandboxResponse,
    ExecuteRequest, ExecuteResponse,
    WriteFileRequest, MkdirRequest, CopyRequest, FileContentResponse,
    HealthResponse,
)
from agentbox.manager.box_manager import BoxManager

router = APIRouter(prefix="/internal", tags=["internal"])


def _get_box(sandbox_id: str, mgr: BoxManager):
    info = mgr._sandboxes.get(sandbox_id)
    if info is None:
        raise HTTPException(status_code=404, detail=f"Sandbox {sandbox_id!r} not found.")
    return info.box


# --- Health ---

@router.get("/health")
async def health(mgr: BoxManager = Depends(get_manager)):
    m = mgr.metrics()
    return {"status": "ok", **m}


@router.get("/metrics")
async def metrics(mgr: BoxManager = Depends(get_manager)):
    return mgr.metrics()


# --- Sandbox CRUD ---

@router.post("/sandboxes", status_code=201)
async def create_sandbox(req: CreateSandboxRequest,
                         mgr: BoxManager = Depends(get_manager)):
    try:
        info = await mgr.create_sandbox(
            sandbox_id=req.sandbox_id,
            box_type=req.box_type,
            timeout=req.timeout,
            repo_id=req.repo_id,
        )
        return info
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))


@router.get("/sandboxes")
async def list_sandboxes(mgr: BoxManager = Depends(get_manager)):
    return await mgr.list_sandboxes()


@router.get("/sandboxes/{sandbox_id}")
async def get_sandbox(sandbox_id: str,
                      mgr: BoxManager = Depends(get_manager)):
    info = await mgr.get_sandbox(sandbox_id)
    if info is None:
        raise HTTPException(status_code=404, detail=f"Sandbox {sandbox_id!r} not found.")
    return info


@router.delete("/sandboxes/{sandbox_id}", status_code=200)
async def destroy_sandbox(sandbox_id: str,
                          mgr: BoxManager = Depends(get_manager)):
    destroyed = await mgr.destroy_sandbox(sandbox_id)
    if not destroyed:
        raise HTTPException(status_code=404, detail=f"Sandbox {sandbox_id!r} not found.")
    return {"status": "destroyed", "sandbox_id": sandbox_id}


# --- Execution ---

@router.post("/sandboxes/{sandbox_id}/execute")
async def execute(sandbox_id: str, req: ExecuteRequest,
                  mgr: BoxManager = Depends(get_manager)):
    try:
        if req.language == "python":
            result = await mgr.run_code(sandbox_id, req.code, language="python")
        elif req.language == "shell":
            result = await mgr.run_shell(sandbox_id, req.code)
        else:
            raise HTTPException(status_code=400, detail=f"Unsupported language: {req.language!r}")
        return result
    except KeyError:
        raise HTTPException(status_code=404, detail=f"Sandbox {sandbox_id!r} not found.")


# --- File operations ---

@router.get("/sandboxes/{sandbox_id}/files")
async def list_dir(sandbox_id: str,
                   path: str = Query("/"),
                   recursive: bool = Query(False),
                   info: bool = Query(False),
                   mgr: BoxManager = Depends(get_manager)):
    box = _get_box(sandbox_id, mgr)
    mgr._sandboxes[sandbox_id].touch()
    result = await box.memfs.list_dir(path, recursive=recursive, info=info)
    return {"path": path, "entries": result}


@router.get("/sandboxes/{sandbox_id}/files/read")
async def read_file(sandbox_id: str,
                    path: str = Query(...),
                    binary: bool = Query(False),
                    mgr: BoxManager = Depends(get_manager)):
    box = _get_box(sandbox_id, mgr)
    mgr._sandboxes[sandbox_id].touch()
    if binary:
        import base64
        data = await box.memfs.read_file_binary(path)
        if data is None:
            return {"path": path, "content": None, "exists": False}
        return {
            "path": path,
            "content": base64.b64encode(data).decode("ascii"),
            "exists": True,
        }
    content = await box.memfs.read_file(path)
    if content is None:
        return {"path": path, "content": None, "exists": False}
    return {"path": path, "content": content, "exists": True}


@router.post("/sandboxes/{sandbox_id}/files/write", status_code=201)
async def write_file(sandbox_id: str, req: WriteFileRequest,
                     mgr: BoxManager = Depends(get_manager)):
    box = _get_box(sandbox_id, mgr)
    mgr._sandboxes[sandbox_id].touch()
    ok = await box.memfs.write_file(req.path, req.content)
    if not ok:
        raise HTTPException(status_code=500, detail="Write failed.")
    return {"path": req.path, "written": True}


@router.post("/sandboxes/{sandbox_id}/files/mkdir", status_code=201)
async def mkdir(sandbox_id: str, req: MkdirRequest,
                mgr: BoxManager = Depends(get_manager)):
    box = _get_box(sandbox_id, mgr)
    mgr._sandboxes[sandbox_id].touch()
    ok = await box.memfs.mkdir_p(req.path)
    if not ok:
        raise HTTPException(status_code=500, detail="mkdir failed.")
    return {"path": req.path, "created": True}


@router.delete("/sandboxes/{sandbox_id}/files")
async def remove_file(sandbox_id: str,
                      path: str = Query(...),
                      mgr: BoxManager = Depends(get_manager)):
    box = _get_box(sandbox_id, mgr)
    mgr._sandboxes[sandbox_id].touch()
    ok = await box.memfs.remove_file(path)
    if not ok:
        raise HTTPException(status_code=404, detail=f"File {path!r} not found.")
    return {"path": path, "removed": True}


@router.post("/sandboxes/{sandbox_id}/files/copy")
async def copy(sandbox_id: str, req: CopyRequest,
               mgr: BoxManager = Depends(get_manager)):
    box = _get_box(sandbox_id, mgr)
    mgr._sandboxes[sandbox_id].touch()
    ok = await box.memfs.copy(req.src, req.dst)
    if not ok:
        raise HTTPException(status_code=500, detail="Copy failed.")
    return {"src": req.src, "dst": req.dst, "copied": True}
